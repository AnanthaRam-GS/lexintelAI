"""Explainable combined candidate quality decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from backend.scripts.corpus_analysis.criminal_relevance import (
    STRONG_THRESHOLD,
    UNCERTAIN_THRESHOLD,
    assess_criminal_relevance,
)
from backend.scripts.corpus_analysis.document_type import assess_document_type
from backend.scripts.corpus_analysis.metadata_quality import assess_metadata_quality
from backend.scripts.corpus_analysis.regime_detector import detect_legal_regime
from backend.scripts.corpus_analysis.statute_detector import detect_statutes


DOCUMENT_TYPE_THRESHOLD = 0.6
METADATA_THRESHOLD = 0.65
ALLOWED_DECISIONS = {"accept_candidate", "needs_review", "reject"}


@dataclass(frozen=True)
class CandidateQualityDecision:
    decision: str
    reasons: list[str]
    document_type_score: float
    criminal_relevance_score: float
    metadata_quality_score: float
    detected_statutes: list[str]
    legal_regime: str
    recommended_offence_family: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def quota_allows(offence_family: str, accepted_counts: dict[str, int], quotas: dict[str, int]) -> bool:
    return accepted_counts.get(offence_family, 0) < quotas.get(offence_family, 0)


def decide_candidate_quality(
    text: str,
    record: dict[str, Any],
    accepted_counts: dict[str, int] | None = None,
    quotas: dict[str, int] | None = None,
    duplicate: bool = False,
    corrupt: bool = False,
) -> CandidateQualityDecision:
    document_type = assess_document_type(text)
    criminal = assess_criminal_relevance(text)
    metadata = assess_metadata_quality(record)
    statutes = detect_statutes(text)
    regime = detect_legal_regime(text)
    reasons: list[str] = []

    if duplicate:
        reasons.append("duplicate_candidate")
    if corrupt:
        reasons.append("corrupt_or_invalid_content")
    if not document_type.likely_judgment:
        reasons.append("low_document_type_score")
    if criminal.score < UNCERTAIN_THRESHOLD:
        reasons.append("low_criminal_relevance")
    if metadata.score < METADATA_THRESHOLD:
        reasons.append("insufficient_metadata_quality")
    if accepted_counts is not None and quotas is not None:
        family = str(record.get("offence_family") or "")
        if not quota_allows(family, accepted_counts, quotas):
            reasons.append("offence_family_quota_reached")

    if duplicate or corrupt or "low_criminal_relevance" in reasons:
        decision = "reject"
    elif (
        document_type.score >= DOCUMENT_TYPE_THRESHOLD
        and criminal.score >= STRONG_THRESHOLD
        and metadata.score >= METADATA_THRESHOLD
        and not reasons
    ):
        decision = "accept_candidate"
    else:
        decision = "needs_review"
        if regime.regime == "unknown":
            reasons.append("insufficient_regime_evidence")

    return CandidateQualityDecision(
        decision=decision,
        reasons=reasons,
        document_type_score=document_type.score,
        criminal_relevance_score=criminal.score,
        metadata_quality_score=metadata.score,
        detected_statutes=statutes.detected_statutes,
        legal_regime=regime.regime,
        recommended_offence_family=str(record.get("offence_family") or "") or None,
    )

