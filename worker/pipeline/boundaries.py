import re
from dataclasses import dataclass

from api.app.schemas import OutputSettings, Transcript
from worker.pipeline.contracts import Moment, ScoredClip

FILLERS = {"eh", "em", "ehm", "hmm", "jadi", "oke", "okay", "ok", "nah"}


def iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    overlap = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    return overlap / max(a[1] - a[0] + b[1] - b[0] - overlap, 1e-6)


@dataclass
class Boundary:
    start: float
    end: float
    start_id: str
    end_id: str
    precision: str
    word_ids: list[str]


def snap_boundaries(
    moment: Moment,
    scored: ScoredClip,
    transcript: Transcript,
    settings: OutputSettings,
    duration: float,
) -> Boundary:
    positions = {s.id: i for i, s in enumerate(transcript.sentences)}
    a, b = positions[moment.start_id], positions[moment.end_id]
    first = scored.trim_start_id or moment.start_id
    last = scored.trim_end_id or moment.end_id
    if (
        first not in positions
        or last not in positions
        or not a <= positions[first] <= positions[last] <= b
    ):
        raise ValueError("Trim harus merupakan rentang kalimat di dalam kandidat")
    a, b = positions[first], positions[last]
    selected = transcript.sentences[a : b + 1]
    first_s, last_s = selected[0], selected[-1]
    start, end = first_s.start, last_s.end
    precision = "sentence_only"
    all_words = transcript.words
    selected_words = [w for w in all_words if w.start < end and w.end > start]
    if selected_words:
        if any(not s.word_ids for s in selected):
            raise ValueError("Referensi kata tidak lengkap; sertakan word_ids untuk setiap kalimat")
        precision = "word"
        # Snap outward, including any word that straddles a sidecar sentence boundary.
        start, end = selected_words[0].start, selected_words[-1].end
        if len(selected_words) > 1:
            word, following = selected_words[:2]
            if (
                re.sub(r"[^\w]", "", word.text.casefold()) in FILLERS
                and following.start - word.end >= 0.25
            ):
                selected_words = selected_words[1:]
                start = following.start
        previous = max((w.end for w in all_words if w.end <= start), default=0)
        following = min((w.start for w in all_words if w.start >= end), default=duration)
    else:
        # Do not fabricate word timestamps for old sentence-only user sidecars.
        if (
            a < b
            and re.sub(r"[^\w]", "", first_s.text.casefold()) in FILLERS
            and selected[1].start - first_s.end >= 0.25
        ):
            a += 1
            first_s = transcript.sentences[a]
            start = first_s.start
        previous = transcript.sentences[a - 1].end if a else 0
        following = (
            transcript.sentences[b + 1].start if b + 1 < len(transcript.sentences) else duration
        )
    speech_start = selected_words[0].start if selected_words else first_s.start
    speech_end = selected_words[-1].end if selected_words else last_s.end
    if speech_end > duration + 1e-6:
        raise ValueError("Kata/kalimat berakhir di luar sumber; tidak boleh dipotong")
    # Padding is clipped to free space; it never includes a neighbour's spoken word.
    start = max(0, previous, start - 0.12)
    end = min(duration, following, end + 0.25)
    # If padding alone would cross max, remove padding, never cut through speech.
    if end - start > min(180, settings.max_clip_seconds):
        start, end = speech_start, speech_end
    if (
        not settings.min_clip_seconds - 1e-6
        <= end - start
        <= min(180, settings.max_clip_seconds) + 1e-6
    ):
        raise ValueError("Durasi akhir klip di luar batas; kata tidak dipotong untuk memaksakannya")
    return Boundary(
        round(start, 6),
        round(end, 6),
        first_s.id,
        last_s.id,
        precision,
        [w.id for w in selected_words],
    )
