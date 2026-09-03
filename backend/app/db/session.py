"""Database engine and session management for LegalAI."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings

settings = Settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency generator yielding a database session for FastAPI requests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> tuple[bool, str]:
    """Safely verify PostgreSQL database connectivity without leaking credentials.

    Returns:
        tuple[bool, str]: (is_connected, status_message)
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "PostgreSQL connected"
    except Exception as exc:
        # Avoid leaking database URL, passwords, or internal server paths
        error_type = type(exc).__name__
        return False, f"PostgreSQL unavailable: {error_type}"
