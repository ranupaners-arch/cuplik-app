"""Timed short phrases with measured typography; never whole paragraphs on screen."""

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from api.app.models import Clip
from api.app.schemas import RetentionSettings, Transcript
from worker.pipeline.framing import FramingPlan

VERSION = 1


@lru_cache(maxsize=1)
def font_spec() -> tuple[str, str]:
    if shutil.which("fc-match"):
        result = subprocess.run(
            ["fc-match", "-f", "%{file}\n%{family}\n", "DejaVu Sans:style=Bold"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.splitlines()
        if len(result) >= 2 and Path(result[0]).is_file():
            return result[0], result[1].split(",")[0]
    for path, family in [
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "Arial"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu Sans"),
        ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ]:
        if Path(path).is_file():
            return path, family
    raise RuntimeError(
        "Font caption tidak tersedia. Pasang fontconfig dan fonts-dejavu-core (Linux) atau Arial (macOS)."
    )


@dataclass
class Token:
    start: float
    end: float
    text: str
    sentence_id: str
    estimated: bool = False
    word_id: str | None = None
    occurrence: int = 0


@dataclass
class Cue:
    start: float
    end: float
    text: str
    font_size: int
    word_count: int
    tokens: list[Token] = field(default_factory=list)


@dataclass
class CaptionPlan:
    font_family: str
    font_size: int
    cues: list[Cue]
    hook_lines: str
    hook_font_size: int
    hook_end: float
    timing: str
    max_width: int
    karaoke: bool = False
    keywords: list[str] = field(default_factory=list)

    def model_dump(self):
        return asdict(self)


def timed_tokens(clip: Clip, transcript: Transcript) -> list[Token]:
    words = {w.id: w for w in transcript.words}
    result = []
    for s in transcript.sentences:
        start, end = max(clip.start_s, s.start), min(clip.end_s, s.end)
        if start >= end:
            continue
        visible = [words[w] for w in s.word_ids if words[w].start < end and words[w].end > start]
        override = clip.caption_overrides.get(s.id)
        if visible and override is None:
            result.extend(
                Token(
                    max(start, w.start) - clip.start_s,
                    min(end, w.end) - clip.start_s,
                    w.text,
                    s.id,
                    False,
                    w.id,
                )
                for w in visible
            )
        elif visible and override is not None and len(override.split()) == len(visible):
            result.extend(
                Token(
                    max(start, w.start) - clip.start_s,
                    min(end, w.end) - clip.start_s,
                    text,
                    s.id,
                    False,
                    w.id,
                )
                for w, text in zip(visible, override.split(), strict=True)
            )
        else:
            parts = (override if override is not None else s.text).split()
            span = end - start
            # Estimated timing is explicit for sentence-only sidecars and word-count edits.
            result.extend(
                Token(
                    start - clip.start_s + span * i / len(parts),
                    start - clip.start_s + span * (i + 1) / len(parts),
                    text,
                    s.id,
                    True,
                )
                for i, text in enumerate(parts)
            )
    for token in result:
        if token.word_id and token.word_id in clip.caption_overrides:
            token.text = clip.caption_overrides[token.word_id]
    return result


def wrap_text(
    text: str, font_path: str, size: int, width: int, *, minimum_size: int
) -> tuple[str, int]:
    """Use real glyph widths, at most two explicit lines; long words shrink to fit."""
    for chosen_size in range(size, minimum_size - 1, -1):
        font = ImageFont.truetype(font_path, chosen_size)
        lines = [""]
        valid = True
        for word in text.split():
            if font.getlength(word) > width:
                valid = False
                break
            trial = (lines[-1] + " " + word).strip()
            if font.getlength(trial) <= width:
                lines[-1] = trial
            else:
                lines.append(word)
        if valid and len(lines) <= 2:
            return "\n".join(lines), chosen_size
    # Pathological unbroken text: scale via ASS ScaleX, determined in write_ass below.
    return text, minimum_size


def caption_plan(
    clip: Clip,
    transcript: Transcript,
    framing: FramingPlan,
    *,
    mapped_tokens: list[Token] | None = None,
    duration: float | None = None,
) -> CaptionPlan:
    font_path, family = font_spec()
    portrait = framing.width < framing.height
    font_size = max(2, round(framing.height * (0.027 if portrait else 0.032)))
    max_width = round(framing.width * 0.84)
    minimum_size = max(2, round(font_size * 0.72))
    maximum_words = 3 if portrait else 5
    tokens = timed_tokens(clip, transcript) if mapped_tokens is None else mapped_tokens
    options = RetentionSettings.model_validate(clip.retention)
    groups = []
    current = []
    for token in tokens:
        if current and (
            len(current) >= maximum_words
            or token.sentence_id != current[0].sentence_id
            or token.occurrence != current[0].occurrence
            or token.start - current[-1].end >= 0.35
            or token.end - current[0].start > 2.2
        ):
            groups.append(current)
            current = []
        if current:
            trial = " ".join(t.text for t in [*current, token])
            wrapped, _ = wrap_text(trial, font_path, font_size, max_width, minimum_size=font_size)
            font = ImageFont.truetype(font_path, font_size)
            if len(wrapped.splitlines()) > 2 or any(
                font.getlength(line) > max_width for line in wrapped.splitlines()
            ):
                groups.append(current)
                current = []
        current.append(token)
    if current:
        groups.append(current)
    cues = []
    for group in groups:
        text, size = wrap_text(
            " ".join(t.text for t in group),
            font_path,
            font_size,
            max_width,
            minimum_size=minimum_size,
        )
        if options.emoji:
            emoji = next(
                (
                    e.get("emoji", "")
                    for e in clip.emoji
                    if e.get("word") in {t.text for t in group}
                ),
                "",
            )
            if emoji:
                proposed, proposed_size = wrap_text(
                    text.replace("\n", " ") + " " + emoji,
                    font_path,
                    font_size,
                    max_width,
                    minimum_size=minimum_size,
                )
                if len(proposed.splitlines()) <= 2:
                    text, size = proposed, proposed_size
        cues.append(Cue(group[0].start, group[-1].end, text, size, len(group), group))
    # Screen/context footage gets the full visual area; packaging remains in metadata.
    hook = " ".join(clip.hook_options[clip.hook_choice].split()[:8])
    first_words = {re.sub(r"\W", "", t.text).casefold() for t in tokens[:12]}
    hook_words = {w.casefold() for w in re.findall(r"\w+", hook)}
    duplicate = bool(hook_words) and len(hook_words & first_words) / len(hook_words) >= 0.65
    show_hook = portrait and framing.content_kind == "speaker" and not duplicate
    hook_size = max(2, round(framing.height * 0.03))
    hook_lines, hook_size = (
        wrap_text(
            hook, font_path, hook_size, max_width, minimum_size=max(2, round(hook_size * 0.72))
        )
        if show_hook
        else ("", hook_size)
    )
    estimated = sum(t.estimated for t in tokens)
    timing = (
        "sentence_estimate"
        if estimated == len(tokens)
        else "mixed_estimate"
        if estimated
        else "word"
    )
    return CaptionPlan(
        family,
        font_size,
        cues if clip.captions else [],
        hook_lines,
        hook_size,
        min(2, duration if duration is not None else clip.end_s - clip.start_s),
        timing,
        max_width,
        clip.captions and options.karaoke and any(not t.estimated for t in tokens),
        clip.keywords if options.keyword_highlights else [],
    )


def ass_time(seconds: float) -> str:
    ticks = max(0, round(seconds * 100))
    return f"{ticks // 360000}:{ticks // 6000 % 60:02d}:{ticks // 100 % 60:02d}.{ticks % 100:02d}"


def ass_text(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", r"\N")


def cue_markup(cue: Cue, plan: CaptionPlan) -> str:
    painted, index = [], 0
    for line in cue.text.splitlines():
        parts = []
        for word in line.split():
            token = cue.tokens[index] if index < len(cue.tokens) else None
            if word in plan.keywords:
                color = r"{\1c&H4DE1FF&}"
            elif plan.karaoke and token is not None and not token.estimated:
                start, end = (
                    round((token.start - cue.start) * 1000),
                    round((token.end - cue.start) * 1000),
                )
                color = f"{{\\1c&HFFFFFF&\\t({start},{start + 1},\\1c&H4DE1FF&)\\t({end},{end + 1},\\1c&HFFFFFF&)}}"
            else:
                color = r"{\1c&HFFFFFF&}"
            parts.append(color + ass_text(word))
            index += 1
        painted.append(" ".join(parts))
    return r"\N".join(painted)


def write_ass(path: Path, plan: CaptionPlan, framing: FramingPlan):
    width, height = framing.width, framing.height
    outline = max(0.6, round(height * 0.0012, 2))
    margin = round(width * 0.08)
    text = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,{plan.font_family},{plan.font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,{margin},{margin},0,1
Style: Hook,{plan.font_family},{plan.hook_font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,{margin},{margin},0,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    font_path, _ = font_spec()
    items = [
        (
            cue.start,
            cue.end,
            cue.text,
            cue.font_size,
            "Caption",
            0.94 * height,
            cue_markup(cue, plan),
        )
        for cue in plan.cues
    ]
    if plan.hook_lines:
        items.append(
            (
                0,
                plan.hook_end,
                plan.hook_lines,
                plan.hook_font_size,
                "Hook",
                0.05 * height,
                ass_text(plan.hook_lines),
            )
        )
    for start, end, line, size, style, y, markup in items:
        if round(end * 100) <= round(start * 100):
            continue
        measured = max(
            ImageFont.truetype(font_path, size).getlength(part) for part in line.splitlines()
        )
        horizontal_scale = min(100, 100 * plan.max_width / max(measured, 1))
        tags = f"{{\\an5\\pos({width // 2},{round(y)})\\fs{size}\\fscx{horizontal_scale:.2f}}}"
        text += f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{tags}{markup}\n"
    path.write_text(text, encoding="utf-8")
