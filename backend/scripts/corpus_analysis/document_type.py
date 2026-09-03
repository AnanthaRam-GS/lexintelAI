"""Deterministic document-type assessment for judgment candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass


POSITIVE_SIGNALS = {
    "case_party_marker": r"\b(?:v\.?|vs\.?|versus)\b",
    "judgment_or_order": r"\b(?:judgment|order)\b",
    "criminal_case_number": r"\bcriminal\s+(?:appeal|revision|petition|misc|case)\b",
    "bench_or_coram": r"\b(?:bench|coram|hon'?ble|justice|judge)\b",
    "party_role": r"\b(?:petitioner|respondent|appellant|accused|state)\b",
}
NEGATIVE_SIGNALS = {
    "rules_and_orders_collection": r"\brules\s+and\s+orders\b",
    "act_or_rules_collection": r"\b(?:act|rules|regulations|circular|gazette)\b",
    "law_commission_report": r"\blaw commission report\b",
    "report_volume": r"\b(?:vol\(|volume|report)\b",
    "schedule_or_form": r"\b(?:schedule|form no\.|template)\b",
    "navigation_page": r"\b(?:captcha|navigation|document not found|errmsg)\b",
}


@dataclass(frozen=True)
class DocumentTypeAssessment:
    likely_judgment: bool
    score: float
    positive_signals: list[str]
    negative_signals: list[str]


def assess_document_type(text: str) -> DocumentTypeAssessment:
    positive = [
        code
        for code, pattern in POSITIVE_SIGNALS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    negative = [
        code
        for code, pattern in NEGATIVE_SIGNALS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    score = 0.2 + (0.16 * len(positive)) - (0.18 * len(negative))
    if (
        "law_commission_report" in negative
        or "navigation_page" in negative
        or "rules_and_orders_collection" in negative
    ):
        score -= 0.25
    score = max(0.0, min(1.0, round(score, 3)))
    return DocumentTypeAssessment(
        likely_judgment=score >= 0.6,
        score=score,
        positive_signals=positive,
        negative_signals=negative,
    )
