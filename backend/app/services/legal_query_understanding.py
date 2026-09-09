"""Deterministic query-understanding orchestration for LegalAI."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.app.schemas.legal_ner import CanonicalEntity, NER_SCHEMA_VERSION
from backend.app.schemas.query_analysis import LegalQueryAnalysis, PredictedLegalSection, SectionSignal, StatuteSignal
from backend.app.services.legal_ner import extract_deterministic_entities
from backend.app.services.legal_regime import LegalRegimeResolution, resolve_legal_regime
from backend.app.services.legal_section_hybrid_ranking import LegalSectionRankedCandidate, deterministic_ranked_candidates
from backend.app.services.legal_section_prediction import DEFAULT_TOP_K, normalize_section
from backend.app.services.query_analysis import ANALYSIS_VERSION, analyze_legal_query


QUERY_UNDERSTANDING_VERSION = "legalai-query-understanding-v1"
SECTION_RANKING_SELECTION_VERSION = "legalai-section-selected-configuration-v1"
RETRIEVAL_ENRICHMENT_VERSION = "legalai-retrieval-enrichment-v1"

SectionRankingMode = Literal["deterministic", "cross_encoder_protected_hybrid"]
ProvenanceSource = Literal[
    "user_explicit",
    "deterministic_query_analysis",
    "deterministic_ner",
    "regime_resolver",
    "deterministic_section_predictor",
    "cross_encoder_section_ranker",
]


class QueryUnderstandingWarning(BaseModel):
    code: str
    message: str
    source: str


class QueryUnderstandingConflict(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    evidence: list[str] = Field(default_factory=list)
    affected_fields: list[str] = Field(default_factory=list)


class QueryUnderstandingProvenance(BaseModel):
    field: str
    source: ProvenanceSource
    detail: str
    priority: int


class QueryUnderstandingVersions(BaseModel):
    query_understanding: str = QUERY_UNDERSTANDING_VERSION
    query_analysis: str = ANALYSIS_VERSION
    ner_schema: str = NER_SCHEMA_VERSION
    section_prediction: str = "legalai-section-prediction-baseline-v1"
    section_ranking_selection: str = SECTION_RANKING_SELECTION_VERSION
    retrieval_enrichment: str = RETRIEVAL_ENRICHMENT_VERSION


class QueryUnderstandingTimings(BaseModel):
    query_analysis_ms: float = 0.0
    ner_ms: float = 0.0
    regime_ms: float = 0.0
    section_candidate_generation_ms: float = 0.0
    section_ranking_ms: float = 0.0
    total_ms: float = 0.0


class LegalRetrievalEnrichment(BaseModel):
    schema_version: str = RETRIEVAL_ENRICHMENT_VERSION
    original_query: str
    explicit_sections: list[SectionSignal] = Field(default_factory=list)
    statutes: list[StatuteSignal] = Field(default_factory=list)
    offence_families: list[str] = Field(default_factory=list)
    procedural_posture: list[str] = Field(default_factory=list)
    regime: str
    predicted_sections: list[LegalSectionRankedCandidate] = Field(default_factory=list)
    priority_policy: list[str] = Field(
        default_factory=lambda: [
            "original_query",
            "explicit_sections",
            "deterministic_high_confidence_signals",
            "deterministic_ner",
            "procedure_offence_family_regime",
            "predicted_sections_supplementary",
        ]
    )


class LegalQueryUnderstanding(BaseModel):
    schema_version: str = QUERY_UNDERSTANDING_VERSION
    query: str
    normalized_query: str
    analysis: LegalQueryAnalysis
    entities: list[CanonicalEntity] = Field(default_factory=list)
    explicit_statutes: list[StatuteSignal] = Field(default_factory=list)
    explicit_sections: list[SectionSignal] = Field(default_factory=list)
    procedural_posture: list[str] = Field(default_factory=list)
    offence_families: list[str] = Field(default_factory=list)
    legal_regime: LegalRegimeResolution
    predicted_sections: list[LegalSectionRankedCandidate] = Field(default_factory=list)
    warnings: list[QueryUnderstandingWarning] = Field(default_factory=list)
    conflicts: list[QueryUnderstandingConflict] = Field(default_factory=list)
    provenance: list[QueryUnderstandingProvenance] = Field(default_factory=list)
    versions: QueryUnderstandingVersions = Field(default_factory=QueryUnderstandingVersions)
    timings: QueryUnderstandingTimings = Field(default_factory=QueryUnderstandingTimings)
    section_ranking_status: str = "deterministic"
    fallbacks_used: list[str] = Field(default_factory=list)
    retrieval_enrichment: LegalRetrievalEnrichment


class CrossEncoderSectionRanker(Protocol):
    def rank(
        self,
        query: str,
        analysis: LegalQueryAnalysis,
        deterministic_candidates: list[PredictedLegalSection],
        top_k: int = DEFAULT_TOP_K,
    ) -> list[LegalSectionRankedCandidate]:
        ...


def understand_legal_query(
    query: str,
    *,
    section_ranking_mode: SectionRankingMode | None = None,
    section_ranker: CrossEncoderSectionRanker | None = None,
    timer=perf_counter,
) -> LegalQueryUnderstanding:
    total_start = timer()
    requested_mode: SectionRankingMode = section_ranking_mode or "deterministic"

    started = timer()
    analysis = analyze_legal_query(query)
    query_analysis_ms = elapsed_ms(timer, started)

    started = timer()
    ner_result = extract_deterministic_entities(query)
    ner_ms = elapsed_ms(timer, started)

    started = timer()
    regime = resolve_legal_regime(query)
    regime_ms = elapsed_ms(timer, started)

    started = timer()
    deterministic_candidates = sorted(analysis.predicted_sections, key=lambda item: item.rank)[:DEFAULT_TOP_K]
    section_candidate_ms = elapsed_ms(timer, started)

    warnings = structured_warnings(analysis, deterministic_candidates)
    conflicts = structured_conflicts(analysis, regime, deterministic_candidates)
    fallbacks: list[str] = []

    started = timer()
    if requested_mode == "cross_encoder_protected_hybrid":
        if section_ranker is None:
            ranked_sections = deterministic_ranked_candidates(deterministic_candidates, DEFAULT_TOP_K)
            fallbacks.append("SECTION_RANKER_FALLBACK_DETERMINISTIC")
            warnings.append(
                QueryUnderstandingWarning(
                    code="SECTION_RANKER_FALLBACK_DETERMINISTIC",
                    message="Cross-encoder section ranking was requested but unavailable; deterministic ranking was used.",
                    source="section_ranking",
                )
            )
            ranking_status = "fallback_deterministic"
        else:
            ranked_sections = section_ranker.rank(query, analysis, deterministic_candidates, DEFAULT_TOP_K)
            ranked_sections = enforce_explicit_authority(ranked_sections, deterministic_candidates, analysis)
            ranking_status = "cross_encoder_protected_hybrid"
    else:
        ranked_sections = deterministic_ranked_candidates(deterministic_candidates, DEFAULT_TOP_K)
        ranking_status = "deterministic"
    section_ranking_ms = elapsed_ms(timer, started)

    retrieval_enrichment = LegalRetrievalEnrichment(
        original_query=query,
        explicit_sections=analysis.explicit_sections,
        statutes=analysis.explicit_statutes,
        offence_families=stable_values(signal.normalized for signal in analysis.offence_family_hints),
        procedural_posture=stable_values(signal.normalized for signal in analysis.procedural_posture),
        regime=regime.regime,
        predicted_sections=ranked_sections,
    )
    timings = QueryUnderstandingTimings(
        query_analysis_ms=query_analysis_ms,
        ner_ms=ner_ms,
        regime_ms=regime_ms,
        section_candidate_generation_ms=section_candidate_ms,
        section_ranking_ms=section_ranking_ms,
        total_ms=elapsed_ms(timer, total_start),
    )
    return LegalQueryUnderstanding(
        query=query,
        normalized_query=analysis.normalized_query,
        analysis=analysis,
        entities=sorted(ner_result.entities, key=lambda item: (item.start_char, item.end_char, item.entity_type)),
        explicit_statutes=analysis.explicit_statutes,
        explicit_sections=analysis.explicit_sections,
        procedural_posture=retrieval_enrichment.procedural_posture,
        offence_families=retrieval_enrichment.offence_families,
        legal_regime=regime,
        predicted_sections=ranked_sections,
        warnings=sorted(warnings, key=lambda item: (item.code, item.message)),
        conflicts=sorted(conflicts, key=lambda item: (item.code, item.message)),
        provenance=build_provenance(requested_mode, ranking_status),
        timings=timings,
        section_ranking_status=ranking_status,
        fallbacks_used=fallbacks,
        retrieval_enrichment=retrieval_enrichment,
    )


def elapsed_ms(timer, started: float) -> float:
    return round((timer() - started) * 1000, 3)


def stable_values(values) -> list[str]:
    return sorted({value for value in values if value})


def structured_warnings(
    analysis: LegalQueryAnalysis,
    candidates: list[PredictedLegalSection],
) -> list[QueryUnderstandingWarning]:
    warnings = [
        QueryUnderstandingWarning(code=code.upper(), message=warning_message(code), source="deterministic_query_analysis")
        for code in analysis.warnings
    ]
    if analysis.legal_regime == "mixed_or_transition":
        warnings.append(
            QueryUnderstandingWarning(
                code="TRANSITIONAL_LAW_CONTEXT",
                message="The query contains old/new criminal law transition signals.",
                source="regime_resolver",
            )
        )
    if analysis.legal_regime == "unknown" and (analysis.explicit_sections or analysis.explicit_statutes):
        warnings.append(
            QueryUnderstandingWarning(
                code="AMBIGUOUS_LEGAL_REGIME",
                message="The query has legal references but no confident old/new regime resolution.",
                source="regime_resolver",
            )
        )
    if not candidates:
        warnings.append(
            QueryUnderstandingWarning(
                code="NO_SECTION_CANDIDATES",
                message="No deterministic section candidates were generated.",
                source="deterministic_section_predictor",
            )
        )
    if not analysis.offence_family_hints and not analysis.explicit_sections and candidates:
        warnings.append(
            QueryUnderstandingWarning(
                code="LOW_CONFIDENCE_OFFENCE_FAMILY",
                message="No high-confidence offence-family hint was extracted from the query.",
                source="deterministic_query_analysis",
            )
        )
    return warnings


def warning_message(code: str) -> str:
    messages = {
        "section_without_explicit_statute": "An explicit section was detected without an attached statute.",
        "conflicting_old_new_statutes": "The query contains both old-code and new-code statute references.",
        "ambiguous_date_context": "Date evidence did not resolve a confident legal regime.",
        "multiple_offence_families": "Multiple offence-family hints were detected.",
    }
    return messages.get(code, code.replace("_", " "))


def structured_conflicts(
    analysis: LegalQueryAnalysis,
    regime: LegalRegimeResolution,
    candidates: list[PredictedLegalSection],
) -> list[QueryUnderstandingConflict]:
    conflicts: list[QueryUnderstandingConflict] = []
    explicit_statutes = {statute.canonical for statute in analysis.explicit_statutes}
    if explicit_statutes & {"IPC", "CrPC"} and explicit_statutes & {"BNS", "BNSS"}:
        conflicts.append(
            QueryUnderstandingConflict(
                code="EXPLICIT_OLD_NEW_STATUTE_MIX",
                severity="info",
                message="Both old-code and new-code statute references are explicit in the query.",
                evidence=sorted(explicit_statutes),
                affected_fields=["explicit_statutes", "legal_regime"],
            )
        )
    if regime.regime == "mixed_or_transition":
        return conflicts
    for candidate in candidates:
        if candidate.relationship_to_explicit == "conflicts_with_explicit":
            conflicts.append(
                QueryUnderstandingConflict(
                    code="EXPLICIT_PREDICTION_CONFLICT",
                    severity="warning",
                    message="A predicted section is from the same explicit statute but does not match the explicit section.",
                    evidence=[f"{candidate.statute} {candidate.section}"],
                    affected_fields=["explicit_sections", "predicted_sections"],
                )
            )
    return conflicts


def enforce_explicit_authority(
    ranked_sections: list[LegalSectionRankedCandidate],
    deterministic_candidates: list[PredictedLegalSection],
    analysis: LegalQueryAnalysis,
) -> list[LegalSectionRankedCandidate]:
    explicit_keys = {(section.statute, normalize_section(section.section)) for section in analysis.explicit_sections if section.statute}
    if not explicit_keys:
        return rerank_with_top_k(ranked_sections)
    by_key = {(item.statute, item.normalized_section): item for item in ranked_sections}
    deterministic_by_key = {(item.statute, item.normalized_section): item for item in deterministic_candidates}
    protected = []
    for key in sorted(explicit_keys):
        existing = by_key.get(key)
        if existing is not None:
            protected.append(mark_protected(existing))
        elif key in deterministic_by_key:
            protected.append(ranked_from_prediction(deterministic_by_key[key], len(protected) + 1))
    protected_keys = {(item.statute, item.normalized_section) for item in protected}
    remainder = [item for item in ranked_sections if (item.statute, item.normalized_section) not in protected_keys]
    return rerank_with_top_k(protected + remainder)


def mark_protected(candidate: LegalSectionRankedCandidate) -> LegalSectionRankedCandidate:
    return replace(candidate, protected_explicit=True)


def ranked_from_prediction(candidate: PredictedLegalSection, rank: int) -> LegalSectionRankedCandidate:
    return LegalSectionRankedCandidate(
        statute=candidate.statute,
        section=candidate.section,
        normalized_section=candidate.normalized_section,
        rank=rank,
        final_score=candidate.score,
        deterministic_score=candidate.score,
        semantic_score=None,
        deterministic_rank=candidate.rank,
        semantic_rank=None,
        ranking_source="deterministic",
        protected_explicit=candidate.relationship_to_explicit == "supports_explicit",
        regime_compatible=True,
        evidence=candidate.evidence,
    )


def rerank_with_top_k(candidates: list[LegalSectionRankedCandidate]) -> list[LegalSectionRankedCandidate]:
    return [
        replace(item, rank=index)
        for index, item in enumerate(candidates[:DEFAULT_TOP_K], start=1)
    ]


def build_provenance(requested_mode: str, ranking_status: str) -> list[QueryUnderstandingProvenance]:
    items = [
        QueryUnderstandingProvenance(field="query", source="user_explicit", detail="Original user query preserved exactly.", priority=1),
        QueryUnderstandingProvenance(field="explicit_sections", source="deterministic_query_analysis", detail="Explicit section spans extracted from original query.", priority=2),
        QueryUnderstandingProvenance(field="entities", source="deterministic_ner", detail="Phase 0 deterministic legal NER.", priority=4),
        QueryUnderstandingProvenance(field="legal_regime", source="regime_resolver", detail="Frozen deterministic legal-regime resolver.", priority=5),
        QueryUnderstandingProvenance(field="predicted_sections", source="deterministic_section_predictor", detail="Supplementary deterministic section candidates.", priority=6),
    ]
    if requested_mode == "cross_encoder_protected_hybrid" and ranking_status == "cross_encoder_protected_hybrid":
        items.append(
            QueryUnderstandingProvenance(
                field="predicted_sections",
                source="cross_encoder_section_ranker",
                detail="Injected/local cross-encoder ranker reordered bounded deterministic candidates.",
                priority=6,
            )
        )
    return sorted(items, key=lambda item: (item.priority, item.field, item.source))
