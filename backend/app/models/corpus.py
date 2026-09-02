"""Corpus source metadata contracts for LegalAI."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel


class DocumentType(StrEnum):
    """Supported source document types."""

    JUDGMENT = "judgment"
    STATUTE = "statute"
    FIR = "fir"
    CHARGE_SHEET = "charge_sheet"
    OTHER = "other"


class SourceProvider(StrEnum):
    """Known source providers for corpus acquisition."""

    INDIA_CODE = "india_code"
    INDIAN_KANOON = "indian_kanoon"
    COURT_WEBSITE = "court_website"
    GOVERNMENT_PORTAL = "government_portal"
    MANUAL = "manual"
    OTHER = "other"


class CorpusDocumentMetadata(BaseModel):
    """Source-level metadata and provenance for one corpus document."""

    document_id: str
    document_type: DocumentType
    title: str
    case_name: str | None = None
    case_number: str | None = None
    court_name: str | None = None
    court_level: str | None = None
    decision_date: date | None = None
    year: int | None = None
    statute_name: str | None = None
    source_provider: SourceProvider
    source_url: str
    source_document_id: str | None = None
    source_retrieved_at: datetime
    source_license_or_terms: str | None = None
    attribution_required: bool
    attribution_text: str | None = None
    raw_file_path: str
    sha256: str
    file_size_bytes: int
    mime_type: str
    language: str | None = None
    notes: str | None = None
