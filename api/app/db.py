from functools import lru_cache

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlmodel import Session, create_engine

from api.app.config import ROOT, get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    settings.storage.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.database_url, connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")

    return engine


def init_db():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "api/migrations"))
    command.upgrade(cfg, "head")


def get_session():
    with Session(get_engine()) as session:
        yield session
