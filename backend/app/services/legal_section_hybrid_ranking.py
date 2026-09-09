"""Experiment-only legal section semantic ranking boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from backend.app.schemas.query_analysis import LegalQueryAnalysis, PredictedLegalSection
from backend.app.services.legal_section_prediction import DEFAULT_TOP_K, load_section_catalog, normalize_section


RankingMode = Literal["deterministic", "semantic", "hybrid"]
CandidateGenerationMode = Literal["deterministic", "bounded_catalog"]


@dataclass(frozen=True)
class LegalSectionRankingConfig:
    """Experimental ranking config with intentionally unselected weights."""

    mode: RankingMode = "deterministic"
    candidate_generation: CandidateGenerationMode = "deterministic"
    final_top_k: int = DEFAULT_TOP_K
    semantic_weight: float | None = None
    deterministic_weight: float | None = None
    explicit_section_protection: bool = True
    regime_protection: bool = True
    zero_positive_guardrail: bool = True
    gold_training_allowed: bool = False

    def validate(self) -> None:
        if self.final_top_k > DEFAULT_TOP_K:
            raise ValueError(f"final_top_k must remain <= {DEFAULT_TOP_K}")
        if self.gold_training_allowed:
            raise ValueError("frozen 36-query gold set must not be used for training")
        if self.mode == "hybrid" and (self.semantic_weight is None or self.deterministic_weight is None):
            raise ValueError("hybrid trial weights are intentionally unselected in 0.7C")


@dataclass(frozen=True)
class SectionSemanticCandidate:
    statute: str
    section: str
    normalized_section: str
    semantic_text: str
    catalog_entry: dict[str, Any]
    deterministic_candidate: PredictedLegalSection | None = None


@dataclass(frozen=True)
class LegalSectionRankedCandidate:
    statute: str
    section: str
    normalized_section: str
    rank: int
    final_score: float
    deterministic_score: float | None
    semantic_score: float | None
    deterministic_rank: int | None
    semantic_rank: int | None
    ranking_source: RankingMode
    protected_explicit: bool = False
    regime_compatible: bool = True
    evidence: list[str] = field(default_factory=list)


class LegalSectionSemanticRanker(Protocol):
    model_id: str
    revision: str | None

    def encode_sections(self, sections: list[SectionSemanticCandidate]) -> None:
        """Optionally pre-encode bounded section representations."""

    def score_query_candidates(
        self,
        query_text: str,
        candidates: list[SectionSemanticCandidate],
    ) -> dict[tuple[str, str], float]:
        """Return semantic scores keyed by normalized statute and section."""


class MockLegalSectionSemanticRanker:
    """Deterministic mock scorer for architecture tests only."""

    model_id = "mock-legal-section-semantic-ranker"
    revision = "test"

    def __init__(self, scores: dict[tuple[str, str], float] | None = None) -> None:
        self._scores = scores or {}

    def encode_sections(self, sections: list[SectionSemanticCandidate]) -> None:
        return None

    def score_query_candidates(
        self,
        query_text: str,
        candidates: list[SectionSemanticCandidate],
    ) -> dict[tuple[str, str], float]:
        del query_text
        return {
            (candidate.statute, candidate.normalized_section): self._scores.get(
                (candidate.statute, candidate.normalized_section),
                0.0,
            )
            for candidate in candidates
        }


def build_section_semantic_text(entry: dict[str, Any]) -> str:
    return (
        f"{entry['statute']} Section {entry['section']}: {entry['canonical_name']}. "
        f"{entry['brief_description']} Family: {entry['offence_family']}. "
        f"Regime: {entry['regime']}."
    )


def build_query_representation(analysis: LegalQueryAnalysis, variant: Literal["Q0", "Q1", "Q2"] = "Q0") -> str:
    if variant == "Q0":
        return analysis.original_query
    explicit = ", ".join(
        f"{section.statute or 'Unknown'} {section.section}" for section in analysis.explicit_sections
    )
    if variant == "Q1":
        return f"{analysis.original_query}\nExplicit sections: {explicit or 'none'}"
    concepts = sorted({item.normalized for item in [*analysis.offence_family_hints, *analysis.procedural_posture]})
    return (
        f"{analysis.original_query}\n"
        f"Explicit sections: {explicit or 'none'}\n"
        f"Legal regime: {analysis.legal_regime}\n"
        f"Deterministic concepts: {', '.join(concepts) or 'none'}"
    )


def deterministic_candidates_to_semantic(
    candidates: list[PredictedLegalSection],
    catalog: list[dict[str, Any]] | None = None,
) -> list[SectionSemanticCandidate]:
    entries = catalog or load_section_catalog()
    by_key = {(entry["statute"], normalize_section(entry["section"])): entry for entry in entries}
    semantic_candidates = []
    for candidate in candidates:
        entry = by_key[(candidate.statute, candidate.normalized_section)]
        semantic_candidates.append(
            SectionSemanticCandidate(
                statute=entry["statute"],
                section=entry["section"],
                normalized_section=normalize_section(entry["section"]),
                semantic_text=build_section_semantic_text(entry),
                catalog_entry=entry,
                deterministic_candidate=candidate,
            )
        )
    return semantic_candidates


def rank_legal_section_candidates(
    query_text: str,
    analysis: LegalQueryAnalysis,
    deterministic_candidates: list[PredictedLegalSection],
    semantic_ranker: LegalSectionSemanticRanker | None = None,
    config: LegalSectionRankingConfig | None = None,
) -> list[LegalSectionRankedCandidate]:
    config = config or LegalSectionRankingConfig()
    config.validate()
    if not deterministic_candidates and config.zero_positive_guardrail:
        return []
    if config.mode == "deterministic":
        return deterministic_ranked_candidates(deterministic_candidates, config.final_top_k)
    if semantic_ranker is None:
        raise ValueError("semantic_ranker is required for semantic or hybrid experiment modes")

    semantic_candidates = deterministic_candidates_to_semantic(deterministic_candidates)
    semantic_ranker.encode_sections(semantic_candidates)
    scores = semantic_ranker.score_query_candidates(query_text, semantic_candidates)
    semantic_order = {
        key: index
        for index, key in enumerate(
            sorted(scores, key=lambda item: (-scores[item], item[0], item[1])),
            start=1,
        )
    }
    explicit = {(section.statute, normalize_section(section.section)) for section in analysis.explicit_sections if section.statute}
    rows = []
    for candidate in semantic_candidates:
        deterministic = candidate.deterministic_candidate
        candidate_key = (candidate.statute, candidate.normalized_section)
        semantic_score = scores.get(candidate_key, 0.0)
        deterministic_score = deterministic.score if deterministic else None
        if config.mode == "semantic":
            final_score = semantic_score
        else:
            final_score = (config.deterministic_weight or 0.0) * (deterministic_score or 0.0)
            final_score += (config.semantic_weight or 0.0) * semantic_score
        protected = config.explicit_section_protection and candidate_key in explicit
        if protected:
            final_score += 10.0
        rows.append(
            LegalSectionRankedCandidate(
                statute=candidate.statute,
                section=candidate.section,
                normalized_section=candidate.normalized_section,
                rank=0,
                final_score=round(final_score, 6),
                deterministic_score=deterministic_score,
                semantic_score=semantic_score,
                deterministic_rank=deterministic.rank if deterministic else None,
                semantic_rank=semantic_order[candidate_key],
                ranking_source=config.mode,
                protected_explicit=protected,
                regime_compatible=True,
                evidence=deterministic.evidence if deterministic else [],
            )
        )
    ranked = sorted(rows, key=lambda item: (-item.final_score, item.deterministic_rank or 999, item.statute, item.section))[
        : config.final_top_k
    ]
    return [candidate_with_rank(candidate, index) for index, candidate in enumerate(ranked, start=1)]


def deterministic_ranked_candidates(
    candidates: list[PredictedLegalSection],
    top_k: int = DEFAULT_TOP_K,
) -> list[LegalSectionRankedCandidate]:
    return [
        LegalSectionRankedCandidate(
            statute=candidate.statute,
            section=candidate.section,
            normalized_section=candidate.normalized_section,
            rank=index,
            final_score=candidate.score,
            deterministic_score=candidate.score,
            semantic_score=None,
            deterministic_rank=candidate.rank,
            semantic_rank=None,
            ranking_source="deterministic",
            protected_explicit=candidate.relationship_to_explicit == "supports_explicit",
            evidence=candidate.evidence,
        )
        for index, candidate in enumerate(sorted(candidates, key=lambda item: item.rank)[:top_k], start=1)
    ]


def candidate_with_rank(candidate: LegalSectionRankedCandidate, rank: int) -> LegalSectionRankedCandidate:
    return LegalSectionRankedCandidate(
        statute=candidate.statute,
        section=candidate.section,
        normalized_section=candidate.normalized_section,
        rank=rank,
        final_score=candidate.final_score,
        deterministic_score=candidate.deterministic_score,
        semantic_score=candidate.semantic_score,
        deterministic_rank=candidate.deterministic_rank,
        semantic_rank=candidate.semantic_rank,
        ranking_source=candidate.ranking_source,
        protected_explicit=candidate.protected_explicit,
        regime_compatible=candidate.regime_compatible,
        evidence=candidate.evidence,
    )


def compare_against_d0(candidate_eval: dict[str, Any], d0_eval: dict[str, Any]) -> dict[str, Any]:
    metrics = [
        "precision_at_1",
        "precision_at_3",
        "precision_at_5",
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "mrr",
        "ndcg_at_5",
        "hit_at_1",
        "hit_at_3",
        "hit_at_5",
    ]
    candidate_metrics = candidate_eval["overall_metrics"]
    d0_metrics = d0_eval["overall_metrics"]
    return {
        metric: round(candidate_metrics[metric] - d0_metrics[metric], 6)
        for metric in metrics
    }
