"""Expire only regenerable source copies, retaining uploads, transcripts and outputs."""

import time

from sqlmodel import Session, select

from api.app.config import get_settings
from api.app.db import get_engine
from api.app.dispatch import ACTIVE
from api.app.models import Output, Project, Task
from worker.pipeline.storage import try_file_lock


def cleanup_sources(*, clock: float | None = None) -> list[str]:
    settings = get_settings()
    cutoff = (time.time() if clock is None else clock) - settings.source_cache_days * 86400
    removed = []
    with Session(get_engine()) as session:
        projects = session.exec(select(Project)).all()
    for project in projects:
        directory = settings.storage / "projects" / project.id
        source = directory / "source.mp4"
        if not source.is_file() or source.is_symlink():
            continue
        with try_file_lock(directory / ".source.lock") as acquired:
            if not acquired or not source.is_file():
                continue
            accessed = directory / ".source-used"
            stamp = max(
                source.stat().st_mtime, accessed.stat().st_mtime if accessed.exists() else 0
            )
            if stamp >= cutoff:
                continue
            with Session(get_engine()) as session:
                output_ids = session.exec(
                    select(Output.id).where(Output.project_id == project.id)
                ).all()
                pending = session.exec(
                    select(Task).where(
                        Task.subject_id.in_([project.id, *output_ids]),
                        Task.state.in_(ACTIVE),
                    )
                ).first()
                if pending:
                    continue
            # URL/demo can be restored; uploaded projects retain their original .bin.
            if (
                project.source_kind == "upload"
                and not (settings.storage / "uploads" / f"{project.source_ref}.bin").is_file()
            ):
                continue
            source.unlink()
            removed.append(project.id)
    return removed
