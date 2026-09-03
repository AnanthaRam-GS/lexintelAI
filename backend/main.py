"""FastAPI application entrypoint for LegalAI."""

from fastapi import FastAPI

from backend.app.db.session import check_db_connection

app = FastAPI(
    title="LegalAI Backend API",
    version="0.1.0",
)


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
