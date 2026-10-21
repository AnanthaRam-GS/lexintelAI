"""Security checks that refuse an unsafe configuration (SEC-002, SEC-005).

- The JWT secret must be set, at least 32 bytes, and not the old public default,
  outside ``APP_ENV=test``. (In test, an unset secret becomes a random per-process one.)
- Outside development and test, no user may have a password that verifies against
  a historical seed password.

Errors never include the secret, any password or any email; only counts and user IDs.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

from backend.app.core.config import Settings
from backend.app.core.known_credentials import PUBLIC_JWT_SECRET_SHA256, historical_seed_passwords

logger = logging.getLogger("legalai.security")

MIN_JWT_SECRET_BYTES = 32
SEED_CHECK_EXEMPT_ENVS = {"development", "test"}


class InsecureConfigurationError(RuntimeError):
    """The application must not start with this configuration."""


def app_env(settings: Settings) -> str:
    return (settings.app_env or "").strip().casefold()


def jwt_secret_problem(secret: str | None) -> str | None:
    """Why ``secret`` is unusable, or None. The message never contains the value."""
    value = (secret or "").strip()
    if not value:
        return "JWT_SECRET_KEY is not set"
    if hashlib.sha256(value.encode("utf-8")).hexdigest() == PUBLIC_JWT_SECRET_SHA256:
        return "JWT_SECRET_KEY is the old public default"
    if len(value.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        return f"JWT_SECRET_KEY is shorter than {MIN_JWT_SECRET_BYTES} bytes"
    return None


def validate_jwt_secret(settings: Settings) -> None:
    if app_env(settings) == "test":
        return
    problem = jwt_secret_problem(settings.jwt_secret_key)
    if problem:
        raise InsecureConfigurationError(
            f"{problem}. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\" "
            "and set JWT_SECRET_KEY in .env (see docs/SECURITY.md)."
        )


def users_with_seed_passwords(rows: list[tuple[int, str]], verify: Callable[[str, str], bool]) -> list[int]:
    """IDs of users whose password hash verifies against a historical seed password."""
    candidates = historical_seed_passwords()
    return [user_id for user_id, hashed in rows if hashed and any(verify(candidate, hashed) for candidate in candidates)]


def validate_no_seed_passwords(settings: Settings, session_factory: Callable[[], Any]) -> None:
    if app_env(settings) in SEED_CHECK_EXEMPT_ENVS:
        return
    from backend.app.core.security import verify_password
    from backend.app.db.models import User

    db = session_factory()
    try:
        rows = [(user.id, user.hashed_password) for user in db.query(User.id, User.hashed_password).all()]
    finally:
        db.close()
    found = users_with_seed_passwords(rows, verify_password)
    if found:
        raise InsecureConfigurationError(
            f"{len(found)} user account(s) (ids {sorted(found)}) use a known development seed password. "
            "Reset those passwords before starting outside development (see docs/SECURITY.md)."
        )


def run_startup_security_checks(settings: Settings, session_factory: Callable[[], Any]) -> None:
    validate_jwt_secret(settings)
    validate_no_seed_passwords(settings, session_factory)
    logger.info("startup_security_checks passed app_env=%s", app_env(settings))
