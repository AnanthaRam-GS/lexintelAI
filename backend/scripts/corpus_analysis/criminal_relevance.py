"""Weighted deterministic criminal-domain relevance scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.scripts.corpus_analysis.statute_detector import detect_statutes


STRONG_THRESHOLD = 0.7
UNCERTAIN_THRESHOLD = 0.4
CRIMINAL_TERMS = {
    "fir": r"\bFIR\b",
    "accused": r"\baccused\b",
    "prosecution": r"\bprosecution\b",
    "conviction": r"\bconviction\b",
    "acquittal": r"\bacquittal\b",
    "sentence": r"\bsentence\b",
    "bail": r"\bbail\b",
    "charge_sheet": r"\bcharge[- ]sheet\b",
    "criminal_appeal": r"\bcriminal\s+appeal\b",
    "criminal_complaint": r"\bcriminal\s+complaint\b",
    "criminal_revision": r"\bcriminal\s+revision\b",
    "sessions_court": r"\bsessions\s+court\b",
    "complainant": r"\bcomplainant\b",
    "investigation": r"\binvestigation\b",
}
NEGATIVE_TERMS = {
    "income_tax": r"\bincome tax\b",
    "gst": r"\bGST\b",
    "service_matter": r"\bservice matter\b",
    "company_law": r"\bcompany law\b",
    "commercial_arbitration": r"\bcommercial arbitration\b",
    "civil_suit": r"\bcivil suit\b",
    "property_dispute": r"\bproperty dispute\b",
}


@dataclass(frozen=True)
class CriminalRelevanceAssessment:
    score: float
    is_criminal_candidate: bool
    positive_signals: list[str]
    negative_signals: list[str]
    detected_criminal_terms: list[str]
    explanation_codes: list[str]


def assess_criminal_relevance(text: str) -> CriminalRelevanceAssessment:
    statute_detection = detect_statutes(text)
    statutes = statute_detection.detected_statutes
    terms = [
        code
        for code, pattern in CRIMINAL_TERMS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    negatives = [
        code
        for code, pattern in NEGATIVE_TERMS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    positive_signals = [f"statute:{statute}" for statute in statutes] + terms
    score = 0.13
    if statutes:
        score += min(0.42, 0.16 * len(statutes))
    if statute_detection.detected_sections:
        score += min(0.26, 0.12 * len(statute_detection.detected_sections))
    score += min(0.34, 0.05 * len(terms))
    score -= min(0.18, 0.03 * len(negatives))
    score = max(0.0, min(1.0, round(score, 3)))
    explanation_codes: list[str] = []
    if score >= STRONG_THRESHOLD:
        explanation_codes.append("strong_criminal_relevance")
    elif score >= UNCERTAIN_THRESHOLD:
        explanation_codes.append("moderate_criminal_relevance")
    else:
        explanation_codes.append("low_criminal_relevance")
    if negatives:
        explanation_codes.append("civil_or_noncriminal_terms_present")
    return CriminalRelevanceAssessment(
        score=score,
        is_criminal_candidate=score >= UNCERTAIN_THRESHOLD,
        positive_signals=positive_signals,
        negative_signals=negatives,
        detected_criminal_terms=terms,
        explanation_codes=explanation_codes,
    )
