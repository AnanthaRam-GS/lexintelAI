"""FastAPI dependencies for authentication, user session, and role enforcement."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
import jwt
from sqlalchemy.orm import Session

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
        )
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )

    try:
        user_id = int(user_id_str)
        user = db.query(User).filter(User.id == user_id).first()
    except ValueError:
        user = db.query(User).filter(User.email == user_id_str).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def require_role(allowed_roles: list[str]) -> Callable[[User], User]:
    """Dependency factory restricting route access to specific user roles."""

    def _role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{current_user.role}'",
            )
        return current_user

    return _role_checker


require_admin = require_role(["admin"])
require_lawyer_or_admin = require_role(["lawyer", "admin"])
