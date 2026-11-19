from collections import Counter

from api.app.schemas import OutlinePlan, Selection, Transcript


def validate_selection(selection: Selection, transcript: Transcript, maximum: float, count: int):
    by_id = {s.id: s for s in transcript.sentences}
    topics = Counter()
    accepted = []
    for candidate in selection.candidates:
        if candidate.start_id not in by_id or candidate.end_id not in by_id:
            raise ValueError(
                "LLM memilih ID kalimat yang tidak ada; tidak ada rentang rekaan yang dirender."
            )
        start, end = by_id[candidate.start_id].start, by_id[candidate.end_id].end
        if start >= end or end - start > maximum + 0.01:
            continue
        if topics[candidate.topic.casefold()] >= 2:
            continue
        duplicate = False
        for _, a, b in accepted:
            intersection = max(0, min(end, b) - max(start, a))
            union = max(end, b) - min(start, a)
            if intersection / union > 0.3:
                duplicate = True
                break
        if duplicate:
            continue
        accepted.append((candidate, start, end))
        topics[candidate.topic.casefold()] += 1
        if len(accepted) >= count:
            break
    if not accepted:
        raise ValueError(
            "Tidak ada klip valid dalam batas durasi. Coba fokus atau panjang klip lain."
        )
    return accepted


def validate_outline(plan: OutlinePlan, transcript: Transcript):
    positions = {s.id: i for i, s in enumerate(transcript.sentences)}
    expected = 0
    result = []
    for chapter in plan.chapters:
        if chapter.start_id not in positions or chapter.end_id not in positions:
            raise ValueError("Outline berisi ID kalimat yang tidak ada.")
        start, end = positions[chapter.start_id], positions[chapter.end_id]
        if start != expected or end < start:
            raise ValueError(
                "Bab harus berurutan, tidak tumpang tindih, dan mencakup semua kalimat."
            )
        sentences = transcript.sentences[start : end + 1]
        ids = {s.id for s in sentences}
        if not set(chapter.required_sentence_ids).issubset(ids):
            raise ValueError("Kalimat wajib berada di luar babnya.")
        result.append((chapter, sentences))
        expected = end + 1
    if expected != len(transcript.sentences):
        raise ValueError("Outline belum mencakup seluruh transkrip.")
    return result
