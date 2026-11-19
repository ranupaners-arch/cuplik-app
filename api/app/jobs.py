from redis import Redis
from rq import Queue
from sqlalchemy import update
from sqlmodel import Session

from api.app.config import get_settings
from api.app.db import get_engine
from api.app.models import JobEvent, Output, Project, ProjectEvent, Task, now

BUSY = {"queued", "running"}


class QueueUnavailable(RuntimeError):
    pass


def connection() -> Redis:
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=5)


def queue() -> Queue:
    return Queue(
        "cuplik", connection=connection(), default_timeout=get_settings().job_timeout_seconds
    )


def emit(session: Session, output: Output):
    session.add(
        JobEvent(
            output_id=output.id,
            payload={
                "status": output.status,
                "stage": output.stage,
                "progress": output.progress,
                "note": output.note,
                "error": output.error,
            },
        )
    )


def enqueue_project(project_id: str) -> str:
    from api.app.dispatch import dispatch_pending

    with Session(get_engine()) as session:
        project = session.get(Project, project_id)
        task = prepare_project_task(session, project)
        session.commit()
        identifier = task.rq_job_id
    dispatch_pending()
    return identifier


def prepare_project_task(session: Session, project: Project) -> Task:
    task = Task(kind="ingest", subject_id=project.id)
    project.job_id = task.rq_job_id
    session.add(task)
    emit_project(session, project)
    return task


def enqueue_output(
    output_id: str,
    *,
    expected_statuses: set[str],
    render_only: bool = False,
    clip_id: str | None = None,
) -> str:
    with Session(get_engine()) as session:
        task = Task(
            kind="output",
            subject_id=output_id,
            payload={"render_only": render_only, "clip_id": clip_id},
        )
        claimed = session.exec(
            update(Output)
            .where(Output.id == output_id, Output.status.in_(expected_statuses))
            .values(status="queued", error=None, job_id=task.rq_job_id, note="Menunggu worker")
        )
        if claimed.rowcount != 1:
            raise ValueError("Output sedang diproses atau statusnya tidak mengizinkan operasi ini.")
        output = session.get(Output, output_id)
        session.add(task)
        emit(session, output)
        session.commit()
        identifier = task.rq_job_id
    from api.app.dispatch import dispatch_pending

    dispatch_pending()
    return identifier


def emit_project(session: Session, project: Project):
    project.updated_at = now()
    session.add(project)
    session.add(
        ProjectEvent(
            project_id=project.id,
            payload={
                "stage": project.stage,
                "progress": project.progress,
                "note": project.note,
                "ingest_status": project.ingest_status,
                "transcript_status": project.transcript_status,
                "error": project.error,
            },
        )
    )
