from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="RAG_",
        extra="ignore",
    )

    data_dir: Path = PROJECT_ROOT / "data"
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 5
    max_context_chars: int = 12_000
    max_upload_mb: int = 40

    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    request_timeout: float = 60.0

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "metadata.sqlite3"

    @property
    def effective_api_key(self) -> str | None:
        return (
            self.api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
        )

    @property
    def effective_base_url(self) -> str:
        if self.api_key:
            return self.base_url.rstrip("/")
        if os.getenv("DEEPSEEK_API_KEY") and not os.getenv("OPENAI_API_KEY"):
            return "https://api.deepseek.com/v1"
        return self.base_url.rstrip("/")

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
