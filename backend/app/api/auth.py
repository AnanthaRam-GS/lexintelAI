"""Authentication API endpoints for LegalAI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.dependencies import get_current_user
from backend.app.core.security import (
    COOKIE_NAME,
    create_access_token,
    get_cookie_options,
    hash_password,
    verify_password,
)
from backend.app.db.models import EmailVerificationToken, User
from backend.app.db.session import get_db
from backend.app.models.auth import (
    AuthenticatedUser,
    EmailVerificationResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegistrationResponse,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def user_response(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        role=user.role,
        full_name=user.full_name,
        email_verified=bool(user.email_verified),
    )


def validate_registration_password(password: str) -> None:
    if password.strip() != password or not password.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "WEAK_PASSWORD", "message": "Password must not be blank or padded with whitespace."},
        )


def validate_email_format(email: str) -> None:
    if not EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_EMAIL", "message": "Enter a valid email address."},
        )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_email_verification_token(db: Session, user: User, settings: Settings) -> tuple[str, EmailVerificationToken]:
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    raw_token = secrets.token_urlsafe(32)
    row = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.email_verification_token_minutes),
    )
    db.add(row)
    db.flush()
    return raw_token, row


def dev_token(raw_token: str, settings: Settings) -> str | None:
    return raw_token if settings.app_env in {"development", "test"} and settings.expose_dev_verification_tokens else None


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegistrationResponse:
    """Create an ordinary public account; privileged roles are backend/admin controlled."""
    settings = Settings()
    validate_registration_password(request.password)
    normalized_email = normalize_email(request.email)
    validate_email_format(normalized_email)
    user = User(
        full_name=request.full_name.strip(),
        email=normalized_email,
        hashed_password=hash_password(request.password),
        role="public",
        email_verified=0,
        is_active=1,
    )
    db.add(user)
    try:
        db.flush()
        raw_token, _ = create_email_verification_token(db, user, settings)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_ALREADY_REGISTERED", "message": "An account already exists for this email."},
        ) from exc
    db.refresh(user)
    return RegistrationResponse(
        user=user_response(user),
        message="Registration successful. Verify your email before applying for lawyer access.",
        dev_verification_token=dev_token(raw_token, settings),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Validate credentials, derive account role, and set JWT in secure HttpOnly cookie."""
    normalized_email = normalize_email(request.email)
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

    return LoginResponse(user=user_response(user), message="Login successful")


@router.post("/verify-email", response_model=EmailVerificationResponse)
def verify_email(request: VerifyEmailRequest, db: Session = Depends(get_db)) -> EmailVerificationResponse:
    """Consume a single-use email verification token."""
    row = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.token_hash == token_hash(request.token), EmailVerificationToken.used_at.is_(None))
        .first()
    )
    now = datetime.now(UTC)
    if row is None or row.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OR_EXPIRED_TOKEN", "message": "The verification link is invalid or expired."},
        )
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_TOKEN", "message": "Invalid verification token."})
    user.email_verified = 1
    row.used_at = now
    db.commit()
    return EmailVerificationResponse(email_verified=True, message="Email verified successfully.")


@router.post("/resend-verification", response_model=EmailVerificationResponse)
def resend_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmailVerificationResponse:
    """Replace any active verification token for the authenticated account."""
    if current_user.email_verified:
        return EmailVerificationResponse(email_verified=True, message="Email already verified.")
    settings = Settings()
    raw_token, row = create_email_verification_token(db, current_user, settings)
    db.commit()
    return EmailVerificationResponse(
        email_verified=False,
        message="Verification token refreshed. Email delivery integration is future production work.",
        dev_verification_token=dev_token(raw_token, settings),
        expires_at=row.expires_at,
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
    return user_response(current_user)
