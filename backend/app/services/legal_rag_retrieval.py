"""Grounded retrieval orchestration for LegalAI RAG evidence."""

from __future__ import annotations

from time import perf_counter
from pydantic import BaseModel, Field

from backend.app.services.legal_query_understanding import LegalQueryUnderstanding
from backend.app.services.retrieval.service import HybridConfig, RetrievalResponse, RetrievalService
from backend.app.services.vector_store import RetrievalResult


LEGAL_RAG_RETRIEVAL_VERSION = "legalai-rag-retrieval-v1"
FROZEN_RETRIEVAL_DECISION = "RETAIN_UNTUNED_HYBRID_RERANK"
FROZEN_COLLECTION_NAME = "legalai_trusted_judgments_v1"
FROZEN_BM25_INDEX_VERSION = "legalai-bm25-index-v1"
FROZEN_TOKENIZER_VERSION = "legalai-legal-tokenizer-v1"
FROZEN_DENSE_MODEL = "BAAI/bge-m3"
FROZEN_DENSE_DIMENSION = 1024
FROZEN_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
FROZEN_RRF_K = 60
FROZEN_CANDIDATE_DEPTH = 20
FROZEN_FINAL_TOP_K = 5
FROZEN_RERANKER_MAX_LENGTH = 512
FROZEN_RERANKER_BATCH_SIZE = 8


class RetrievalWarning(BaseModel):
    code: str
    message: str
    affected_chunk_id: str | None = None


class RetrievalError(BaseModel):
    code: str
    message: str
    stage: str
    fallback_used: bool = False


class RetrievalProvenance(BaseModel):
    stage: str
    source: str
    detail: str


class CitationMetadata(BaseModel):
    citation_id: str
    chunk_id: str
    document_id: str
    judgment_id: str
    case_name: str | None = None
    court: dict | None = None
    date: str | None = None
    source_url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


class LegalEvidenceChunk(BaseModel):
    rank: int
    citation_id: str
    chunk_id: str
    document_id: str
    judgment_id: str
    text: str
    source: str | None = None
    source_url: str | None = None
    court: dict | None = None
    case_name: str | None = None
    case_citation: str | None = None
    judgment_date: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int
    paragraph_end: int
    heading: str | None = None
    offence_family: str | None = None
    legal_regime: str | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None
    dense_rank: int | None = None
    rrf_score: float | None = None
    rrf_rank: int | None = None
    reranker_score: float | None = None
    reranker_rank: int | None = None
    citation_metadata: CitationMetadata


class RetrievalStageCounts(BaseModel):
    bm25_returned: int
    dense_returned: int
    rrf_unique_candidates: int
    reranker_candidates: int
    final_evidence_count: int


class RetrievalTimings(BaseModel):
    query_understanding_ms: float | None = None
    bm25_ms: float = 0.0
    dense_embedding_ms: float = 0.0
    dense_search_ms: float = 0.0
    rrf_ms: float = 0.0
    reranker_ms: float = 0.0
    total_retrieval_ms: float = 0.0


class FrozenRetrievalConfig(BaseModel):
    decision: str = FROZEN_RETRIEVAL_DECISION
    bm25_index: str = FROZEN_BM25_INDEX_VERSION
    tokenizer: str = FROZEN_TOKENIZER_VERSION
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    dense_model: str = FROZEN_DENSE_MODEL
    dense_embedding_dimension: int = FROZEN_DENSE_DIMENSION
    dense_normalized_embeddings: bool = True
    chroma_collection: str = FROZEN_COLLECTION_NAME
    fusion: str = "RRF"
    rrf_k: int = FROZEN_RRF_K
    candidate_depth: int = FROZEN_CANDIDATE_DEPTH
    reranker_model: str = FROZEN_RERANKER_MODEL
    reranker_max_length: int = FROZEN_RERANKER_MAX_LENGTH
    reranker_batch_size: int = FROZEN_RERANKER_BATCH_SIZE
    final_top_k: int = FROZEN_FINAL_TOP_K
    legal_regime_ranking_enabled: bool = False
    query_expansion_enabled: bool = False
    metadata_reranking_enabled: bool = False


class LegalRetrievalResult(BaseModel):
    schema_version: str = LEGAL_RAG_RETRIEVAL_VERSION
    query: str
    query_understanding_version: str
    retrieval_version: str = LEGAL_RAG_RETRIEVAL_VERSION
    frozen_config: FrozenRetrievalConfig = Field(default_factory=FrozenRetrievalConfig)
    understanding_summary: dict
    evidence: list[LegalEvidenceChunk] = Field(default_factory=list)
    stage_counts: RetrievalStageCounts
    timings: RetrievalTimings
    warnings: list[RetrievalWarning] = Field(default_factory=list)
    error: RetrievalError | None = None
    fallbacks: list[dict[str, str]] = Field(default_factory=list)
    provenance: list[RetrievalProvenance] = Field(default_factory=list)


class RetrievalDependencyError(RuntimeError):
    """Raised when a required frozen retrieval dependency is unavailable."""


def retrieve_legal_evidence(
    understanding: LegalQueryUnderstanding,
    *,
    retrieval_service: RetrievalService,
    top_k: int = FROZEN_FINAL_TOP_K,
    candidate_depth: int = FROZEN_CANDIDATE_DEPTH,
    timer=perf_counter,
) -> LegalRetrievalResult:
    if not understanding.normalized_query:
        return empty_result(understanding, warning_code="NO_RETRIEVAL_RESULTS", warning_message="Empty query; retrieval was not executed.")
    if top_k > FROZEN_FINAL_TOP_K:
        raise ValueError(f"top_k must remain <= {FROZEN_FINAL_TOP_K}")
    if candidate_depth != FROZEN_CANDIDATE_DEPTH:
        raise ValueError(f"candidate_depth must remain {FROZEN_CANDIDATE_DEPTH}")

    started = timer()
    try:
        response = retrieval_service.retrieve(
            understanding.query,
            mode="hybrid",
            top_k=top_k,
            candidate_k=candidate_depth,
            filters=None,
            rerank=True,
        )
    except RuntimeError as exc:
        return dependency_error_result(understanding, exc, elapsed_ms(timer, started))
    timings = timings_from_trace(response, elapsed_ms(timer, started), understanding.timings.total_ms)
    warnings = result_warnings(response.results)
    if not response.results:
        warnings.append(RetrievalWarning(code="NO_RETRIEVAL_RESULTS", message="The frozen retrieval stack returned no evidence."))
    return LegalRetrievalResult(
        query=understanding.query,
        query_understanding_version=understanding.schema_version,
        understanding_summary=understanding_summary(understanding),
        evidence=[evidence_from_result(result, index) for index, result in enumerate(response.results, start=1)],
        stage_counts=stage_counts_from_trace(response),
        timings=timings,
        warnings=sorted(warnings, key=lambda item: (item.code, item.affected_chunk_id or "")),
        provenance=retrieval_provenance(understanding),
    )


def empty_result(understanding: LegalQueryUnderstanding, warning_code: str, warning_message: str) -> LegalRetrievalResult:
    return LegalRetrievalResult(
        query=understanding.query,
        query_understanding_version=understanding.schema_version,
        understanding_summary=understanding_summary(understanding),
        evidence=[],
        stage_counts=RetrievalStageCounts(
            bm25_returned=0,
            dense_returned=0,
            rrf_unique_candidates=0,
            reranker_candidates=0,
            final_evidence_count=0,
        ),
        timings=RetrievalTimings(query_understanding_ms=understanding.timings.total_ms),
        warnings=[RetrievalWarning(code=warning_code, message=warning_message)],
        provenance=retrieval_provenance(understanding),
    )


def dependency_error_result(
    understanding: LegalQueryUnderstanding,
    exc: RuntimeError,
    total_ms: float,
) -> LegalRetrievalResult:
    code, stage = dependency_failure_code(str(exc))
    return LegalRetrievalResult(
        query=understanding.query,
        query_understanding_version=understanding.schema_version,
        understanding_summary=understanding_summary(understanding),
        evidence=[],
        stage_counts=RetrievalStageCounts(
            bm25_returned=0,
            dense_returned=0,
            rrf_unique_candidates=0,
            reranker_candidates=0,
            final_evidence_count=0,
        ),
        timings=RetrievalTimings(
            query_understanding_ms=understanding.timings.total_ms,
            total_retrieval_ms=total_ms,
        ),
        warnings=[
            RetrievalWarning(
                code=code,
                message="A required frozen retrieval dependency is unavailable; no fallback retrieval was executed.",
            )
        ],
        error=RetrievalError(code=code, message=str(exc), stage=stage, fallback_used=False),
        fallbacks=[],
        provenance=retrieval_provenance(understanding),
    )


def dependency_failure_code(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if "rerank" in lowered:
        return "RERANKER_UNAVAILABLE", "reranker"
    if "lexical" in lowered or "bm25" in lowered:
        return "BM25_UNAVAILABLE", "bm25"
    if "dense" in lowered or "vector store" in lowered or "chroma" in lowered:
        return "DENSE_INDEX_UNAVAILABLE", "dense"
    return "RETRIEVAL_DEPENDENCY_UNAVAILABLE", "retrieval"


def understanding_summary(understanding: LegalQueryUnderstanding) -> dict:
    return {
        "schema_version": understanding.schema_version,
        "legal_regime": understanding.legal_regime.regime,
        "explicit_sections": [
            {"statute": item.statute, "section": item.section, "source": item.source}
            for item in understanding.explicit_sections
        ],
        "offence_families": understanding.offence_families,
        "procedural_posture": understanding.procedural_posture,
        "section_ranking_status": understanding.section_ranking_status,
        "retrieval_query_policy": "original_query_only",
        "query_expansion_enabled": False,
    }


def stage_counts_from_trace(response: RetrievalResponse) -> RetrievalStageCounts:
    return RetrievalStageCounts(
        bm25_returned=response.trace.lexical_candidate_count,
        dense_returned=response.trace.dense_candidate_count,
        rrf_unique_candidates=max(
            len({result.chunk_id for result in response.results}),
            response.trace.fused_candidate_count,
        ),
        reranker_candidates=response.trace.fused_candidate_count,
        final_evidence_count=len(response.results),
    )


def timings_from_trace(response: RetrievalResponse, total_ms: float, query_understanding_ms: float | None) -> RetrievalTimings:
    return RetrievalTimings(
        query_understanding_ms=query_understanding_ms,
        bm25_ms=response.trace.lexical_latency_ms,
        dense_embedding_ms=response.trace.dense_embedding_latency_ms,
        dense_search_ms=response.trace.dense_query_latency_ms,
        rrf_ms=response.trace.fusion_latency_ms,
        reranker_ms=response.trace.rerank_latency_ms,
        total_retrieval_ms=total_ms,
    )


def evidence_from_result(result: RetrievalResult, index: int) -> LegalEvidenceChunk:
    citation_id = f"E{index}"
    citation = CitationMetadata(
        citation_id=citation_id,
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        judgment_id=result.document_id,
        case_name=result.case_title,
        court=result.court,
        date=result.decision_date,
        source_url=result.source_url,
        page_start=result.page_start,
        page_end=result.page_end,
        paragraph_start=result.paragraph_start,
        paragraph_end=result.paragraph_end,
    )
    return LegalEvidenceChunk(
        rank=index,
        citation_id=citation_id,
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        judgment_id=result.document_id,
        text=result.text,
        source=result.text_source_type,
        source_url=result.source_url,
        court=result.court,
        case_name=result.case_title,
        case_citation=None,
        judgment_date=result.decision_date,
        page_start=result.page_start,
        page_end=result.page_end,
        paragraph_start=result.paragraph_start,
        paragraph_end=result.paragraph_end,
        heading=None,
        offence_family=result.effective_offence_family,
        legal_regime=result.effective_legal_regime,
        bm25_score=float(result.lexical_score) if result.lexical_score is not None else None,
        bm25_rank=result.lexical_rank,
        dense_score=float(result.dense_score) if result.dense_score is not None else None,
        dense_rank=result.dense_rank,
        rrf_score=float(result.hybrid_score) if result.hybrid_score is not None else None,
        rrf_rank=result.pre_rerank_rank or result.rank,
        reranker_score=float(result.rerank_score) if result.rerank_score is not None else None,
        reranker_rank=result.rerank_rank,
        citation_metadata=citation,
    )


def result_warnings(results: list[RetrievalResult]) -> list[RetrievalWarning]:
    warnings = []
    for result in results:
        missing = []
        if not result.document_id:
            missing.append("document_id")
        if result.paragraph_start is None or result.paragraph_end is None:
            missing.append("paragraph_range")
        if not result.case_title:
            missing.append("case_name")
        if missing:
            warnings.append(
                RetrievalWarning(
                    code="INCOMPLETE_EVIDENCE_PROVENANCE",
                    message=f"Evidence provenance is incomplete: {', '.join(missing)}.",
                    affected_chunk_id=result.chunk_id,
                )
            )
    return warnings


def retrieval_provenance(understanding: LegalQueryUnderstanding) -> list[RetrievalProvenance]:
    return [
        RetrievalProvenance(stage="query", source="user_explicit", detail="Original query used for BM25 and dense retrieval."),
        RetrievalProvenance(stage="understanding", source=understanding.schema_version, detail="Structured enrichment attached as metadata only."),
        RetrievalProvenance(stage="bm25", source=FROZEN_BM25_INDEX_VERSION, detail="Frozen lexical retrieval stage."),
        RetrievalProvenance(stage="dense", source=FROZEN_DENSE_MODEL, detail="Frozen BGE-M3 dense retrieval stage."),
        RetrievalProvenance(stage="fusion", source="reciprocal_rank_fusion", detail=f"Frozen RRF K={FROZEN_RRF_K}."),
        RetrievalProvenance(stage="reranker", source=FROZEN_RERANKER_MODEL, detail="Frozen BGE reranker stage."),
    ]


def elapsed_ms(timer, started: float) -> float:
    return round((timer() - started) * 1000, 3)
