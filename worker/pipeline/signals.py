"""Moment IQ: reproducible media hints, not a model of virality."""

import hashlib
import json
import math
import re
import wave
from pathlib import Path

import numpy as np
from pydantic import Field, model_validator

from api.app.schemas import StrictModel, Transcript
from worker.pipeline.ingest import checksum
from worker.pipeline.storage import atomic_json, file_lock, json_object

VERSION = 1
WEIGHTS = {
    "energy": 0.35,
    "speech_rate": 0.25,
    "hook_words": 0.20,
    "scene_change": 0.10,
    "silence": -0.10,
}
HOOKS_PATH = Path(__file__).with_name("hook_words.txt")


class SignalPoint(StrictModel):
    t: int = Field(ge=0)
    rms: float = Field(ge=0, le=1)
    energy_z: float
    words_per_second: float = Field(ge=0)
    speech_rate_z: float
    hook_words: float = Field(ge=0)
    scene_change: float = Field(ge=0, le=1)
    silence: float = Field(ge=0, le=1)
    iq: float = Field(ge=0, le=1)


class Signals(StrictModel):
    version: int
    fingerprint: str
    duration_s: float = Field(gt=0)
    precision: str
    weights: dict[str, float]
    smoothing_seconds: int
    scene_detector: str
    mean: float
    std: float = Field(ge=0)
    points: list[SignalPoint]

    @model_validator(mode="after")
    def complete(self):
        if [p.t for p in self.points] != list(range(math.ceil(self.duration_s))):
            raise ValueError("Sinyal harus mencakup setiap detik sumber secara berurutan")
        return self


def zscore(values):
    values = np.asarray(values, dtype=float)
    return (values - values.mean()) / max(float(values.std()), 1e-6)


def scene_cuts(source: Path) -> list[float]:
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(source), backend="opencv")
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=27.0))
    manager.auto_downscale = True
    try:
        # Keep every frame: skipping frames misses short cuts and changes the detector.
        manager.detect_scenes(video=video, show_progress=False)
        return [start.seconds for start, _ in manager.get_scene_list()[1:]]
    finally:
        # VideoStreamCv2 exposes its capture via this public property.
        video.capture.release()


def audio_features(audio: Path, count: int):
    energy, silence = np.zeros(count), np.ones(count)
    with wave.open(str(audio)) as handle:
        rate = handle.getframerate()
        if (rate, handle.getnchannels(), handle.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Moment IQ memerlukan WAV PCM 16 kHz mono 16-bit")
        for second in range(count):
            samples = np.frombuffer(handle.readframes(rate), dtype="<i2").astype(float) / 32768
            if not samples.size:
                break
            energy[second] = float(np.sqrt(np.mean(samples**2)))
            chunks = [samples[i : i + 320] for i in range(0, len(samples), 320)]
            silence[second] = np.mean([np.sqrt(np.mean(chunk**2)) < 0.01 for chunk in chunks])
    return energy, silence


def compute_signals(
    audio: Path, transcript: Transcript, duration: float, cuts: list[float], fingerprint: str
) -> Signals:
    count = math.ceil(duration)
    energy, silence = audio_features(audio, count)
    rate, hooks, scenes = np.zeros(count), np.zeros(count), np.zeros(count)
    phrases = [
        line.strip()
        for line in HOOKS_PATH.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in phrases) + r")(?!\w)", re.I)
    # Sentence-only sidecars remain supported, but their timing precision is explicit.
    timed = [(w.start, w.end, w.text) for w in transcript.words]
    if not timed:
        for s in transcript.sentences:
            words = s.text.split()
            for i, text in enumerate(words):
                start = s.start + (s.end - s.start) * i / len(words)
                timed.append((start, start + (s.end - s.start) / len(words), text))
    for start, end, _ in timed:
        for second in range(max(0, int(start)), min(count, math.ceil(end))):
            rate[second] += max(0, min(end, second + 1) - max(start, second)) / max(
                end - start, 1e-6
            )
    for s in transcript.sentences:
        # Also detects multi-word triggers without counting substrings like 'how' in 'show'.
        for match in pattern.finditer(s.text):
            when = s.start + (s.end - s.start) * match.start() / max(1, len(s.text))
            hooks[min(count - 1, int(when))] += 1
    for cut in cuts:
        if 0 <= cut < duration:
            scenes[int(cut)] = 1
    energy_z, rate_z = zscore(energy), zscore(rate)
    raw = 0.35 * energy_z + 0.25 * rate_z + 0.20 * hooks + 0.10 * scenes - 0.10 * silence
    # Centered five-second smoothing; edge padding avoids artificial end spikes.
    smooth = np.convolve(np.pad(raw, (2, 2), mode="edge"), np.ones(5) / 5, mode="valid")
    span = float(np.ptp(smooth))
    iq = (smooth - smooth.min()) / span if span > 1e-6 else np.zeros(count)
    return Signals(
        version=VERSION,
        fingerprint=fingerprint,
        duration_s=duration,
        precision="word" if transcript.words else "sentence_estimate",
        weights=WEIGHTS,
        smoothing_seconds=5,
        scene_detector="PySceneDetect ContentDetector(27.0), every frame",
        mean=float(iq.mean()),
        std=float(iq.std()),
        points=[
            SignalPoint(
                t=i,
                rms=float(energy[i]),
                energy_z=float(energy_z[i]),
                words_per_second=float(rate[i]),
                speech_rate_z=float(rate_z[i]),
                hook_words=float(hooks[i]),
                scene_change=float(scenes[i]),
                silence=float(silence[i]),
                iq=float(iq[i]),
            )
            for i in range(count)
        ],
    )


def build_signals(directory: Path, transcript: Transcript, duration: float) -> Signals:
    with file_lock(directory / ".signals.lock"):
        manifest = json_object(directory / "ingest.json")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "version": VERSION,
                    "source": manifest.get("source_sha256") or checksum(directory / "source.mp4"),
                    "audio": checksum(directory / "audio.wav"),
                    "transcript": transcript.model_dump(),
                    "duration": duration,
                    "hooks": HOOKS_PATH.read_text(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        path = directory / "signals.json"
        cached = json_object(path)
        if cached.get("fingerprint") == digest:
            try:
                return Signals.model_validate(cached)
            except ValueError:
                pass
        result = compute_signals(
            directory / "audio.wav",
            transcript,
            duration,
            scene_cuts(directory / "source.mp4"),
            digest,
        )
        atomic_json(path, result.model_dump())
        return result


def mean_iq(signals: Signals, start: float, end: float) -> float:
    weighted, total = 0.0, 0.0
    for p in signals.points[max(0, int(start)) : math.ceil(end)]:
        overlap = max(0, min(end, p.t + 1, signals.duration_s) - max(start, p.t))
        weighted += p.iq * overlap
        total += overlap
    return weighted / max(total, 1e-6)


def energy_peaks(signals: Signals, start: float, end: float) -> list[dict]:
    points = [
        p
        for p in signals.points[int(start) : math.ceil(end)]
        if p.iq >= max(0.7, signals.mean + signals.std)
    ]
    spans = []
    for p in points:
        if spans and spans[-1]["end_s"] == p.t:
            spans[-1]["end_s"] = min(p.t + 1, end)
            spans[-1]["iq"] = max(spans[-1]["iq"], round(p.iq, 3))
        else:
            spans.append({"start_s": p.t, "end_s": min(p.t + 1, end), "iq": round(p.iq, 3)})
    return spans[:20]
