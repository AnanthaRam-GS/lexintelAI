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
