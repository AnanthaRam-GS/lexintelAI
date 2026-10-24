"""FastAPI dependencies for authentication, user session, and role enforcement."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
import jwt
from sqlalchemy.orm import Session

from backend.app.core.errors import api_error
from backend.app.core.security import COOKIE_NAME, decode_access_token
from backend.app.db.models import User
from backend.app.db.session import get_db


def get_token_from_cookie(request: Request) -> str:
    """Extract the JWT access token from request cookies.

    Raises:
        HTTPException: 401 if cookie is missing.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        # Check Authorization header as fallback for testing/API clients
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "NOT_AUTHENTICATED", "Please sign in to continue.")
    return token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Validate JWT cookie and retrieve the authenticated user from PostgreSQL.

    Raises:
        HTTPException: 401 if token is expired, invalid, or user is not found.
    """
    token = get_token_from_cookie(request)
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "SESSION_EXPIRED", "Your session has expired. Please sign in again.")
    except jwt.PyJWTError:
        raise invalid_session()

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise invalid_session()

    try:
        user_id = int(user_id_str)
        user = db.query(User).filter(User.id == user_id).first()
    except ValueError:
        user = db.query(User).filter(User.email == user_id_str).first()

    # SEC-004: a missing or deactivated account gets the same generic failure as a bad token.
    # The role always comes from this DB row, never from the token's claims.
    if user is None or not user.is_active:
        raise invalid_session()

    return user


def invalid_session() -> HTTPException:
    """One body for a bad token, a token without a subject, and a missing or deactivated account (SEC-004)."""
    return api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_SESSION", "Your session is not valid. Please sign in again.")


def require_role(allowed_roles: list[str]) -> Callable[[User], User]:
    """Dependency factory restricting route access to specific user roles."""

    def _role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise api_error(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You do not have access to this feature.")
        return current_user

    return _role_checker


require_admin = require_role(["admin"])
require_lawyer_or_admin = require_role(["lawyer", "admin"])
