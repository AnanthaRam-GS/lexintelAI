"""Security and authentication utilities for LegalAI.

Provides bcrypt-based password hashing/verification, PyJWT token creation/validation,
and HttpOnly cookie configuration helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Any

import bcrypt
import jwt

from backend.app.core.config import Settings

COOKIE_NAME = "access_token"
COOKIE_SAMESITE_VALUES = {"lax", "strict", "none"}
# APP_ENV=test only, when no secret is configured: a random secret for this process.
_TEST_PROCESS_SECRET = secrets.token_urlsafe(48)


def _get_settings(settings: Settings | None = None) -> Settings:
    return settings or Settings()


def get_jwt_secret(settings: Settings | None = None) -> str:
    """Return the configured JWT secret; there is no public fallback (SEC-005).

    Outside APP_ENV=test an unset, default or short secret raises. In test, an
    unset secret is a random per-process value.
    """
    from backend.app.core.startup_checks import InsecureConfigurationError, app_env, jwt_secret_problem

    s = _get_settings(settings)
    if app_env(s) == "test" and not (s.jwt_secret_key or "").strip():
        return _TEST_PROCESS_SECRET
    problem = jwt_secret_problem(s.jwt_secret_key)
    if problem and app_env(s) != "test":
        raise InsecureConfigurationError(f"{problem}; see docs/SECURITY.md.")
    return s.jwt_secret_key.strip()


def hash_password(password: str) -> str:
    """Hash a plaintext password with a unique bcrypt salt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
    settings: Settings | None = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        data: Payload claims (e.g. sub, email, role).
        expires_delta: Optional custom expiry duration.
        settings: Optional Settings instance.

    Returns:
        Encoded JWT string.
    """
    s = _get_settings(settings)
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=s.jwt_expiry_minutes)

    to_encode.update({
        "exp": expire,
        "iat": now,
    })

    secret = get_jwt_secret(s)
    return jwt.encode(to_encode, secret, algorithm=s.jwt_algorithm)


def decode_access_token(
    token: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: Raw JWT string.
        settings: Optional Settings instance.

    Returns:
        Decoded payload dictionary.

    Raises:
        jwt.PyJWTError: If token is expired, tampered, or invalid.
    """
    s = _get_settings(settings)
    secret = get_jwt_secret(s)
    return jwt.decode(token, secret, algorithms=[s.jwt_algorithm])


def get_cookie_options(settings: Settings | None = None) -> dict[str, Any]:
    """Cookie options for the HttpOnly JWT cookie (SEC-006).

    HttpOnly always; an explicit SameSite (AUTH_COOKIE_SAMESITE, default lax);
    Secure in production, and always with SameSite=None (browsers require it).
    """
    s = _get_settings(settings)
    samesite = (s.auth_cookie_samesite or "lax").strip().lower()
    if samesite not in COOKIE_SAMESITE_VALUES:
        samesite = "lax"
    is_production = s.app_env.casefold() == "production"
    return {
        "httponly": True,
        "secure": is_production or samesite == "none",
        "samesite": samesite,
        "path": "/",
        "max_age": s.jwt_expiry_minutes * 60,
    }
