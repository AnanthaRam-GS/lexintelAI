"""Corpus ingestion API contracts for LegalAI."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class IngestionStatus(StrEnum):
    """Persistent ingestion job states."""

    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IngestionMetadata(BaseModel):
    """Metadata submitted with a multipart corpus upload."""

    doc_type: str
    court_level: str | None = None
    year: int | None = None
    source_url: str | None = None


class IngestionUploadResponse(BaseModel):
    """Response after a corpus upload job is accepted."""

    job_id: str
    status: IngestionStatus


class IngestionStatusResponse(BaseModel):
    """Status response for a persistent ingestion job."""

    job_id: str
    status: IngestionStatus
    progress: int
    document_id: int | str | None = None
    chunk_count: int | None = None
    error: str | None = None


class CorpusTypeCount(BaseModel):
    """Document count grouped by corpus document type."""

    doc_type: str
    count: int


class CorpusStatsResponse(BaseModel):
    """Corpus and storage health summary."""

    total_documents: int
    last_updated: datetime | None = None
    by_type: list[CorpusTypeCount]
    postgres_status: str
    chroma_status: str
