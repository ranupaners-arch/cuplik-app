"""Word-safe edit decisions and a source/output time map, including real audio overlaps."""

import math
import re
from dataclasses import asdict, dataclass, field, replace

from api.app.models import Clip
from api.app.schemas import RetentionSettings, Transcript

FILLERS = {"eh", "em", "ehm", "hmm", "emm", "um", "uh"}


@dataclass
class Span:
    src_start: float
    src_end: float
    dst_start: float = 0
    dst_end: float = 0
    fade_in: float = 0
    kind: str = "body"


@dataclass
class EditPlan:
    spans: list[Span]
    duration: float
    source_duration: float
    options: dict
    removed: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def model_dump(self):
        return asdict(self)


def schedule(spans: list[Span]) -> float:
    end = 0.0
    for i, span in enumerate(spans):
        length = 0.2 if span.kind == "transition" else span.src_end - span.src_start
        previous = spans[i - 1].dst_end - spans[i - 1].dst_start if i else 0
        span.fade_in = min(0.01, length / 4, previous / 4) if i else 0
        span.dst_start = end - span.fade_in
        span.dst_end = span.dst_start + length
        end = span.dst_end
    return end


def build_edl(clip: Clip, transcript: Transcript) -> EditPlan:
    options = RetentionSettings.model_validate(clip.retention)
    words = [
        w for w in transcript.words if w.start >= clip.start_s - 1e-6 and w.end <= clip.end_s + 1e-6
    ]
    cuts, removed, warnings = [], [], []
    corrected = {}
    uncertain = False
    for sentence in transcript.sentences:
        if sentence.start >= clip.end_s or sentence.end <= clip.start_s:
            continue
        visible = [w for w in words if w.id in sentence.word_ids]
        override = clip.caption_overrides.get(sentence.id)
        if words and not sentence.word_ids:
            uncertain = True
        if override is not None:
            if len(override.split()) != len(visible):
                uncertain = True
            else:
                corrected.update(
                    (word.id, text) for word, text in zip(visible, override.split(), strict=True)
                )
    if uncertain:
        words = []
        warnings.append(
            "Retensi waktu dilewati karena koreksi/referensi kata tidak memiliki pemetaan waktu pasti."
        )
    else:
        corrected.update(
            (w.id, clip.caption_overrides[w.id]) for w in words if w.id in clip.caption_overrides
        )
        words = [
            w.model_copy(update={"text": corrected[w.id]}) if w.id in corrected else w
            for w in words
        ]
    if options.shorten_pauses:
        for previous, following in zip(words, words[1:], strict=False):
            if following.start - previous.end > 0.35:
                # Keep 130 ms before the 10 ms overlap, yielding a 120 ms output pause.
                cuts.append((previous.end + 0.065, following.start - 0.065))
                removed.append(
                    {"kind": "pause", "start": previous.end + 0.065, "end": following.start - 0.065}
                )
    if options.remove_fillers:
        for i, word in enumerate(words):
            before = words[i - 1].end if i else clip.start_s
            after = words[i + 1].start if i + 1 < len(words) else clip.end_s
            standalone = (i == 0 or word.start - before >= 0.12) and (
                i + 1 == len(words) or after - word.end >= 0.12
            )
            if re.sub(r"[^\w]", "", word.text.casefold()) in FILLERS and standalone:
                cuts.append(
                    (
                        max(clip.start_s, (before + word.start) / 2),
                        min(clip.end_s, (word.end + after) / 2),
                    )
                )
                removed.append(
                    {
                        "kind": "filler",
                        "word_id": word.id,
                        "text": word.text,
                        "start": word.start,
                        "end": word.end,
                    }
                )
    if not words and (options.shorten_pauses or options.remove_fillers):
        warnings.append("Pemotongan jeda/pengisi dilewati karena timestamp kata tidak tersedia.")
    merged = []
    for start, end in sorted(cuts):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    cursor, spans = clip.start_s, []
    for start, end in merged:
        if start - cursor > 1e-6:
            spans.append(Span(cursor, start))
        cursor = max(cursor, end)
    if clip.end_s - cursor > 1e-6:
        spans.append(Span(cursor, clip.end_s))
    duration = schedule(spans)
    if duration < min(3, clip.end_s - clip.start_s) - 1e-6:
        spans, removed = [Span(clip.start_s, clip.end_s)], []
        warnings.append("Pemotongan dibatalkan agar klip tidak menjadi terlalu pendek.")
        duration = schedule(spans)
    if options.cold_open:
        opener = next(
            (s for s in transcript.sentences if s.id == clip.selection.get("cold_open_id")), None
        )
        if (
            opener
            and opener.start >= clip.start_s
            and opener.end <= clip.end_s
            and opener.end - opener.start <= 3.5
        ):
            body = spans
            proposed = [
                Span(opener.start, opener.end, kind="cold_open"),
                Span(max(opener.start, opener.end - 1 / 30), opener.end, kind="transition"),
                *body,
            ]
            duration = schedule(proposed)
            if duration <= 180:
                spans = proposed
            else:
                duration = schedule(body)
                warnings.append("Cold open dilewati agar hasil tidak melewati 180 detik.")
        else:
            warnings.append("Cold open tidak tersedia atau tidak valid di dalam batas klip.")
    return EditPlan(
        spans, duration, clip.end_s - clip.start_s, options.model_dump(), removed, warnings
    )


def remap_tokens(tokens, clip: Clip, plan: EditPlan):
    result = []
    for occurrence, span in enumerate(plan.spans):
        if span.kind == "transition":
            continue
        for token in tokens:
            start, end = token.start + clip.start_s, token.end + clip.start_s
            if start >= span.src_start - 1e-6 and end <= span.src_end + 1e-6:
                result.append(
                    replace(
                        token,
                        start=span.dst_start + start - span.src_start,
                        end=span.dst_start + end - span.src_start,
                        occurrence=occurrence,
                    )
                )
    return result


def zoom_at(source_time: float, clip: Clip, transcript: Transcript, plan: EditPlan) -> float:
    options = plan.options
    sentences = [s for s in transcript.sentences if s.start < clip.end_s and s.end > clip.start_s]
    zoom = 1.0
    if options["zoom"]:
        for i, sentence in enumerate(sentences):
            if sentence.start <= source_time <= sentence.end:
                target = 1.12 if i % 2 else 1.0
                previous = 1.0 if i % 2 else 1.12 if i else 1.0
                progress = min(1, max(0, (source_time - sentence.start) / 0.25))
                eased = 0.5 - 0.5 * math.cos(math.pi * progress)
                zoom = previous + (target - previous) * eased
                break
    if options["emphasis"]:
        ids = set(clip.selection.get("emphasis_word_ids", []))
        for word in transcript.words:
            if word.id in ids and word.start <= source_time < word.start + 0.6:
                phase = (source_time - word.start) / 0.6
                pulse = math.sin(math.pi * phase) ** 2
                zoom = max(zoom, 1 + 0.2 * pulse)
    return zoom
