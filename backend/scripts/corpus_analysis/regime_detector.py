"""Legal regime detection from explicit statute evidence."""

from __future__ import annotations

from dataclasses import dataclass

from backend.scripts.corpus_analysis.statute_detector import detect_statutes


ALLOWED_LEGAL_REGIMES = {"ipc_crpc", "bns_bnss", "mixed_or_transition", "unknown"}


@dataclass(frozen=True)
class LegalRegimeAssessment:
    regime: str
    evidence: list[str]
    confidence_level: str


def detect_legal_regime(text: str) -> LegalRegimeAssessment:
    detection = detect_statutes(text)
    statutes = set(detection.detected_statutes)
    legacy = sorted(statutes & {"IPC", "CrPC"})
    current = sorted(statutes & {"BNS", "BNSS"})
    if legacy and current:
        return LegalRegimeAssessment("mixed_or_transition", legacy + current, "high")
    if legacy:
        confidence = "high" if {"IPC", "CrPC"} <= statutes else "medium"
        return LegalRegimeAssessment("ipc_crpc", legacy, confidence)
    if current:
        confidence = "high" if {"BNS", "BNSS"} <= statutes else "medium"
        return LegalRegimeAssessment("bns_bnss", current, confidence)
    return LegalRegimeAssessment("unknown", [], "low")

