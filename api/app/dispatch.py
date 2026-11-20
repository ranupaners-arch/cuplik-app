"""Durable dispatch/recovery for one-machine API and worker deployments."""

import logging
from datetime import UTC

from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy import update
from sqlmodel import Session, select

from api.app import jobs
from api.app.config import get_settings
from api.app.db import get_engine
from api.app.models import Output, Project, Task, new_id, now
from worker.pipeline.storage import file_lock, try_file_lock

logger = logging.getLogger(__name__)
ACTIVE = ("pending", "enqueued", "running")


def task_lock(task_id):
    return get_settings().storage / "tasks" / f"{task_id}.lock"


def dispatch_pending() -> int:
    delivered = 0
    with file_lock(get_settings().storage / ".dispatch.lock"):
        with Session(get_engine()) as session:
            identifiers = list(
                session.exec(
                    select(Task.id)
                    .where(Task.state == "pending")
                    .order_by(Task.created_at)
                    .limit(100)
                ).all()
            )
        for identifier in identifiers:
            with Session(get_engine()) as session:
                task = session.get(Task, identifier)
                try:
                    job = Job.fetch(task.rq_job_id, connection=jobs.connection())
                except NoSuchJobError:
                    job = None
                except Exception:
                    # Leave the intent pending. A worker will dispatch after Redis recovers.
                    task.error = "Antrean tidak tersedia; tugas tersimpan dan akan dikirim ulang."
                    session.commit()
                    break
                try:
                    if job is None:
                        jobs.queue().enqueue(
                            "worker.tasks.execute", task.id, job_id=task.rq_job_id, result_ttl=86400
                        )
                    session.exec(
                        update(Task)
                        .where(Task.id == task.id, Task.state == "pending")
                        .values(state="enqueued", error=None, updated_at=now())
                    )
                    session.commit()
                    delivered += 1
                except Exception:
                    session.rollback()
                    # Network interruption after enqueue is resolved by deterministic rq_job_id.
                    break
    return delivered


def recover_tasks() -> int:
    recovered = 0
    with file_lock(get_settings().storage / ".dispatch.lock"):
        with Session(get_engine()) as session:
            # Close the narrow legacy/create-before-intent gap as well as Redis loss.
            known = set(session.exec(select(Task.subject_id).where(Task.state.in_(ACTIVE))).all())
            for project in session.exec(
                select(Project).where(Project.transcript_status.in_(("queued", "running")))
            ).all():
                if (
                    project.id not in known
                    and (now() - project.created_at.replace(tzinfo=UTC)).total_seconds() > 30
                ):
                    task = Task(kind="ingest", subject_id=project.id)
                    project.job_id = task.rq_job_id
                    session.add(task)
                    session.add(project)
            for output in session.exec(
                select(Output).where(Output.status.in_(("new", "queued", "running")))
            ).all():
                if (
                    output.id not in known
                    and (now() - output.created_at.replace(tzinfo=UTC)).total_seconds() > 30
                ):
                    task = Task(
                        kind="output",
                        subject_id=output.id,
                        payload={
                            "render_only": output.mode == "condense"
                            and output.stage in ("solve", "coherence", "render"),
                            "clip_id": None,
                        },
                    )
                    output.job_id, output.status = task.rq_job_id, "queued"
                    session.add(task)
                    session.add(output)
            session.commit()
            tasks = list(
                session.exec(select(Task).where(Task.state.in_(("enqueued", "running")))).all()
            )
            for task in tasks:
                with try_file_lock(task_lock(task.id)) as available:
                    if not available:
                        continue  # A living workhorse still owns it; never steal its work.
                    try:
                        job = Job.fetch(task.rq_job_id, connection=jobs.connection())
                        status = job.get_status(refresh=True)
                    except NoSuchJobError:
                        status = None
                    except Exception:
                        continue
                    if task.state == "enqueued" and status in ("queued", "deferred", "scheduled"):
                        continue
                    age = (now() - task.updated_at.replace(tzinfo=UTC)).total_seconds()
                    if task.state == "enqueued" and status == "started" and age < 30:
                        continue  # Dispatch-to-execute transition.
                    task.state, task.rq_job_id, task.updated_at = "pending", new_id(), now()
                    task.error = None
                    if task.kind == "ingest":
                        project = session.get(Project, task.subject_id)
                        project.job_id = task.rq_job_id
                        project.note = (
                            "Melanjutkan proses dari checkpoint setelah worker/antrean terputus"
                        )
                        jobs.emit_project(session, project)
                    else:
                        output = session.get(Output, task.subject_id)
                        output.job_id, output.status = task.rq_job_id, "queued"
                        output.note = "Melanjutkan dari checkpoint setelah worker/antrean terputus"
                        jobs.emit(session, output)
                    session.add(task)
                    recovered += 1
            session.commit()
    return recovered
