from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    data_dir: Path = ROOT / "data"
    redis_url: str = "redis://127.0.0.1:6386/0"
    web_origin: str = "http://localhost:3000"
    llm_provider: Literal["mock", "gemini", "anthropic", "ollama"] = "mock"
    llm_model_fast: str = ""
    llm_model_vision: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_num_ctx: int = Field(default=16384, ge=4096, le=262144)
    llm_timeout_seconds: int = Field(default=90, ge=1, le=600)
    job_timeout_seconds: int = Field(default=7200, ge=60)
    max_upload_bytes: int = Field(default=4 * 1024**3, ge=1)
    max_source_seconds: int = Field(default=10800, ge=1)
    transcription_backend: Literal["auto", "faster-whisper", "mlx"] = "auto"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_chunk_seconds: int = Field(default=60, ge=10, le=300)
    maintenance_interval_seconds: int = Field(default=15, ge=1, le=300)
    ytdlp_auto_update: bool = True
    ytdlp_update_timezone: str = "Asia/Jakarta"
    render_height: int = Field(default=1280, ge=320, le=1920, multiple_of=32)
    render_threads: int = Field(default=4, ge=1, le=32)
    source_cache_days: int = Field(default=14, ge=1, le=365)

    @property
    def storage(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.storage / 'cuplik.sqlite3'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
