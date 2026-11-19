"""Human review drafts, optimistic concurrency and portable evaluation packages."""

import hashlib
import html
import json
import zipfile
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import text
from sqlmodel import Session, select

from api.app.db import get_session
from api.app.jobs import prepare_project_task
from api.app.models import Annotation, Chapter, Clip, Output, Project, now
from api.app.preferences import read_preferences
from api.app.schemas import AnnotationDocument, AnnotationSave, AnnotationView
from worker.pipeline.provenance import project_snapshot
from worker.pipeline.storage import file_lock, output_dir, project_dir, try_file_lock

router = APIRouter(prefix="/api/projects", tags=["evaluation"])
DB = Annotated[Session, Depends(get_session)]
Mode = Literal["clips", "condense"]


def source_snapshot(session, identifier):
    project = session.get(Project, identifier)
    if project is None:
        raise HTTPException(404, "Proyek tidak ditemukan")
    if project.ingest_status != "done" or project.transcript_status != "done":
        raise HTTPException(409, "Tunggu sumber dan transkrip selesai sebelum anotasi")
    try:
        snapshot, transcript = project_snapshot(identifier)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Checkpoint sumber belum siap; siapkan ulang sumber") from exc
    return project, snapshot, transcript


def predictions_exist(session, project_id, mode):
    model = Clip if mode == "clips" else Chapter
    return (
        session.exec(
            select(model.id)
            .join(Output, model.output_id == Output.id)
            .where(Output.project_id == project_id)
        ).first()
        is not None
    )


def annotation_row(session, identifier, mode):
    return session.exec(
        select(Annotation).where(Annotation.project_id == identifier, Annotation.mode == mode)
    ).first()


@router.get("/{project_id}/annotations/{mode}", response_model=AnnotationView)
def read_annotation(project_id: str, mode: Mode, session: DB):
    project, snapshot, transcript = source_snapshot(session, project_id)
    row = annotation_row(session, project_id, mode)
    exposed = predictions_exist(session, project_id, mode)
    document = (
        AnnotationDocument.model_validate(row.document)
        if row
        else AnnotationDocument(
            settings=getattr(read_preferences(session), mode), independent=not exposed
        )
    )
    return AnnotationView(
        project_id=project_id,
        mode=mode,
        revision=row.revision if row else 0,
        document=document,
        dataset_kind="synthetic" if project.source_kind == "demo" else "human",
        independent=row.independent if row else False,
        predictions_exist=exposed,
        stale=bool(
            row
            and (
                row.source_fingerprint != snapshot["source_sha256"]
                or row.transcript_fingerprint != snapshot["transcript_sha256"]
            )
        ),
        source_fingerprint=snapshot["source_sha256"],
        transcript_fingerprint=snapshot["transcript_sha256"],
        duration_s=project.duration_s,
        language=transcript.language,
    )


@router.put("/{project_id}/annotations/{mode}", response_model=AnnotationView)
def save_annotation(project_id: str, mode: Mode, body: AnnotationSave, session: DB):
    session.exec(text("BEGIN IMMEDIATE"))
    project, snapshot, _ = source_snapshot(session, project_id)
    if (
        body.source_fingerprint != snapshot["source_sha256"]
        or body.transcript_fingerprint != snapshot["transcript_sha256"]
    ):
        raise HTTPException(409, "Sumber/transkrip berubah; muat ulang sebelum menyimpan anotasi")
    row = annotation_row(session, project_id, mode)
    if body.expected_revision != (row.revision if row else 0):
        raise HTTPException(
            409, "Anotasi telah diubah di tempat lain. Muat ulang; perubahan lokal belum disimpan."
        )
    document = body.document.model_copy(deep=True)
    if (mode == "clips" and (document.required_chapters or document.required_specs)) or (
        mode == "condense" and document.ranges
    ):
        raise HTTPException(422, "Jenis rentang harus sesuai mode anotasi")
    groups = [document.ranges, document.required_chapters, document.required_specs]
    for group in groups:
        if len({(r.start_s, r.end_s) for r in group}) != len(group):
            raise HTTPException(422, "Rentang anotasi yang sama tidak boleh dihitung ulang")
        if any(r.end_s > project.duration_s + 0.001 for r in group):
            raise HTTPException(422, "Rentang anotasi berada di luar durasi sumber")
    if mode == "clips" and any(r.end_s - r.start_s > 180 for r in document.ranges):
        raise HTTPException(422, "Rentang Klip maksimal 180 detik")
    if document.status == "reviewed":
        required = document.ranges if mode == "clips" else document.required_chapters
        if not required or (
            mode == "condense"
            and any(
                not r.label.strip() for r in [*document.required_chapters, *document.required_specs]
            )
        ):
            raise HTTPException(
                422, "Tambahkan rentang yang ditinjau beserta label bab/spesifikasi"
            )
    if (
        row
        and row.document == document.model_dump()
        and row.source_fingerprint == body.source_fingerprint
        and row.transcript_fingerprint == body.transcript_fingerprint
    ):
        return read_annotation(project_id, mode, session)
    independent = document.independent and not predictions_exist(session, project_id, mode)
    document.independent = independent
    if row is None:
        row = Annotation(
            project_id=project_id,
            mode=mode,
            document={},
            dataset_kind="synthetic" if project.source_kind == "demo" else "human",
            source_fingerprint=body.source_fingerprint,
            transcript_fingerprint=body.transcript_fingerprint,
        )
    else:
        row.revision += 1
    row.document, row.independent = document.model_dump(), independent
    row.source_fingerprint, row.transcript_fingerprint = (
        body.source_fingerprint,
        body.transcript_fingerprint,
    )
    row.updated_at = now()
    session.add(row)
    session.commit()
    return read_annotation(project_id, mode, session)


@router.get("/{project_id}/source")
def source_file(project_id: str, session: DB):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Proyek tidak ditemukan")
    directory = project_dir(project_id)
    source = directory / "source.mp4"
    with try_file_lock(directory / ".source.lock") as acquired:
        if not source.is_file():
            raise HTTPException(410, "Salinan sumber tidak tersedia; siapkan ulang sumber")
        if acquired:
            (directory / ".source-used").touch()
    return FileResponse(
        source, media_type="video/mp4", filename="source.mp4", content_disposition_type="inline"
    )


@router.post("/{project_id}/prepare-source", status_code=202)
def prepare_source(project_id: str, session: DB):
    session.exec(text("BEGIN IMMEDIATE"))
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Proyek tidak ditemukan")
    if project.ingest_status in {"queued", "running"}:
        raise HTTPException(409, "Sumber sedang disiapkan")
    project.ingest_status, project.error, project.note = (
        "queued",
        None,
        "Menyiapkan ulang salinan sumber dari checkpoint",
    )
    task = prepare_project_task(session, project)
    session.commit()
    from api.app.dispatch import dispatch_pending

    dispatch_pending()
    return {"job_id": task.rq_job_id}


def vtt_time(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


@router.get("/{project_id}/transcript.vtt")
def transcript_track(project_id: str, session: DB):
    _, _, transcript = source_snapshot(session, project_id)
    cues = [
        f"{s.id}\n{vtt_time(s.start)} --> {vtt_time(s.end)}\n{html.escape(' '.join(s.text.split()))}\n"
        for s in transcript.sentences
    ]
    return Response("WEBVTT\n\n" + "\n".join(cues), media_type="text/vtt")


@router.get("/{project_id}/annotations/{mode}/export.zip")
def export_annotation(project_id: str, mode: Mode, session: DB, output_id: str | None = None):
    view = read_annotation(project_id, mode, session)
    row = annotation_row(session, project_id, mode)
    if not row or view.document.status != "reviewed" or view.stale:
        raise HTTPException(409, "Tinjau dan simpan anotasi terhadap sumber terbaru sebelum ekspor")
    _, snapshot, transcript = source_snapshot(session, project_id)
    document = view.document
    expected = {
        "mode": mode,
        "dataset_kind": view.dataset_kind,
        "annotator": document.annotator,
        "annotation_status": "reviewed",
        "independent": row.independent,
        "source": "./source.mp4",
        "transcript": "./transcript.json",
        "settings": document.settings.model_dump(),
        "note": document.note,
        "provenance": {
            **snapshot,
            "annotation_revision": row.revision,
            "reviewed_at": row.updated_at.isoformat(),
            "duration_s": view.duration_s,
        },
    }

    def ranges(items):
        return [{"start_s": r.start_s, "end_s": r.end_s, "topic": r.label} for r in items]

    if mode == "clips":
        expected["ranges"] = ranges(document.ranges)
    else:
        expected.update(
            required_chapters=ranges(document.required_chapters),
            required_specs=ranges(document.required_specs),
        )
    prediction = None
    if output_id:
        output = session.get(Output, output_id)
        if (
            output is None
            or output.project_id != project_id
            or output.mode != mode
            or output.status != "done"
        ):
            raise HTTPException(409, "Pilih output selesai dari proyek dan mode yang sama")
        if output.provenance != snapshot:
            raise HTTPException(
                409, "Jejak sumber output belum cocok; buat output baru untuk evaluasi"
            )
        if mode == "clips":
            path = output_dir(output_id) / "selection.json"
            if not path.is_file():
                raise HTTPException(409, "Laporan seleksi output tidak tersedia")
            prediction = json.loads(path.read_text())
            prediction["provenance"] = snapshot
        else:
            path = output_dir(output_id) / "condensed.timeline.json"
            if not path.is_file():
                raise HTTPException(409, "Garis waktu Ringkas belum tersedia")
            timeline = json.loads(path.read_text())
            prediction = {
                "mode": mode,
                "provider": output.provider,
                "duration_s": timeline["duration_s"],
                "retained_ranges": [
                    {"start_s": s["source_start_s"], "end_s": s["source_end_s"]}
                    for s in timeline["spans"]
                ],
                "provenance": snapshot,
            }
    directory = project_dir(project_id) / "evaluation"
    directory.mkdir(exist_ok=True)
    package_key = hashlib.sha256((output_id or "labels").encode()).hexdigest()[:12]
    path = directory / f"{mode}-r{row.revision}-{package_key}.zip"
    with file_lock(directory / ".export.lock"):
        temporary = path.with_suffix(".tmp.zip")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("expected.json", json.dumps(expected, ensure_ascii=False, indent=2))
            archive.writestr("transcript.json", transcript.model_dump_json(indent=2))
            archive.writestr("annotation.json", view.model_dump_json(indent=2))
            if prediction:
                archive.writestr(
                    "predictions.json", json.dumps(prediction, ensure_ascii=False, indent=2)
                )
            archive.writestr(
                "README.txt",
                "Simpan sumber asli sebagai source.mp4 di folder kasus ini. Paket tidak menyertakan media.\nSalin folder kasus ke eval/golden/<nama-kasus>/ lalu jalankan make eval.\nAnotasi assisted, draft, demo, dan prediksi mock tidak dihitung sebagai kualitas independen.\n",
            )
        temporary.replace(path)
    return FileResponse(
        path, media_type="application/zip", filename=f"cuplik-evaluation-{project_id}-{mode}.zip"
    )
