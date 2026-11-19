"""Measure the final encoded file. A QC failure stays downloadable for human review."""

import re
from pathlib import Path

from PIL import ImageFont

from worker.pipeline.audio import capture, loudness
from worker.pipeline.captions import CaptionPlan, font_spec
from worker.pipeline.framing import FramingPlan
from worker.pipeline.media import probe_file


def intervals(log: str, prefix: str, duration: float):
    results, start = [], None
    for match in re.finditer(rf"{prefix}_(start|end):\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)", log):
        kind, value = match.group(1), max(0, float(match.group(2)))
        if kind == "start":
            start = value
        elif start is not None:
            results.append({"start": start, "end": value, "duration": value - start})
            start = None
    if start is not None:
        results.append({"start": start, "end": duration, "duration": max(0, duration - start)})
    return results


def caption_bounds(plan: CaptionPlan, framing: FramingPlan, duration: float):
    font_path, _ = font_spec()
    issues = []
    for i, cue in enumerate(plan.cues):
        lines = cue.text.splitlines()
        font = ImageFont.truetype(font_path, cue.font_size)
        measured = max((font.getlength(line) for line in lines), default=0)
        displayed = min(measured, plan.max_width)
        half_height = len(lines) * cue.font_size * 0.7 + max(0.6, framing.height * 0.0012)
        if (
            len(lines) > 2
            or displayed > 0.85 * framing.width
            or 0.94 * framing.height - half_height < 0.88 * framing.height
            or 0.94 * framing.height + half_height > framing.height
        ):
            issues.append({"cue": i, "reason": "outside_caption_safe_band"})
        if cue.start < -0.001 or cue.end > duration + 0.04 or cue.end <= cue.start:
            issues.append({"cue": i, "reason": "invalid_caption_time"})
    if plan.hook_lines:
        half_height = len(plan.hook_lines.splitlines()) * plan.hook_font_size * 0.7 + max(
            0.6, framing.height * 0.0012
        )
        if (
            0.05 * framing.height - half_height < 0
            or 0.05 * framing.height + half_height > 0.1 * framing.height
        ):
            issues.append({"reason": "outside_hook_safe_band"})
    return issues


def inspect_clip(
    path: Path,
    expected_duration: float,
    framing: FramingPlan,
    captions: CaptionPlan,
    roi: dict,
    directory: Path,
):
    media = probe_file(path)
    duration = media["duration_s"]
    stream = next(s for s in media["streams"] if s.get("codec_type") == "video")
    crop = f"crop={roi['width']}:{roi['height']}:{roi['x']}:{roi['y']}"
    result = capture(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            crop + ",blackdetect=d=0.05:pix_th=0.1:pic_th=0.98",
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
    levels = loudness(path, directory)
    bounds = caption_bounds(captions, framing, expected_duration)
    checks = {
        "video_stream": True,
        "audio_stream": True,
        "duration": abs(duration - expected_duration) <= 0.1,
        "dimensions": (stream["width"], stream["height"]) == (framing.width, framing.height),
        "black_frames": not any(s["duration"] > 0.5 + 1e-3 for s in black),
        "silence": not any(s["duration"] > 1 + 1e-3 for s in silent),
        "loudness": levels["input_i"] is not None and abs(levels["input_i"] + 14) <= 1,
        "true_peak": levels["input_tp"] is not None and levels["input_tp"] <= -1 + 0.05,
        "caption_safe_area": not bounds,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "needs_review": [name for name, passed in checks.items() if not passed],
        "duration_s": duration,
        "expected_duration_s": expected_duration,
        "width": framing.width,
        "height": framing.height,
        "black_intervals": black,
        "silence_intervals": silent,
        "black_detection_roi": roi,
        "loudness": levels,
        "caption_issues": bounds,
        "limitations": "QC mengukur file akhir dan batas geometris. Makna edit dan sinkron timestamp ASR terhadap ucapan perlu peninjauan manusia.",
    }
