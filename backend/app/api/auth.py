"""Authentication API endpoints for LegalAI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.core.security import (
    COOKIE_NAME,
    create_access_token,
    get_cookie_options,
    verify_password,
)
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.models.auth import AuthenticatedUser, LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Validate credentials, derive account role, and set JWT in secure HttpOnly cookie."""
    normalized_email = request.email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Role is derived directly from PostgreSQL user record
    token_payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
    }
    access_token = create_access_token(data=token_payload)

    # Set secure HttpOnly cookie
    cookie_opts = get_cookie_options()
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=cookie_opts["httponly"],
        secure=cookie_opts["secure"],
        samesite=cookie_opts["samesite"],
        path=cookie_opts["path"],
        max_age=cookie_opts["max_age"],
    )

    return LoginResponse(
        user=AuthenticatedUser(
            id=user.id,
            email=user.email,
            role=user.role,
        ),
        message="Login successful",
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    """Clear the authentication cookie."""
    cookie_opts = get_cookie_options()
    response.delete_cookie(
        key=COOKIE_NAME,
        path=cookie_opts["path"],
        httponly=cookie_opts["httponly"],
        samesite=cookie_opts["samesite"],
    )
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=AuthenticatedUser)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> AuthenticatedUser:
    """Return the profile of the currently authenticated user."""
    return AuthenticatedUser(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
    )
