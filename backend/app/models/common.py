"""Shared API contract primitives for LegalAI."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Common error response shape for all API surfaces."""

    error: str
    code: str
    detail: str | None = None


class SourceReference(BaseModel):
    """Citation and retrieval provenance for a source document."""

    document_id: int | str
    case_name: str | None = None
    court: str | None = None
    year: int | None = None
    source_url: str | None = None
    excerpt: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


class SectionReference(BaseModel):
    """Identified statutory section with optional classifier context."""

    statute: str
    section: str
    confidence: float | None = None
    context: str | None = None
