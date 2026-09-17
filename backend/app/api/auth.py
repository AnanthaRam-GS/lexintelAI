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
from backend.app.db.models import EmailVerificationOtp, User
from backend.app.db.session import get_db
from backend.app.models.auth import (
    AuthenticatedUser,
    EmailVerificationResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegistrationResponse,
    ResendVerificationRequest,
    VerifyEmailRequest,
)
from backend.app.services.email_delivery import EmailDeliveryError, get_email_delivery_service

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


def generate_email_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def create_email_verification_otp(db: Session, user: User, settings: Settings) -> tuple[str, EmailVerificationOtp]:
    now = datetime.now(UTC)
    db.query(EmailVerificationOtp).filter(
        EmailVerificationOtp.user_id == user.id,
        EmailVerificationOtp.consumed_at.is_(None),
    ).update({"consumed_at": now}, synchronize_session=False)
    raw_otp = generate_email_otp()
    row = EmailVerificationOtp(
        user_id=user.id,
        otp_hash=token_hash(raw_otp),
        expires_at=now + timedelta(minutes=settings.email_otp_expiry_minutes),
        attempts=0,
    )
    db.add(row)
    db.flush()
    return raw_otp, row


def dev_otp(raw_otp: str, settings: Settings) -> str | None:
    return raw_otp if settings.app_env in {"development", "test"} and settings.expose_dev_verification_tokens else None


def send_verification_otp(email: str, raw_otp: str, settings: Settings) -> None:
    get_email_delivery_service(settings).send_email_verification_otp(
        email,
        raw_otp,
        settings.email_otp_expiry_minutes,
    )


def latest_active_otp(db: Session, user: User) -> EmailVerificationOtp | None:
    return (
        db.query(EmailVerificationOtp)
        .filter(EmailVerificationOtp.user_id == user.id, EmailVerificationOtp.consumed_at.is_(None))
        .order_by(EmailVerificationOtp.created_at.desc(), EmailVerificationOtp.id.desc())
        .first()
    )


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


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
        raw_otp, _ = create_email_verification_otp(db, user, settings)
        send_verification_otp(user.email, raw_otp, settings)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_ALREADY_REGISTERED", "message": "An account already exists for this email."},
        ) from exc
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EMAIL_DELIVERY_FAILED", "message": "Verification email could not be sent. Try again later."},
        ) from exc
    db.refresh(user)
    return RegistrationResponse(
        user=user_response(user),
        message="Registration successful. Enter the 6-digit code sent to your email.",
        dev_verification_otp=dev_otp(raw_otp, settings),
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
    """Consume a single-use email verification OTP."""
    now = datetime.now(UTC)
    normalized_email = normalize_email(request.email)
    validate_email_format(normalized_email)
    if not request.otp.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_OTP", "message": "Enter the 6-digit verification code."},
        )
    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OTP", "message": "Invalid or expired verification code."},
        )
    row = latest_active_otp(db, user)
    if row is None or as_utc(row.expires_at) < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OR_EXPIRED_OTP", "message": "Invalid or expired verification code."},
        )
    if row.attempts >= Settings().email_otp_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "OTP_ATTEMPTS_EXCEEDED", "message": "Too many verification attempts. Request a new code."},
        )
    row.attempts += 1
    if row.otp_hash != token_hash(request.otp):
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_OTP", "message": "Invalid or expired verification code."},
        )
    user.email_verified = 1
    row.consumed_at = now
    db.commit()
    return EmailVerificationResponse(email_verified=True, message="Email verified successfully.")


@router.post("/resend-verification", response_model=EmailVerificationResponse)
def resend_verification(
    request: ResendVerificationRequest,
    db: Session = Depends(get_db),
) -> EmailVerificationResponse:
    """Replace any active verification OTP for the account, subject to cooldown."""
    normalized_email = normalize_email(request.email)
    validate_email_format(normalized_email)
    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None:
        return EmailVerificationResponse(
            email_verified=False,
            message="If the account exists, a new verification code will be sent.",
        )
    if user.email_verified:
        return EmailVerificationResponse(email_verified=True, message="Email already verified.")
    settings = Settings()
    now = datetime.now(UTC)
    existing = latest_active_otp(db, user)
    if (
        existing
        and existing.created_at
        and (now - as_utc(existing.created_at)).total_seconds() < settings.email_otp_resend_cooldown_seconds
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "OTP_RESEND_COOLDOWN", "message": "Please wait before requesting another code."},
        )
    raw_otp, row = create_email_verification_otp(db, user, settings)
    try:
        send_verification_otp(user.email, raw_otp, settings)
        db.commit()
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EMAIL_DELIVERY_FAILED", "message": "Verification email could not be sent. Try again later."},
        ) from exc
    return EmailVerificationResponse(
        email_verified=False,
        message="A new verification code has been sent.",
        dev_verification_otp=dev_otp(raw_otp, settings),
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
