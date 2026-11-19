"""Production Klip contracts; the original sample API keeps its simpler schema."""

from pydantic import Field, field_validator

from api.app.schemas import Rubric, StrictModel


class Moment(StrictModel):
    start_id: str = Field(pattern=r"^s[1-9][0-9]*$")
    end_id: str = Field(pattern=r"^s[1-9][0-9]*$")
    hook_sentence_id: str = Field(pattern=r"^s[1-9][0-9]*$")
    cold_open_id: str | None
    angle: str = Field(min_length=1, max_length=1000)


class Moments(StrictModel):
    candidates: list[Moment] = Field(max_length=24)


class Emoji(StrictModel):
    word: str = Field(min_length=1, max_length=100)
    emoji: str = Field(min_length=1, max_length=16)


class ScoredClip(StrictModel):
    id: str = Field(pattern=r"^c[1-9][0-9]*$")
    scores: Rubric
    topic: str = Field(min_length=1, max_length=100)
    titles: list[str] = Field(min_length=2, max_length=2)
    hook_texts: list[str] = Field(min_length=2, max_length=2)
    reason: str = Field(min_length=1, max_length=1000)
    keywords: list[str] = Field(max_length=6)
    emphasis_word_ids: list[str] = Field(max_length=4)
    emoji: list[Emoji] = Field(max_length=3)
    description: str = Field(max_length=2000)
    hashtags: list[str] = Field(max_length=5)
    trim_start_id: str | None
    trim_end_id: str | None

    @field_validator("titles")
    @classmethod
    def valid_titles(cls, values):
        if len(set(values)) != 2 or any(not v.strip() or len(v) > 60 for v in values):
            raise ValueError("Dua judul harus berbeda, tidak kosong, dan maksimal 60 karakter")
        return values

    @field_validator("hook_texts")
    @classmethod
    def valid_hooks(cls, values):
        if len(set(values)) != 2 or any(not v.strip() or len(v.split()) > 8 for v in values):
            raise ValueError("Dua hook harus berbeda dan maksimal delapan kata")
        return values

    @field_validator("hashtags")
    @classmethod
    def valid_hashtags(cls, values):
        if any(
            not v.startswith("#") or v != v.lower() or any(c.isspace() for c in v) for v in values
        ):
            raise ValueError("Hashtag harus diawali #, huruf kecil, dan tanpa spasi")
        return values


class Scores(StrictModel):
    clips: list[ScoredClip] = Field(max_length=6)


class RankItem(StrictModel):
    id: str
    note: str = Field(min_length=1, max_length=1000)


class Reranking(StrictModel):
    ranking: list[RankItem] = Field(max_length=20)
