"""Lawyer verification application and admin-review endpoints."""

from __future__ import annotations

import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.dependencies import get_current_user, require_admin
from backend.app.db.models import LawyerVerificationApplication, User
from backend.app.db.session import get_db
from backend.app.models.lawyer_verification import (
    AdminLawyerApplicationList,
    AdminLawyerApplicationResponse,
    LawyerApplicationEnvelope,
    LawyerApplicationResponse,
    ReviewDecisionRequest,
)

router = APIRouter(tags=["Lawyer verification"])

ALLOWED_PROOF_TYPES = {
    "application/pdf": b"%PDF",
    "image/png": b"\x89PNG",
    "image/jpeg": b"\xff\xd8\xff",
}
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
ACTIVE_STATUSES = {"PENDING", "UNDER_REVIEW"}


@router.post("/lawyer-applications", response_model=LawyerApplicationResponse, status_code=status.HTTP_201_CREATED)
async def submit_lawyer_application(
    bar_council: str = Form(..., min_length=1, max_length=255),
    enrollment_number: str = Form(..., min_length=1, max_length=100),
    enrollment_year: int = Form(..., ge=1900, le=2100),
    jurisdiction: str = Form(..., min_length=1, max_length=150),
    organization: str | None = Form(None, max_length=255),
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LawyerApplicationResponse:
    """Submit credential evidence for admin review without touching legal corpus ingestion."""
    if current_user.role == "lawyer":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "ALREADY_VERIFIED", "message": "This account is already verified as a lawyer."})
    if not current_user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "EMAIL_VERIFICATION_REQUIRED", "message": "Verify your email before applying for lawyer access."})
    existing = latest_application(db, current_user.id)
    if existing and existing.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "APPLICATION_ALREADY_PENDING", "message": "A lawyer verification application is already pending."})
    safe_name, content_type, storage_key = await store_proof_document(proof)
    application = LawyerVerificationApplication(
        user_id=current_user.id,
        bar_council=bar_council.strip(),
        enrollment_number=enrollment_number.strip(),
        enrollment_year=enrollment_year,
        jurisdiction=jurisdiction.strip(),
        organization=organization.strip() if organization else None,
        proof_file_name=safe_name,
        proof_content_type=content_type,
        proof_storage_key=storage_key,
        status="PENDING",
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application_response(application)


@router.get("/lawyer-applications/me", response_model=LawyerApplicationEnvelope)
def get_my_lawyer_application(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LawyerApplicationEnvelope:
    application = latest_application(db, current_user.id)
    return LawyerApplicationEnvelope(application=application_response(application) if application else None)


@router.get("/admin/lawyer-applications", response_model=AdminLawyerApplicationList)
def list_lawyer_applications(
    status_filter: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminLawyerApplicationList:
    query = db.query(LawyerVerificationApplication).join(User, LawyerVerificationApplication.user_id == User.id)
    if status_filter:
        query = query.filter(LawyerVerificationApplication.status == status_filter.strip().upper())
    rows = query.order_by(LawyerVerificationApplication.submitted_at.desc()).limit(min(max(limit, 1), 100)).all()
    return AdminLawyerApplicationList(applications=[admin_application_response(row) for row in rows])


@router.get("/admin/lawyer-applications/{application_id}", response_model=AdminLawyerApplicationResponse)
def get_lawyer_application_detail(
    application_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminLawyerApplicationResponse:
    return admin_application_response(get_application_or_404(db, application_id))


@router.post("/admin/lawyer-applications/{application_id}/approve", response_model=AdminLawyerApplicationResponse)
def approve_lawyer_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminLawyerApplicationResponse:
    application = get_application_or_404(db, application_id)
    if application.status == "VERIFIED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "APPLICATION_ALREADY_VERIFIED", "message": "Application is already verified."})
    if application.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "APPLICATION_NOT_APPROVABLE", "message": "Application is not in a reviewable state."})
    user = db.query(User).filter(User.id == application.user_id).one()
    application.status = "VERIFIED"
    application.reviewed_at = datetime.now(UTC)
    application.reviewed_by = current_admin.id
    user.role = "lawyer"
    db.commit()
    db.refresh(application)
    return admin_application_response(application)


@router.post("/admin/lawyer-applications/{application_id}/reject", response_model=AdminLawyerApplicationResponse)
def reject_lawyer_application(
    application_id: int,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminLawyerApplicationResponse:
    application = get_application_or_404(db, application_id)
    if application.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "APPLICATION_NOT_REJECTABLE", "message": "Application is not in a reviewable state."})
    if not request.reason or not request.reason.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "REJECTION_REASON_REQUIRED", "message": "A safe rejection reason is required."})
    application.status = "REJECTED"
    application.reviewed_at = datetime.now(UTC)
    application.reviewed_by = current_admin.id
    application.review_note = request.reason.strip()
    db.commit()
    db.refresh(application)
    return admin_application_response(application)


@router.post("/admin/lawyer-applications/{application_id}/request-resubmission", response_model=AdminLawyerApplicationResponse)
def request_lawyer_resubmission(
    application_id: int,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminLawyerApplicationResponse:
    application = get_application_or_404(db, application_id)
    if application.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "APPLICATION_NOT_REVIEWABLE", "message": "Application is not in a reviewable state."})
    if not request.reason or not request.reason.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "RESUBMISSION_REASON_REQUIRED", "message": "A resubmission reason is required."})
    application.status = "RESUBMISSION_REQUIRED"
    application.reviewed_at = datetime.now(UTC)
    application.reviewed_by = current_admin.id
    application.review_note = request.reason.strip()
    db.commit()
    db.refresh(application)
    return admin_application_response(application)


async def store_proof_document(proof: UploadFile) -> tuple[str, str, str]:
    settings = Settings()
    filename = Path(proof.filename or "").name.replace(" ", "_")
    suffix = Path(filename).suffix.lower()
    content_type = (proof.content_type or "").lower()
    if suffix not in ALLOWED_EXTENSIONS or content_type not in ALLOWED_PROOF_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_PROOF_TYPE", "message": "Proof must be a PDF, PNG, or JPEG file."})
    first = await proof.read(8)
    expected = ALLOWED_PROOF_TYPES[content_type]
    if not first.startswith(expected):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_PROOF_HEADER", "message": "Proof file header does not match its declared type."})
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    private_dir = Path(settings.verification_document_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{secrets.token_urlsafe(16)}{suffix}"
    path = private_dir / storage_name
    total = len(first)
    with path.open("wb") as handle:
        handle.write(first)
        while chunk := await proof.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                handle.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail={"code": "PROOF_TOO_LARGE", "message": "Proof file exceeds the configured upload limit."})
            handle.write(chunk)
    return filename or f"proof{suffix}", content_type, storage_name


def latest_application(db: Session, user_id: int) -> LawyerVerificationApplication | None:
    return (
        db.query(LawyerVerificationApplication)
        .filter(LawyerVerificationApplication.user_id == user_id)
        .order_by(LawyerVerificationApplication.created_at.desc())
        .first()
    )


def get_application_or_404(db: Session, application_id: int) -> LawyerVerificationApplication:
    application = db.query(LawyerVerificationApplication).filter(LawyerVerificationApplication.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "APPLICATION_NOT_FOUND", "message": "Lawyer application not found."})
    return application


def application_response(application: LawyerVerificationApplication) -> LawyerApplicationResponse:
    return LawyerApplicationResponse(
        id=application.id,
        user_id=application.user_id,
        bar_council=application.bar_council,
        enrollment_number=application.enrollment_number,
        enrollment_year=application.enrollment_year,
        jurisdiction=application.jurisdiction,
        organization=application.organization,
        proof_file_name=application.proof_file_name,
        proof_content_type=application.proof_content_type,
        status=application.status,
        submitted_at=application.submitted_at,
        reviewed_at=application.reviewed_at,
        review_note=application.review_note,
    )


def admin_application_response(application: LawyerVerificationApplication) -> AdminLawyerApplicationResponse:
    base = application_response(application).model_dump()
    return AdminLawyerApplicationResponse(
        **base,
        applicant_email=application.user.email,
        applicant_name=application.user.full_name,
        reviewed_by=application.reviewed_by,
    )
