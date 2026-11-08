"""Shared API contract primitives for LegalAI."""

from typing import Literal

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


class SectionLabel(BaseModel):
    """How a section's label was resolved against LegalAI's trusted sources (step 25, services/section_labels.py).

    ``state``: ``verified`` (``title`` is the trusted title), ``corrected_statute`` (the statute named by the answer
    was corrected; ``statute_corrected_from`` is the original, ``title`` is set when a trusted title exists for the
    corrected section), ``unverified`` (no trusted title; ``model_label`` is the answer's own wording) or
    ``conflict`` (the trusted source disagrees with itself; no title). ``source`` is ``section_catalog`` or
    ``ipc_bns_mapping`` and ``source_key`` the entry used, for example ``"BNS 309"``. Both sources are UNREVIEWED.
    """

    state: Literal["verified", "corrected_statute", "unverified", "conflict"]
    title: str | None = None
    source: str | None = None
    source_key: str | None = None
    model_label: str | None = None
    statute_corrected_from: str | None = None
    note: str | None = None


class SectionReference(BaseModel):
    """Identified statutory section with optional classifier context and, for answer-named sections, its label."""

    statute: str
    section: str
    confidence: float | None = None
    context: str | None = None
    label: SectionLabel | None = None
