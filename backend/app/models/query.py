"""Professional and public query API contracts for LegalAI."""

from pydantic import BaseModel

from backend.app.models.common import SectionReference


class ProfessionalTextQueryRequest(BaseModel):
    """Professional text query input.

    Professional PDF uploads will later use multipart/form-data with FastAPI
    UploadFile. Uploaded query documents are temporary analysis inputs and do
    not imply persistent corpus ingestion.
    """

    text: str


class ProfessionalPrecedent(BaseModel):
    """Retrieved precedent metadata with backend-provided provenance."""

    document_id: int | str
    case_name: str
    court: str | None = None
    year: int | None = None
    relevance_score: float
    excerpt: str | None = None
    source_url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


class ProfessionalCaseBrief(BaseModel):
    """Structured professional case analysis."""

    summary: str
    applicable_law: list[str]
    key_issues: list[str]
    procedural_considerations: list[str]
    precedent_analysis: list[str]
    limitations: list[str]


class ProfessionalQueryResponse(BaseModel):
    """Professional query response contract."""

    identified_sections: list[SectionReference]
    precedents: list[ProfessionalPrecedent]
    case_brief: ProfessionalCaseBrief


class PublicTextQueryRequest(BaseModel):
    """Public text query input.

    Public PDF uploads will later use multipart/form-data with FastAPI
    UploadFile. Uploaded query documents are temporary analysis inputs and do
    not imply persistent corpus ingestion.
    """

    text: str


class PublicSource(BaseModel):
    """Public-facing source reference."""

    label: str
    type: str
    source_url: str | None = None


class PublicQueryResponse(BaseModel):
    """Public query response contract."""

    explanation: str
    sections_cited: list[SectionReference]
    sources: list[PublicSource]
