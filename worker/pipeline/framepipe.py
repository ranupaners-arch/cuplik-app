"""Bounded frame pipeline: FFmpeg decode → OpenCV tracking/composition → FFmpeg encode."""

import math
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from threading import Timer

import cv2
import numpy as np

from api.app.config import get_settings
from api.app.models import Clip
from api.app.schemas import Transcript
from worker.pipeline.framing import FramingPlan
from worker.pipeline.media import MediaError
from worker.pipeline.reframe import Tracker, compose
from worker.pipeline.retention import EditPlan, zoom_at
from worker.pipeline.storage import atomic_json

FPS = 30


def encode_clip(
    source: Path,
    destination: Path,
    clip: Clip,
    transcript: Transcript,
    edit: EditPlan,
    framing: FramingPlan,
    audio: Path,
    ass: Path,
    *,
    captions: bool,
    hook: bool,
):
    frames = math.ceil(edit.duration * FPS - 1e-8)
    directory = destination.parent
    processes, trace = [], []
    tracker = Tracker(framing)
    cv2.setNumThreads(get_settings().render_threads)
    started = time.monotonic()
    best, best_score, best_face, best_info = None, -1.0, False, {}
    roi = {"x": 0, "y": 0, "right": framing.width, "bottom": framing.height}
    temporary = destination.with_suffix(".tmp.mp4")

    def stop():
        for process in processes:
            if process.poll() is None:
                process.kill()

    timer = Timer(get_settings().job_timeout_seconds, stop)
    with (directory / f"{clip.id}.encoder.log").open("wb") as errors:
        encoder = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-filter_threads",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{framing.width}x{framing.height}",
                "-r",
                str(FPS),
                "-i",
                "pipe:0",
                "-i",
                str(audio),
                "-vf",
                f"ass={ass.name}",
                "-af",
                "apad=pad_dur=1",
                "-t",
                f"{frames / FPS:.8f}",
                "-c:v",
                "libx264",
                "-threads",
                str(get_settings().render_threads),
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            cwd=directory,
        )
        processes.append(encoder)
        timer.start()
        index, last_canvas, last_meta = 0, None, None
        try:
            for occurrence, span in enumerate(edit.spans):
                next_cut = (
                    edit.spans[occurrence + 1].dst_start + edit.spans[occurrence + 1].fade_in / 2
                    if occurrence + 1 < len(edit.spans)
                    else frames / FPS
                )
                if index / FPS >= next_cut - 1e-9:
                    continue
                decoder = None
                if span.kind != "transition":
                    decoder = subprocess.Popen(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-threads",
                            "2",
                            "-filter_threads",
                            "1",
                            "-ss",
                            str(span.src_start),
                            "-t",
                            str(span.src_end - span.src_start + 1 / FPS),
                            "-i",
                            str(source),
                            "-an",
                            "-vf",
                            f"fps={FPS},scale={framing.source_width}:{framing.source_height},setsar=1",
                            "-f",
                            "rawvideo",
                            "-pix_fmt",
                            "bgr24",
                            "pipe:1",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=errors,
                    )
                    processes.append(decoder)
                read_index, raw, first = -1, None, True
                try:
                    while index < frames and index / FPS < next_cut - 1e-9:
                        output_time = index / FPS
                        if span.kind == "transition":
                            if last_canvas is None:
                                raise MediaError("Transisi memerlukan frame pembuka yang valid.")
                            canvas, meta = last_canvas.copy(), {**last_meta, "transition": True}
                            source_time = span.src_end - 1 / FPS
                            state = {"face": None}
                        else:
                            desired = max(0, round((output_time - span.dst_start) * FPS))
                            while read_index < desired:
                                data = decoder.stdout.read(
                                    framing.source_width * framing.source_height * 3
                                )
                                if len(data) != framing.source_width * framing.source_height * 3:
                                    if desired - read_index > 1:
                                        raise MediaError(
                                            "Decoder berakhir sebelum rentang edit selesai."
                                        )
                                    break
                                raw = np.frombuffer(data, dtype=np.uint8).reshape(
                                    framing.source_height, framing.source_width, 3
                                )
                                read_index += 1
                            if raw is None:
                                raise MediaError("Decoder tidak menghasilkan frame video.")
                            source_time = min(
                                span.src_end, span.src_start + max(0, output_time - span.dst_start)
                            )
                            state = tracker.update(raw, index, output_time, reset=first)
                            zoom = (
                                zoom_at(source_time, clip, transcript, edit)
                                if framing.content_kind == "speaker"
                                else 1
                            )
                            canvas, meta = compose(
                                raw, framing, state, zoom, captions=captions, hook=hook
                            )
                        meta = {
                            **meta,
                            "frame": index,
                            "output_s": round(output_time, 6),
                            "source_s": round(source_time, 6),
                            "span": occurrence,
                        }
                        trace.append(meta)
                        box = meta["content_box"]
                        roi = {
                            "x": max(roi["x"], box["x"]),
                            "y": max(roi["y"], box["y"]),
                            "right": min(roi["right"], box["x"] + box["width"]),
                            "bottom": min(roi["bottom"], box["y"] + box["height"]),
                        }
                        if (
                            span.kind != "transition"
                            and output_time <= edit.duration * 0.3
                            and (index % 3 == 0 or best is None)
                        ):
                            face = state["face"] if tracker.last_seen == output_time else None
                            patch = raw
                            if face:
                                left, top = (
                                    max(0, round(face.x * raw.shape[1])),
                                    max(0, round(face.y * raw.shape[0])),
                                )
                                right, bottom = (
                                    min(raw.shape[1], round((face.x + face.w) * raw.shape[1])),
                                    min(raw.shape[0], round((face.y + face.h) * raw.shape[0])),
                                )
                                if right > left and bottom > top:
                                    patch = raw[top:bottom, left:right]
                            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
                            score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                            if (face is not None and not best_face) or (
                                (face is not None) == best_face and score > best_score
                            ):
                                best, best_score, best_face = canvas.copy(), score, face is not None
                                best_info = {
                                    "output_s": output_time,
                                    "source_s": source_time,
                                    "sharpness": score,
                                    "face": asdict(face) if face else None,
                                }
                        encoder.stdin.write(canvas.tobytes())
                        last_canvas, last_meta = canvas, meta
                        index += 1
                        first = False
                finally:
                    if decoder is not None:
                        decoder.stdout.close()
                        if decoder.poll() is None:
                            decoder.terminate()
                        try:
                            decoder.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            decoder.kill()
                            decoder.wait(timeout=5)
            encoder.stdin.close()
            encoder.wait(timeout=get_settings().job_timeout_seconds)
            if encoder.returncode or index != frames:
                raise MediaError(
                    "Encoder gagal atau jumlah frame tidak lengkap; lihat log encoder."
                )
        except (BrokenPipeError, OSError) as exc:
            raise MediaError("Pipa video terputus; lihat log encoder pada output.") from exc
        finally:
            timer.cancel()
            stop()
            for process in processes:
                process.wait(timeout=5)
            if not encoder.stdin.closed:
                encoder.stdin.close()
    temporary.replace(destination)
    if best is not None:
        image = directory / f"{clip.id}.tmp.jpg"
        if not cv2.imwrite(str(image), best, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise MediaError("Thumbnail gagal disimpan.")
        image.replace(directory / f"{clip.id}.jpg")
    trace_path = directory / "reframe" / f"{clip.id}.json"
    trace_path.parent.mkdir(exist_ok=True)
    summary = {
        "frames": index,
        "fps": FPS,
        "detection_stride": 3,
        "detections": tracker.detections,
        "blur_frames": sum(f["mode"] == "blur_fit" for f in trace),
        "scene_cuts": sum(f["scene_cut"] for f in trace),
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    atomic_json(trace_path, {"summary": summary, "framing": framing.model_dump(), "frames": trace})
    roi = {
        "x": roi["x"],
        "y": roi["y"],
        "width": max(2, (roi["right"] - roi["x"]) // 2 * 2),
        "height": max(2, (roi["bottom"] - roi["y"]) // 2 * 2),
    }
    return summary, best_info, roi
