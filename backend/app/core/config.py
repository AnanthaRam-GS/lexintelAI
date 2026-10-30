"""Shared backend configuration contract for LegalAI.

This module defines the environment variables backend services will consume.
It intentionally does not instantiate settings or initialize external
resources. The intended runtime dependency is `pydantic-settings`.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHROMA_COLLECTION = "legalai_trusted_judgments_v1"
_ENV_FILE = os.environ.get("LEGALAI_ENV_FILE", ".env")


class Settings(BaseSettings):
    """Typed environment settings for future backend services."""

    # Required (step 20b): no default. development | test | production; startup refuses anything else
    # (core/startup_checks.py). The test runners set it to test themselves.
    app_env: str = ""
    # Loopback by default (step 20b); a deployment that must accept outside connections sets 0.0.0.0 explicitly.
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    gemini_api_key: str = ""
    legalai_llm_provider: str = "gemini"
    # Fallback answer provider, tried only on a provider failure of the primary
    # (services/llm_provider_chain.py). Empty or "none" disables it.
    legalai_llm_fallback_provider: str = "gemini"
    # Optional override of each answer adapter's automatic retries (None keeps the adapter default).
    legalai_llm_max_retries: int | None = None
    # Output token limit sent to every answer provider; a length stop is a generation failure.
    legalai_llm_max_output_tokens: int = 2048
    # Groq reasoning effort for gpt-oss models (low | medium | high); empty sends none.
    legalai_groq_reasoning_effort: str = "low"
    # Groq per-request token ceiling (the account's tokens-per-minute limit); unset disables the size guard.
    legalai_groq_max_request_tokens: int | None = None
    # Groq's real prompt tokens are 1.07-1.49x estimate_tokens(prompt + schema) on all 27 recorded live runs (prompt
    # v1-v3); 1.57 is the worst ratio (1.4928, step 22 B3, v3) plus 5% (backend/scripts/calibrate_request_size_guard.py).
    # Step 12 set 1.51 from the 10 runs then available.
    legalai_groq_token_estimate_factor: float = 1.57
    # Step 23 pacing (services/llm_pacing.py): requests wait in a FIFO queue for model capacity, at most this long,
    # then get MODEL_BUSY with Retry-After. Groq's limits are per model; its rate-limit headers refine the estimate.
    legalai_llm_pacing_enabled: bool = True
    legalai_llm_queue_max_wait_seconds: float = 90.0
    # Step 24 per-mode fallback policy: a professional answer waits this long for its primary model (gpt-oss-120b)
    # before the fallback may answer; public answers fall back at once when the primary is at its limit.
    legalai_professional_primary_max_wait_seconds: float = 45.0
    legalai_groq_tokens_per_minute: int = 8000
    legalai_groq_requests_per_minute: int = 30
    # Gemini 3 thinking level (low | medium | high); empty sends none.
    legalai_gemini_thinking: str = "low"
    legalai_gemini_timeout_seconds: float = 90.0
    # Product prompt (v2 | v3; v1 is the frozen evaluation baseline). v3 = v2 plus concision (step 22).
    legalai_prompt_version: str = "v3"
    # Return per-stage query timings and the answering backend in the response `debug` field.
    legalai_query_debug: bool = False
    # Device for the query embedder and reranker (auto | cpu | mps | cuda); auto uses MPS when torch reports it.
    legalai_model_device: str = "auto"
    # Half precision for the reranker on MPS/CUDA (ignored on CPU). The query embedder stays fp32 to match
    # the fp32 index vectors. Step 12: rankings identical to the frozen benchmark, about 4x faster on MPS.
    legalai_reranker_fp16: bool = True
    # Load the query models and run one tiny inference at startup.
    legalai_model_warmup: bool = True
    # Step 18: how long a request waits for the process-wide model lock (inference_lock.py) before it is answered
    # MODEL_BUSY / MODELS_LOADING with Retry-After. Warm-up and ingestion wait without a limit.
    legalai_inference_lock_timeout_seconds: float = 30.0
    # Test only (step 17): deterministic providers for browser end-to-end runs (backend/app/testing/e2e.py).
    # Refused at startup unless APP_ENV=test.
    legalai_e2e_fake_providers: bool = False
    gemini_model: str = ""
    legalai_llm_temperature: float = 0.1
    legalai_llm_timeout_seconds: float = 60.0

    groq_api_key: str = ""
    groq_model: str = ""
    # Step 22 per-mode routing: a separate Groq model (own rate limits) for public answers; empty uses GROQ_MODEL.
    groq_public_model: str = ""
    # Step 22: the model of the groq_backup fallback profile (a second Groq model with its own rate limits).
    groq_backup_model: str = ""
    # Its model for public answers (the fallback of GROQ_PUBLIC_MODEL); empty uses GROQ_BACKUP_MODEL.
    groq_backup_public_model: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # OpenAI-compatible provider profiles (step 21; services/openai_compatible_adapter.py). Each is selected by name
    # in LEGALAI_LLM_PROVIDER / LEGALAI_LLM_FALLBACK_PROVIDER. Model IDs have no default: set the verified ID.
    # NVIDIA API catalog (build.nvidia.com).
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = ""
    nvidia_max_output_tokens: int | None = None  # None: LEGALAI_LLM_MAX_OUTPUT_TOKENS
    nvidia_timeout_seconds: float = 120.0
    nvidia_structured_output: str = "json_schema"  # json_schema | json_object | prompt (schema in the prompt only)
    nvidia_reasoning_effort: str = ""  # sent as reasoning_effort when set
    nvidia_max_request_tokens: int | None = None  # per-request ceiling for the size guard; None: no guard
    nvidia_stream: bool = False  # stream: true (SSE); the timeout then applies per read, not to the whole answer
    nvidia_stream_deadline_seconds: float = 300.0  # total time a streamed answer may take
    # Ollama (local), through its OpenAI-compatible /v1 API, with ollama_base_url and ollama_model (below).
    ollama_max_output_tokens: int | None = None
    ollama_timeout_seconds: float = 300.0
    # prompt: the Homebrew build's MLX runner answers 501 "structured output is unavailable" to response_format.
    ollama_structured_output: str = "prompt"
    ollama_reasoning_effort: str = ""
    # The model's context window (num_ctx). The OpenAI-compatible API cannot set it per request, so it is
    # fixed in a Modelfile; the size guard keeps prompt + schema + output within it.
    ollama_context_tokens: int | None = None
    # Defined for future keys; disabled while the key is empty.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""

    # Application-level context budget for a single generative call, deliberately
    # independent of any provider's advertised maximum context window. A model
    # (or an account's rate-limited tier) may accept far less than its nominal
    # context in practice; these settings bound what LegalAI will ever attempt to
    # send, and are checked before invoking the provider, not just relied upon
    # via the provider's own rejection. See docs/PRIVATE_PDF_CONTEXT_BUDGETING.md.
    legalai_product_max_input_tokens: int = 40000
    legalai_llm_reserved_output_tokens: int = 6000
    legalai_llm_context_safety_margin_tokens: int = 4000
    prompt_overhead_reserve_tokens: int = 1500
    private_pdf_input_budget_tokens: int = 18000
    trusted_evidence_input_budget_tokens: int = 10000
    private_pdf_top_k: int = 10
    private_pdf_max_chunks_per_batch: int = 8
    # Professional brief: maximum characters of a precedent excerpt (trusted chunk text).
    precedent_excerpt_max_chars: int = 400

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"

    # Required (step 20): no default. backend/app/db/session.py refuses to start without it outside APP_ENV=test.
    database_url: str = ""

    chroma_persist_dir: str = "./chroma_store"
    chroma_collection_name: str = DEFAULT_CHROMA_COLLECTION

    indian_kanoon_api_token: str = ""
    indian_kanoon_base_url: str = "https://api.indiankanoon.org"

    # Required outside APP_ENV=test: at least 32 bytes, never the old public default (core/startup_checks.py).
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    # Development seed accounts (backend/scripts/seed_users.py only); never used by the app.
    seed_lawyer_password: str = ""
    seed_admin_password: str = ""
    # Auth cookie SameSite (lax | strict | none); Secure is set in production, and always with SameSite=None.
    auth_cookie_samesite: str = "lax"

    # Login throttling (SEC-003): failures within the window lock the account key or the client IP.
    login_max_failures_per_account: int = 5
    login_max_failures_per_ip: int = 20
    login_failure_window_seconds: int = 900
    login_lockout_seconds: int = 900
    # Query rate limits (SEC-001): per client IP on public routes, per user on professional routes.
    public_query_limit_per_minute: int = 5
    public_query_limit_per_day: int = 100
    professional_query_limit_per_minute: int = 10
    professional_query_limit_per_day: int = 300
    # Global cap on concurrent LLM generations; a request waits up to the timeout for a slot, then gets 503.
    llm_max_concurrent_generations: int = 4
    llm_generation_wait_seconds: float = 10.0
    # Comma-separated proxy IPs/CIDRs whose X-Forwarded-For is trusted; empty trusts no proxy.
    trusted_proxies: str = ""

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

    # Ingestion jobs still non-terminal after this long are reaped to FAILED.
    ingestion_stale_job_minutes: int = 30

    # OCR fallback for scanned PDF pages (services/ocr.py; docs/OCR.md).
    ocr_enabled: bool = True
    # A page whose native text is shorter than this, and which contains an image, is OCR'd.
    ocr_min_chars_per_page: int = 50
    ocr_dpi: int = 300
    ocr_language: str = "eng"
    # Pages that may be OCR'd per document: query-time uploads are interactive, so the cap is small.
    ocr_max_pages_query: int = 10
    ocr_max_pages_ingestion: int = 200
    ocr_page_timeout_seconds: float = 30.0
    ocr_document_timeout_seconds_query: float = 90.0
    ocr_document_timeout_seconds_ingestion: float = 1800.0
    # Mean Tesseract word confidence (0-100) below which an OCR'd page is flagged as possibly inaccurate.
    ocr_low_confidence_threshold: float = 80.0
    # Optional path to the tesseract binary; empty uses PATH.
    tesseract_cmd: str = ""

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
        # LEGALAI_ENV_FILE=none (set by the test runners, step 23): ignore the developer's .env so local test results
        # match CI, which has none. Anything else names the file; the default is ./.env.
        env_file=None if _ENV_FILE.lower() == "none" else _ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


def resolve_chroma_location(settings: Settings) -> tuple[Path, str]:
    """Return the Chroma persist directory and collection shared by ingestion and query.

    A relative ``CHROMA_PERSIST_DIR`` is resolved against the repository root,
    so both paths open the same store regardless of the working directory.
    """
    persist_dir = Path(settings.chroma_persist_dir)
    if not persist_dir.is_absolute():
        persist_dir = REPO_ROOT / persist_dir
    return persist_dir, settings.chroma_collection_name


def allowed_origins(settings: Settings) -> list[str]:
    """The browser origins allowed by CORS, and by the Origin/Referer check on cookie-authenticated writes."""
    configured = [settings.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"]
    return list(dict.fromkeys(origin.strip().rstrip("/") for origin in configured if origin and origin.strip()))
