from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError
from sqlmodel import Session, select

from api.app.models import Clip, Output
from api.app.schemas import OutputSettings, Transcript
from worker.pipeline.moments import find_moments
from worker.pipeline.rerank import rerank
from worker.pipeline.scoring import score_moments
from worker.pipeline.signals import Signals
from worker.pipeline.storage import atomic_json, project_dir


def liked_examples(session: Session, purpose: str | None = None) -> list[dict]:
    query = select(Clip, Output).where(Clip.rating == "up")
    if purpose:
        query = query.where(Clip.purpose == purpose)
    liked = session.exec(
        query.join(Output, Clip.output_id == Output.id)
        .order_by(Output.created_at.desc(), Clip.rank)
        .limit(20)
    ).all()
    result = []
    for clip, output in liked:
        path = project_dir(output.project_id) / "transcript.json"
        try:
            transcript = Transcript.model_validate_json(path.read_text())
        except (OSError, ValidationError):
            continue
        sentences = [
            s for s in transcript.sentences if s.start < clip.end_s and s.end > clip.start_s
        ]
        if sentences:
            result.append(
                {
                    "first_sentence": sentences[0].text,
                    "last_sentence": sentences[-1].text,
                    "duration": round(clip.end_s - clip.start_s, 2),
                    "note": clip.rating_note,
                    "purpose": clip.purpose,
                    "platform": clip.platform,
                }
            )
        if len(result) == 3:
            break
    return result


def select_clips(
    client,
    transcript: Transcript,
    signals: Signals,
    settings: OutputSettings,
    title: str,
    examples: list[dict],
    directory: Path,
    progress=None,
):
    audit = {
        "version": 1,
        "provider": client.settings.llm_provider,
        "model": "deterministic-fixture"
        if client.settings.llm_provider == "mock"
        else client.settings.llm_model_fast,
        "signals_fingerprint": signals.fingerprint,
        "settings": settings.model_dump(),
        "windows": 0,
        "liked_examples_used": len(examples[:3]),
        "warnings": [],
        "rejected": [],
    }
    try:
        moments = find_moments(
            client, transcript, signals, settings, title, examples, directory, audit
        )
        if progress:
            progress("scoring", 0.23, f"Menilai {len(moments)} kandidat dalam batch enam")
        scored = score_moments(client, moments, transcript, signals, settings, directory, audit)
        if progress:
            progress(
                "rerank", 0.3, f"Mengurutkan maksimal 20 finalis dari {len(scored)} kandidat valid"
            )
        accepted = rerank(client, scored, settings.clip_count, directory, audit)
        audit["candidates"] = [
            asdict(c) | {"moment": c.moment.model_dump(), "packaging": c.packaging.model_dump()}
            for c in scored
        ]
        if not accepted:
            raise ValueError(
                "Tidak ada klip valid setelah seleksi dan validasi batas kata. Coba fokus atau rentang durasi lain; lihat selection.json untuk alasan penolakan."
            )
        audit["status"] = "complete"
        return accepted
    except Exception:
        audit["status"] = "failed"
        raise
    finally:
        atomic_json(directory / "selection.json", audit)
