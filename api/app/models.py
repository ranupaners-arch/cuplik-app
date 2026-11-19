from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Float, String
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Project(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    title: str
    source_kind: str
    source_ref: str = ""
    source_url: str | None = None
    language: str = "id"
    duration_s: float = 0
    ingest_status: str = "queued"
    transcript_status: str = "queued"
    error: str | None = None
    job_id: str | None = None
    stage: str = Field(
        default="queued", sa_column=Column(String, nullable=False, server_default="queued")
    )
    progress: float = Field(default=0, sa_column=Column(Float, nullable=False, server_default="0"))
    note: str = Field(
        default="Menunggu worker",
        sa_column=Column(String, nullable=False, server_default="Menunggu worker"),
    )
    requested_language: str = Field(
        default="auto", sa_column=Column(String, nullable=False, server_default="auto")
    )
    updated_at: datetime = Field(
        default_factory=now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
        ),
    )
    created_at: datetime = Field(default_factory=now)


class Output(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    mode: str
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = "queued"
    stage: str = "queued"
    progress: float = 0
    note: str = "Menunggu worker"
    error: str | None = None
    job_id: str | None = None
    provider: str = "mock"
    actual_duration_s: float | None = None
    created_at: datetime = Field(default_factory=now)


class Clip(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    output_id: str = Field(foreign_key="output.id", index=True)
    rank: int
    start_s: float
    end_s: float
    topic: str
    titles: list[str] = Field(sa_column=Column(JSON, nullable=False))
    hook_options: list[str] = Field(sa_column=Column(JSON, nullable=False))
    hook_choice: int = 0
    title_choice: int = 0
    score: float
    rubric: dict = Field(sa_column=Column(JSON, nullable=False))
    reason: str
    selection: dict = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
    description: str = Field(
        default="", sa_column=Column(String, nullable=False, server_default="")
    )
    hashtags: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    keywords: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    emoji: list[dict] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    retention: dict = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
    layout: str = Field(
        default="center", sa_column=Column(String, nullable=False, server_default="center")
    )
    thumb_path: str | None = None
    caption_overrides: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    captions: bool = True
    purpose: str = Field(
        default="discovery", sa_column=Column(String, nullable=False, server_default="discovery")
    )
    platform: str = Field(
        default="youtube", sa_column=Column(String, nullable=False, server_default="youtube")
    )
    rating: str | None = None
    rating_note: str = ""
    file_path: str | None = None
    render_fingerprint: str | None = None
    qc: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class Chapter(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    output_id: str = Field(foreign_key="output.id", index=True)
    order: int
    title: str
    goal: str
    importance: str
    required: bool = True
    kept_s: float = 0


class Beat(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    output_id: str = Field(foreign_key="output.id", index=True)
    chapter_id: str = Field(foreign_key="chapter.id", index=True)
    sentence_id: str
    start_s: float
    end_s: float
    text: str
    kind: str = Field(
        default="speech", sa_column=Column(String, nullable=False, server_default="speech")
    )
    visual_desc: str = Field(
        default="", sa_column=Column(String, nullable=False, server_default="")
    )
    label: str = Field(
        default="step", sa_column=Column(String, nullable=False, server_default="step")
    )
    importance: float = Field(
        default=1, sa_column=Column(Float, nullable=False, server_default="1")
    )
    required: bool = False
    decision: str = "keep"
    speed: float = 1
    locked: bool = False


class JobEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    output_id: str = Field(foreign_key="output.id", index=True)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=now)


class Upload(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    filename: str
    total_bytes: int
    complete: bool = False
    created_at: datetime = Field(default_factory=now)


class Preference(SQLModel, table=True):
    id: str = Field(default="default", primary_key=True)
    defaults: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    caption_preset: str = "karaoke"


class GlossaryTerm(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    wrong: str = Field(unique=True, index=True)
    correct: str


class ProjectEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=now)


class Task(SQLModel, table=True):
    """Durable queue intent; Redis may be reconstructed from this table."""

    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str
    subject_id: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    state: str = Field(default="pending", index=True)
    rq_job_id: str = Field(default_factory=new_id)
    attempts: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
