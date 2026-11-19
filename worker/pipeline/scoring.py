from dataclasses import dataclass
from pathlib import Path

from api.app.schemas import OutputSettings, Transcript
from worker.pipeline.boundaries import Boundary, snap_boundaries
from worker.pipeline.contracts import Moment, ScoredClip, Scores
from worker.pipeline.llm import LLMValidationError
from worker.pipeline.selection_cache import call_stage
from worker.pipeline.signals import Signals, mean_iq


@dataclass
class Finalist:
    id: str
    moment: Moment
    packaging: ScoredClip
    boundary: Boundary
    text: str
    base_score: float
    viral: float
    delta_iq: float
    iq: float
    rerank_note: str = ""


def base_score(scores, clip_iq: float, video_mean: float, video_std: float):
    viral = scores.weighted()
    delta = max(-0.5, min(0.5, (clip_iq - video_mean) / max(video_std, 1e-6) * 0.25))
    return round(max(0, min(10, viral + delta)), 1), viral, delta


def candidate_payload(identifier: str, moment: Moment, transcript: Transcript):
    positions = {s.id: i for i, s in enumerate(transcript.sentences)}
    a, b = positions[moment.start_id], positions[moment.end_id]
    sentences = transcript.sentences[a : b + 1]
    words = {w.id: w for w in transcript.words}
    text = []
    for s in sentences:
        if s.word_ids:
            parts = [
                f"{words[w].text}({w})" if len(words[w].text) >= 4 else words[w].text
                for w in s.word_ids
            ]
            text.append(f"{s.id}: {' '.join(parts)}")
        else:
            text.append(f"{s.id}: {s.text}")
    return {
        "id": identifier,
        "duration": round(sentences[-1].end - sentences[0].start, 3),
        "context_before": " ".join(s.text for s in transcript.sentences[max(0, a - 2) : a]),
        "context_after": " ".join(s.text for s in transcript.sentences[b + 1 : b + 3]),
        "words_with_ids": "\n".join(text),
        "raw_text": " ".join(s.text for s in sentences),
    }


def score_moments(
    client,
    moments: list[Moment],
    transcript: Transcript,
    signals: Signals,
    settings: OutputSettings,
    directory: Path,
    audit: dict,
):
    found = []
    for offset in range(0, len(moments), 6):
        batch = {f"c{i + 1}": m for i, m in enumerate(moments[offset : offset + 6], start=offset)}
        variables = {
            "language": transcript.language,
            "output_language": transcript.language,
            "audience": f"Tujuan {settings.purpose}; platform {settings.platform}. Untuk tutorial, nilai apakah langkah dan hasil dapat diikuti, serta pertahankan konteks.",
            "moment_focus": settings.focus,
            "candidates": [
                candidate_payload(identifier, m, transcript) for identifier, m in batch.items()
            ],
        }
        try:
            result = call_stage(client, "scorer", variables, Scores, directory)
        except LLMValidationError as exc:
            audit["warnings"].append({"stage": "scorer", "batch": offset // 6, "reason": str(exc)})
            continue
        seen = set()
        duplicates = {
            c.id for c in result.clips if sum(item.id == c.id for item in result.clips) > 1
        }
        for c in result.clips:
            if c.id not in batch or c.id in duplicates:
                audit["rejected"].append(
                    {"stage": "scorer", "id": c.id, "reason": "unknown_or_duplicate_candidate_id"}
                )
                continue
            seen.add(c.id)
            try:
                boundary = snap_boundaries(batch[c.id], c, transcript, settings, signals.duration_s)
            except ValueError as exc:
                audit["rejected"].append({"stage": "boundaries", "id": c.id, "reason": str(exc)})
                continue
            word_map = {w.id: w for w in transcript.words}
            if boundary.word_ids:
                tokens = [word_map[w].text for w in boundary.word_ids]
                text = " ".join(tokens)
            else:
                text = " ".join(
                    s.text
                    for s in transcript.sentences
                    if s.start < boundary.end and s.end > boundary.start
                )
                tokens = text.split()
            # Unsafe annotations are removed, never rendered or sent as true assertions.
            original = (
                list(c.keywords),
                list(c.emphasis_word_ids),
                [e.model_dump() for e in c.emoji],
            )
            c.keywords = list(
                dict.fromkeys(
                    w for w in c.keywords if w in tokens and not any(ch.isspace() for ch in w)
                )
            )
            c.emphasis_word_ids = list(
                dict.fromkeys(w for w in c.emphasis_word_ids if w in boundary.word_ids)
            )
            c.emoji = [e for e in c.emoji if e.word in tokens]
            if original != (c.keywords, c.emphasis_word_ids, [e.model_dump() for e in c.emoji]):
                audit["warnings"].append(
                    {"stage": "scorer", "id": c.id, "reason": "non_verbatim_annotations_removed"}
                )
            iq = mean_iq(signals, boundary.start, boundary.end)
            score, viral, delta = base_score(c.scores, iq, signals.mean, signals.std)
            found.append(Finalist(c.id, batch[c.id], c, boundary, text, score, viral, delta, iq))
        for missing in batch.keys() - seen:
            audit["rejected"].append({"stage": "scorer", "id": missing, "reason": "missing_score"})
    return found
