"""Citation-grounded legal answer foundation contracts."""

from __future__ import annotations

from enum import StrEnum
import json
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from backend.app.core.config import Settings
from backend.app.services.legal_citation_validation import CitationValidationResult, validate_legal_answer_citations
from backend.app.services.legal_query_understanding import LegalQueryUnderstanding
from backend.app.services.legal_rag_retrieval import LegalRetrievalResult


LEGAL_ANSWER_SCHEMA_VERSION = "legalai-grounded-answer-v1"


class AnswerMode(StrEnum):
    PUBLIC = "public"
    PROFESSIONAL = "professional"


class ClaimType(StrEnum):
    LEGAL_RULE = "LEGAL_RULE"
    PROCEDURAL_GUIDANCE = "PROCEDURAL_GUIDANCE"
    CASE_LAW = "CASE_LAW"
    STATUTORY_REFERENCE = "STATUTORY_REFERENCE"
    FACTUAL_SUMMARY = "FACTUAL_SUMMARY"
    UNCERTAINTY = "UNCERTAINTY"
    GENERAL_EXPLANATION = "GENERAL_EXPLANATION"


class GroundingStatus(StrEnum):
    STRUCTURALLY_GROUNDED = "STRUCTURALLY_GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    INSUFFICIENT_RETRIEVED_AUTHORITY = "INSUFFICIENT_RETRIEVED_AUTHORITY"


class LegalAnswerWarning(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    related_claims: list[str] = Field(default_factory=list)
    related_evidence: list[str] = Field(default_factory=list)


class LegalAnswerUncertainty(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    related_claims: list[str] = Field(default_factory=list)
    related_evidence: list[str] = Field(default_factory=list)


class GroundedCitation(BaseModel):
    evidence_id: str
    claim_id: str
    supported_text: str
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    support_level: str = "structural"


class GroundedLegalClaim(BaseModel):
    claim_id: str
    text: str
    claim_type: ClaimType
    citations: list[GroundedCitation] = Field(default_factory=list)
    grounding_status: GroundingStatus = GroundingStatus.UNGROUNDED
    warnings: list[LegalAnswerWarning] = Field(default_factory=list)


class PublicLegalAnswer(BaseModel):
    summary: str
    what_this_may_mean: list[str] = Field(default_factory=list)
    possible_legal_provisions: list[str] = Field(default_factory=list)
    possible_next_steps: list[str] = Field(default_factory=list)
    important_cautions: list[str] = Field(default_factory=list)
    citations: list[GroundedCitation] = Field(default_factory=list)


class RetrievedAuthority(BaseModel):
    evidence_id: str
    case_name: str | None = None
    court: dict[str, Any] | None = None
    judgment_date: str | None = None
    source_url: str | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


class ProfessionalLegalBrief(BaseModel):
    issue_summary: str
    material_facts_from_query: list[str] = Field(default_factory=list)
    explicit_legal_provisions: list[str] = Field(default_factory=list)
    potential_additional_provisions: list[str] = Field(default_factory=list)
    procedural_posture: list[str] = Field(default_factory=list)
    legal_regime: str
    retrieved_authorities: list[RetrievedAuthority] = Field(default_factory=list)
    legal_issues: list[str] = Field(default_factory=list)
    applicable_principles: list[str] = Field(default_factory=list)
    analysis: list[str] = Field(default_factory=list)
    counterpoints: list[str] = Field(default_factory=list)
    uncertainties: list[LegalAnswerUncertainty] = Field(default_factory=list)
    recommended_research_questions: list[str] = Field(default_factory=list)
    citations: list[GroundedCitation] = Field(default_factory=list)


class GroundedEvidenceItem(BaseModel):
    evidence_id: str
    text: str
    document_id: str
    judgment_id: str
    case_name: str | None = None
    court: dict[str, Any] | None = None
    judgment_date: str | None = None
    source_url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    source: str | None = None
    offence_family: str | None = None
    legal_regime: str | None = None


class GroundedEvidencePacket(BaseModel):
    schema_version: str = LEGAL_ANSWER_SCHEMA_VERSION
    original_query: str
    normalized_query: str
    legal_regime: str
    explicit_sections: list[dict[str, Any]] = Field(default_factory=list)
    predicted_sections: list[dict[str, Any]] = Field(default_factory=list)
    offence_families: list[str] = Field(default_factory=list)
    procedural_posture: list[str] = Field(default_factory=list)
    evidence: list[GroundedEvidenceItem] = Field(default_factory=list)
    citation_policy: str = "retrieval_evidence_only"
    notes: list[str] = Field(default_factory=list)


class ModelGenerationMetadata(BaseModel):
    provider: str
    configured_model_id: str
    actual_model_id: str | None = None
    temperature: float = 0.1
    response_mode: AnswerMode
    fallback_used: bool = False
    primary_provider: str | None = None
    fallback_provider: str | None = None
    fallback_reason: str | None = None
    repair_attempted: bool = False
    repair_reason: str | None = None


class LegalAnswerResult(BaseModel):
    answer_schema_version: str = LEGAL_ANSWER_SCHEMA_VERSION
    query: str
    mode: AnswerMode
    answer: PublicLegalAnswer | ProfessionalLegalBrief | None = None
    summary: str = ""
    claims: list[GroundedLegalClaim] = Field(default_factory=list)
    citations: list[GroundedCitation] = Field(default_factory=list)
    grounding_status: GroundingStatus = GroundingStatus.UNGROUNDED
    warnings: list[LegalAnswerWarning] = Field(default_factory=list)
    uncertainties: list[LegalAnswerUncertainty] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    evidence_retrieved: list[str] = Field(default_factory=list)
    evidence_unused: list[str] = Field(default_factory=list)
    model_metadata: ModelGenerationMetadata | None = None
    fallbacks: list[dict[str, str]] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    query_understanding_version: str
    retrieval_version: str
    citation_validation: CitationValidationResult | None = None


class LegalAnswerModelResponse(BaseModel):
    raw_response: str
    parsed_response: dict[str, Any] | None
    model_metadata: ModelGenerationMetadata
    timings: dict[str, float] = Field(default_factory=dict)
    error: dict[str, str] | None = None


class LegalAnswerModelAdapter(Protocol):
    def generate_structured_answer(self, prompt: str, *, schema: type[BaseModel], mode: AnswerMode) -> LegalAnswerModelResponse:
        ...


class ModelUnavailableError(RuntimeError):
    """Raised by adapters when an explicitly configured model cannot run."""


class GeminiAnswerAdapter:
    def __init__(self, settings: Settings, *, temperature: float = 0.1) -> None:
        self.settings = settings
        self.temperature = temperature

    @property
    def configured_model_id(self) -> str:
        return self.settings.gemini_model

    def generate_structured_answer(self, prompt: str, *, schema: type[BaseModel], mode: AnswerMode) -> LegalAnswerModelResponse:
        del prompt, schema
        if not self.settings.gemini_api_key or not self.settings.gemini_model:
            raise ModelUnavailableError("Gemini API key and GEMINI_MODEL must be configured before live generation.")
        raise ModelUnavailableError("Live Gemini generation is outside the Phase 0.9A mocked-validation boundary.")


class OllamaAnswerAdapter:
    def __init__(self, settings: Settings, *, temperature: float = 0.1) -> None:
        self.settings = settings
        self.temperature = temperature

    @property
    def configured_model_id(self) -> str:
        return self.settings.ollama_model

    def generate_structured_answer(self, prompt: str, *, schema: type[BaseModel], mode: AnswerMode) -> LegalAnswerModelResponse:
        del prompt, schema, mode
        raise ModelUnavailableError("Live Ollama generation is outside the Phase 0.9A mocked-validation boundary.")


def build_grounded_evidence_packet(
    understanding: LegalQueryUnderstanding,
    retrieval: LegalRetrievalResult,
) -> GroundedEvidencePacket:
    return GroundedEvidencePacket(
        original_query=understanding.query,
        normalized_query=understanding.normalized_query,
        legal_regime=understanding.legal_regime.regime,
        explicit_sections=[structured_dump(item) for item in understanding.explicit_sections],
        predicted_sections=[structured_dump(item) for item in understanding.predicted_sections],
        offence_families=understanding.offence_families,
        procedural_posture=understanding.procedural_posture,
        evidence=[
            GroundedEvidenceItem(
                evidence_id=item.citation_id,
                text=item.text,
                document_id=item.document_id,
                judgment_id=item.judgment_id,
                case_name=item.case_name,
                court=item.court,
                judgment_date=item.judgment_date,
                source_url=item.source_url,
                page_start=item.page_start,
                page_end=item.page_end,
                paragraph_start=item.paragraph_start,
                paragraph_end=item.paragraph_end,
                source=item.source,
                offence_family=item.offence_family,
                legal_regime=item.legal_regime,
            )
            for item in retrieval.evidence
        ],
        notes=[
            "EXPLICIT USER SECTIONS ARE USER-PROVIDED EVIDENCE.",
            "PREDICTED SECTIONS ARE SUPPLEMENTARY CANDIDATES ONLY.",
        ],
    )


def generate_legal_answer(
    understanding: LegalQueryUnderstanding,
    retrieval: LegalRetrievalResult,
    *,
    mode: AnswerMode = AnswerMode.PUBLIC,
    adapter: LegalAnswerModelAdapter | None = None,
    prompt: str = "",
    timer=perf_counter,
) -> LegalAnswerResult:
    started = timer()
    evidence_ids = [item.citation_id for item in retrieval.evidence]
    if not retrieval.evidence:
        return insufficient_retrieval_result(understanding, retrieval, mode, elapsed_ms(timer, started))
    if adapter is None:
        return model_unavailable_result(understanding, retrieval, mode, elapsed_ms(timer, started))
    schema: type[BaseModel] = PublicLegalAnswer if mode == AnswerMode.PUBLIC else ProfessionalLegalBrief
    try:
        model_response = adapter.generate_structured_answer(prompt, schema=schema, mode=mode)
    except ModelUnavailableError as exc:
        return model_unavailable_result(understanding, retrieval, mode, elapsed_ms(timer, started), message=str(exc))
    try:
        parsed = parse_model_payload(model_response.raw_response, model_response.parsed_response, schema)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as exc:
        return model_output_failure_result(understanding, retrieval, mode, model_response, elapsed_ms(timer, started), str(exc))
    claims = parsed.get("claims", [])
    citations = [citation for claim in claims for citation in claim.citations]
    result = LegalAnswerResult(
        query=understanding.query,
        mode=mode,
        answer=parsed["answer"],
        summary=parsed["summary"],
        claims=claims,
        citations=citations,
        grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED,
        evidence_used=sorted({citation.evidence_id for citation in citations}),
        evidence_retrieved=evidence_ids,
        evidence_unused=[item for item in evidence_ids if item not in {citation.evidence_id for citation in citations}],
        model_metadata=model_response.model_metadata,
        timings={"answer_generation_ms": elapsed_ms(timer, started), **model_response.timings},
        query_understanding_version=understanding.schema_version,
        retrieval_version=retrieval.retrieval_version,
    )
    result.citation_validation = validate_legal_answer_citations(result, retrieval)
    return apply_grounding_validation(result)


def parse_model_payload(raw_response: str, parsed_response: dict[str, Any] | None, schema: type[BaseModel]) -> dict[str, Any]:
    payload = parsed_response if parsed_response is not None else json.loads(raw_response)
    answer = schema.model_validate(payload["answer"])
    claims = [GroundedLegalClaim.model_validate(item) for item in payload.get("claims", [])]
    return {"answer": answer, "claims": claims, "summary": payload.get("summary", "")}


def structured_dump(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {"value": item}


def apply_grounding_validation(result: LegalAnswerResult) -> LegalAnswerResult:
    from backend.app.services.legal_citation_validation import validate_claim_grounding

    grounding = validate_claim_grounding(result.claims, {item for item in result.evidence_retrieved})
    result.grounding_status = grounding
    if result.citation_validation and not result.citation_validation.valid:
        result.warnings.append(
            LegalAnswerWarning(code="CITATION_VALIDATION_FAILED", message="One or more citations failed structural validation.")
        )
        result.uncertainties.append(
            LegalAnswerUncertainty(code="CITATION_VALIDATION_FAILED", message="Citation structure must be fixed before relying on this answer.")
        )
    return result


def insufficient_retrieval_result(
    understanding: LegalQueryUnderstanding,
    retrieval: LegalRetrievalResult,
    mode: AnswerMode,
    total_ms: float,
) -> LegalAnswerResult:
    warning = LegalAnswerWarning(
        code="INSUFFICIENT_RETRIEVED_AUTHORITY",
        message="No retrieved evidence is available for a citation-grounded legal answer.",
        severity="error",
    )
    return LegalAnswerResult(
        query=understanding.query,
        mode=mode,
        answer=None,
        summary="Retrieved evidence is insufficient for a citation-grounded answer.",
        grounding_status=GroundingStatus.INSUFFICIENT_RETRIEVED_AUTHORITY,
        warnings=[warning],
        uncertainties=[LegalAnswerUncertainty(**warning.model_dump())],
        evidence_retrieved=[],
        timings={"answer_generation_ms": total_ms},
        query_understanding_version=understanding.schema_version,
        retrieval_version=retrieval.retrieval_version,
    )


def model_unavailable_result(
    understanding: LegalQueryUnderstanding,
    retrieval: LegalRetrievalResult,
    mode: AnswerMode,
    total_ms: float,
    message: str = "No legal answer model adapter was provided.",
) -> LegalAnswerResult:
    evidence_ids = [item.citation_id for item in retrieval.evidence]
    metadata = ModelGenerationMetadata(provider="unavailable", configured_model_id="", response_mode=mode)
    return LegalAnswerResult(
        query=understanding.query,
        mode=mode,
        answer=None,
        summary="Model generation was not executed.",
        grounding_status=GroundingStatus.UNGROUNDED,
        warnings=[LegalAnswerWarning(code="MODEL_UNAVAILABLE", message=message, severity="error")],
        evidence_retrieved=evidence_ids,
        evidence_unused=evidence_ids,
        model_metadata=metadata,
        timings={"answer_generation_ms": total_ms},
        query_understanding_version=understanding.schema_version,
        retrieval_version=retrieval.retrieval_version,
    )


def model_output_failure_result(
    understanding: LegalQueryUnderstanding,
    retrieval: LegalRetrievalResult,
    mode: AnswerMode,
    model_response: LegalAnswerModelResponse,
    total_ms: float,
    message: str,
) -> LegalAnswerResult:
    evidence_ids = [item.citation_id for item in retrieval.evidence]
    metadata = model_response.model_metadata
    metadata.repair_attempted = False
    metadata.repair_reason = "No repair attempted in Phase 0.9A foundation."
    return LegalAnswerResult(
        query=understanding.query,
        mode=mode,
        answer=None,
        summary="Model output failed schema validation.",
        grounding_status=GroundingStatus.UNGROUNDED,
        warnings=[LegalAnswerWarning(code="MODEL_OUTPUT_VALIDATION_FAILED", message=message, severity="error")],
        evidence_retrieved=evidence_ids,
        evidence_unused=evidence_ids,
        model_metadata=metadata,
        timings={"answer_generation_ms": total_ms, **model_response.timings},
        query_understanding_version=understanding.schema_version,
        retrieval_version=retrieval.retrieval_version,
    )


def elapsed_ms(timer, started: float) -> float:
    return round((timer() - started) * 1000, 3)
