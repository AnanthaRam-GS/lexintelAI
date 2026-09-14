"""Security and authentication utilities for LegalAI.

Provides bcrypt-based password hashing/verification, PyJWT token creation/validation,
and HttpOnly cookie configuration helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from backend.app.core.config import Settings

COOKIE_NAME = "access_token"
DEFAULT_DEV_SECRET = "legalai-development-jwt-secret-key-must-be-at-least-32-bytes-long!"


def _get_settings(settings: Settings | None = None) -> Settings:
    return settings or Settings()


def get_jwt_secret(settings: Settings | None = None) -> str:
    """Return configured JWT secret or a safe development fallback."""
    s = _get_settings(settings)
    if s.jwt_secret_key and len(s.jwt_secret_key.strip()) > 0:
        return s.jwt_secret_key.strip()
    if s.app_env.casefold() == "production":
        raise RuntimeError("JWT_SECRET_KEY must be configured in production.")
    return DEFAULT_DEV_SECRET


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
    """Return standard cookie options for HttpOnly JWT storage."""
    s = _get_settings(settings)
    is_production = s.app_env.casefold() == "production"
    return {
        "httponly": True,
        "secure": is_production,
        "samesite": "lax",
        "path": "/",
        "max_age": s.jwt_expiry_minutes * 60,
    }
