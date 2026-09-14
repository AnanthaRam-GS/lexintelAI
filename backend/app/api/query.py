"""Public and professional grounded legal query endpoints."""

from __future__ import annotations

from argparse import Namespace
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.dependencies import require_lawyer_or_admin
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.models.common import SectionReference
from backend.app.models.query import (
    ProfessionalCaseBrief,
    ProfessionalPrecedent,
    ProfessionalQueryResponse,
    ProfessionalTextQueryRequest,
    PublicQueryResponse,
    PublicSection,
    PublicSource,
    PublicTextQueryRequest,
)
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    GeminiAnswerAdapter,
    GroundedCitation,
    LegalAnswerResult,
    ProfessionalLegalBrief,
    PublicLegalAnswer,
    build_grounded_evidence_packet,
    generate_legal_answer,
)
from backend.app.services.legal_answer_prompt import build_legal_answer_prompt
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.legal_rag_retrieval import retrieve_legal_evidence
from backend.app.services.query_history import PROFESSIONAL_MODE, save_query_history
from backend.scripts.build_lexical_index import DEFAULT_PERSIST_DIR as BM25_PERSIST_DIR
from backend.scripts.build_vector_index import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR as CHROMA_PERSIST_DIR
from backend.scripts.retrieve_legal_evidence import DEFAULT_INDEX_NAME, make_service


router = APIRouter(prefix="/query", tags=["Query"])


class QueryExecutionError(RuntimeError):
    """Sanitized query failure for HTTP mapping."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _cached_retrieval_service():
    args = Namespace(
        bm25_persist_dir=BM25_PERSIST_DIR,
        chroma_persist_dir=CHROMA_PERSIST_DIR,
        index_name=DEFAULT_INDEX_NAME,
        collection=DEFAULT_COLLECTION,
    )
    return make_service(args)


def get_retrieval_service():
    return _cached_retrieval_service()


def get_answer_adapter(settings: Settings = Depends(get_settings)):
    provider = settings.legalai_llm_provider.strip().lower()
    if provider == "gemini":
        return GeminiAnswerAdapter(settings)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "MODEL_PROVIDER_UNAVAILABLE", "message": "Configured answer model provider is unavailable."},
    )


@router.post("/public", response_model=PublicQueryResponse)
def query_public(
    request: PublicTextQueryRequest,
    retrieval_service=Depends(get_retrieval_service),
    adapter=Depends(get_answer_adapter),
) -> PublicQueryResponse:
    try:
        result = run_frozen_query_pipeline(request.text, mode=AnswerMode.PUBLIC, retrieval_service=retrieval_service, adapter=adapter)
        return public_response_from_result(result)
    except QueryExecutionError as exc:
        raise http_error(exc) from exc


@router.post("/professional", response_model=ProfessionalQueryResponse)
def query_professional(
    request: ProfessionalTextQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_lawyer_or_admin),
    retrieval_service=Depends(get_retrieval_service),
    adapter=Depends(get_answer_adapter),
) -> ProfessionalQueryResponse:
    try:
        result = run_frozen_query_pipeline(
            request.text,
            mode=AnswerMode.PROFESSIONAL,
            retrieval_service=retrieval_service,
            adapter=adapter,
        )
        response = professional_response_from_result(result)
        save_query_history(
            db,
            query_text=request.text,
            mode=PROFESSIONAL_MODE,
            user_id=current_user.id,
            session_id=request.session_id,
            response_json=response.model_dump(mode="json"),
            generation_backend=result.model_metadata.provider if result.model_metadata else None,
        )
        return response
    except QueryExecutionError as exc:
        raise http_error(exc) from exc


def http_error(exc: QueryExecutionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def run_frozen_query_pipeline(query: str, *, mode: AnswerMode, retrieval_service: Any, adapter: Any) -> LegalAnswerResult:
    try:
        understanding = understand_legal_query(query, section_ranking_mode="deterministic")
        retrieval = retrieve_legal_evidence(understanding, retrieval_service=retrieval_service)
        if retrieval.error:
            raise QueryExecutionError("RETRIEVAL_UNAVAILABLE", "The legal evidence index is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        packet = build_grounded_evidence_packet(understanding, retrieval)
        prompt = build_legal_answer_prompt(packet, mode=mode)
        result = generate_legal_answer(understanding, retrieval, mode=mode, adapter=adapter, prompt=prompt.prompt)
    except QueryExecutionError:
        raise
    except ValueError as exc:
        raise QueryExecutionError("INVALID_QUERY_REQUEST", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    except Exception as exc:
        raise QueryExecutionError("QUERY_PIPELINE_UNAVAILABLE", "The legal query pipeline is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    ensure_successful_answer(result)
    return result


def ensure_successful_answer(result: LegalAnswerResult) -> None:
    if result.answer is not None:
        return
    codes = {warning.code for warning in result.warnings}
    if "INSUFFICIENT_RETRIEVED_AUTHORITY" in codes:
        raise QueryExecutionError("INSUFFICIENT_RETRIEVED_AUTHORITY", "Retrieved legal authority is insufficient for a grounded answer.", status.HTTP_424_FAILED_DEPENDENCY)
    if "MODEL_UNAVAILABLE" in codes:
        raise QueryExecutionError("MODEL_UNAVAILABLE", "The legal answer model is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if any(code.startswith("GEMINI_") or code.endswith("_PROVIDER_ERROR") for code in codes):
        raise QueryExecutionError("MODEL_PROVIDER_ERROR", "The legal answer provider is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if "MODEL_OUTPUT_VALIDATION_FAILED" in codes:
        raise QueryExecutionError("MODEL_OUTPUT_VALIDATION_FAILED", "The legal answer provider returned an invalid structured answer.", status.HTTP_502_BAD_GATEWAY)
    raise QueryExecutionError("ANSWER_GENERATION_FAILED", "A grounded legal answer could not be generated.", status.HTTP_502_BAD_GATEWAY)


def public_response_from_result(result: LegalAnswerResult) -> PublicQueryResponse:
    answer = result.answer
    if not isinstance(answer, PublicLegalAnswer):
        raise QueryExecutionError("PUBLIC_SCHEMA_MISMATCH", "The legal answer provider returned an invalid public answer.", status.HTTP_502_BAD_GATEWAY)
    sections = [public_section(item) for item in answer.possible_legal_provisions]
    if not sections:
        sections = [public_section_from_reference(item) for item in result.citations]
    sources = public_sources(result.citations)
    return PublicQueryResponse(
        explanation=answer.summary or result.summary,
        sections=sections,
        sources=sources,
        nextStepGuidance=" ".join(answer.possible_next_steps).strip()
        or "Keep copies of relevant documents and consider speaking with a qualified legal professional.",
    )


def professional_response_from_result(result: LegalAnswerResult) -> ProfessionalQueryResponse:
    answer = result.answer
    if not isinstance(answer, ProfessionalLegalBrief):
        raise QueryExecutionError("PROFESSIONAL_SCHEMA_MISMATCH", "The legal answer provider returned an invalid professional answer.", status.HTTP_502_BAD_GATEWAY)
    return ProfessionalQueryResponse(
        identified_sections=section_references(answer.explicit_legal_provisions + answer.potential_additional_provisions),
        precedents=[precedent_from_authority(item.model_dump(mode="json")) for item in answer.retrieved_authorities],
        case_brief=ProfessionalCaseBrief(
            summary=answer.issue_summary,
            applicable_law=answer.applicable_principles,
            key_issues=answer.legal_issues,
            procedural_considerations=answer.procedural_posture,
            precedent_analysis=answer.analysis + answer.counterpoints,
            limitations=[item.message for item in answer.uncertainties],
        ),
    )


def public_section(text: str) -> PublicSection:
    title = text.strip() or "General legal information"
    return PublicSection(title=title, explanation="Applicability depends on the specific facts and documents.", link="https://www.indiacode.nic.in/")


def public_section_from_reference(citation: GroundedCitation) -> PublicSection:
    metadata = citation.source_metadata or {}
    title = str(metadata.get("case_name") or metadata.get("source") or "Retrieved legal authority")
    return PublicSection(title=title, explanation="This source was retrieved by LegalAI as potentially relevant authority.", link=safe_public_link(metadata.get("source_url")))


def public_sources(citations: list[GroundedCitation]) -> list[PublicSource]:
    seen: set[tuple[str, str]] = set()
    sources: list[PublicSource] = []
    for citation in citations:
        metadata = citation.source_metadata or {}
        title = str(metadata.get("case_name") or metadata.get("source") or "Retrieved legal authority")
        link = safe_public_link(metadata.get("source_url"))
        key = (title, link)
        if key not in seen:
            seen.add(key)
            sources.append(PublicSource(title=title, link=link))
    return sources or [PublicSource(title="India Code", link="https://www.indiacode.nic.in/")]


def safe_public_link(value: Any) -> str:
    link = str(value or "").strip()
    if link.startswith("https://"):
        return link
    return "https://www.indiacode.nic.in/"


def section_references(values: list[str]) -> list[SectionReference]:
    sections: list[SectionReference] = []
    for value in values:
        cleaned = value.strip()
        if cleaned:
            sections.append(SectionReference(statute="Unspecified", section=cleaned, context="generated_from_grounded_answer"))
    return sections


def precedent_from_authority(authority: dict[str, Any]) -> ProfessionalPrecedent:
    court = authority.get("court")
    return ProfessionalPrecedent(
        document_id=authority.get("document_id") or authority.get("evidence_id") or "",
        case_name=authority.get("case_name") or "Retrieved authority",
        court=court.get("name") if isinstance(court, dict) else court,
        year=year_from_date(authority.get("judgment_date")),
        relevance_score=1.0,
        source_url=authority.get("source_url"),
        page_start=authority.get("page_start"),
        page_end=authority.get("page_end"),
        paragraph_start=authority.get("paragraph_start"),
        paragraph_end=authority.get("paragraph_end"),
    )


def year_from_date(value: Any) -> int | None:
    text = str(value or "")
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None
