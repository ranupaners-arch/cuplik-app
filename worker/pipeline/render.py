import hashlib
import json
import tempfile
import time
from pathlib import Path

from api.app.config import get_settings
from api.app.models import Beat, Clip
from api.app.schemas import RetentionSettings, Transcript
from worker.pipeline.audio import normalize_audio
from worker.pipeline.captions import caption_plan, timed_tokens, write_ass
from worker.pipeline.delivery import effective_layout, inspect_delivery
from worker.pipeline.framepipe import encode_clip
from worker.pipeline.framing import FramingPlan, analyze_framing, video_filter
from worker.pipeline.media import run
from worker.pipeline.qc import inspect_clip
from worker.pipeline.reframe import tracked_plan
from worker.pipeline.retention import build_edl, remap_tokens
from worker.pipeline.storage import atomic_json, json_object


def fingerprint(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clip_fingerprint(clip: Clip) -> str:
    return fingerprint(
        {
            "version": 4,
            "purpose": clip.purpose,
            "platform": clip.platform,
            "retention": RetentionSettings.model_validate(clip.retention).model_dump(),
            "keywords": clip.keywords,
            "emoji": clip.emoji,
            "cold_open_id": clip.selection.get("cold_open_id"),
            "emphasis_word_ids": clip.selection.get("emphasis_word_ids", []),
            "caption_profile": "compact-karaoke-v2",
            "framing_profile": "tracked-visual-delivery-v4",
            "layout": clip.layout,
            "start": clip.start_s,
            "end": clip.end_s,
            "hook": clip.hook_options[clip.hook_choice],
            "captions": clip.captions,
            "overrides": clip.caption_overrides,
            "height": get_settings().render_height,
        }
    )


def ass_time(seconds: float) -> str:
    ticks = max(0, round(seconds * 100))
    return f"{ticks // 360000}:{ticks // 6000 % 60:02d}:{ticks // 100 % 60:02d}.{ticks % 100:02d}"


def ass_text(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", r"\N")


def subtitles(
    path: Path, lines: list[tuple[float, float, str]], width: int, height: int, hook: str = ""
):
    text = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,DejaVu Sans,{max(16, width // 20)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,2,24,24,{height // 5},1
Style: Hook,DejaVu Sans,{max(18, width // 18)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,8,24,24,{height // 6},1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    for start, end, line in lines:
        if end > start:
            text += (
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{ass_text(line)}\n"
            )
    if hook:
        text += f"Dialogue: 1,0:00:00.00,{ass_time(min(3, max((e for _, e, _ in lines), default=3)))},Hook,,0,0,0,,{ass_text(hook)}\n"
    path.write_text(text, encoding="utf-8")


def encode(
    source: Path,
    destination: Path,
    start: float,
    end: float,
    *,
    portrait: bool,
    speed: float = 1,
    subtitle_path: Path | None = None,
    framing: FramingPlan | None = None,
    caption_band: bool = False,
    hook_band: bool = False,
):
    height = get_settings().render_height
    width = (height * 9 // 16 if portrait else height * 16 // 9) // 2 * 2
    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
        f"setpts=(PTS-STARTPTS)/{speed}",
    ]
    if framing:
        filters, _ = video_filter(framing, captions=caption_band, hook=hook_band)
        filters.append(f"setpts=(PTS-STARTPTS)/{speed}")
    if subtitle_path:
        # Generated filenames contain only UUIDs; no text/path interpolation into filters.
        filters.append(f"ass={subtitle_path.name}")
    temporary = destination.with_suffix(".tmp.mp4")
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            ",".join(filters),
            "-af",
            f"atempo={speed},aresample=48000",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20" if framing else "26",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30" if framing else "24",
            "-c:a",
            "aac",
            "-b:a",
            "160k" if framing else "128k",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        cwd=destination.parent,
        timeout=get_settings().job_timeout_seconds,
    )
    temporary.replace(destination)


def render_clip(
    source: Path, clip: Clip, transcript: Transcript, directory: Path
) -> tuple[Path, dict]:
    path = directory / f"{clip.id}.mp4"
    key = clip_fingerprint(clip)
    input_key = fingerprint(
        {
            "source_size": source.stat().st_size,
            "source_mtime": source.stat().st_mtime_ns,
            "transcript": transcript.model_dump(),
        }
    )
    manifest = directory / f"{clip.id}.render.json"
    cached = json_object(manifest)
    if (
        path.exists()
        and (directory / f"{clip.id}.jpg").exists()
        and cached.get("fingerprint") == key
        and cached.get("input_fingerprint") == input_key
    ):
        return path, cached["qc"]
    started = time.monotonic()
    requested = effective_layout(clip)
    framing = tracked_plan(analyze_framing(source, clip.start_s, clip.end_s, requested), requested)
    if clip.platform != "youtube":
        # A multiple of 32 makes both sides even and preserves an exact 9:16 canvas.
        framing.height = max(32, framing.height // 32 * 32)
        framing.width = framing.height * 9 // 16
    edit = build_edl(clip, transcript)
    tokens = remap_tokens(timed_tokens(clip, transcript), clip, edit)
    captions = caption_plan(clip, transcript, framing, mapped_tokens=tokens, duration=edit.duration)
    ass = directory / f"{clip.id}.ass"
    write_ass(ass, captions, framing)
    planned = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"{clip.id}-work-", dir=directory) as temporary:
        audio, normalization = normalize_audio(source, clip, edit, Path(temporary))
        audio_done = time.monotonic()
        tracking, thumbnail, roi = encode_clip(
            source,
            path,
            clip,
            transcript,
            edit,
            framing,
            audio,
            ass,
            captions=bool(captions.cues),
            hook=bool(captions.hook_lines),
        )
        video_done = time.monotonic()
    qc = inspect_clip(path, edit.duration, framing, captions, roi, directory)
    delivery = inspect_delivery(clip, framing, qc["duration_s"])
    qc["delivery"] = delivery
    qc["checks"]["platform_format"] = delivery["format_valid"]
    qc["passed"] = all(qc["checks"].values())
    _, content_box = video_filter(
        framing, captions=bool(captions.cues), hook=bool(captions.hook_lines)
    )
    qc.update(
        {
            "framing": framing.model_dump(),
            "content_box": content_box,
            "tracking": tracking,
            "thumbnail": thumbnail,
            "normalization": normalization,
            "caption_timing": captions.timing,
            "karaoke_enabled": captions.karaoke,
            "caption_max_words": max((c.word_count for c in captions.cues), default=0),
            "caption_max_lines": max((len(c.text.splitlines()) for c in captions.cues), default=0),
            "caption_font_size": captions.font_size,
            "hook_shown": bool(captions.hook_lines),
            "retention": {
                "source_duration_s": edit.source_duration,
                "output_duration_s": edit.duration,
                "removed": edit.removed,
                "warnings": edit.warnings,
                "options": edit.options,
            },
            "timings": {
                "planning_s": round(planned - started, 3),
                "audio_s": round(audio_done - planned, 3),
                "video_s": round(video_done - audio_done, 3),
                "qc_s": round(time.monotonic() - video_done, 3),
                "total_s": round(time.monotonic() - started, 3),
            },
        }
    )
    atomic_json(
        directory / f"{clip.id}.framing.json",
        {"framing": framing.model_dump(), "content_box": content_box, "tracking": tracking},
    )
    atomic_json(directory / f"{clip.id}.edl.json", edit.model_dump())
    atomic_json(directory / f"{clip.id}.captions.json", captions.model_dump())
    atomic_json(manifest, {"fingerprint": key, "input_fingerprint": input_key, "qc": qc})
    return path, qc


def render_condensed(
    source: Path, beats: list[Beat], directory: Path, captions: bool, progress
) -> Path:
    kept = sorted((b for b in beats if b.decision != "drop"), key=lambda b: b.start_s)
    if not kept:
        raise ValueError("Tidak ada beat yang dipertahankan")
    height = get_settings().render_height
    parts = []
    for i, beat in enumerate(kept):
        key = fingerprint({"beat": beat.model_dump(), "height": height, "captions": captions})[:20]
        part = directory / f"part-{key}.mp4"
        if not part.exists():
            ass = directory / f"part-{key}.ass"
            rate = beat.speed if beat.decision == "speed" else 1
            subtitles(
                ass,
                [(0, (beat.end_s - beat.start_s) / rate, beat.text)] if captions else [],
                height * 16 // 9 // 2 * 2,
                height,
            )
            encode(
                source,
                part,
                beat.start_s,
                beat.end_s,
                portrait=False,
                speed=rate,
                subtitle_path=ass,
            )
        parts.append(part)
        progress((i + 1) / len(kept), f"Merender bagian {i + 1}/{len(kept)}")
    concat = directory / "concat.txt"
    concat.write_text("\n".join(f"file '{part.name}'" for part in parts))
    temporary = directory / "condensed.tmp.mp4"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            concat.name,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            temporary.name,
        ],
        cwd=directory,
    )
    destination = directory / "condensed.mp4"
    temporary.replace(destination)
    return destination
