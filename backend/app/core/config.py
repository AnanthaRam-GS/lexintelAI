"""Shared backend configuration contract for LegalAI.

This module defines the environment variables backend services will consume.
It intentionally does not instantiate settings or initialize external
resources. The intended runtime dependency is `pydantic-settings`.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed environment settings for future backend services."""

    app_env: str = "development"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.7-flash"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"

    database_url: str = "postgresql://user:password@localhost:5432/legalai"

    chroma_persist_dir: str = "./chroma_store"
    chroma_collection_name: str = "judgments"

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    inlegalbert_model_path: str = "./models/inlegalbert-finetuned"
    inlegalbert_classification_threshold: float = 0.5

    bge_m3_model: str = "BAAI/bge-m3"
    bge_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_batch_size: int = 16
    retrieval_top_k: int = 20
    rerank_top_k: int = 5

    max_upload_size_mb: int = 10
    max_query_length: int = 5000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
