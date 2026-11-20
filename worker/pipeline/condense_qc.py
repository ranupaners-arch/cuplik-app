"""Measure final Ringkas media, accounting for explicitly muted timelapse spans."""

import math
from pathlib import Path

from worker.pipeline.audio import capture, loudness
from worker.pipeline.media import probe_file
from worker.pipeline.qc import intervals
from worker.pipeline.storage import atomic_json, json_object


def normalize_condensed(path: Path, directory: Path):
    levels = loudness(path, directory)
    finite = all(
        levels.get(k) is not None
        for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    )
    if not finite:
        return {"status": "unmeasurable_silence", "target_lufs": -14}
    filters = "loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:" + ":".join(
        f"{key}={levels[value]}"
        for key, value in {
            "measured_I": "input_i",
            "measured_TP": "input_tp",
            "measured_LRA": "input_lra",
            "measured_thresh": "input_thresh",
            "offset": "target_offset",
        }.items()
    )
    temporary = directory / "condensed.normalized.mp4"
    capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-af",
            filters,
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        directory=directory,
    )
    temporary.replace(path)
    timeline = json_object(directory / "condensed.timeline.json")
    duration = probe_file(path)["duration_s"]
    timeline["duration_drift_s"] += duration - timeline["duration_s"]
    timeline["duration_s"] = duration
    if duration <= timeline["spans"][-1]["output_start_s"]:
        raise ValueError("Durasi setelah normalisasi tidak sesuai garis waktu Ringkas")
    timeline["spans"][-1]["output_end_s"] = duration
    atomic_json(directory / "condensed.timeline.json", timeline)
    return {"status": "two_pass", "target_lufs": -14, "peak_limit_db": -1, "video_reencoded": False}


def unexpected_silence(silence, allowed):
    remaining = []
    for interval in silence:
        pieces = [(interval["start"], interval["end"])]
        for left, right in allowed:
            pieces = [
                piece
                for a, b in pieces
                for piece in ((a, min(b, left)), (max(a, right), b))
                if piece[1] > piece[0]
            ]
        remaining.extend({"start": a, "end": b, "duration": b - a} for a, b in pieces)
    return remaining


def inspect_condensed(path: Path, directory: Path, beats, target: float, normalization: dict):
    media = probe_file(path)
    duration = media["duration_s"]
    timeline = json_object(directory / "condensed.timeline.json")
    spans = timeline["spans"]
    video = next(s for s in media["streams"] if s["codec_type"] == "video")
    audio = next(s for s in media["streams"] if s["codec_type"] == "audio")
    expected = sum(
        (b.end_s - b.start_s) / (b.speed if b.decision == "speed" else 1)
        for b in beats
        if b.decision != "drop"
    )
    result = capture(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.05:pix_th=0.1:pic_th=0.98",
            "-af",
            "silencedetect=noise=-40dB:d=1",
            "-f",
            "null",
            "-",
        ],
        directory=directory,
    )
    log = result.stderr.decode(errors="replace")
    black, silent = intervals(log, "black", duration), intervals(log, "silence", duration)
    allowed = [
        (s["output_start_s"], s["output_end_s"]) for s in spans if s.get("audio_mode") == "muted"
    ]
    unexpected = unexpected_silence(silent, allowed)
    levels = loudness(path, directory)
    audible = any(s.get("audio_mode") != "muted" for s in spans)
    offset = abs(float(video.get("start_time", 0)) - float(audio.get("start_time", 0)))
    ends = [
        float(s.get("start_time", 0)) + float(s.get("duration", duration)) for s in (video, audio)
    ]
    timeline_valid = bool(spans) and abs(spans[0]["output_start_s"]) <= 0.001
    for index, span in enumerate(spans):
        a, b = span["output_start_s"], span["output_end_s"]
        timeline_valid = timeline_valid and math.isfinite(a) and math.isfinite(b) and 0 <= a < b
        if index:
            timeline_valid = timeline_valid and abs(a - spans[index - 1]["output_end_s"]) <= 0.001
    checks = {
        "duration": abs(duration - expected) <= max(0.1, len(spans) / 24),
        "target_duration": abs(duration - target) <= target * 0.03,
        "stream_alignment": offset <= 0.1 and abs(ends[0] - ends[1]) <= 0.1,
        "chapter_timeline": timeline_valid and abs(spans[-1]["output_end_s"] - duration) <= 0.1,
        "black_frames": not any(s["duration"] > 0.501 for s in black),
        "silence": not any(s["duration"] > 1.001 for s in unexpected),
        "loudness": not audible
        or (levels["input_i"] is not None and abs(levels["input_i"] + 14) <= 1),
        "true_peak": not audible
        or (levels["input_tp"] is not None and levels["input_tp"] <= -0.95),
    }
    report = {
        "version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "needs_review": [key for key, passed in checks.items() if not passed],
        "duration_s": duration,
        "expected_duration_s": expected,
        "target_duration_s": target,
        "stream_offset_s": offset,
        "stream_end_difference_s": abs(ends[0] - ends[1]),
        "black_intervals": black,
        "silence_intervals": silent,
        "expected_silence": [{"start": a, "end": b} for a, b in allowed],
        "unexpected_silence": unexpected,
        "loudness": levels,
        "loudness_applicable": audible,
        "normalization": normalization,
        "limitations": "QC mengukur file akhir. Selisih waktu stream bukan bukti sinkronisasi ucapan/bibir atau ketepatan timestamp ASR; tetap tinjau video.",
    }
    atomic_json(directory / "condensed.qc.json", report)
    return report
