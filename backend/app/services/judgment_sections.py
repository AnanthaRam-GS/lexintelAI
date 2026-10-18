"""Statute and section citations in judgment text, for document_sections.

This module does not add a second extractor. Section detection is the
existing deterministic one, ``query_analysis.extract_statutes`` and
``extract_sections`` (also used by the deterministic legal NER). This module
adds only:

- text pre-normalization for citation forms common in judgments that the
  query-oriented patterns miss ("u/s 302/34 IPC", "302 r/w 34", "Cr.P.C.");
- canonical section format (base section with letter suffix, uppercase:
  "498A"; subsections such as "(1)" dropped) and range validation per
  statute, so years, paragraph numbers or OCR noise are rejected rather than
  stored;
- the IPC/CrPC (``ipc_crpc``) versus BNS/BNSS (``bns_bnss``) distinction, from
  the legal section catalog's statute regimes.

Only mentions bound to an explicit statute are kept. Precision matters more
than coverage: a section number without a statute is never assigned one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re

from backend.app.services.legal_section_prediction import load_section_catalog
from backend.app.services.query_analysis import extract_sections, extract_statutes

EXTRACTION_METHOD = "query_analysis.extract_sections+judgment_v2"

# Highest section number in each statute supported by query_analysis.
SECTION_RANGES = {
    "IPC": 511,
    "CrPC": 484,
    "BNS": 358,
    "BNSS": 531,
    "Evidence Act": 167,
    "NDPS Act": 83,
    "POCSO Act": 46,
    "SC/ST Act": 23,
}

_PRE_NORMALIZATIONS = (
    (re.compile(r"\bu/s\.?\s*", re.IGNORECASE), "Section "),
    (re.compile(r"\bCr\.?\s*P\.?\s*C\.?(?=\W|$)", re.IGNORECASE), "CrPC"),
    (re.compile(r"\bI\.\s*P\.\s*C\.?(?=\W|$)"), "IPC"),
    # "498-A" is section 498A, not 498 (ranges such as "147-151" are untouched).
    (re.compile(r"(?<=\d)\s*-\s*([A-Za-z])\b"), r"\1"),
    # "498 A" likewise; only suffixes A-E, and not before an abbreviation such as "A.P.".
    (re.compile(r"(?<=\d) ([A-E])(?=[\s,;)]|\.(?![A-Za-z])|$)"), r"\1"),
    (re.compile(r"\s+r/w\s+(?:section\s+|sec\.?\s+|s\.?\s+)?(?=\d)", re.IGNORECASE), ", "),
    (re.compile(r"(?<=[0-9A-Za-z)])\s*/\s*(?=\d)"), ", "),
)
_SECTION_FORM = re.compile(r"0*(\d+)([A-Za-z]?)(?:\(.*\))?")
# A single uppercase letter in parentheses after a number: suffix or sub-part?
_AMBIGUOUS_LETTER_SUFFIX = re.compile(r"\b\d+\s*\(\s*[A-Z]\s*\)")


@dataclass
class SectionExtraction:
    """Accepted (statute, section) mentions plus counts of rejected candidates."""

    mentions: list[tuple[str, str]] = field(default_factory=list)
    rejected: Counter = field(default_factory=Counter)


def prepare_judgment_text(text: str) -> str:
    for pattern, replacement in _PRE_NORMALIZATIONS:
        text = pattern.sub(replacement, text)
    return text


def canonical_section(raw: str) -> str | None:
    """'0302' -> '302', '498a' -> '498A', '103(1)' -> '103'; None if not a section form.

    A single uppercase letter in parentheses ("120(B)", "506(B)") may be a
    suffix (120B) or a sub-part (506 Part II), so it is rejected rather than
    guessed. Lowercase clauses such as NDPS "20(b)" belong to the section.
    """
    compact = re.sub(r"\s+", "", raw)
    if re.fullmatch(r"\d+\([A-Z]\)", compact):
        return None
    match = _SECTION_FORM.fullmatch(compact)
    if not match:
        return None
    return f"{int(match.group(1))}{match.group(2).upper()}"


def extract_section_mentions(text: str) -> SectionExtraction:
    result = SectionExtraction()
    prepared = prepare_judgment_text(text)
    # "120(B)": the extractor would keep "120" and drop "(B)"; remove these citations instead.
    ambiguous = _AMBIGUOUS_LETTER_SUFFIX.findall(prepared)
    if ambiguous:
        result.rejected["ambiguous_letter_suffix"] += len(ambiguous)
        # A non-numeric placeholder keeps lists such as "Sections 120(B), 34 IPC" parseable.
        prepared = _AMBIGUOUS_LETTER_SUFFIX.sub("x", prepared)
    for signal in extract_sections(prepared, extract_statutes(prepared)):
        if signal.statute is None:
            result.rejected["no_explicit_statute"] += 1
            continue
        if signal.statute not in SECTION_RANGES:
            result.rejected["unsupported_statute"] += 1
            continue
        section = canonical_section(signal.section)
        if section is None:
            result.rejected["malformed_section"] += 1
            continue
        number = int(re.match(r"\d+", section).group(0))
        if not 1 <= number <= SECTION_RANGES[signal.statute]:
            result.rejected["out_of_range"] += 1
            continue
        result.mentions.append((signal.statute, section))
    return result


def statute_regimes() -> dict[str, str]:
    """Statute -> regime from the section catalog: IPC/CrPC ipc_crpc, BNS/BNSS bns_bnss."""
    regimes: dict[str, set[str]] = {}
    for entry in load_section_catalog():
        regimes.setdefault(entry["statute"], set()).add(entry.get("regime") or "unknown")
    return {statute: next(iter(values)) if len(values) == 1 else "mixed" for statute, values in regimes.items()}


def regime_for(statute: str, regimes: dict[str, str] | None = None) -> str:
    return (regimes or statute_regimes()).get(statute, "statute_neutral")
