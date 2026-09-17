"""Authentication API contracts for LegalAI."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Login credentials; user role is derived by the backend."""

    email: str
    password: str


class RegisterRequest(BaseModel):
    """Public account registration request; role is never client-controlled."""

    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class AuthenticatedUser(BaseModel):
    """Authenticated user identity returned after login."""

    id: int | str
    email: str
    role: Literal["public", "lawyer", "admin"]
    full_name: str | None = None
    email_verified: bool = False


class LoginResponse(BaseModel):
    """Login response for HttpOnly-cookie based authentication."""

    user: AuthenticatedUser
    message: str


class RegistrationResponse(BaseModel):
    """Safe registration response without password material."""

    user: AuthenticatedUser
    message: str
    email_verification_required: bool = True
    dev_verification_otp: str | None = None


class VerifyEmailRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    otp: str = Field(..., min_length=6, max_length=6)


class ResendVerificationRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class EmailVerificationResponse(BaseModel):
    email_verified: bool
    message: str
    dev_verification_otp: str | None = None
    expires_at: datetime | None = None
