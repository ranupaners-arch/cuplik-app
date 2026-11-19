import asyncio
import json
import shutil
import zipfile
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, Response
from redis.exceptions import RedisError
from rq.job import Job
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from api.app.config import get_settings
from api.app.db import get_engine, get_session, init_db
from api.app.evaluation import router as evaluation_router
from api.app.jobs import (
    BUSY,
    QueueUnavailable,
    connection,
    emit,
    enqueue_output,
    prepare_project_task,
)
from api.app.models import (
    Beat,
    Chapter,
    Clip,
    GlossaryTerm,
    JobEvent,
    Output,
    Preference,
    Project,
    ProjectEvent,
    Task,
    Upload,
)
from api.app.preferences import read_preferences, resolve_settings
from api.app.schemas import (
    BeatPatch,
    ChapterExport,
    ClipPatch,
    ClipView,
    GlossaryCreate,
    OutlineReview,
    OutputCreate,
    OutputDetail,
    OutputPreferences,
    OutputSettings,
    ProbeRequest,
    ProjectCreate,
    ProjectView,
    SampleRequest,
    Selection,
    SolveRequest,
    Transcript,
    UploadCreate,
    VisionReport,
    retention_profile,
)
from worker.pipeline.chapters import read_chapter_export
from worker.pipeline.clip_edits import (
    caption_ids,
    preserve_trimmed_overrides,
    snap_manual_range,
    validate_overrides,
)
from worker.pipeline.llm import LLMClient, LLMError
from worker.pipeline.media import MediaError, demo_transcript, probe_file, probe_url
from worker.pipeline.render import clip_fingerprint
from worker.pipeline.signals import Signals
from worker.pipeline.solver import InfeasibleDuration, solve
from worker.pipeline.storage import atomic_json, file_lock, output_dir, project_dir
from worker.pipeline.vision import read_vision_report


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Cuplik API",
    version="0.1.0",
    lifespan=lifespan,
    description="Fondasi lokal: Project → Output Klip/Ringkas → tinjau → render → unduh. LLM mock secara default.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)
app.include_router(evaluation_router)
DB = Annotated[Session, Depends(get_session)]
CHUNK_BYTES = 4 * 1024 * 1024


@app.get("/api/docs", include_in_schema=False)
def proxy_docs():
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Cuplik API")


@app.get("/api/openapi.json", include_in_schema=False)
def proxy_openapi():
    return app.openapi()


@app.exception_handler(QueueUnavailable)
async def queue_error(_, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LLMError)
async def llm_error(_, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(MediaError)
async def media_error(_, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(InfeasibleDuration)
async def duration_error(_, exc):
    return JSONResponse(
        status_code=409,
        content={"detail": {"message": str(exc), "min_duration_s": exc.minimum_seconds}},
    )


def require(session: Session, model, identifier: str):
    item = session.get(model, identifier)
    if item is None:
        raise HTTPException(404, "Data tidak ditemukan")
    return item


def begin_write(session: Session):
    session.exec(text("BEGIN IMMEDIATE"))


def idle(output: Output):
    if output.status in BUSY:
        raise HTTPException(409, "Tunggu proses berjalan selesai sebelum mengubah output.")


def clip_view(clip: Clip) -> ClipView:
    stale = clip.render_fingerprint != clip_fingerprint(clip)
    return ClipView(
        **clip.model_dump(),
        needs_render=stale,
        file_url=f"/api/clips/{clip.id}/file" if clip.file_path else None,
        thumbnail_url=f"/api/clips/{clip.id}/thumbnail" if clip.thumb_path and not stale else None,
    )


def reconcile(output: Output, session: Session):
    if output.status not in BUSY or not output.job_id:
        return
    if session.exec(
        select(Task.id).where(
            Task.subject_id == output.id, Task.state.in_(("pending", "enqueued", "running"))
        )
    ).first():
        return  # Durable dispatcher owns recovery; a killed RQ job is not a terminal failure.
    try:
        job = Job.fetch(output.job_id, connection=connection())
        status = job.get_status(refresh=True)
        if status in {"failed", "stopped", "canceled"}:
            output.status, output.error = (
                "failed",
                "Worker berhenti atau batas waktu job terlewati. Coba ulang dari cache.",
            )
            emit(session, output)
            session.commit()
    except (RedisError, KeyError):
        pass
    except Exception:
        # Redis retention may expire independently of the durable project records.
        pass


@app.get("/api/health")
def health():
    try:
        redis_ok = connection().ping()
    except RedisError:
        redis_ok = False
    return {
        "status": "ok" if redis_ok else "degraded",
        "database": "sqlite",
        "redis": bool(redis_ok),
        "provider": get_settings().llm_provider,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
    }


@app.get("/api/config")
def config():
    settings = get_settings()
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model_fast
        if settings.llm_provider != "mock"
        else "deterministic-fixture",
        "live_configured": settings.llm_provider == "mock"
        or bool(
            settings.llm_model_fast
            and (
                settings.llm_provider == "ollama"
                or (
                    settings.gemini_api_key
                    if settings.llm_provider == "gemini"
                    else settings.anthropic_api_key
                )
            )
        ),
        "max_upload_bytes": settings.max_upload_bytes,
        "render_height": settings.render_height,
        "transcription_backend": settings.transcription_backend,
    }


@app.post("/api/probe")
def probe(body: ProbeRequest):
    return probe_url(body.url)


@app.post("/api/uploads", status_code=201)
def create_upload(body: UploadCreate, session: DB):
    if body.total_bytes > get_settings().max_upload_bytes:
        raise HTTPException(413, "Berkas melebihi batas unggah konfigurasi.")
    upload = Upload(filename=body.filename, total_bytes=body.total_bytes)
    session.add(upload)
    session.commit()
    return {
        "id": upload.id,
        "offset": 0,
        "chunk_bytes": CHUNK_BYTES,
        "total_bytes": upload.total_bytes,
        "complete": False,
    }


@app.get("/api/uploads/{upload_id}")
def upload_status(upload_id: str, session: DB):
    upload = require(session, Upload, upload_id)
    path = get_settings().storage / "uploads" / f"{upload.id}.bin"
    return {
        "id": upload.id,
        "offset": path.stat().st_size if path.exists() else 0,
        "total_bytes": upload.total_bytes,
        "complete": upload.complete,
        "chunk_bytes": CHUNK_BYTES,
    }


@app.put("/api/uploads/{upload_id}")
async def upload_chunk(
    upload_id: str, request: Request, offset: Annotated[int, Query(ge=0)], session: DB
):
    upload = require(session, Upload, upload_id)
    chunk = bytearray()
    async for part in request.stream():
        chunk.extend(part)
        if len(chunk) > CHUNK_BYTES:
            raise HTTPException(413, "Chunk maksimal 4 MiB.")
    if not chunk:
        raise HTTPException(422, "Chunk kosong")
    path = get_settings().storage / "uploads" / f"{upload.id}.bin"
    total_bytes, was_complete = upload.total_bytes, upload.complete

    def append_and_validate():
        # Disk locking and ffprobe run outside the event loop. Concurrent chunks cannot
        # block SSE or deadlock each other while the final chunk is being validated.
        with file_lock(path.with_suffix(".lock")):
            current = path.stat().st_size if path.exists() else 0
            if was_complete or offset != current:
                raise HTTPException(
                    409,
                    {
                        "message": "Offset berubah; baca status lalu lanjutkan.",
                        "expected_offset": current,
                    },
                )
            if current + len(chunk) > total_bytes:
                raise HTTPException(413, "Chunk melebihi ukuran berkas yang dinyatakan")
            with path.open("ab") as handle:
                handle.write(chunk)
            current += len(chunk)
            if current == total_bytes:
                try:
                    probe_file(path)
                except (MediaError, ValueError) as exc:
                    path.unlink(missing_ok=True)
                    raise HTTPException(422, str(exc)) from exc
            return current

    current = await asyncio.to_thread(append_and_validate)
    if current == total_bytes:
        upload.complete = True
        session.add(upload)
        session.commit()
    return {
        "id": upload.id,
        "offset": current,
        "total_bytes": upload.total_bytes,
        "complete": upload.complete,
    }


@app.post("/api/uploads/{upload_id}/complete")
def complete_upload(upload_id: str, session: DB):
    upload = require(session, Upload, upload_id)
    path = get_settings().storage / "uploads" / f"{upload.id}.bin"
    with file_lock(path.with_suffix(".lock")):
        if not path.exists() or path.stat().st_size != upload.total_bytes:
            raise HTTPException(409, "Unggah belum lengkap; baca offset lalu lanjutkan chunk")
        try:
            probe_file(path)
        except (MediaError, ValueError) as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        upload.complete = True
        session.add(upload)
        session.commit()
    return {
        "id": upload.id,
        "offset": upload.total_bytes,
        "total_bytes": upload.total_bytes,
        "complete": True,
    }


@app.post("/api/projects", status_code=201, response_model=Project)
def create_project(body: ProjectCreate, session: DB):
    source_ref = body.url or ""
    if body.source_kind == "upload":
        upload = require(session, Upload, body.upload_id)
        if not upload.complete:
            raise HTTPException(409, "Unggah belum selesai")
        source_ref = upload.id
    project = Project(
        title=body.title or ("Video demo sintetis" if body.source_kind == "demo" else "Video baru"),
        source_kind=body.source_kind,
        source_ref=source_ref,
        source_url=body.url if body.source_kind == "url" else None,
        requested_language=body.language,
    )
    if body.transcript:
        atomic_json(
            project_dir(project.id) / "sidecar.json",
            body.transcript.model_copy(update={"source": "sidecar"}).model_dump(),
        )
    session.add(project)
    session.flush()
    prepare_project_task(session, project)
    session.commit()
    from api.app.dispatch import dispatch_pending

    dispatch_pending()
    session.refresh(project)
    return project


@app.post("/api/projects/{project_id}/retry", status_code=202)
def retry_project(project_id: str, session: DB):
    begin_write(session)
    project = require(session, Project, project_id)
    if project.transcript_status != "failed":
        raise HTTPException(409, "Hanya ingest/transkripsi gagal yang dapat dicoba ulang")
    project.transcript_status, project.error = "queued", None
    if project.ingest_status != "done":
        project.ingest_status = "queued"
    project.note = "Menunggu worker untuk melanjutkan dari checkpoint"
    task = prepare_project_task(session, project)
    session.commit()
    from api.app.dispatch import dispatch_pending

    dispatch_pending()
    return {"job_id": task.rq_job_id}


@app.get("/api/projects/{project_id}/transcript", response_model=Transcript)
def project_transcript(project_id: str, session: DB):
    project = require(session, Project, project_id)
    path = project_dir(project_id) / "transcript.json"
    if project.transcript_status != "done" or not path.exists():
        raise HTTPException(409, "Transkrip belum selesai")
    return Transcript.model_validate_json(path.read_text())


@app.get("/api/projects/{project_id}/signals", response_model=Signals)
def project_signals(project_id: str, session: DB):
    require(session, Project, project_id)
    path = project_dir(project_id) / "signals.json"
    if not path.exists():
        raise HTTPException(409, "Moment IQ tersedia setelah pemilihan Klip dimulai")
    return Signals.model_validate_json(path.read_text())


@app.get("/api/outputs/{output_id}/selection")
def output_selection(output_id: str, session: DB):
    require(session, Output, output_id)
    path = output_dir(output_id) / "selection.json"
    if not path.exists():
        raise HTTPException(409, "Laporan seleksi belum tersedia")
    return json.loads(path.read_text())


@app.get("/api/projects/{project_id}/events")
async def project_events(
    project_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
):
    with Session(get_engine()) as session:
        require(session, Project, project_id)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(400, "Last-Event-ID harus berupa angka") from exc

    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            with Session(get_engine()) as session:
                project = require(session, Project, project_id)
                rows = session.exec(
                    select(ProjectEvent)
                    .where(ProjectEvent.project_id == project_id, ProjectEvent.id > cursor)
                    .order_by(ProjectEvent.id)
                    .limit(100)
                ).all()
                terminal = project.transcript_status in ("done", "failed")
            for row in rows:
                cursor = row.id
                yield {"event": "progress", "id": str(row.id), "data": json.dumps(row.payload)}
            if terminal and len(rows) < 100:
                yield {
                    "event": "complete",
                    "data": json.dumps({"transcript_status": project.transcript_status}),
                }
                return
            await asyncio.sleep(0.35)

    return EventSourceResponse(
        generate(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/api/glossary", response_model=list[GlossaryTerm])
def glossary(session: DB):
    return session.exec(select(GlossaryTerm).order_by(GlossaryTerm.wrong)).all()


@app.get("/api/preferences", response_model=OutputPreferences)
def preferences(session: DB):
    return read_preferences(session)


@app.put("/api/preferences", response_model=OutputPreferences)
def save_preferences(body: OutputPreferences, session: DB):
    for settings in (body.clips, body.condense):
        settings.retention.karaoke = body.caption_preset == "karaoke"
    row = session.get(Preference, "default") or Preference()
    row.defaults = {"clips": body.clips.model_dump(), "condense": body.condense.model_dump()}
    row.caption_preset = body.caption_preset
    session.add(row)
    session.commit()
    return read_preferences(session)


@app.post("/api/glossary", status_code=201, response_model=GlossaryTerm)
def add_glossary(body: GlossaryCreate, session: DB):
    term = GlossaryTerm(wrong=body.wrong.casefold(), correct=body.correct)
    session.add(term)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Kata ini sudah ada di glosarium") from exc
    session.refresh(term)
    return term


@app.put("/api/glossary/{term_id}", response_model=GlossaryTerm)
def edit_glossary(term_id: str, body: GlossaryCreate, session: DB):
    term = require(session, GlossaryTerm, term_id)
    term.wrong, term.correct = body.wrong.casefold(), body.correct
    session.add(term)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Kata ini sudah ada di glosarium") from exc
    session.refresh(term)
    return term


@app.delete("/api/glossary/{term_id}")
def delete_glossary(term_id: str, session: DB):
    term = require(session, GlossaryTerm, term_id)
    session.delete(term)
    session.commit()
    return {"deleted": True}


@app.get("/api/projects", response_model=list[ProjectView])
def projects(session: DB):
    rows = session.exec(select(Project).order_by(Project.created_at.desc()).limit(100)).all()
    return [
        ProjectView(
            **p.model_dump(),
            outputs=list(
                session.exec(
                    select(Output)
                    .where(Output.project_id == p.id)
                    .order_by(Output.created_at.desc())
                ).all()
            ),
        )
        for p in rows
    ]


@app.get("/api/projects/{project_id}", response_model=ProjectView)
def project_detail(project_id: str, session: DB):
    project = require(session, Project, project_id)
    return ProjectView(
        **project.model_dump(),
        outputs=list(session.exec(select(Output).where(Output.project_id == project_id)).all()),
    )


@app.post("/api/projects/{project_id}/outputs", status_code=201, response_model=Output)
def create_output(project_id: str, body: OutputCreate, session: DB):
    require(session, Project, project_id)
    defaults = read_preferences(session)
    try:
        settings = resolve_settings(
            getattr(defaults, body.mode), body.settings, defaults.caption_preset
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    output = Output(
        project_id=project_id,
        mode=body.mode,
        settings=settings.model_dump(),
        status="new",
        provider=get_settings().llm_provider,
    )
    session.add(output)
    session.commit()
    enqueue_output(output.id, expected_statuses={"new"})
    session.refresh(output)
    return output


@app.get("/api/outputs/{output_id}", response_model=OutputDetail)
def output_detail(output_id: str, session: DB):
    output = require(session, Output, output_id)
    reconcile(output, session)
    project = require(session, Project, output.project_id)
    transcript_path = project_dir(project.id) / "transcript.json"
    transcript = (
        Transcript.model_validate_json(transcript_path.read_text())
        if transcript_path.exists()
        else None
    )
    return OutputDetail(
        output=output,
        project=project,
        clips=[
            clip_view(c)
            for c in session.exec(
                select(Clip).where(Clip.output_id == output_id).order_by(Clip.rank)
            ).all()
        ],
        chapters=list(
            session.exec(
                select(Chapter).where(Chapter.output_id == output_id).order_by(Chapter.order)
            ).all()
        ),
        beats=list(
            session.exec(
                select(Beat).where(Beat.output_id == output_id).order_by(Beat.start_s)
            ).all()
        ),
        transcript=transcript,
        chapter_export=read_chapter_export(output_dir(output_id), output.actual_duration_s or 0)
        if output.mode == "condense" and output.status == "done"
        else None,
        vision_report=read_vision_report(output_dir(output_id))
        if output.mode == "condense"
        else None,
    )


@app.get("/api/outputs/{output_id}/events")
async def events(
    output_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
):
    with Session(get_engine()) as session:
        require(session, Output, output_id)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(400, "Last-Event-ID harus berupa angka") from exc

    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            with Session(get_engine()) as session:
                output = require(session, Output, output_id)
                rows = session.exec(
                    select(JobEvent)
                    .where(JobEvent.output_id == output_id, JobEvent.id > cursor)
                    .order_by(JobEvent.id)
                    .limit(100)
                ).all()
                terminal = output.status in {"done", "failed", "awaiting_review"}
                snapshot = {
                    "status": output.status,
                    "stage": output.stage,
                    "progress": output.progress,
                    "note": output.note,
                }
            for row in rows:
                cursor = row.id
                yield {"event": "progress", "id": str(row.id), "data": json.dumps(row.payload)}
            if terminal and len(rows) < 100:
                yield {"event": "complete", "data": json.dumps(snapshot)}
                return
            await asyncio.sleep(0.35)

    return EventSourceResponse(
        generate(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.post("/api/outputs/{output_id}/retry", status_code=202)
def retry(output_id: str, session: DB):
    output = require(session, Output, output_id)
    if output.status != "failed":
        raise HTTPException(409, "Hanya output gagal yang dapat dicoba ulang")
    # Existing solve/render stage indicates an accepted outline, which must not ask for review again.
    render_only = output.mode == "condense" and output.stage in {"solve", "render"}
    try:
        job_id = enqueue_output(output_id, expected_statuses={"failed"}, render_only=render_only)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id}


@app.patch("/api/clips/{clip_id}", response_model=ClipView)
def patch_clip(clip_id: str, body: ClipPatch, session: DB):
    begin_write(session)
    clip = require(session, Clip, clip_id)
    output = require(session, Output, clip.output_id)
    idle(output)
    changes = body.model_dump(exclude_unset=True)
    if any(value is None and key != "rating" for key, value in changes.items()):
        raise HTTPException(422, "Pengaturan klip tidak boleh null, kecuali rating")
    if any(key in changes for key in ("caption_overrides", "start_s", "end_s")):
        transcript = Transcript.model_validate_json(
            (project_dir(output.project_id) / "transcript.json").read_text()
        )
        valid = caption_ids(transcript, clip.start_s, clip.end_s)
        try:
            if "start_s" in changes or "end_s" in changes:
                project = require(session, Project, output.project_id)
                start, end, precision = snap_manual_range(
                    transcript,
                    changes.get("start_s", clip.start_s),
                    changes.get("end_s", clip.end_s),
                    project.duration_s,
                )
                changes.update(start_s=start, end_s=end)
                final_ids = caption_ids(transcript, start, end)
                valid |= final_ids
                clip.selection = {
                    **clip.selection,
                    "boundary_precision": precision,
                    "boundary_edited": True,
                    "word_ids": [
                        w.id for w in transcript.words if w.start >= start and w.end <= end
                    ],
                }
            else:
                final_ids = valid
            overrides = changes.get("caption_overrides", clip.caption_overrides)
            validate_overrides(overrides, valid)
            if "start_s" in changes or "end_s" in changes:
                overrides = preserve_trimmed_overrides(
                    overrides,
                    transcript,
                    clip.start_s,
                    clip.end_s,
                    changes["start_s"],
                    changes["end_s"],
                )
            changes["caption_overrides"] = {k: v for k, v in overrides.items() if k in final_ids}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    purpose = changes.get("purpose", clip.purpose)
    retention = clip.retention
    if purpose != clip.purpose:
        retention = retention_profile(
            purpose, "karaoke" if clip.retention.get("karaoke", True) else "compact"
        ).model_dump()
    if "retention" in changes or purpose != clip.purpose:
        changes["retention"] = {**retention, **changes.get("retention", {})}
    try:
        OutputSettings.model_validate(
            {
                "purpose": purpose,
                "platform": changes.get("platform", clip.platform),
                "layout": changes.get("layout", "auto" if clip.layout == "center" else clip.layout),
                "retention": changes.get("retention", clip.retention),
                "visual_focus": changes.get("visual_focus", clip.visual_focus),
            }
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for key, value in changes.items():
        setattr(clip, key, value)
    session.add(clip)
    session.commit()
    session.refresh(clip)
    return clip_view(clip)


@app.post("/api/clips/{clip_id}/render", status_code=202)
def rerender(clip_id: str, session: DB):
    clip = require(session, Clip, clip_id)
    try:
        job_id = enqueue_output(
            clip.output_id, expected_statuses={"done", "failed"}, clip_id=clip.id
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id}


@app.get("/api/outputs/{output_id}/outline")
def outline_detail(output_id: str, session: DB):
    detail = output_detail(output_id, session)
    if detail.output.mode != "condense":
        raise HTTPException(409, "Output ini bukan mode Ringkas")
    return {
        "chapters": detail.chapters,
        "beats": detail.beats,
        "target_seconds": detail.output.settings["target_seconds"],
    }


def solve_output(
    output: Output, session: Session, target: float, choices: dict[str, bool] | None = None
):
    chapters = list(session.exec(select(Chapter).where(Chapter.output_id == output.id)).all())
    beats = list(
        session.exec(select(Beat).where(Beat.output_id == output.id).order_by(Beat.start_s)).all()
    )
    if not chapters:
        raise HTTPException(409, "Outline belum tersedia")
    if choices is not None:
        if set(choices) != {c.id for c in chapters}:
            raise HTTPException(422, "Kirim seluruh ID bab tepat satu kali")
        for chapter in chapters:
            chapter.required = choices[chapter.id]
    plan = solve(beats, chapters, target, output.settings.get("max_speech_speed", 1.15))
    by_id = {b.id: b for b in beats}
    for item in plan["beats"]:
        beat = by_id[item["id"]]
        beat.decision, beat.speed = item["decision"], item["speed"]
        session.add(beat)
    for chapter in chapters:
        chapter.kept_s = sum(
            (b.end_s - b.start_s) / b.speed
            for b in beats
            if b.chapter_id == chapter.id and b.decision != "drop"
        )
        session.add(chapter)
    output.settings = {**output.settings, "target_seconds": target}
    output.actual_duration_s, output.stage = plan["actual_duration_s"], "solve"
    session.add(output)
    return plan


@app.post("/api/outputs/{output_id}/solve")
def solve_preview(output_id: str, body: SolveRequest, session: DB):
    begin_write(session)
    output = require(session, Output, output_id)
    if output.mode != "condense" or output.status != "awaiting_review":
        raise HTTPException(409, "Solver tersedia saat tinjau outline Ringkas")
    choices = {c.id: c.required for c in body.chapters} if body.chapters is not None else None
    if body.chapters is not None and len(choices) != len(body.chapters):
        raise HTTPException(422, "ID bab duplikat")
    result = solve_output(output, session, body.target_seconds, choices)
    session.commit()
    return result


@app.put("/api/outputs/{output_id}/outline", status_code=202)
def accept_outline(output_id: str, body: OutlineReview, session: DB):
    begin_write(session)
    output = require(session, Output, output_id)
    if output.mode != "condense" or output.status != "awaiting_review":
        raise HTTPException(409, "Output sedang tidak menunggu tinjauan")
    choices = {c.id: c.required for c in body.chapters}
    if len(choices) != len(body.chapters):
        raise HTTPException(422, "ID bab duplikat")
    plan = solve_output(output, session, body.target_seconds, choices)
    session.commit()
    try:
        job_id = enqueue_output(output_id, expected_statuses={"awaiting_review"}, render_only=True)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id, "plan": plan}


@app.patch("/api/beats/{beat_id}", response_model=Beat)
def patch_beat(beat_id: str, body: BeatPatch, session: DB):
    begin_write(session)
    beat = require(session, Beat, beat_id)
    output = require(session, Output, beat.output_id)
    if output.status != "awaiting_review":
        raise HTTPException(409, "Ubah beat pada tahap tinjau")
    chapter = require(session, Chapter, beat.chapter_id)
    if body.decision == "drop" and beat.required and chapter.required:
        raise HTTPException(409, "Beat wajib tidak dapat dibuang")
    if body.decision == "speed" and body.speed > output.settings.get("max_speech_speed", 1.15):
        raise HTTPException(422, "Kecepatan melampaui batas pengaturan output")
    beat.decision, beat.speed, beat.locked = (
        body.decision,
        body.speed if body.decision == "speed" else 1,
        body.locked,
    )
    session.add(beat)
    session.commit()
    session.refresh(beat)
    return beat


@app.post("/api/llm/sample")
def sample_llm(body: SampleRequest):
    transcript = demo_transcript()
    client = LLMClient()
    result = client.call_json(
        "select",
        {
            "sentences": [s.model_dump() for s in transcript.sentences],
            "requested_count": 3,
            "max_clip_seconds": 60,
            "focus": body.focus,
        },
        Selection,
    )
    from worker.pipeline.planning import validate_selection

    validate_selection(result, transcript, 60, 3)
    return {
        "provider": client.settings.llm_provider,
        "model": client.settings.llm_model_fast or "deterministic-fixture",
        "result": result,
        "usage": client.usage,
        "sample_is_synthetic": True,
    }


def artifact(path):
    if not path.is_file():
        raise HTTPException(404, "Hasil belum tersedia")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/clips/{clip_id}/file")
def clip_file(clip_id: str, session: DB):
    clip = require(session, Clip, clip_id)
    if clip_view(clip).needs_render:
        raise HTTPException(409, "Pengaturan klip berubah; render ulang sebelum mengunduh")
    return artifact(output_dir(clip.output_id) / f"{clip.id}.mp4")


@app.get("/api/clips/{clip_id}/thumbnail")
def clip_thumbnail(clip_id: str, session: DB):
    clip = require(session, Clip, clip_id)
    if clip_view(clip).needs_render:
        raise HTTPException(409, "Render ulang perubahan sebelum mengambil thumbnail")
    path = output_dir(clip.output_id) / f"{clip.id}.jpg"
    if not path.is_file():
        raise HTTPException(404, "Thumbnail belum tersedia")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@app.get("/api/outputs/{output_id}/file")
def condensed_file(output_id: str, session: DB):
    output = require(session, Output, output_id)
    if output.mode != "condense" or output.status != "done":
        raise HTTPException(409, "Ringkasan belum selesai")
    return artifact(output_dir(output_id) / "condensed.mp4")


@app.get("/api/outputs/{output_id}/export.zip")
def export(output_id: str, session: DB):
    detail = output_detail(output_id, session)
    if detail.output.status != "done" or any(c.needs_render for c in detail.clips):
        raise HTTPException(409, "Selesaikan render seluruh perubahan sebelum ekspor")
    directory = output_dir(output_id)
    # Zip is written to disk, not accumulated in RAM; MP4s are already compressed.
    with file_lock(directory / ".export.lock"):
        temporary = directory / "export.tmp.zip"
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("metadata.json", detail.model_dump_json(indent=2))
            if detail.output.mode == "clips":
                archive.writestr(
                    "captions.txt",
                    "\n\n".join(
                        f"#{c.rank} {c.titles[c.title_choice]}\nHook: {c.hook_options[c.hook_choice]}\nSkor: {c.score:.1f}\n{c.reason}\n\n{c.description}\n{' '.join(c.hashtags)}"
                        for c in detail.clips
                    ),
                )
            elif detail.chapter_export:
                archive.writestr("chapters.json", detail.chapter_export.model_dump_json(indent=2))
                archive.writestr("chapters.txt", detail.chapter_export.index_text)
                if detail.chapter_export.youtube_valid:
                    archive.writestr("youtube-chapters.txt", detail.chapter_export.youtube_text)
                timeline = directory / "condensed.timeline.json"
                if timeline.exists():
                    archive.write(timeline, timeline.name)
            paths = (
                [directory / f"{c.id}.mp4" for c in detail.clips]
                if detail.output.mode == "clips"
                else [directory / "condensed.mp4"]
            )
            for path in paths:
                if not path.exists():
                    raise HTTPException(409, "Artefak hilang; coba render ulang")
                archive.write(path, path.name)
            for c in detail.clips:
                thumbnail = directory / f"{c.id}.jpg"
                if thumbnail.exists():
                    archive.write(thumbnail, thumbnail.name)
        temporary.replace(directory / "export.zip")
    return FileResponse(
        directory / "export.zip", media_type="application/zip", filename=f"cuplik-{output_id}.zip"
    )


@app.get("/api/outputs/{output_id}/chapters", response_model=ChapterExport)
def chapter_export(output_id: str, session: DB):
    output = require(session, Output, output_id)
    if output.mode != "condense" or output.status != "done":
        raise HTTPException(409, "Daftar bab tersedia setelah Ringkas selesai")
    return read_chapter_export(output_dir(output_id), output.actual_duration_s or 0)


@app.get("/api/outputs/{output_id}/vision", response_model=VisionReport)
def vision_report(output_id: str, session: DB):
    require(session, Output, output_id)
    report = read_vision_report(output_dir(output_id))
    if report is None:
        raise HTTPException(404, "Laporan vision belum tersedia untuk output ini")
    return report


@app.get("/api/outputs/{output_id}/vision/frames/{frame_id}")
def vision_frame(output_id: str, frame_id: str, session: DB):
    report = vision_report(output_id, session)
    frame = next((f for f in report.frames if f.id == frame_id), None)
    if frame is None:
        raise HTTPException(404, "ID frame tidak ditemukan")
    path = output_dir(output_id) / "vision-frames" / f"{frame.image_sha256}.jpg"
    if not path.is_file():
        raise HTTPException(404, "Gambar frame tidak tersedia; laporan teks tetap dapat dibaca")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/outputs/{output_id}/chapters.txt")
def chapter_file(
    output_id: str,
    session: DB,
    chapter_format: Annotated[Literal["index", "youtube"], Query(alias="format")] = "index",
):
    report = chapter_export(output_id, session)
    if chapter_format == "youtube" and not report.youtube_valid:
        raise HTTPException(
            409, {"message": "Daftar bab belum memenuhi format YouTube", "reasons": report.reasons}
        )
    content = report.youtube_text if chapter_format == "youtube" else report.index_text
    if not content:
        raise HTTPException(404, "Indeks bab belum tersedia")
    filename = "youtube-chapters.txt" if chapter_format == "youtube" else "chapters.txt"
    return Response(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
