"""Source-clock speech/gap beats and bounded, reproducible local motion hints."""

import hashlib
import json
import math
import subprocess
from bisect import bisect_left
from pathlib import Path
from threading import Timer
from typing import Literal

import cv2
import numpy as np
from pydantic import Field
from scenedetect import FrameTimecode
from scenedetect.detectors import ContentDetector

from api.app.config import get_settings
from api.app.schemas import StrictModel, Transcript
from worker.pipeline.ingest import checksum
from worker.pipeline.media import MediaError
from worker.pipeline.storage import atomic_json, file_lock, json_object


class MotionSample(StrictModel):
    time_s: float = Field(ge=0)
    activity: float = Field(ge=0, le=1)


class MotionReport(StrictModel):
    version: int = 1
    fingerprint: str
    duration_s: float = Field(gt=0)
    samples: list[MotionSample] = Field(min_length=1)
    cuts: list[float]


class BeatDraft(StrictModel):
    id: str
    sentence_id: str = ""
    start_s: float
    end_s: float
    text: str = ""
    kind: Literal["speech", "visual"]
    activity: float = Field(default=0, ge=0, le=1)


def analyze_motion(directory: Path, duration: float) -> MotionReport:
    source = directory / "source.mp4"
    identity = json_object(directory / "ingest.json").get("source_sha256") or checksum(source)
    digest = hashlib.sha256(
        json.dumps(
            {"version": 1, "source": identity, "duration": duration}, sort_keys=True
        ).encode()
    ).hexdigest()
    path = directory / "condense-motion.json"
    with file_lock(directory / ".condense-motion.lock"):
        try:
            cached = MotionReport.model_validate_json(path.read_text())
            if cached.fingerprint == digest:
                return cached
        except (OSError, ValueError):
            pass
        samples, cuts, previous = [], [], None
        detector = ContentDetector(threshold=27, min_scene_len=1)
        with (directory / "condense-motion.log").open("wb") as errors:
            process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-threads",
                    str(get_settings().render_threads),
                    "-i",
                    str(source),
                    "-an",
                    "-vf",
                    "fps=2,scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2",
                    "-pix_fmt",
                    "bgr24",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=errors,
            )
            timer = Timer(get_settings().job_timeout_seconds, process.kill)
            timer.start()
            try:
                while True:
                    data = bytearray()
                    while len(data) < 160 * 90 * 3:
                        chunk = process.stdout.read(160 * 90 * 3 - len(data))
                        if not chunk:
                            break
                        data.extend(chunk)
                    if not data:
                        break
                    if len(data) != 160 * 90 * 3 or len(samples) > math.ceil(duration * 2) + 2:
                        raise MediaError("Frame analisis tidak sesuai durasi sumber.")
                    index = len(samples)
                    image = np.frombuffer(data, np.uint8).reshape(90, 160, 3)
                    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    activity = (
                        float(np.mean(cv2.absdiff(previous, gray)) / 255)
                        if previous is not None
                        else 0
                    )
                    previous = gray
                    samples.append(MotionSample(time_s=index / 2, activity=activity))
                    detected = detector.process_frame(FrameTimecode(index, 2.0), image)
                    cuts.extend(c.seconds for c in detected if 0 < c.seconds < duration)
                if process.wait() or not samples:
                    raise MediaError("Analisis gambar gagal; lihat condense-motion.log.")
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.stdout.close()
                process.wait()
        result = MotionReport(fingerprint=digest, duration_s=duration, samples=samples, cuts=cuts)
        atomic_json(path, result.model_dump())
        return result


def build_beats(transcript: Transcript, duration: float, motion: MotionReport) -> list[BeatDraft]:
    if transcript.sentences[-1].end > duration + 0.1:
        raise ValueError("Transkrip melampaui durasi sumber untuk beat Ringkas.")
    drafts, gaps, previous = [], [], 0.0
    for sentence in transcript.sentences:
        if sentence.start - previous >= 1.5:
            gaps.append((previous, sentence.start))
        drafts.append(
            BeatDraft(
                id="",
                sentence_id=sentence.id,
                start_s=sentence.start,
                end_s=min(duration, sentence.end),
                text=sentence.text,
                kind="speech",
            )
        )
        previous = sentence.end
    if duration - previous >= 1.5:
        gaps.append((previous, duration))
    for start, end in gaps:
        boundaries = sorted({start, end, *(c for c in motion.cuts if start < c < end)})
        for a, b in zip(boundaries, boundaries[1:], strict=False):
            while a < b - 1e-6:
                finish = min(a + 20, b)
                drafts.append(BeatDraft(id="", start_s=a, end_s=finish, kind="visual"))
                a = finish
    times = [s.time_s for s in motion.samples]
    drafts.sort(key=lambda d: (d.start_s, d.end_s))
    for index, beat in enumerate(drafts, 1):
        beat.id = f"b{index}"
        samples = motion.samples[bisect_left(times, beat.start_s) : bisect_left(times, beat.end_s)]
        beat.activity = round(sum(s.activity for s in samples) / len(samples), 6) if samples else 0
    return drafts


def frame_schedule(beats: list[BeatDraft], maximum: int) -> list[dict]:
    result = []
    for beat in beats:
        interval = 5 if beat.kind == "visual" else 15
        count = max(1, math.ceil((beat.end_s - beat.start_s) / interval))
        for index in range(count):
            start = beat.start_s + index * interval
            end = min(beat.end_s, start + interval)
            result.append(
                {"id": f"f{len(result) + 1}", "beat_id": beat.id, "time_s": (start + end) / 2}
            )
    if len(result) > maximum:
        raise ValueError(
            f"Vision memerlukan {len(result)} frame, melebihi batas {maximum}. Naikkan batas frame atau gunakan mode transkrip; belum ada permintaan LLM dikirim."
        )
    return result
