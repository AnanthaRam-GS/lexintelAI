"""Deterministic legal-regime resolution for retrieval experiments."""

from __future__ import annotations

from dataclasses import dataclass
import re


REGIMES = {"ipc_crpc", "bns_bnss", "mixed_or_transition", "unknown"}


@dataclass(frozen=True)
class LegalRegimeResolution:
    regime: str
    confidence: str
    explicit_codes: list[str]
    explicit_sections: list[str]
    detected_dates: list[str]
    transition_terms: list[str]


OLD_CODE_PATTERNS = {
    "IPC": re.compile(r"\b(?:ipc|indian penal code)\b", re.IGNORECASE),
    "CrPC": re.compile(r"\b(?:crpc|cr\.?\s*p\.?\s*c\.?|code of criminal procedure)\b", re.IGNORECASE),
}
NEW_CODE_PATTERNS = {
    "BNS": re.compile(r"\b(?:bns|bharatiya nyaya sanhita)\b", re.IGNORECASE),
    "BNSS": re.compile(r"\b(?:bnss|bharatiya nagarik suraksha sanhita)\b", re.IGNORECASE),
}
SECTION_PATTERN = re.compile(r"\bsection\s+\d+[a-z]?\b", re.IGNORECASE)
DATE_PATTERN = re.compile(r"\b(?:1\s+july\s+2024|july\s+2024|2023|2024|2025|post\s+july\s+2024|before\s+july\s+2024|after\s+july\s+2024)\b", re.IGNORECASE)
TRANSITION_TERMS = [
    "old criminal law",
    "new criminal law",
    "transition",
    "repeal",
    "savings",
    "commencement",
    "pending proceeding",
    "old offence",
    "new procedure",
    "before july 2024",
    "after july 2024",
    "post july 2024",
    "new laws commenced",
]


def resolve_legal_regime(query: str) -> LegalRegimeResolution:
    text = query.casefold()
    old_codes = [name for name, pattern in OLD_CODE_PATTERNS.items() if pattern.search(query)]
    new_codes = [name for name, pattern in NEW_CODE_PATTERNS.items() if pattern.search(query)]
    sections = [match.group(0) for match in SECTION_PATTERN.finditer(query)]
    dates = [match.group(0) for match in DATE_PATTERN.finditer(query)]
    transition = [term for term in TRANSITION_TERMS if term in text]
    if old_codes and new_codes:
        return LegalRegimeResolution("mixed_or_transition", "high", old_codes + new_codes, sections, dates, transition)
    if new_codes:
        if transition or any("before" in date.casefold() for date in dates):
            return LegalRegimeResolution("mixed_or_transition", "medium", new_codes, sections, dates, transition)
        return LegalRegimeResolution("bns_bnss", "high", new_codes, sections, dates, transition)
    if old_codes:
        if transition or any(marker in text for marker in ["after july 2024", "post july 2024", "new procedure", "new law"]):
            return LegalRegimeResolution("mixed_or_transition", "medium", old_codes, sections, dates, transition)
        return LegalRegimeResolution("ipc_crpc", "high", old_codes, sections, dates, transition)
    if transition:
        return LegalRegimeResolution("mixed_or_transition", "medium", [], sections, dates, transition)
    if dates and any("2023" in date or "2025" in date for date in dates):
        return LegalRegimeResolution("unknown", "low", [], sections, dates, transition)
    return LegalRegimeResolution("unknown", "low", [], sections, dates, transition)


def regime_match_class(query_regime: str, chunk_regime: str | None) -> str:
    if not chunk_regime or chunk_regime == "unknown":
        return "unknown_metadata"
    if query_regime == "unknown":
        return "unknown_metadata"
    if query_regime == chunk_regime:
        return "exact_regime_match"
    if query_regime == "mixed_or_transition" and chunk_regime in {"ipc_crpc", "bns_bnss", "mixed_or_transition"}:
        return "transition_compatible"
    if chunk_regime == "mixed_or_transition" and query_regime in {"ipc_crpc", "bns_bnss"}:
        return "transition_compatible"
    return "regime_mismatch"
