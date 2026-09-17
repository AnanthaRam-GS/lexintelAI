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
    legalai_llm_provider: str = "gemini"
    gemini_model: str = ""
    legalai_llm_temperature: float = 0.1
    legalai_llm_timeout_seconds: float = 60.0

    groq_api_key: str = ""
    groq_model: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Application-level context budget for a single generative call, deliberately
    # independent of any provider's advertised maximum context window. A model
    # (or an account's rate-limited tier) may accept far less than its nominal
    # context in practice; these settings bound what LegalAI will ever attempt to
    # send, and are checked before invoking the provider, not just relied upon
    # via the provider's own rejection. See docs/PRIVATE_PDF_CONTEXT_BUDGETING.md.
    legalai_llm_context_tokens: int = 40000
    legalai_llm_reserved_output_tokens: int = 6000
    legalai_llm_context_safety_margin_tokens: int = 4000
    private_pdf_input_budget_tokens: int = 18000
    trusted_evidence_input_budget_tokens: int = 10000
    private_pdf_top_k: int = 10
    private_pdf_max_chunks_per_batch: int = 8

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"

    database_url: str = "postgresql://user:password@localhost:5432/legalai"

    chroma_persist_dir: str = "./chroma_store"
    chroma_collection_name: str = "legalai_trusted_judgments_v1"

    indian_kanoon_api_token: str = ""
    indian_kanoon_base_url: str = "https://api.indiankanoon.org"

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    inlegalbert_model_path: str = "./models/inlegalbert-finetuned"
    inlegalbert_classification_threshold: float = 0.5
    legal_ner_enabled: bool = False
    legal_ner_model: str = ""
    legal_ner_device: str = "cpu"
    legal_ner_min_confidence: float = 0.7
    legal_ner_mode: str = "deterministic"

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 16
    embedding_normalize: bool = True
    bge_m3_model: str = "BAAI/bge-m3"
    bge_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "cpu"
    reranker_batch_size: int = 8
    reranker_max_length: int = 512
    reranker_top_k: int = 5

    max_upload_size_mb: int = 10
    max_query_length: int = 5000
    verification_document_dir: str = "./data/private/lawyer_verification"
    email_verification_token_minutes: int = 1440
    email_otp_expiry_minutes: int = 10
    email_otp_resend_cooldown_seconds: int = 60
    email_otp_max_attempts: int = 5
    expose_dev_verification_tokens: bool = False
    email_delivery_mode: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
