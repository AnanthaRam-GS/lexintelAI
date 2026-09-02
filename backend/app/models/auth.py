"""Authentication API contracts for LegalAI."""

from typing import Literal

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Login credentials; user role is derived by the backend."""

    email: str
    password: str


class AuthenticatedUser(BaseModel):
    """Authenticated user identity returned after login."""

    id: int | str
    email: str
    role: Literal["lawyer", "admin"]


class LoginResponse(BaseModel):
    """Login response for HttpOnly-cookie based authentication."""

    user: AuthenticatedUser
    message: str
