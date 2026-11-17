"""Application configuration loaded from environment variables / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bharat Police Intelligence"
    environment: str = "development"

    # Database
    database_url: str = "postgresql+psycopg://bpi:bpi_password@localhost:5432/bpi"
    # Disable server-side prepared statements (needed behind PgBouncer/PGlite-style connection multiplexers)
    db_disable_prepared_statements: bool = False

    # Security
    secret_key: str = Field(default="change-this-secret-key-in-production-please")
    access_token_minutes: int = 120
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Storage
    data_dir: Path = PROJECT_DIR / "data"
    max_upload_mb: int = 50

    # OCR
    tesseract_cmd: str | None = None  # e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe
    ocr_languages: str = "eng+hin"
    ocr_min_chars_per_page: int = 40  # pages with fewer extracted chars are OCR'd
    ocr_dpi: int = 300

    # Chunking
    chunk_size_tokens: int = 700
    chunk_overlap_tokens: int = 120

    # Embeddings: sentence_transformers | ollama | hashing (hashing = offline test embedder only)
    embedding_provider: str = "sentence_transformers"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384
    embedding_device: str = "cpu"
    embedding_batch_size: int = 16

    # Reranker: cross_encoder | none
    reranker_provider: str = "cross_encoder"
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: int = 180
    llm_temperature: float = 0.1
    llm_num_ctx: int = 8192

    # Retrieval defaults (runtime-editable from Settings page)
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    dense_similarity_threshold: float = 0.2
    rerank_score_threshold: float = -2.0
    rrf_k: int = 60
    citation_support_threshold: float = 0.35

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, v: Path) -> Path:
        return v if v.is_absolute() else (PROJECT_DIR / v).resolve()

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    s.processed_dir.mkdir(parents=True, exist_ok=True)
    return s
