"""Sample-accurate EDL audio, 10 ms crossfades and measured two-pass normalization."""

import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

from api.app.config import get_settings
from api.app.models import Clip
from worker.pipeline.media import MediaError
from worker.pipeline.retention import EditPlan

RATE = 48000


def capture(arguments, *, directory: Path):
    try:
        result = subprocess.run(
            arguments, capture_output=True, timeout=get_settings().job_timeout_seconds
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError("FFmpeg audio/QC tidak tersedia atau melewati batas waktu.") from exc
    if result.returncode:
        (directory / "audio-qc-error.log").write_bytes(result.stderr[-16000:])
        raise MediaError(
            "FFmpeg gagal pada audio/QC. Lihat audio-qc-error.log di direktori output."
        )
    return result


def loudness(path: Path, directory: Path):
    result = capture(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        directory=directory,
    )
    matches = re.findall(r'\{\s*"input_i".*?\}', result.stderr.decode(errors="replace"), re.S)
    if not matches:
        raise MediaError("Pengukuran loudness tidak mengembalikan laporan FFmpeg.")
    data = json.loads(matches[-1])
    return {
        key: float(value) if math.isfinite(float(value)) else None
        for key, value in data.items()
        if key != "normalization_type"
    } | {"normalization_type": data.get("normalization_type")}


def mixed_audio(source: Path, clip: Clip, plan: EditPlan, directory: Path) -> np.ndarray:
    result = capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(clip.start_s),
            "-t",
            str(clip.end_s - clip.start_s),
            "-i",
            str(source),
            "-vn",
            "-ac",
            "2",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-",
        ],
        directory=directory,
    )
    decoded = np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2)
    output = np.zeros((round(plan.duration * RATE), 2), dtype=np.float32)
    for span in plan.spans:
        length = round((span.dst_end - span.dst_start) * RATE)
        if span.kind == "transition":
            rng = np.random.default_rng(0)
            noise = rng.standard_normal(length).astype(np.float32)
            spectrum = np.fft.rfft(noise)
            freqs = np.fft.rfftfreq(length, 1 / RATE)
            spectrum[(freqs < 400) | (freqs > 8000)] = 0
            signal = np.fft.irfft(spectrum, n=length)
            signal = signal / max(float(np.max(np.abs(signal))), 1e-6) * 0.08
            signal *= np.sin(np.linspace(0, np.pi, length)) ** 2
            samples = np.repeat(signal[:, None], 2, axis=1).astype(np.float32)
        else:
            start = round((span.src_start - clip.start_s) * RATE)
            samples = decoded[start : start + length]
            if len(samples) < length:
                samples = np.pad(samples, ((0, length - len(samples)), (0, 0)))
        start = round(span.dst_start * RATE)
        length = min(length, len(output) - start)
        fade = min(round(span.fade_in * RATE), length)
        if fade:
            ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
            output[start : start + fade] *= 1 - ramp
            output[start : start + fade] += samples[:fade] * ramp
        output[start + fade : start + length] = samples[fade:length]
    return output


def normalize_audio(source: Path, clip: Clip, plan: EditPlan, work: Path):
    raw = work / "edited.f32"
    samples = mixed_audio(source, clip, plan, work)
    samples.astype("<f4", copy=False).tofile(raw)
    del samples
    args = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-f",
        "f32le",
        "-ar",
        str(RATE),
        "-ac",
        "2",
        "-i",
        str(raw),
    ]
    result = capture(
        [*args, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        directory=work,
    )
    matches = re.findall(r'\{\s*"input_i".*?\}', result.stderr.decode(errors="replace"), re.S)
    if not matches:
        raise MediaError("Analisis loudnorm tidak tersedia.")
    measured = json.loads(matches[-1])
    destination = work / "normalized.wav"
    if all(
        math.isfinite(float(measured[k]))
        for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    ):
        filters = "loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:print_format=json:" + ":".join(
            f"{key}={measured[value]}"
            for key, value in {
                "measured_I": "input_i",
                "measured_TP": "input_tp",
                "measured_LRA": "input_lra",
                "measured_thresh": "input_thresh",
                "offset": "target_offset",
            }.items()
        )
        status = "two_pass"
    else:
        filters, status = "anull", "unmeasurable_silence"
    capture(
        [*args, "-y", "-af", filters, "-ar", str(RATE), "-c:a", "pcm_s24le", str(destination)],
        directory=work,
    )
    return destination, {
        "status": status,
        "target_lufs": -14,
        "normalization_peak_db": -1.5,
        "final_peak_limit_db": -1,
        "sample_rate": RATE,
        "crossfade_ms": 10,
    }
