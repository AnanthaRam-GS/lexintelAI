"""Corpus ingestion API endpoints for LegalAI."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import re
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.dependencies import require_admin
from backend.app.core.errors import api_error
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.models.ingest import (
    CorpusStatsResponse,
    IngestionStatus,
    IngestionStatusResponse,
    IngestionUploadResponse,
)
from backend.app.services.ingestion import (
    create_ingestion_job,
    find_document_by_checksum,
    get_corpus_stats,
    get_ingestion_job,
    get_job_chunk_count,
    process_ingestion_job,
    reap_stale_jobs,
)

logger = logging.getLogger("legalai.ingest")

router = APIRouter(prefix="/ingest", tags=["Corpus Ingestion"])
settings = Settings()

UPLOAD_DIR = Path("data/raw/uploads")


def sanitize_filename(filename: str) -> str:
    """Sanitize uploaded filename to prevent directory traversal."""
    cleaned = re.sub(r"[^\w\-.]", "_", Path(filename).name)
    return cleaned or "document.pdf"


UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


async def read_upload_within_limit(file: UploadFile, *, max_bytes: int, limit_mb: int) -> bytes:
    """SEC-008: read the upload in chunks and stop with 413 as soon as it passes the limit.

    At most ``max_bytes`` plus one chunk is ever read, never the whole oversize file.
    """
    received = bytearray()
    while chunk := await file.read(UPLOAD_READ_CHUNK_BYTES):
        received.extend(chunk)
        if len(received) > max_bytes:
            raise api_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF_TOO_LARGE", f"File size exceeds limit of {limit_mb} MB.", limit_mb=limit_mb)
    return bytes(received)


@router.post(
    "/upload",
    response_model=IngestionUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_corpus_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    court_level: str | None = Form(None),
    year: int | None = Form(None),
    source_url: str | None = Form(None),
    case_name: str | None = Form(None),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> IngestionUploadResponse:
    """Accept an administrator-supplied PDF for ingestion into the shared corpus."""
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise api_error(status.HTTP_400_BAD_REQUEST, "INVALID_PDF_EXTENSION", "Uploaded file must have a .pdf extension.")

    content_type = (file.content_type or "").lower().strip()
    if content_type and content_type not in {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    }:
        raise api_error(status.HTTP_400_BAD_REQUEST, "INVALID_PDF_MIME_TYPE", "Invalid content type. Must be a PDF document.")

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    file_bytes = await read_upload_within_limit(file, max_bytes=max_bytes, limit_mb=settings.max_upload_size_mb)
    if len(file_bytes) == 0:
        raise api_error(status.HTTP_400_BAD_REQUEST, "EMPTY_UPLOAD", "Uploaded file is empty.")

    # Validate PDF magic header signature within the first 1024 bytes per ISO 32000-1
    if not file_bytes.startswith(b"%PDF-") and b"%PDF-" not in file_bytes[:1024]:
        raise api_error(status.HTTP_400_BAD_REQUEST, "INVALID_PDF_HEADER", "Invalid PDF file: Missing '%PDF-' header signature.")

    checksum = hashlib.sha256(file_bytes).hexdigest()
    # DATA-003: reject a known document before saving the upload, creating a
    # job or touching any store. The write phase re-checks under its lock.
    existing = find_document_by_checksum(db, checksum)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DOCUMENT_ALREADY_INGESTED",
                "message": "This document has already been ingested.",
                "document_id": existing.id,
            },
        )
    job_id = str(uuid.uuid4())

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(filename)
    saved_path = UPLOAD_DIR / f"{job_id}_{safe_name}"
    saved_path.write_bytes(file_bytes)

    # Persist job in database
    job = create_ingestion_job(db=db, job_id=job_id)

    # Dispatch asynchronous background ingestion
    background_tasks.add_task(
        process_ingestion_job,
        job_id=job.id,
        file_path=str(saved_path),
        doc_type=doc_type.strip(),
        court_level=court_level.strip() if court_level else None,
        year=year,
        source_url=source_url.strip() if source_url else None,
        checksum=checksum,
        case_name=case_name.strip() if case_name else safe_name,
    )

    return IngestionUploadResponse(
        job_id=job.id,
        status=IngestionStatus.QUEUED,
    )


@router.get(
    "/status/{job_id}",
    response_model=IngestionStatusResponse,
)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> IngestionStatusResponse:
    """Retrieve current progress, stage, document id, chunk count, or error for an ingestion job."""
    try:
        reap_stale_jobs(db, upload_dir=UPLOAD_DIR)
    except Exception as exc:  # status reads must not fail because of the reaper
        db.rollback()
        logger.error("stale-job reaper failed during status read: %s", type(exc).__name__)
    job = get_ingestion_job(db=db, job_id=job_id)
    if not job:
        raise api_error(status.HTTP_404_NOT_FOUND, "INGESTION_JOB_NOT_FOUND", "Ingestion job not found.", job_id=job_id)

    chunk_count = get_job_chunk_count(db=db, document_id=job.document_id)

    return IngestionStatusResponse(
        job_id=job.id,
        status=IngestionStatus(job.status),
        progress=job.progress,
        document_id=job.document_id,
        chunk_count=chunk_count if job.document_id else None,
        error=job.error_message,
        error_code=job.error_code,
        needs_reconciliation=bool(job.needs_reconciliation),
    )


@router.get(
    "/corpus/stats",
    response_model=CorpusStatsResponse,
)
def get_corpus_statistics(
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> CorpusStatsResponse:
    """Return overall corpus document counts, type breakdown, and storage service health."""
    return get_corpus_stats(db=db)
