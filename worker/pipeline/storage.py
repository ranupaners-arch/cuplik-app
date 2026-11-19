import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from api.app.config import get_settings


def project_dir(project_id: str) -> Path:
    path = get_settings().storage / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(output_id: str) -> Path:
    path = get_settings().storage / "outputs" / output_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def json_object(path: Path) -> dict:
    """Optional cache metadata can be rebuilt; malformed user sidecars remain errors."""
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def try_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
