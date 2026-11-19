import logging
from contextlib import contextmanager
from threading import Event, Thread

from sqlmodel import Session

from api.app.db import get_engine
from api.app.dispatch import task_lock
from api.app.models import Task, now
from worker.pipeline.storage import file_lock

logger = logging.getLogger(__name__)


@contextmanager
def heartbeat(identifier):
    stop = Event()

    def beat():
        while not stop.wait(10):
            try:
                with Session(get_engine()) as session:
                    task = session.get(Task, identifier)
                    task.updated_at = now()
                    session.add(task)
                    session.commit()
            except Exception:
                logger.exception("Task heartbeat could not be saved")

    thread = Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def execute(identifier: str):
    from worker.runner import ingest_project, run_output

    with file_lock(task_lock(identifier)):
        with Session(get_engine()) as session:
            task = session.get(Task, identifier)
            if task is None or task.state in ("done", "failed"):
                return
            task.state, task.updated_at = "running", now()
            task.attempts += 1
            session.add(task)
            session.commit()
            kind, subject, payload = task.kind, task.subject_id, task.payload
        try:
            with heartbeat(identifier):
                if kind == "ingest":
                    ingest_project(subject)
                else:
                    run_output(subject, payload.get("render_only", False), payload.get("clip_id"))
        except Exception as exc:
            with Session(get_engine()) as session:
                task = session.get(Task, identifier)
                task.state, task.error, task.updated_at = "failed", str(exc)[:1500], now()
                session.add(task)
                session.commit()
            raise
        with Session(get_engine()) as session:
            task = session.get(Task, identifier)
            task.state, task.error, task.updated_at = "done", None, now()
            session.add(task)
            session.commit()
