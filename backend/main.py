"""FastAPI application entrypoint for LegalAI."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import ingest as ingest_api
from backend.app.api.analytics import router as analytics_router
from backend.app.api.auth import router as auth_router
from backend.app.api.ingest import router as ingest_router
from backend.app.api.lawyer_verification import router as lawyer_verification_router
from backend.app.api.query import configure_answer_pacing, get_retrieval_service, router as query_router
from backend.app.api.query_history import router as query_history_router
from backend.app.core.config import Settings, allowed_origins
from backend.app.core.errors import (
    RequestIdMiddleware,
    UnhandledErrorMiddleware,
    install_error_handlers,
    install_request_id_logging,
)
from backend.app.core.request_guards import BodySizeLimitMiddleware, OriginCheckMiddleware, max_request_body_bytes
from backend.app.core.startup_checks import run_startup_security_checks, validate_e2e_fake_providers
from backend.app.db.session import SessionLocal, check_db_connection
from backend.app.services.ingestion import reap_stale_jobs
from backend.app.services.llm_daily_quota import daily_quota
from backend.app.services.llm_pacing import llm_pacer
from backend.app.services.ocr import tesseract_status
from backend.app.services.query_models import model_status, start_warm_up

settings = Settings()
logger = logging.getLogger("legalai.startup")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refuse an insecure configuration (SEC-002, SEC-005), then reap ingestion jobs left non-terminal (BE-005)."""
    # Raises InsecureConfigurationError, which aborts startup; the message never contains a secret.
    run_startup_security_checks(settings, SessionLocal)
    db = SessionLocal()
    try:
        reaped = reap_stale_jobs(db, upload_dir=ingest_api.UPLOAD_DIR)
        if reaped:
            logger.warning("startup reaped %d stale ingestion job(s)", len(reaped))
    except Exception as exc:  # never block startup on the reaper
        logger.error("startup stale-job reaper failed: %s", type(exc).__name__)
    finally:
        db.close()
    if settings.legalai_model_warmup:
        # Load the query embedder and reranker in the background; /health reports the progress.
        start_warm_up(get_retrieval_service)
    try:
        # Step 23: register the configured answer models' rate-limit buckets so /health shows them from the start.
        configure_answer_pacing(settings)
    except Exception as exc:  # never block startup on it; requests register their buckets themselves
        logger.error("startup answer pacing setup failed: %s", type(exc).__name__)
    yield


app = FastAPI(
    title="LegalAI Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# BE-003: every error response is {error, code, detail} (see core/errors.py and docs/API_CONTRACTS.md).
install_error_handlers(app)
install_request_id_logging()

# CORS Configuration
unique_origins = allowed_origins(settings)

# Starlette runs the last-added middleware first: request ID, body size, the Origin check, CORS, then the
# unhandled-error middleware, which is inside CORS so a 500 still carries the CORS headers.
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=unique_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# SEC-006: cookie-authenticated writes must come from an allowed origin (see core/request_guards.py).
app.add_middleware(OriginCheckMiddleware, allowed_origins=unique_origins)
# SEC-008: reject an oversize body by its Content-Length before reading it.
app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=max_request_body_bytes(settings.max_upload_size_mb))
app.add_middleware(RequestIdMiddleware)

# Test only (step 17): browser end-to-end runs. Refused here, before anything is imported, outside APP_ENV=test,
# and again by the startup checks; the module is never imported otherwise.
if settings.legalai_e2e_fake_providers:
    validate_e2e_fake_providers(settings)
    from backend.app.testing.e2e import install_e2e_providers

    install_e2e_providers(app, settings)

# Router Wiring
app.include_router(auth_router)
app.include_router(ingest_router)
app.include_router(analytics_router)
app.include_router(query_router)
app.include_router(query_history_router)
app.include_router(lawyer_verification_router)


@app.get("/health", tags=["Health"])
def health_check() -> dict:
    """Verify backend and database service health without exposing credentials."""
    is_db_connected, db_status = check_db_connection()
    status = "ok" if is_db_connected else "degraded"
    return {
        "status": status,
        "database": {
            "type": "postgresql",
            "connected": is_db_connected,
            "status": db_status,
        },
        # Query embedder and reranker: not_loaded | loading | loaded | failed, with devices once loaded.
        "models": model_status(),
        # Tesseract OCR for scanned PDFs: available, version, languages (or the reason it is unavailable).
        "ocr": tesseract_status(settings),
        # Step 23 answer pacing: requests waiting for model capacity, the estimated wait of the last one, and each
        # paced model's available tokens (services/llm_pacing.py). Counts only.
        "llm_queue": {
            "enabled": settings.legalai_llm_pacing_enabled,
            "max_wait_seconds": settings.legalai_llm_queue_max_wait_seconds,
            **llm_pacer.status(),
        },
        # Step 24b daily budgets: tokens and requests used today (UTC) per model, remaining tokens, and any model
        # marked exhausted by the provider (services/llm_daily_quota.py). Counts only.
        "llm_daily": daily_quota(settings).status(),
    }
