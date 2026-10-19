"""Professional and public query API contracts for LegalAI."""

from pydantic import BaseModel, Field

from backend.app.models.common import SectionReference


class ProfessionalTextQueryRequest(BaseModel):
    """Professional text query input.

    Professional PDF uploads will later use multipart/form-data with FastAPI
    UploadFile. Uploaded query documents are temporary analysis inputs and do
    not imply persistent corpus ingestion.
    """

    text: str = Field(..., min_length=1, max_length=5000)
    session_id: str | None = None


class ProfessionalPrecedent(BaseModel):
    """Retrieved precedent, built from retrieved trusted evidence (never from model text).

    ``relevance_score`` is the reranker score normalized to 0-1 with a logistic
    sigmoid (``services/professional_brief.py``), or None when the evidence has
    no reranker score. ``reranker_score`` is the raw score. ``excerpt`` is a
    bounded span of the trusted chunk ``chunk_id``.
    """

    document_id: int | str
    chunk_id: str | None = None
    case_name: str
    court: str | None = None
    year: int | None = None
    relevance_score: float | None = None
    reranker_score: float | None = None
    excerpt: str | None = None
    source_url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


class ProfessionalCaseBrief(BaseModel):
    """Structured professional case analysis."""

    summary: str
    parties_and_roles: list[str] = Field(default_factory=list)
    material_facts: list[str] = Field(default_factory=list)
    chronology: list[str] = Field(default_factory=list)
    statutory_provisions: list[str] = Field(default_factory=list)
    evidence_identified: list[str] = Field(default_factory=list)
    applicable_law: list[str]
    key_issues: list[str]
    procedural_considerations: list[str]
    precedent_analysis: list[str]
    limitations: list[str]
    recommended_research_questions: list[str] = Field(default_factory=list)


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

    text: str = Field(..., min_length=1, max_length=5000)


class PublicSection(BaseModel):
    """Public-facing statutory section reference."""

    title: str
    explanation: str
    link: str


class PublicSource(BaseModel):
    """Public-facing source reference."""

    title: str
    link: str


class PublicQueryResponse(BaseModel):
    """Public query response contract."""

    explanation: str
    sections: list[PublicSection]
    sources: list[PublicSource]
    nextStepGuidance: str
