"""Database engine and session management for LegalAI."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings

# Test runs that never open a connection (unit suites without a database) get this; it cannot resolve or connect.
UNCONFIGURED_TEST_DATABASE_URL = "postgresql://unconfigured.invalid:5432/legalai_unconfigured"


class MissingConfigurationError(RuntimeError):
    """A required setting is missing; the application must not start."""


def resolve_database_url(settings: Settings) -> str:
    """DATABASE_URL, which has no default (step 20). Missing: an error outside APP_ENV=test, a dead URL in test."""
    url = (settings.database_url or "").strip()
    if url:
        return url
    if (settings.app_env or "").strip().casefold() == "test":
        return UNCONFIGURED_TEST_DATABASE_URL
    raise MissingConfigurationError(
        "DATABASE_URL is not set. Copy .env.example to .env and set DATABASE_URL to your PostgreSQL database "
        "(postgresql://<user>:<password>@<host>:5432/<database>); see README.md, \"Configure\"."
    )


settings = Settings()

engine = create_engine(
    resolve_database_url(settings),
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
