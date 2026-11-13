"""Shared API contract primitives for LegalAI."""

from typing import Literal

from pydantic import BaseModel, Field


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


class OtherSourceTitle(BaseModel):
    source: str
    source_key: str
    title: str
    agrees: bool


class SectionLabel(BaseModel):
    """How a section's label was resolved against LegalAI's trusted sources (step 25, services/section_labels.py).

    ``state``: ``verified`` (``title`` is the trusted title), ``corrected_statute`` (the statute named by the answer
    was corrected; ``statute_corrected_from`` is the original, ``title`` is set when a trusted title exists for the
    corrected section), ``unverified`` (no trusted title; ``model_label`` is the answer's own wording) or
    ``conflict`` (the trusted source disagrees with itself; no title). ``source`` is ``section_catalog`` or
    ``ipc_bns_mapping``, or since step 26 ``official_heading`` (India Code marginal notes, the first source), and
    ``source_key`` the entry used, for example ``"BNS 309"``. All sources are UNREVIEWED.
    """

    state: Literal["verified", "corrected_statute", "unverified", "conflict"]
    title: str | None = None
    source: str | None = None
    source_key: str | None = None
    model_label: str | None = None
    statute_corrected_from: str | None = None
    note: str | None = None
    # Step 26: when the official heading is shown, the lower-trust titles for the same section (catalog, mapping),
    # kept for review rather than dropped; ``agrees`` is False when one shares no content word with the heading.
    other_sources: list[OtherSourceTitle] = Field(default_factory=list)
    # Step 26b: the answer's label clearly does not match the section's trusted entries (and no sister statute matched);
    # the trusted title is shown and ``model_label`` keeps the answer's wording for audit.
    model_label_differs: bool = False
    # Step 26b: when ``title`` is the catalog's title of the exact sub-section, the section's official heading.
    section_heading: str | None = None
    section_heading_source: str | None = None
    section_heading_key: str | None = None
    # Step 26c: why a statute was corrected: "label" (the answer's label fits the sister statute) or
    # "document_evidence" (the uploaded document cites this number only under the sister statute, at
    # ``document_evidence_id``, a P# chunk).
    correction_reason: str | None = None
    document_evidence_id: str | None = None



class SectionReference(BaseModel):
    """Identified statutory section with optional classifier context and, for answer-named sections, its label."""

    statute: str
    section: str
    confidence: float | None = None
    context: str | None = None
    label: SectionLabel | None = None
