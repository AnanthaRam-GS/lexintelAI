"""Verified section labels for answers and briefs (step 25), applied in the response layer.

The answer model writes provisions as free text with a one-line label ("Section 309(4) BNS – offences relating to
suicide attempts."). Those labels are not checked by the citation validator, and the docs-site screenshots showed
wrong ones. This module resolves each provision the model names against LegalAI's local trusted sources and decides
what may be shown. It never invents a title, and it changes no prompt, validator or retrieval code.

**Parsing.** The existing deterministic extractor (``judgment_sections.prepare_judgment_text`` and
``query_analysis.extract_sections``) finds the statute and section. Before it, a label-only normalization handles the
model's wording: narrow and no-break spaces, "Sec." and "§" for "Section" ("§§" for "Sections"), and a statute
written before its sections ("IPC Sec. 302" -> "Sections 302 IPC"; "IPC §§420, 406" -> "Sections 420, 406 IPC"). When a provision string names exactly one statute, that statute applies to its
section (the extractor leaves "Section 113B Evidence Act" without one). The clause form ("3(1)(r)") is read back from
the string. The model's label is what remains after the section and statute references are removed.

**Trusted sources, in order of trust.**
1. The legal section catalog (``data/structured/manifests/legal_section_catalog.json``): canonical name, description,
   aliases and concepts. An exact (statute, section) entry, else the entry for the base section (``309(4)`` ->
   ``309``) when the catalog lists the base section itself.
2. The IPC-BNS mapping's CYTRAIN rows (``data/processed/ipc_bns/ipc_bns_mapping.csv``, the file
   ``load_ipc_bns.py --source cytrain`` loads): the BNS description for a BNS section, and the IPC description for an
   IPC section listed on its own (rows keyed by an IPC group label such as "415 to 420" give no IPC title). The
   mapping's NCRB rows are not used: NCRB prints crime-head names that cover several sections, not section titles.

Both sources are UNREVIEWED for legal review, so a "verified" title is only as good as they are.

**States** (``SectionLabel.state``):
- ``verified``: a trusted title exists; it replaces the model's label.
- ``corrected_statute``: the model named the wrong statute of a substantive/procedural pair (BNS/BNSS, IPC/CrPC). The
  stated statute has no trusted entry for the number, or its entry disagrees with the model's label, while the other
  statute has an entry for the same section number that agrees with it (for example "Section 173 BNS – registration
  of FIR": BNS 173 is bribery, and the catalog's BNSS 173(4) is about FIR registration). The statute is corrected and
  the reason recorded. The title is the other statute's trusted title when the catalog or mapping has one for that
  exact section; otherwise the model's label is kept and marked unverified.
- ``unverified``: no trusted title; the model's label is kept and marked unverified.
- ``conflict``: the highest-trust source with entries for the section disagrees with itself; no label is shown.

**Agreement** between a model label and a trusted entry: they share at least one content word. Stop words and generic
legal words ("section", "punishment", "offence", "relating", statute names…) are ignored; words are compared after
removing a common suffix ("-ings", "-ation", "-es"…), on their first three to five letters ("saves" and "savings",
"register" and "registration"). A label with no content words counts as no label. Agreement is used only to choose
between two trusted entries or to note a disagreeing model label, never to create a title.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from backend.app.core.config import REPO_ROOT
from backend.app.models.common import SectionLabel, SectionReference
from backend.app.services.judgment_sections import canonical_section, prepare_judgment_text
from backend.app.services.legal_section_prediction import load_section_catalog
from backend.app.services.query_analysis import extract_sections, extract_statutes

MAPPING_PATH = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_mapping.csv"
CATALOG_SOURCE = "section_catalog"
MAPPING_SOURCE = "ipc_bns_mapping"
GENERATED_CONTEXT = "generated_from_grounded_answer"

# A substantive code and its procedural companion in the same regime.
COMPANION_STATUTE = {"BNS": "BNSS", "BNSS": "BNS", "IPC": "CrPC", "CrPC": "IPC"}

_SPACES = re.compile(r"[    ]")
_SEC_ABBREVIATION = re.compile(r"\b(?:Sec|S)\.\s*(?=\d)|\bSec\s+(?=\d)", re.IGNORECASE)
# A section number with its sub-section or clause parts: "309(4)", "3(1)(r)", "36A(4)" (not a word such as "(murder)").
_NUMBER = r"\d+[A-Za-z]?(?:\s*\((?:\d+[A-Za-z]?|[A-Za-z]{1,3})\))*"
_CLAUSES = re.compile(r"(?:\s*\((?:\d+[A-Za-z]?|[A-Za-z]{1,3})\))+")
_NUMBER_LIST = rf"{_NUMBER}(?:\s*(?:,|and|&)\s*{_NUMBER})*"
_STATUTE_FIRST = re.compile(
    r"\b(IPC|BNSS|BNS|CrPC|Cr\.?\s*P\.?\s*C\.?|NDPS Act|POCSO Act|SC/ST Act)\s*,?\s+(?:[Ss]ections?\s+)?"
    rf"({_NUMBER_LIST})",
)
_SECTION_SIGN = re.compile(r"§§?\s*")
_STATUTE_WORDS = re.compile(
    r"(?:\bof\s+the\s+)?(?:\bIPC\b|\bBNSS\b|\bBNS\b|\bCrPC\b|\bCr\.?\s*P\.?\s*C\b\.?|\bIndian Penal Code(?:,\s*1860)?\b|"
    r"\bCode of Criminal Procedure(?:,\s*1973)?\b|\bBharatiya Nyaya Sanhita(?:,\s*2023)?\b|"
    r"\bBharatiya Nagarik Suraksha Sanhita(?:,\s*2023)?\b|\b(?:Indian\s+)?Evidence Act(?:,\s*1872)?\b|\bNDPS Act\b|"
    r"\bPOCSO Act\b|\bSC/ST Act\b)",
    re.IGNORECASE,
)
_SECTION_WORDS = re.compile(rf"\bSections?\s+{_NUMBER}(?:\s*(?:,|and|&|r/w|read with)\s*{_NUMBER})*", re.IGNORECASE)
_EDGE_PUNCTUATION = " \t-–—:;,.()[]\"'"

STOP_WORDS = frozenset(
    """a an and are as at be by for from in into is it its of on or that the this to under upon was were with which who
    whoever section sections sec act code provision provisions offence offences offense offenses punishment punishable
    relating related relates regarding under respect matters law laws penal criminal procedure bns bnss ipc crpc
    sanhita nyaya nagarik suraksha bharatiya indian context general specific""".split()
)


@dataclass(frozen=True)
class TrustedEntry:
    statute: str
    section: str
    title: str
    source: str
    words: frozenset[str]


@dataclass
class LabelSources:
    """Trusted titles keyed by (statute, section), each a list of entries from the highest-trust source that has them."""

    catalog: dict[tuple[str, str], list[TrustedEntry]] = field(default_factory=dict)
    mapping: dict[tuple[str, str], list[TrustedEntry]] = field(default_factory=dict)

    def entries(self, statute: str, section: str) -> list[TrustedEntry]:
        """Catalog first (exact, then the base section), then the mapping (exact, then base); never both."""
        base = canonical_section(section) or section
        for table in (self.catalog, self.mapping):
            for key in ((statute, section), (statute, base)):
                if key in table:
                    return table[key]
        return []

    def has_number(self, statute: str, section: str) -> list[TrustedEntry]:
        """Any entry of ``statute`` whose base section is the same number (including sub-section entries)."""
        base = canonical_section(section) or section
        found = []
        for table in (self.catalog, self.mapping):
            for (entry_statute, entry_section), entries in table.items():
                if entry_statute == statute and (canonical_section(entry_section) or entry_section) == base:
                    found.extend(entries)
        return found


_SUFFIXES = ("ations", "ation", "ings", "ing", "ions", "ion", "ments", "ment", "ies", "es", "ed", "s")


def stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)][:5]
    return word[:5]


def content_words(*texts: str) -> frozenset[str]:
    words = set()
    for text in texts:
        for word in re.findall(r"[a-z]+", text.replace("_", " ").casefold()):
            if len(word) > 2 and word not in STOP_WORDS:
                words.add(stem(word))
    return frozenset(words)


def words_match(a: str, b: str) -> bool:
    k = min(len(a), len(b), 5)
    return k >= 3 and a[:k] == b[:k]


def agrees(label: str | None, entries: list[TrustedEntry]) -> bool:
    if not label:
        return False
    label_words = content_words(label)
    return any(words_match(a, b) for entry in entries for a in label_words for b in entry.words)


def meaningful(label: str | None) -> str | None:
    """The label, or None when it has no content words ("…", "Criminal Procedure Code")."""
    return label if label and content_words(label) else None


def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def build_sources(catalog: list[dict] | None = None, mapping_rows: list[dict] | None = None) -> LabelSources:
    sources = LabelSources()
    for entry in catalog if catalog is not None else load_section_catalog():
        title = clean_title(entry.get("canonical_name") or "")
        if not title:
            continue
        words = content_words(title, entry.get("brief_description") or "", *(entry.get("aliases") or []),
                              *(entry.get("concepts") or []))
        key = (entry["statute"], normalize_section(entry["section"]))
        sources.catalog.setdefault(key, []).append(TrustedEntry(key[0], key[1], title, CATALOG_SOURCE, words))
    for row in mapping_rows if mapping_rows is not None else load_mapping_rows():
        bns, bns_description = (row.get("bns_section") or "").strip(), clean_title(row.get("bns_description") or "")
        # "366-B" is 366B, as load_ipc_bns.py stores it.
        ipc = re.sub(r"(?<=\d)-(?=[A-Za-z]\b)", "", (row.get("ipc_section") or "").strip())
        ipc_description = clean_title(row.get("ipc_description") or "")
        if bns and bns_description and re.fullmatch(r"\d+[A-Za-z]?(?:\([0-9A-Za-z]+\))*", bns):
            key = ("BNS", normalize_section(bns))
            words = content_words(bns_description, ipc_description)
            add_unique(sources.mapping, key, TrustedEntry("BNS", key[1], bns_description, MAPPING_SOURCE, words))
        if ipc_description and re.fullmatch(r"\d+[A-Za-z]*", ipc):
            key = ("IPC", normalize_section(ipc))
            words = content_words(ipc_description, bns_description)
            add_unique(sources.mapping, key, TrustedEntry("IPC", key[1], ipc_description, MAPPING_SOURCE, words))
    return sources


def add_unique(table: dict[tuple[str, str], list[TrustedEntry]], key: tuple[str, str], entry: TrustedEntry) -> None:
    entries = table.setdefault(key, [])
    if all(comparable(existing.title) != comparable(entry.title) for existing in entries):
        entries.append(entry)


def comparable(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def load_mapping_rows(path: Path = MAPPING_PATH) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def default_sources() -> LabelSources:
    return build_sources()


def normalize_section(section: str) -> str:
    """'309 (4)' -> '309(4)', '498a' -> '498A'; clause letters inside parentheses keep their case ('20(b)')."""
    compact = re.sub(r"\s+", "", section)
    match = re.fullmatch(r"0*(\d+)([A-Za-z]?)((?:\((?:\d+[A-Za-z]?|[A-Za-z]{1,3})\))*)", compact)
    if not match:
        return compact
    return f"{int(match.group(1))}{match.group(2).upper()}{match.group(3)}"


def normalize_provision_text(text: str) -> str:
    """Label-only normalization in front of the existing extractor (see the module docstring)."""
    text = _SPACES.sub(" ", text)
    text = _SECTION_SIGN.sub(lambda m: "Sections " if m.group(0).startswith("§§") else "Section ", text)
    text = _SEC_ABBREVIATION.sub("Section ", text)
    return _STATUTE_FIRST.sub(lambda m: f"Sections {m.group(2)} {m.group(1)}", text)


@dataclass
class ParsedProvision:
    mentions: list[tuple[str, str]]
    label: str | None


def parse_provision(text: str) -> ParsedProvision:
    normalized = normalize_provision_text(text)
    prepared = prepare_judgment_text(normalized)
    statutes = extract_statutes(prepared)
    named = {statute.canonical for statute in statutes}
    mentions: list[tuple[str, str]] = []
    for signal in extract_sections(prepared, statutes):
        statute = signal.statute or (next(iter(named)) if len(named) == 1 else None)
        if statute is None:
            continue
        section = signal.section
        tail = prepared[signal.span.end:] if signal.span else ""
        clauses = _CLAUSES.match(tail)
        if clauses:
            section += clauses.group(0)
        section = normalize_section(section)
        if (statute, section) not in mentions:
            mentions.append((statute, section))
    label = _SECTION_WORDS.sub(" ", normalized)
    label = _STATUTE_WORDS.sub(" ", label)
    label = re.sub(r"\s+", " ", label).strip(_EDGE_PUNCTUATION)
    label = re.sub(r"^\(|\)$", "", label).strip(_EDGE_PUNCTUATION)
    if label.count("(") > label.count(")"):
        label += ")"
    return ParsedProvision(mentions, label or None)


def resolve_section(statute: str, section: str, label: str | None, sources: LabelSources | None = None) -> SectionReference:
    sources = sources or default_sources()
    label = meaningful(label)
    stated = sources.entries(statute, section)
    companion = COMPANION_STATUTE.get(statute)
    if label and companion and (not stated or not agrees(label, stated)):
        other = sources.has_number(companion, section)
        if agrees(label, other):
            exact = sources.entries(companion, section)
            exact_ok = bool(exact) and len({comparable(entry.title) for entry in exact}) == 1 and agrees(label, exact)
            note = (f"The answer cited this as {statute} {section}; the section number with this subject is in the "
                    f"{companion}.")
            return SectionReference(
                statute=companion, section=section, context=GENERATED_CONTEXT,
                label=SectionLabel(
                    state="corrected_statute",
                    title=exact[0].title if exact_ok else None,
                    source=exact[0].source if exact_ok else other[0].source,
                    source_key=f"{companion} {exact[0].section if exact_ok else other[0].section}",
                    model_label=None if exact_ok else label,
                    statute_corrected_from=statute,
                    note=note,
                ),
            )
    if stated:
        if len({comparable(entry.title) for entry in stated}) > 1:
            return SectionReference(
                statute=statute, section=section, context=GENERATED_CONTEXT,
                label=SectionLabel(state="conflict", source=stated[0].source, source_key=f"{statute} {stated[0].section}",
                                   note="The trusted sources give different titles for this section, so none is shown."),
            )
        entry = stated[0]
        replaced = bool(label) and not agrees(label, stated)
        return SectionReference(
            statute=statute, section=section, context=GENERATED_CONTEXT,
            label=SectionLabel(
                state="verified", title=entry.title, source=entry.source, source_key=f"{statute} {entry.section}",
                note="The answer's own label for this section did not match the trusted title and is not shown." if replaced else None,
            ),
        )
    return SectionReference(
        statute=statute, section=section, context=GENERATED_CONTEXT,
        label=SectionLabel(state="unverified", model_label=label,
                           note="No trusted title is available for this section; the label is the answer's own."),
    )


def resolve_provision(text: str, sources: LabelSources | None = None) -> list[SectionReference]:
    """One reference per section named in a model provision string (one unverified reference when none parses)."""
    parsed = parse_provision(text)
    if not parsed.mentions:
        raw = text.strip()
        if not raw:
            return []
        return [SectionReference(
            statute="Unspecified", section=raw, context=GENERATED_CONTEXT,
            label=SectionLabel(state="unverified", model_label=raw,
                               note="No statute and section could be read from this provision; it is shown as written."),
        )]
    # A label can be attributed to a section only when the string names one section.
    label = parsed.label if len(parsed.mentions) == 1 else None
    return [resolve_section(statute, section, label, sources) for statute, section in parsed.mentions]


def display_text(reference: SectionReference) -> str:
    """The text shown for a resolved reference; a model label never appears unmarked."""
    label = reference.label
    if reference.statute == "Unspecified":
        return f"{reference.section} (unverified label)"
    head = f"Section {reference.section} {reference.statute}"
    if label is None:
        return head
    if label.state == "verified":
        return f"{head} — {label.title}"
    if label.state == "corrected_statute":
        corrected = f"statute corrected from {label.statute_corrected_from}"
        if label.title:
            return f"{head} — {label.title} ({corrected})"
        if label.model_label:
            return f"{head} — {label.model_label} ({corrected}; unverified label)"
        return f"{head} ({corrected})"
    if label.state == "conflict":
        return f"{head} (title not shown: trusted sources disagree)"
    if label.model_label:
        return f"{head} — {label.model_label} (unverified label)"
    return f"{head} (no trusted title)"


def resolve_provisions(values: list[str], sources: LabelSources | None = None) -> list[SectionReference]:
    references: list[SectionReference] = []
    for value in values:
        for reference in resolve_provision(value, sources):
            if all((existing.statute, existing.section) != (reference.statute, reference.section) for existing in references):
                references.append(reference)
    return references
