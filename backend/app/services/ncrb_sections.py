"""Statute-qualified section labels for NCRB crime heads (step 15b).

``ncrb_stats.ipc_section`` / ``bns_section`` keep the section text exactly as
NCRB printed it ("305/306", "64-68,70-71 r/w 62", "190, 189(6), 189(5)").
For filtering, the same text is turned into lists of labels in the
``document_sections`` form: ``"IPC 305"``, ``"BNS 103"``.

The section form is ``judgment_sections.canonical_section`` (base number plus
letter suffix, subsections dropped, "120(B)"-style single capitals rejected)
and the per-statute range check is ``judgment_sections.SECTION_RANGES``, so an
NCRB label and a document_sections label for the same section are identical.

Separators: "/", ",", "&", "and", "or", "r/w" (a read-with section is listed
too, as in document_sections). Ranges "363-369" and "64 to 71" are expanded
only when ascending and short; letter ranges "171-E to 171-I" expand the
suffix. Mentions of another statute without a section ("IT Act") and the
phrase "other Crimes" carry no section and are ignored. Anything else that is
not a section is returned as unparsed: nothing is guessed.
"""

from __future__ import annotations

import re

from backend.app.services.judgment_sections import SECTION_RANGES, canonical_section

STATUTES = ("IPC", "BNS")
MAX_RANGE = 60
# "IT Act" (printed truncated as "IT" on two pages) and "other Crimes" name no IPC/BNS section.
_IGNORED = re.compile(r"\b(?:IT(?:\s*Act)?|other\s+(?:BNS\s+)?Crimes)\b")
_SEPARATORS = re.compile(r"\s*(?:/|,|&|\band\b|\bor\b|\br/w\b)\s*", re.IGNORECASE)
_NUMBER_RANGE = re.compile(r"^(\d+)\s*(?:-|to)\s*(\d+)$", re.IGNORECASE)
_AMBIGUOUS = "\u2047"  # stands in for "(G)"-style single capitals until canonical_section rejects them


def _drop_subsections(text: str) -> str:
    """Remove subsection groups ("103(1)", "310(2 & 3)", "125(a)(b)") before splitting, so their separators
    do not split the list. canonical_section drops them too. A single capital in brackets ("326(G)") is
    kept for canonical_section to reject: it may be a suffix or a sub-part, and is never guessed."""
    text = re.sub(r"(\d)\s*\(\s*([A-Z])\s*\)", lambda m: f"{m.group(1)}{_AMBIGUOUS}{m.group(2)}", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(\d[A-Za-z]?)\s*\([^()]*\)", r"\1", text)
    return text


def section_labels(text: str | None, statute: str) -> tuple[list[str], list[str]]:
    """(labels, unparsed fragments) for one printed section field of ``statute`` (IPC or BNS)."""
    if statute not in STATUTES:
        raise ValueError(f"unsupported statute: {statute}")
    if not text or not text.strip():
        return [], []
    labels: list[str] = []
    unparsed: list[str] = []
    cleaned = _drop_subsections(_IGNORED.sub(" ", text))
    # Letter ranges ("171-E to 171-I", "489A to 489E") contain "to", which is not a separator inside them.
    cleaned = re.sub(r"(\d+)-?([A-Z])\s+to\s+(\d+)-?([A-Z])\b", r"\1\2~\3\4", cleaned)
    for raw in _SEPARATORS.split(cleaned):
        token = raw.strip(" .;")
        if not token:
            continue
        letter = re.fullmatch(r"(\d+)([A-Z])~(\d+)([A-Z])", token, re.IGNORECASE)
        if letter and letter.group(1) == letter.group(3) and letter.group(2).upper() <= letter.group(4).upper():
            for code in range(ord(letter.group(2).upper()), ord(letter.group(4).upper()) + 1):
                labels.append(f"{statute} {letter.group(1)}{chr(code)}")
            continue
        number_range = _NUMBER_RANGE.fullmatch(token)
        if number_range:
            first, last = int(number_range.group(1)), int(number_range.group(2))
            if first < last <= first + MAX_RANGE and last <= SECTION_RANGES[statute]:
                labels.extend(f"{statute} {number}" for number in range(first, last + 1))
            else:
                unparsed.append(token)  # e.g. a printed "447-252": not an ascending range
            continue
        candidate = re.sub(_AMBIGUOUS + r"([A-Z])", r"(\1)", token)
        section = canonical_section(candidate) if re.match(r"\d", candidate) else None
        if section is None or not 1 <= int(re.match(r"\d+", section).group(0)) <= SECTION_RANGES[statute]:
            unparsed.append(candidate)
            continue
        labels.append(f"{statute} {section}")
    return list(dict.fromkeys(labels)), unparsed


def row_labels(ipc_section: str | None, bns_section: str | None) -> tuple[list[str] | None, list[str] | None, list[str]]:
    """(IPC labels or None, BNS labels or None, unparsed 'statute: fragment' notes) for one NCRB row."""
    ipc, ipc_unparsed = section_labels(ipc_section, "IPC")
    bns, bns_unparsed = section_labels(bns_section, "BNS")
    notes = [f"IPC: {item}" for item in ipc_unparsed] + [f"BNS: {item}" for item in bns_unparsed]
    return (ipc or None), (bns or None), notes
