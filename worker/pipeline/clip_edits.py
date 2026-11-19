"""Validated manual edits share the same word IDs and source clock as rendering."""

from api.app.schemas import Transcript


def caption_ids(transcript: Transcript, start: float, end: float):
    sentences = [s for s in transcript.sentences if s.start < end and s.end > start]
    words = {w.id for w in transcript.words if w.start < end and w.end > start}
    return {s.id for s in sentences} | words


def validate_overrides(overrides: dict[str, str], valid: set[str]):
    if not set(overrides).issubset(valid):
        raise ValueError("Koreksi caption harus memakai ID kata/kalimat di dalam klip")
    for identifier, text in overrides.items():
        if not text.strip() or len(text) > 4000:
            raise ValueError("Koreksi caption tidak boleh kosong atau terlalu panjang")
        if identifier.startswith("w") and (len(text) > 500 or any(c.isspace() for c in text)):
            raise ValueError("Koreksi kata harus tetap satu kata agar timestamp tidak berubah")


def preserve_trimmed_overrides(overrides, transcript, old_start, old_end, start, end):
    result = dict(overrides)
    words = {w.id: w for w in transcript.words}
    for sentence in transcript.sentences:
        if sentence.id not in result:
            continue
        visible = [
            words[w]
            for w in sentence.word_ids
            if words[w].start < old_end and words[w].end > old_start
        ]
        retained = [w for w in visible if w.start < end and w.end > start]
        if not visible or len(retained) == len(visible):
            continue
        parts = result.pop(sentence.id).split()
        if not retained:
            continue
        if len(parts) != len(visible):
            raise ValueError(
                f"Pulihkan kata asli caption {sentence.id} sebelum memangkas sebagian kalimat; jumlah kata koreksi tidak memiliki timestamp pasti"
            )
        for word, text in zip(visible, parts, strict=True):
            result.setdefault(word.id, text)
    return result


def snap_manual_range(transcript: Transcript, start: float, end: float, duration: float):
    if not 0 <= start < end <= duration + 0.001:
        raise ValueError("Batas klip harus berurutan dan berada di dalam durasi sumber")
    units = transcript.words or transcript.sentences
    a = min(units, key=lambda w: (abs(w.start - start), w.start))
    b = min(units, key=lambda w: (abs(w.end - end), w.end))
    start, end = a.start, b.end
    if not 1 <= end - start <= 180 or end > duration + 0.001:
        raise ValueError("Setelah snap, durasi klip harus 1–180 detik dan berada di dalam sumber")
    return start, end, "word" if transcript.words else "sentence"
