import logging
from dataclasses import dataclass

from sqlmodel import Session, select

from api.app.config import get_settings
from api.app.db import get_engine
from api.app.jobs import emit
from api.app.models import Beat, Chapter, Clip, Output, Project
from api.app.schemas import OutlinePlan, OutputSettings, Transcript
from worker.pipeline.chapters import write_chapter_export
from worker.pipeline.coherence import check_coherence
from worker.pipeline.ingest import ingest_project as ingest_project
from worker.pipeline.llm import LLMClient
from worker.pipeline.media import probe_file
from worker.pipeline.planning import validate_outline
from worker.pipeline.provenance import project_snapshot
from worker.pipeline.render import clip_fingerprint, render_clip, render_condensed
from worker.pipeline.selection import liked_examples, select_clips
from worker.pipeline.signals import build_signals
from worker.pipeline.storage import atomic_json, file_lock, output_dir, project_dir
from worker.pipeline.vision import VALUES, plan_visual_outline

logger = logging.getLogger(__name__)


@dataclass
class StageContext:
    output_id: str

    def progress(self, stage: str, fraction: float, note: str, *, status: str = "running"):
        with Session(get_engine()) as session:
            output = session.get(Output, self.output_id)
            output.stage, output.progress, output.note, output.status = (
                stage,
                round(fraction, 4),
                note,
                status,
            )
            output.error = None
            emit(session, output)
            session.commit()


def _select_clips(
    output: Output, transcript: Transcript, session: Session, client: LLMClient, ctx: StageContext
):
    output.provider = client.settings.llm_provider
    session.add(output)
    session.commit()
    settings = OutputSettings.model_validate(output.settings)
    project = session.get(Project, output.project_id)
    ctx.progress("signals", 0.1, "Menghitung Moment IQ dari audio, transkrip, dan adegan")
    signals = build_signals(project_dir(output.project_id), transcript, project.duration_s)
    ctx.progress("moments", 0.15, "Mencari momen pada jendela delapan menit dengan overlap")
    accepted = select_clips(
        client,
        transcript,
        signals,
        settings,
        project.title,
        liked_examples(session, settings.purpose),
        output_dir(output.id),
        ctx.progress,
    )
    for i, item in enumerate(accepted):
        c = item.packaging
        session.add(
            Clip(
                output_id=output.id,
                rank=i + 1,
                start_s=item.boundary.start,
                end_s=item.boundary.end,
                topic=c.topic,
                titles=c.titles,
                hook_options=c.hook_texts,
                score=item.base_score,
                rubric=c.scores.model_dump(),
                reason=c.reason,
                captions=settings.captions,
                purpose=settings.purpose,
                platform=settings.platform,
                layout=settings.layout,
                retention=settings.retention.model_dump(),
                visual_focus=settings.visual_focus.model_dump(),
                description=c.description,
                hashtags=c.hashtags,
                keywords=c.keywords,
                emoji=[e.model_dump() for e in c.emoji],
                selection={
                    "candidate_id": item.id,
                    "start_id": item.boundary.start_id,
                    "end_id": item.boundary.end_id,
                    "boundary_precision": item.boundary.precision,
                    "word_ids": item.boundary.word_ids,
                    "viral": item.viral,
                    "delta_iq": item.delta_iq,
                    "iq_mean": item.iq,
                    "rerank_note": item.rerank_note,
                    "hook_sentence_id": item.moment.hook_sentence_id,
                    "cold_open_id": item.moment.cold_open_id,
                    "emphasis_word_ids": c.emphasis_word_ids,
                },
            )
        )
    session.commit()


def _outline(
    output: Output, transcript: Transcript, session: Session, client: LLMClient, ctx: StageContext
):
    output.provider = client.settings.llm_provider
    session.add(output)
    session.commit()
    directory = output_dir(output.id)
    if OutputSettings.model_validate(output.settings).condense_vision.enabled:
        project = session.get(Project, output.project_id)
        plan, annotations, frames, report = plan_visual_outline(
            output,
            project_dir(output.project_id) / "source.mp4",
            transcript,
            project.duration_s,
            client,
            ctx.progress,
        )
        atomic_json(directory / "vision.json", report.model_dump())
        for index, (item, members) in enumerate(plan, 1):
            chapter = Chapter(
                output_id=output.id,
                order=index,
                title=item.title,
                goal=item.goal,
                importance=item.importance,
                required=item.importance == "core",
            )
            session.add(chapter)
            session.flush()
            required = set(item.required_beat_ids)
            first_step = next(
                (b.id for b in members if annotations[b.id].label == "step"), members[0].id
            )
            required.add(first_step)
            first_result = next(
                (
                    b.id
                    for b in members
                    if annotations[b.id].label == "result" and b.end_s - b.start_s >= 2
                ),
                None,
            )
            if first_result:
                required.add(first_result)
            for draft in members:
                annotation = annotations[draft.id]
                uncertain = annotation.uncertain or any(f.uncertain for f in frames[draft.id])
                protected = (
                    draft.id in required
                    or bool(annotation.specs)
                    or annotation.label == "spec"
                    or (draft.kind == "visual" and uncertain)
                )
                session.add(
                    Beat(
                        output_id=output.id,
                        chapter_id=chapter.id,
                        sentence_id=draft.sentence_id,
                        start_s=draft.start_s,
                        end_s=draft.end_s,
                        text=draft.text,
                        kind=draft.kind,
                        label=annotation.label,
                        importance=VALUES[annotation.label],
                        required=protected,
                        visual_desc=" | ".join(f.action for f in frames[draft.id]),
                        evidence={
                            **annotation.model_dump(),
                            "activity": draft.activity,
                            "uncertain": uncertain,
                            "frame_ids": [f.id for f in frames[draft.id]],
                        },
                    )
                )
        session.commit()
        return
    plan = client.call_json(
        "outline",
        {
            "sentences": [s.model_dump() for s in transcript.sentences],
            "focus": output.settings.get("focus", ""),
        },
        OutlinePlan,
        directory / "llm_log.jsonl",
    )
    validated = validate_outline(plan, transcript)
    for i, (item, sentences) in enumerate(validated):
        chapter = Chapter(
            output_id=output.id,
            order=i + 1,
            title=item.title,
            goal=item.goal,
            importance=item.importance,
            required=item.importance == "core",
        )
        session.add(chapter)
        session.flush()
        required = set(item.required_sentence_ids) | {sentences[0].id}
        for sentence in sentences:
            session.add(
                Beat(
                    output_id=output.id,
                    chapter_id=chapter.id,
                    sentence_id=sentence.id,
                    start_s=sentence.start,
                    end_s=sentence.end,
                    text=sentence.text,
                    required=sentence.id in required,
                )
            )
    session.commit()


def run_output(output_id: str, render_only: bool = False, clip_id: str | None = None):
    with Session(get_engine()) as session:
        output = session.get(Output, output_id)
        if output is None:
            raise ValueError("Output tidak ditemukan")
        project_id = output.project_id
    with file_lock(project_dir(project_id) / ".source.lock"):
        _run_output(output_id, render_only, clip_id)


def _run_output(output_id: str, render_only: bool = False, clip_id: str | None = None):
    ctx = StageContext(output_id)
    directory = output_dir(output_id)
    with file_lock(directory / ".output.lock"):
        try:
            with Session(get_engine()) as session:
                output = session.get(Output, output_id)
                if not output:
                    raise ValueError("Output tidak ditemukan")
                project_id, mode = output.project_id, output.mode
            ctx.progress(
                "ingest", 0.02, "Menyiapkan sumber dan transkrip; cache proyek dipakai kembali"
            )
            ingest_project(project_id, source_locked=True)
            source = project_dir(project_id) / "source.mp4"
            transcript = Transcript.model_validate_json(
                (source.parent / "transcript.json").read_text()
            )
            with Session(get_engine()) as session:
                output = session.get(Output, output_id)
                snapshot, _ = project_snapshot(project_id)
                if output.provenance and output.provenance != snapshot:
                    raise ValueError(
                        "Sumber atau transkrip berubah sejak rencana output dibuat. Buat output baru agar hasil tidak memakai rencana lama."
                    )
                has_plan = (
                    session.exec(select(Clip.id).where(Clip.output_id == output_id)).first()
                    if mode == "clips"
                    else session.exec(
                        select(Chapter.id).where(Chapter.output_id == output_id)
                    ).first()
                )
                if not output.provenance and not has_plan:
                    output.provenance = snapshot
                    session.add(output)
                    session.commit()
                client = LLMClient()
                if mode == "clips":
                    clips = session.exec(
                        select(Clip).where(Clip.output_id == output_id).order_by(Clip.rank)
                    ).all()
                    if not clips:
                        ctx.progress(
                            "llm", 0.15, "Memilih momen, memvalidasi ID, dan mengurutkan kandidat"
                        )
                        _select_clips(output, transcript, session, client, ctx)
                        clips = session.exec(
                            select(Clip).where(Clip.output_id == output_id).order_by(Clip.rank)
                        ).all()
                    for i, clip in enumerate(clips):
                        if clip_id and clip.id != clip_id:
                            continue
                        ctx.progress(
                            "render",
                            0.35 + 0.6 * i / len(clips),
                            f"Merender klip {i + 1}/{len(clips)}",
                        )
                        path, qc = render_clip(source, clip, transcript, directory)
                        clip.file_path = str(path.relative_to(get_settings().storage))
                        clip.qc, clip.render_fingerprint = qc, clip_fingerprint(clip)
                        thumbnail = directory / f"{clip.id}.jpg"
                        if thumbnail.exists():
                            clip.thumb_path = str(thumbnail.relative_to(get_settings().storage))
                        session.add(clip)
                        session.commit()
                else:
                    chapters = session.exec(
                        select(Chapter).where(Chapter.output_id == output_id)
                    ).all()
                    if not chapters:
                        ctx.progress("outline", 0.2, "Menyusun bab dari transkrip untuk ditinjau")
                        _outline(output, transcript, session, client, ctx)
                    if not render_only:
                        ctx.progress(
                            "review",
                            0.4,
                            "Tinjau bab wajib dan durasi target sebelum render",
                            status="awaiting_review",
                        )
                        return
                    beats = list(
                        session.exec(select(Beat).where(Beat.output_id == output_id)).all()
                    )
                    chapters = list(
                        session.exec(select(Chapter).where(Chapter.output_id == output_id)).all()
                    )
                    settings = OutputSettings.model_validate(output.settings)
                    if settings.coherence_enabled:
                        report = check_coherence(
                            output, beats, chapters, client, directory, ctx.progress
                        )
                        for beat in beats:
                            session.add(beat)
                        for chapter in chapters:
                            chapter.kept_s = sum(
                                (b.end_s - b.start_s) / b.speed
                                for b in beats
                                if b.chapter_id == chapter.id and b.decision != "drop"
                            )
                            session.add(chapter)
                        output.actual_duration_s = sum(c.kept_s for c in chapters)
                        session.add(output)
                        session.commit()
                        if report.status == "needs_review":
                            ctx.progress("review", 0.4, report.note, status="awaiting_review")
                            return
                    path = render_condensed(
                        source,
                        beats,
                        directory,
                        output.settings.get("captions", True),
                        lambda fraction, note: ctx.progress("render", 0.45 + 0.5 * fraction, note),
                        settings=settings,
                        chapters=chapters,
                    )
                    output = session.get(Output, output_id)
                    output.actual_duration_s = probe_file(path)["duration_s"]
                    session.commit()
                    chapters = session.exec(
                        select(Chapter)
                        .where(Chapter.output_id == output_id)
                        .order_by(Chapter.order)
                    ).all()
                    write_chapter_export(directory, list(chapters))
            ctx.progress("done", 1, "Selesai; hasil siap diputar dan diunduh", status="done")
        except Exception as exc:
            logger.exception("Output %s failed", output_id)
            with Session(get_engine()) as session:
                output = session.get(Output, output_id)
                if output:
                    output.status, output.error, output.note = (
                        "failed",
                        str(exc)[:1500],
                        "Proses gagal; hasil tahap sebelumnya tetap tersimpan",
                    )
                    emit(session, output)
                    session.commit()
            raise
