"""Citation-grounded legal answer foundation contracts."""

from __future__ import annotations

from enum import StrEnum
import json
import socket
from dataclasses import dataclass
import urllib.error
import urllib.request
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
    repair_succeeded: bool | None = None
    repair_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


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
    provider_diagnostic: dict[str, Any] = Field(default_factory=dict)
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


class ModelProviderError(RuntimeError):
    """Raised when a configured provider returns a sanitized runtime error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        provider_code: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.provider_code = provider_code
        self.provider_message = provider_message


class GeminiAnswerAdapter:
    def __init__(self, settings: Settings, *, temperature: float | None = None, timeout_seconds: float | None = None) -> None:
        self.settings = settings
        self.temperature = settings.legalai_llm_temperature if temperature is None else temperature
        self.timeout_seconds = settings.legalai_llm_timeout_seconds if timeout_seconds is None else timeout_seconds

    @property
    def configured_model_id(self) -> str:
        return self.settings.gemini_model

    def generate_structured_answer(self, prompt: str, *, schema: type[BaseModel], mode: AnswerMode) -> LegalAnswerModelResponse:
        if not self.settings.gemini_api_key or not self.settings.gemini_model:
            raise ModelUnavailableError("Gemini API key and GEMINI_MODEL must be configured before live generation.")
        started = perf_counter()
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
                "responseSchema": model_payload_schema(schema),
            },
        }
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.settings.gemini_api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise ModelProviderError("GEMINI_TIMEOUT", "Gemini request timed out.") from exc
        except socket.timeout as exc:
            raise ModelProviderError("GEMINI_TIMEOUT", "Gemini request timed out.") from exc
        except urllib.error.HTTPError as exc:
            diagnostic = sanitized_http_diagnostic(exc)
            raise ModelProviderError(
                http_error_code(exc),
                diagnostic.message,
                http_status=diagnostic.http_status,
                provider_code=diagnostic.provider_code,
                provider_message=diagnostic.provider_message,
            ) from exc
        except urllib.error.URLError as exc:
            raise ModelProviderError("GEMINI_PROVIDER_ERROR", sanitized_url_error(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ModelProviderError("GEMINI_INVALID_RESPONSE", "Gemini returned a non-JSON API response.") from exc
        text = extract_gemini_text(body)
        usage = body.get("usageMetadata", {})
        metadata = ModelGenerationMetadata(
            provider="gemini",
            configured_model_id=self.settings.gemini_model,
            actual_model_id=body.get("modelVersion") or self.settings.gemini_model,
            temperature=self.temperature,
            response_mode=mode,
            fallback_used=False,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
            total_tokens=usage.get("totalTokenCount"),
        )
        return LegalAnswerModelResponse(
            raw_response=text,
            parsed_response=None,
            model_metadata=metadata,
            timings={"generation_latency_ms": elapsed_ms(perf_counter, started)},
        )

    def _endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"


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
    except ModelProviderError as exc:
        return model_provider_failure_result(
            understanding,
            retrieval,
            mode,
            elapsed_ms(timer, started),
            exc.code,
            str(exc),
            configured_model_id=getattr(adapter, "configured_model_id", ""),
            http_status=exc.http_status,
            provider_code=exc.provider_code,
            provider_message=exc.provider_message,
        )
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
        provider_diagnostic={
            "http_status": http_status,
            "provider_code": provider_code,
            "provider_message_sanitized": provider_message,
        },
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


def extract_gemini_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        raise ModelProviderError("GEMINI_EMPTY_RESPONSE", "Gemini returned no candidates.")
    parts = candidates[0].get("content", {}).get("parts") or []
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    text = "\n".join(item for item in texts if item).strip()
    if not text:
        raise ModelProviderError("GEMINI_EMPTY_RESPONSE", "Gemini returned no text content.")
    return text


def model_payload_schema(schema: type[BaseModel]) -> dict[str, Any]:
    return gemini_schema(
        {
        "type": "object",
        "properties": {
            "answer": schema.model_json_schema(mode="serialization"),
            "summary": {"type": "string"},
            "claims": {
                "type": "array",
                "items": GroundedLegalClaim.model_json_schema(mode="serialization"),
            },
        },
        "required": ["answer", "summary", "claims"],
        }
    )


def gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})
    return sanitize_gemini_schema(schema, definitions)


def sanitize_gemini_schema(value: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [sanitize_gemini_schema(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        name = value["$ref"].rsplit("/", 1)[-1]
        return sanitize_gemini_schema(definitions.get(name, {}), definitions)
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"$defs", "title", "default", "examples", "additionalProperties"}:
            continue
        if key == "anyOf":
            options = [option for option in item if option.get("type") != "null"]
            if len(options) == 1:
                sanitized.update(sanitize_gemini_schema(options[0], definitions))
                sanitized["nullable"] = True
            else:
                sanitized["anyOf"] = sanitize_gemini_schema(options, definitions)
            continue
        sanitized[key] = sanitize_gemini_schema(item, definitions)
    return sanitized


def http_error_code(exc: urllib.error.HTTPError) -> str:
    if exc.code == 429:
        return "GEMINI_RATE_LIMIT"
    if exc.code in {401, 403}:
        return "GEMINI_AUTH_ERROR"
    if 500 <= exc.code <= 599:
        return "GEMINI_PROVIDER_ERROR"
    return "GEMINI_HTTP_ERROR"


@dataclass(frozen=True)
class SanitizedHttpDiagnostic:
    http_status: int
    provider_code: str | None
    provider_message: str
    message: str


def sanitized_http_diagnostic(exc: urllib.error.HTTPError) -> SanitizedHttpDiagnostic:
    provider_code = None
    provider_message = f"Gemini request failed with HTTP {exc.code}."
    body = safe_http_error_body(exc)
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            provider_message = body[:300]
        else:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            provider_code = safe_string(error.get("status") or error.get("code"))
            provider_message = safe_string(error.get("message")) or provider_message
    return SanitizedHttpDiagnostic(
        http_status=exc.code,
        provider_code=provider_code,
        provider_message=provider_message,
        message=f"Gemini request failed with HTTP {exc.code}: {provider_message}",
    )


def safe_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    try:
        return raw.decode("utf-8", errors="replace")
    except AttributeError:
        return str(raw)


def safe_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:500]


def sanitized_url_error(exc: urllib.error.URLError) -> str:
    reason = exc.reason.__class__.__name__ if hasattr(exc, "reason") else "URLError"
    return f"Gemini request failed before receiving a response: {reason}."


def model_provider_failure_result(
    understanding: LegalQueryUnderstanding,
    retrieval: LegalRetrievalResult,
    mode: AnswerMode,
    total_ms: float,
    code: str,
    message: str,
    configured_model_id: str = "",
    http_status: int | None = None,
    provider_code: str | None = None,
    provider_message: str | None = None,
) -> LegalAnswerResult:
    evidence_ids = [item.citation_id for item in retrieval.evidence]
    metadata = ModelGenerationMetadata(
        provider="gemini",
        configured_model_id=configured_model_id,
        response_mode=mode,
        fallback_used=False,
    )
    return LegalAnswerResult(
        query=understanding.query,
        mode=mode,
        answer=None,
        summary="Gemini generation failed before a validated structured answer was produced.",
        grounding_status=GroundingStatus.UNGROUNDED,
        warnings=[
            LegalAnswerWarning(
                code=code,
                message=message,
                severity="error",
            )
        ],
        evidence_retrieved=evidence_ids,
        evidence_unused=evidence_ids,
        model_metadata=metadata,
        timings={"answer_generation_ms": total_ms},
        query_understanding_version=understanding.schema_version,
        retrieval_version=retrieval.retrieval_version,
    )


def elapsed_ms(timer, started: float) -> float:
    return round((timer() - started) * 1000, 3)
