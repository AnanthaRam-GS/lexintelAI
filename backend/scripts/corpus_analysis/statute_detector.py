"""Rule-based criminal statute and section detection."""

from __future__ import annotations

import re
from dataclasses import dataclass


STATUTE_PATTERNS = {
    "IPC": r"\b(?:IPC|Indian Penal Code)\b",
    "BNS": r"\b(?:BNS|Bharatiya Nyaya Sanhita)\b",
    "CrPC": r"\b(?:CrPC|Code of Criminal Procedure)\b",
    "BNSS": r"\b(?:BNSS|Bharatiya Nagarik Suraksha Sanhita)\b",
}


@dataclass(frozen=True)
class DetectedSection:
    statute: str
    section: str


@dataclass(frozen=True)
class StatuteDetection:
    detected_statutes: list[str]
    detected_sections: list[DetectedSection]


def detect_statutes(text: str) -> StatuteDetection:
    detected = {
        statute
        for statute, pattern in STATUTE_PATTERNS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    }
    sections: list[DetectedSection] = []
    statute_aliases = {
        "IPC": r"(?:IPC|Indian Penal Code)",
        "BNS": r"(?:BNS|Bharatiya Nyaya Sanhita)",
        "CrPC": r"(?:CrPC|Code of Criminal Procedure)",
        "BNSS": r"(?:BNSS|Bharatiya Nagarik Suraksha Sanhita)",
    }
    for statute, alias in statute_aliases.items():
        patterns = (
            rf"\bSection\s+([0-9][0-9A-Za-z-]*)\s+(?:of\s+(?:the\s+)?)?{alias}\b",
            rf"\b{alias}\s+Section\s+([0-9][0-9A-Za-z-]*)\b",
            rf"\b{alias}\s+([0-9][0-9A-Za-z-]*)\b",
            rf"\b([0-9][0-9A-Za-z-]*)\s+{alias}\b",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                section = match.group(1)
                if any(item.statute == statute and item.section == section for item in sections):
                    continue
                sections.append(DetectedSection(statute=statute, section=section))
                detected.add(statute)
    return StatuteDetection(
        detected_statutes=sorted(detected),
        detected_sections=sections,
    )
