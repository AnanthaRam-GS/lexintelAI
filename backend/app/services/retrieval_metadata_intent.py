"""Deterministic metadata intent parsing and matching for retrieval reranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from backend.app.services.legal_regime import resolve_legal_regime


@dataclass(frozen=True)
class MetadataIntent:
    court_level: str | None
    court_name: str | None
    date_relation: str | None
    date_value: str | None
    posture: str | None
    offence_family: str | None
    legal_regime: str | None
    confidence: str
    evidence: list[str]
    warnings: list[str]


FAMILY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("homicide", ("murder", "culpable homicide", "fatal assault")),
    ("hurt_and_assault", ("assault", "hurt")),
    ("theft_and_robbery", ("robbery", "stealing", "theft", "property taken")),
    ("cheating_and_fraud", ("cheating", "fraud", "false promise", "deception", "commercial dispute")),
    ("criminal_breach_of_trust", ("criminal breach of trust", "entrusted money", "entrustment")),
    ("kidnapping", ("kidnapping", "abducted", "lured away", "lawful custody")),
    ("sexual_offences", ("sexual offence", "prosecutrix", "rape")),
    ("dowry_and_domestic_cruelty", ("dowry", "marriage demands", "husband and in laws")),
    ("conspiracy_common_intention", ("common intention", "shared intention", "conspiracy")),
    ("narcotics_related", ("ndps", "drug", "narcotics")),
)

POSTURE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("criminal_appeal", ("criminal appeal", "appeal against conviction", "conviction appeal")),
    ("bail_petition", ("regular bail", "bail petition", "bail")),
    ("anticipatory_bail", ("anticipatory bail", "pre-arrest bail")),
    ("quashing_petition", ("fir quashing", "quashing petition", "quashing")),
    ("revision", ("revision",)),
    ("trial_court_conviction", ("trial court conviction", "trial court")),
    ("arrest_procedure", ("arrest procedure", "arrest safeguards", "notice practice")),
)


def parse_metadata_intent(query: str) -> MetadataIntent:
    text = " ".join(query.casefold().split())
    evidence: list[str] = []
    warnings: list[str] = []
    court_level = court_name = None
    if "supreme court" in text:
        court_level = "supreme_court"
        court_name = "Supreme Court"
        evidence.append("explicit Supreme Court")
    elif "high court" in text:
        court_level = "high_court"
        court_name = "High Court"
        evidence.append("explicit High Court")
    elif "trial court" in text:
        court_level = "district_court"
        court_name = "trial court"
        evidence.append("explicit trial court")
    elif "district court" in text:
        court_level = "district_court"
        court_name = "District Court"
        evidence.append("explicit district court")

    date_relation, date_value = parse_date_intent(text)
    if date_relation:
        evidence.append(f"date intent {date_relation} {date_value}")

    posture = first_match(text, POSTURE_PATTERNS)
    if posture:
        evidence.append(f"posture {posture}")

    family = first_match(text, FAMILY_PATTERNS)
    if family:
        evidence.append(f"family {family}")
        if " and " in text and family in {"homicide", "theft_and_robbery", "cheating_and_fraud", "criminal_breach_of_trust"}:
            warnings.append("composite_query_family_signal_is_conservative")

    regime_resolution = resolve_legal_regime(query)
    legal_regime = regime_resolution.regime if regime_resolution.confidence in {"high", "medium"} and regime_resolution.regime != "unknown" else None
    if legal_regime:
        evidence.append(f"regime {legal_regime}")

    confidence = "high" if court_level or posture or legal_regime else "medium" if family or date_relation else "low"
    return MetadataIntent(court_level, court_name, date_relation, date_value, posture, family, legal_regime, confidence, evidence, warnings)


def first_match(text: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for value, triggers in patterns:
        if any(trigger in text for trigger in triggers):
            return value
    return None


def parse_date_intent(text: str) -> tuple[str | None, str | None]:
    if "before july 2024" in text or "before 1 july 2024" in text:
        return "before", "2024-07-01"
    if "after july 2024" in text or "post july 2024" in text or "after 1 july 2024" in text or "post-2024" in text:
        return "after", "2024-07-01"
    match = re.search(r"\b(20\d{2})\b", text)
    if match:
        return "year", match.group(1)
    return None, None


def metadata_features(intent: MetadataIntent, metadata: dict[str, Any]) -> dict[str, str]:
    court = metadata.get("court") or {}
    court_level = str(court.get("court_level") or "")
    court_name = str(court.get("court_name") or "")
    return {
        "court_match": match_text(intent.court_name, court_name),
        "court_level_match": match_value(intent.court_level, court_level),
        "date_compatible": match_date(intent.date_relation, intent.date_value, metadata.get("decision_date")),
        "posture_match": match_posture(intent.posture, metadata),
        "family_match": match_value(intent.offence_family, metadata.get("effective_offence_family")),
        "regime_match": match_value(intent.legal_regime, metadata.get("effective_legal_regime")),
    }


def match_value(expected: str | None, actual: Any) -> str:
    if not expected:
        return "neutral"
    if not actual:
        return "neutral"
    return "match" if str(actual) == expected else "mismatch"


def match_text(expected: str | None, actual: str) -> str:
    if not expected:
        return "neutral"
    if not actual:
        return "neutral"
    return "match" if expected.casefold() in actual.casefold() else "mismatch"


def match_date(relation: str | None, value: str | None, actual: Any) -> str:
    if not relation or not value or not actual:
        return "neutral"
    try:
        actual_date = date.fromisoformat(str(actual))
    except ValueError:
        return "neutral"
    if relation == "before":
        return "match" if actual_date < date.fromisoformat(value) else "mismatch"
    if relation == "after":
        return "match" if actual_date >= date.fromisoformat(value) else "mismatch"
    if relation == "year":
        return "match" if str(actual_date.year) == value else "mismatch"
    return "neutral"


def match_posture(posture: str | None, metadata: dict[str, Any]) -> str:
    if not posture:
        return "neutral"
    title = str(metadata.get("case_title") or "").casefold()
    preview = str(metadata.get("bounded_chunk_preview") or "").casefold()
    haystack = f"{title} {preview[:500]}"
    triggers = {
        "criminal_appeal": ("criminal appeal", "appeal", "conviction"),
        "bail_petition": ("bail",),
        "anticipatory_bail": ("anticipatory bail",),
        "quashing_petition": ("quashing", "fir"),
        "revision": ("revision",),
        "trial_court_conviction": ("trial court", "conviction"),
        "arrest_procedure": ("arrest", "notice"),
    }[posture]
    return "match" if any(trigger in haystack for trigger in triggers) else "mismatch"
