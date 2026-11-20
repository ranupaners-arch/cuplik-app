import math
from typing import Literal, Self
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.app.models import Beat, Chapter, Output, Project


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Sentence(StrictModel):
    id: str = Field(pattern=r"^s[1-9][0-9]*$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    word_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Akhir kalimat harus sesudah awal")
        return self


class Word(StrictModel):
    id: str = Field(pattern=r"^w[1-9][0-9]*$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end <= self.start or not self.text.strip():
            raise ValueError("Waktu atau teks kata tidak valid")
        return self


class Transcript(StrictModel):
    language: str = Field(default="id", min_length=2, max_length=12)
    sentences: list[Sentence] = Field(min_length=1, max_length=50000)
    words: list[Word] = Field(default_factory=list)
    source: Literal["demo", "sidecar", "whisper"] = "sidecar"
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        previous = 0.0
        ids = set()
        for sentence in self.sentences:
            if sentence.id in ids or sentence.start < previous - 0.001:
                raise ValueError(
                    "ID kalimat harus unik dan timestamp berurutan tanpa tumpang tindih"
                )
            previous = sentence.end
            ids.add(sentence.id)
        word_ids = {w.id for w in self.words}
        if len(word_ids) != len(self.words):
            raise ValueError("ID kata harus unik")
        previous = 0.0
        for word in self.words:
            if word.start < previous - 0.001:
                raise ValueError("Timestamp kata harus berurutan tanpa tumpang tindih")
            previous = word.end
        used = set()
        by_id = {w.id: w for w in self.words}
        for sentence in self.sentences:
            if (
                len(sentence.word_ids) != len(set(sentence.word_ids))
                or not set(sentence.word_ids).issubset(word_ids)
                or used.intersection(sentence.word_ids)
            ):
                raise ValueError("ID kata kalimat tidak valid atau digunakan ulang")
            referenced = [by_id[identifier] for identifier in sentence.word_ids]
            if referenced and (
                referenced[0].start < sentence.start - 0.001
                or referenced[-1].end > sentence.end + 0.001
                or referenced != sorted(referenced, key=lambda w: w.start)
            ):
                raise ValueError("Urutan atau waktu kata berada di luar kalimat")
            used.update(sentence.word_ids)
        return self


def youtube_url(value: str) -> str:
    url = urlparse(value)
    if (
        url.scheme != "https"
        or url.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
        or url.username
        or url.password
        or url.port not in (None, 443)
    ):
        raise ValueError("Gunakan link HTTPS video YouTube")
    if "list" in parse_qs(url.query) or url.path.startswith("/playlist"):
        raise ValueError("Playlist belum didukung; gunakan satu video")
    if not (
        url.hostname == "youtu.be"
        and url.path.strip("/")
        or url.path.startswith(("/watch", "/shorts/", "/live/"))
    ):
        raise ValueError("Link harus menuju satu video YouTube")
    return value


class ProbeRequest(StrictModel):
    url: str = Field(max_length=2000)

    _url = field_validator("url")(youtube_url)


class ProjectCreate(StrictModel):
    source_kind: Literal["demo", "url", "upload"] = "demo"
    url: str | None = Field(default=None, max_length=2000)
    upload_id: str | None = None
    transcript: Transcript | None = None
    title: str = Field(default="", max_length=200)
    language: Literal["auto", "id", "en", "ar"] = "auto"

    @model_validator(mode="after")
    def source(self) -> Self:
        if self.source_kind == "url":
            if not self.url:
                raise ValueError("Link video diperlukan")
            youtube_url(self.url)
        if self.source_kind == "upload" and not self.upload_id:
            raise ValueError("upload_id diperlukan")
        if self.source_kind == "demo" and self.transcript:
            raise ValueError("Demo memakai transkrip sintetis bawaannya")
        return self


class RetentionSettings(StrictModel):
    shorten_pauses: bool = True
    remove_fillers: bool = True
    zoom: bool = True
    emphasis: bool = True
    cold_open: bool = False
    karaoke: bool = True
    keyword_highlights: bool = True
    emoji: bool = False


Purpose = Literal["discovery", "tutorial"]
Platform = Literal["youtube", "youtube_shorts", "tiktok", "instagram"]


def retention_profile(purpose: str, preset: str = "compact") -> RetentionSettings:
    return RetentionSettings(
        shorten_pauses=purpose != "tutorial",
        remove_fillers=purpose != "tutorial",
        zoom=purpose != "tutorial",
        emphasis=purpose != "tutorial",
        karaoke=preset == "karaoke",
        keyword_highlights=preset == "karaoke",
    )


class FocusRegion(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0.1, le=1)
    height: float = Field(ge=0.1, le=1)

    @model_validator(mode="after")
    def inside_source(self) -> Self:
        if self.x + self.width > 1 + 1e-6 or self.y + self.height > 1 + 1e-6:
            raise ValueError("Area fokus harus berada di dalam bingkai sumber")
        return self


class VisualFocus(StrictModel):
    mode: Literal["safe", "activity", "manual"] = "safe"
    region: FocusRegion | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.mode == "manual" and self.region is None:
            raise ValueError("Area manual diperlukan untuk mode fokus manual")
        if self.mode != "manual" and self.region is not None:
            raise ValueError("Area manual hanya berlaku pada mode fokus manual")
        return self


class CondenseVisionSettings(StrictModel):
    enabled: bool = False
    screen_tutorial: bool = False
    max_frames: int = Field(default=720, ge=16, le=4096)


class OutputSettings(StrictModel):
    clip_count: int = Field(default=8, ge=1, le=12)
    min_clip_seconds: float = Field(default=3, ge=1, le=180)
    max_clip_seconds: float = Field(default=60, ge=3, le=180)
    target_seconds: float = Field(default=20, ge=3, le=3600)
    max_speech_speed: float = Field(default=1.15, ge=1, le=1.25)
    timelapse_enabled: bool = False
    max_visual_speed: float = Field(default=8, ge=2, le=8)
    coherence_enabled: bool = False
    chapter_cards: bool = False
    focus: str = Field(default="", max_length=1000)
    captions: bool = True
    purpose: Purpose = "tutorial"
    platform: Platform = "youtube"
    layout: Literal["auto", "source", "portrait"] = "auto"
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    visual_focus: VisualFocus = Field(default_factory=VisualFocus)
    condense_vision: CondenseVisionSettings = Field(default_factory=CondenseVisionSettings)

    @model_validator(mode="after")
    def clip_range(self) -> Self:
        if self.min_clip_seconds > self.max_clip_seconds:
            raise ValueError("Durasi minimum klip melebihi maksimum")
        if self.platform != "youtube" and self.layout == "source":
            raise ValueError(
                "Pilih pembingkaian otomatis atau vertikal untuk platform video pendek"
            )
        if self.visual_focus.mode != "safe" and self.layout == "source":
            raise ValueError("Gunakan pembingkaian otomatis/vertikal untuk memilih area fokus")
        if "retention" not in self.model_fields_set:
            # Computed defaults must not masquerade as explicit request overrides.
            object.__setattr__(self, "retention", retention_profile(self.purpose))
        return self


class OutputPreferences(StrictModel):
    clips: OutputSettings = Field(default_factory=OutputSettings)
    condense: OutputSettings = Field(default_factory=OutputSettings)
    caption_preset: Literal["compact", "karaoke"] = "compact"


class OutputSettingsInput(OutputSettings):
    @model_validator(mode="after")
    def clip_range(self) -> Self:
        # Validate combinations after persisted defaults and explicit fields are merged.
        return self


class OutputCreate(StrictModel):
    mode: Literal["clips", "condense"]
    settings: OutputSettingsInput = Field(default_factory=OutputSettingsInput)


class UploadCreate(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    total_bytes: int = Field(gt=0)


class Rubric(StrictModel):
    hook: float = Field(ge=0, le=10)
    standalone: float = Field(ge=0, le=10)
    payoff: float = Field(ge=0, le=10)
    emotion: float = Field(ge=0, le=10)
    density: float = Field(ge=0, le=10)

    def weighted(self) -> float:
        return (
            0.30 * self.hook
            + 0.25 * self.standalone
            + 0.20 * self.payoff
            + 0.15 * self.emotion
            + 0.10 * self.density
        )

    def score(self) -> float:
        return round(self.weighted(), 1)


class Candidate(StrictModel):
    start_id: str
    end_id: str
    titles: list[str] = Field(min_length=2, max_length=2)
    hook_options: list[str] = Field(min_length=2, max_length=2)
    topic: str = Field(min_length=1, max_length=100)
    scores: Rubric
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("titles", "hook_options")
    @classmethod
    def short_text(cls, items):
        if any(not item.strip() or len(item) > 200 for item in items):
            raise ValueError("Judul/hook kosong atau terlalu panjang")
        return items


class Selection(StrictModel):
    candidates: list[Candidate] = Field(max_length=24)


class Ranking(StrictModel):
    ids: list[int] = Field(max_length=24)


class ChapterPlan(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(max_length=1000)
    start_id: str
    end_id: str
    required_sentence_ids: list[str]
    importance: Literal["core", "helpful", "optional"]


class OutlinePlan(StrictModel):
    chapters: list[ChapterPlan] = Field(min_length=1, max_length=50)


class ClipPatch(StrictModel):
    title_choice: int | None = Field(default=None, ge=0, le=1)
    hook_choice: int | None = Field(default=None, ge=0, le=1)
    captions: bool | None = None
    purpose: Purpose | None = None
    platform: Platform | None = None
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    layout: Literal["auto", "source", "portrait"] | None = None
    retention: RetentionSettings | None = None
    visual_focus: VisualFocus | None = None
    caption_overrides: dict[str, str] | None = None
    rating: Literal["up", "down"] | None = None
    rating_note: str | None = Field(default=None, max_length=1000)


class ChapterChoice(StrictModel):
    id: str
    required: bool


class CondenseTimingPatch(StrictModel):
    coherence_enabled: bool | None = None
    chapter_cards: bool | None = None
    timelapse_enabled: bool | None = None
    max_visual_speed: float | None = Field(default=None, ge=2, le=8)
    max_speech_speed: float | None = Field(default=None, ge=1, le=1.25)


class OutlineReview(CondenseTimingPatch):
    chapters: list[ChapterChoice]
    target_seconds: float = Field(ge=3, le=3600)


class BeatPatch(StrictModel):
    decision: Literal["keep", "speed", "drop"]
    speed: float = Field(default=1.15, ge=1, le=8)
    locked: bool = True
    timelapse_approved: bool | None = None


class SolveRequest(CondenseTimingPatch):
    target_seconds: float = Field(ge=3, le=3600)
    chapters: list[ChapterChoice] | None = None


class SampleRequest(StrictModel):
    focus: str = Field(default="", max_length=1000)


class ClipView(BaseModel):
    id: str
    output_id: str
    rank: int
    start_s: float
    end_s: float
    topic: str
    titles: list[str]
    hook_options: list[str]
    hook_choice: int
    title_choice: int
    score: float
    rubric: dict[str, float]
    reason: str
    description: str
    hashtags: list[str]
    keywords: list[str]
    emoji: list[dict]
    selection: dict
    caption_overrides: dict[str, str]
    captions: bool
    purpose: str
    platform: str
    layout: str
    retention: dict
    visual_focus: dict
    rating: str | None
    rating_note: str
    render_fingerprint: str | None
    qc: dict
    needs_render: bool = False
    file_url: str | None = None
    thumbnail_url: str | None = None


class ProjectView(BaseModel):
    id: str
    title: str
    source_kind: str
    language: str
    duration_s: float
    ingest_status: str
    transcript_status: str
    error: str | None
    stage: str
    progress: float
    note: str
    requested_language: str
    outputs: list[Output] = Field(default_factory=list)


class GlossaryCreate(StrictModel):
    wrong: str = Field(min_length=1, max_length=120)
    correct: str = Field(min_length=1, max_length=120)

    @field_validator("wrong", "correct")
    @classmethod
    def single_word(cls, value):
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("Gunakan satu kata agar waktu per kata tetap akurat")
        return value


class ChapterMarker(StrictModel):
    chapter_id: str
    title: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    timestamp: str


class ChapterExport(StrictModel):
    version: int = 1
    timing_source: Literal["encoded_parts", "legacy_plan"]
    duration_s: float = Field(ge=0)
    chapters: list[ChapterMarker] = Field(default_factory=list)
    youtube_valid: bool = False
    reasons: list[str] = Field(default_factory=list)
    index_text: str = ""
    youtube_text: str | None = None


class FrameDescription(StrictModel):
    id: str = Field(pattern=r"^f[0-9]+$")
    action: str = Field(min_length=1, max_length=500)
    screen_text: str = Field(default="", max_length=1000)
    result: bool = False
    idle: bool = False
    uncertain: bool = True
    hands_visible: bool | None = None
    objects: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("action")
    @classmethod
    def nonblank_action(cls, value):
        if not value.strip():
            raise ValueError("Deskripsi frame harus berupa teks atau penanda ketidakpastian")
        return value

    @field_validator("objects")
    @classmethod
    def short_object_names(cls, values):
        if any(not value.strip() or len(value) > 80 for value in values):
            raise ValueError("Nama objek kosong atau terlalu panjang")
        return values


class VisionFrame(FrameDescription):
    beat_id: str
    time_s: float = Field(ge=0)
    width: int = Field(gt=0, le=1024)
    height: int = Field(gt=0, le=1024)
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    url: str


class VisionReport(StrictModel):
    version: int = 1
    provider: str
    vision_model: str
    source_sha256: str
    transcript_sha256: str
    speech_beats: int = Field(ge=0)
    visual_beats: int = Field(ge=0)
    frame_count: int = Field(ge=0)
    notes: list[str]
    frames: list[VisionFrame]


class CoherenceIssue(StrictModel):
    at_id: str
    type: Literal["dangling_reference", "missing_prerequisite", "abrupt_jump"]
    fix: Literal["restore", "review"]
    restore_ids: list[str] = Field(default_factory=list, max_length=5)
    note: str = Field(min_length=1, max_length=500)


class CoherenceCheck(StrictModel):
    issues: list[CoherenceIssue] = Field(max_length=20)


class CoherenceReport(StrictModel):
    version: int = 1
    status: Literal["passed", "needs_review"]
    stale: bool = False
    provider: str
    model: str
    rounds: int = Field(ge=1, le=2)
    plan_fingerprint: str
    issues: list[CoherenceIssue]
    restored_ids: list[str]
    dropped_ids: list[str]
    note: str
    min_duration_s: float | None = None


class OutputDetail(BaseModel):
    output: Output
    project: Project
    clips: list[ClipView]
    chapters: list[Chapter]
    beats: list[Beat]
    transcript: Transcript | None
    chapter_export: ChapterExport | None = None
    vision_report: VisionReport | None = None
    coherence_report: CoherenceReport | None = None
    condense_qc: dict | None = None


class AnnotationRange(StrictModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    label: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError("Akhir anotasi harus sesudah awal")
        return self


class AnnotationDocument(StrictModel):
    status: Literal["draft", "reviewed"] = "draft"
    annotator: str = Field(default="", max_length=120)
    independent: bool = True
    review_confirmed: bool = False
    settings: OutputSettings = Field(default_factory=OutputSettings)
    ranges: list[AnnotationRange] = Field(default_factory=list, max_length=100)
    required_chapters: list[AnnotationRange] = Field(default_factory=list, max_length=100)
    required_specs: list[AnnotationRange] = Field(default_factory=list, max_length=100)
    note: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def reviewed_by_person(self) -> Self:
        if self.status == "reviewed" and (not self.annotator.strip() or not self.review_confirmed):
            raise ValueError("Isi nama peninjau dan konfirmasi peninjauan manual")
        return self


class AnnotationSave(StrictModel):
    expected_revision: int = Field(ge=0)
    source_fingerprint: str = Field(min_length=1)
    transcript_fingerprint: str = Field(min_length=1)
    document: AnnotationDocument


class AnnotationView(StrictModel):
    project_id: str
    mode: Literal["clips", "condense"]
    revision: int
    document: AnnotationDocument
    dataset_kind: Literal["human", "synthetic"]
    independent: bool
    predictions_exist: bool
    stale: bool
    source_fingerprint: str
    transcript_fingerprint: str
    duration_s: float
    language: str


def finite_duration(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Durasi video tidak valid")
    return value
