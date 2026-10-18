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
from backend.app.api.query import router as query_router
from backend.app.api.query_history import router as query_history_router
from backend.app.core.config import Settings
from backend.app.db.session import SessionLocal, check_db_connection
from backend.app.services.ingestion import reap_stale_jobs

settings = Settings()
logger = logging.getLogger("legalai.startup")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Reap ingestion jobs left non-terminal by a previous process (BE-005)."""
    db = SessionLocal()
    try:
        reaped = reap_stale_jobs(db, upload_dir=ingest_api.UPLOAD_DIR)
        if reaped:
            logger.warning("startup reaped %d stale ingestion job(s)", len(reaped))
    except Exception as exc:  # never block startup on the reaper
        logger.error("startup stale-job reaper failed: %s", type(exc).__name__)
    finally:
        db.close()
    yield


app = FastAPI(
    title="LegalAI Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Configuration
configured_origins = [
    settings.frontend_origin,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
unique_origins = list(dict.fromkeys(filter(None, configured_origins)))

app.add_middleware(
    CORSMiddleware,
    allow_origins=unique_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    }
