from pathlib import Path

from api.app.schemas import OutputSettings, Transcript
from worker.pipeline.contracts import Moments
from worker.pipeline.llm import LLMValidationError
from worker.pipeline.selection_cache import call_stage
from worker.pipeline.signals import Signals, energy_peaks


def format_sentences(sentences) -> str:
    return "\n".join(
        f"{s.id} [{int(s.start) // 60:02d}:{int(s.start) % 60:02d}] {s.text}" for s in sentences
    )


def transcript_windows(transcript: Transcript, overlap: float):
    start = 0.0
    duration = transcript.sentences[-1].end
    while start < duration:
        end = start + 480
        sentences = [s for s in transcript.sentences if s.start < end and s.end > start]
        if sentences:
            yield sentences
        if end >= duration:
            break
        start += 480 - overlap


def find_moments(
    client,
    transcript: Transcript,
    signals: Signals,
    settings: OutputSettings,
    title: str,
    liked_examples: list[dict],
    directory: Path,
    audit: dict,
):
    found, seen = [], set()
    for index, sentences in enumerate(transcript_windows(transcript, settings.max_clip_seconds)):
        positions = {s.id: i for i, s in enumerate(sentences)}
        pace = sum(len(s.text.split()) for s in sentences) / max(
            1, sentences[-1].end - sentences[0].start
        )
        variables = {
            "video_title": title,
            "language": transcript.language,
            "min_seconds": settings.min_clip_seconds,
            "max_seconds": settings.max_clip_seconds,
            "min_words": round(settings.min_clip_seconds * pace),
            "max_words": round(settings.max_clip_seconds * pace),
            "words_per_second": round(pace, 2),
            "moment_focus": settings.focus
            + (
                "\nTujuan tutorial: pilih satu tugas beserta langkah minimum, prasyarat, dan hasil. Jangan mengorbankan konteks untuk hook."
                if settings.purpose == "tutorial"
                else "\nTujuan penemuan penonton: pilih satu ide dengan pembuka dan payoff yang utuh."
            ),
            "max_candidates": min(24, max(6, settings.clip_count * 2)),
            "energy_peaks": energy_peaks(signals, sentences[0].start, sentences[-1].end),
            "liked_examples": liked_examples[:3],
            "sentences": format_sentences(sentences),
            "sentence_data": [s.model_dump() for s in sentences],
        }
        try:
            result = call_stage(client, "moment_finder", variables, Moments, directory)
        except LLMValidationError as exc:
            audit["warnings"].append(
                {"stage": "moment_finder", "window": index, "reason": str(exc)}
            )
            continue
        for moment in result.candidates:
            a, b = positions.get(moment.start_id), positions.get(moment.end_id)
            if (
                a is None
                or b is None
                or a > b
                or moment.hook_sentence_id not in {s.id for s in sentences[a : min(b + 1, a + 2)]}
            ):
                audit["rejected"].append(
                    {
                        "stage": "moment_finder",
                        "reason": "invalid_sentence_or_hook_id",
                        **moment.model_dump(),
                    }
                )
                continue
            duration = sentences[b].end - sentences[a].start
            if not 0.8 * settings.min_clip_seconds <= duration <= 1.2 * settings.max_clip_seconds:
                audit["rejected"].append(
                    {
                        "stage": "moment_finder",
                        "reason": "duration_outside_tolerance",
                        **moment.model_dump(),
                    }
                )
                continue
            if moment.cold_open_id:
                cold = next((s for s in sentences[a : b + 1] if s.id == moment.cold_open_id), None)
                if not cold or cold.end - cold.start > 3.5:
                    moment.cold_open_id = None
            key = moment.start_id, moment.end_id
            if key not in seen:
                found.append(moment)
                seen.add(key)
        audit["windows"] += 1
    return found
