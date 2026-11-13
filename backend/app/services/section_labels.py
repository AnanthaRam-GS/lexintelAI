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
0. Official headings (step 26): the marginal notes of the Acts as published on India Code, the official legislative
   repository (``data/structured/statute_headings/<act>.csv``, sources in ``SOURCES.md`` there). An exact
   (statute, section) entry, else the base section's heading (``309(4)`` -> ``309``): a sub-section inherits its
   section's heading. Omitted or repealed sections are recorded there but never used as a title. An Act without a
   file simply has no official headings (the catalog and mapping apply as before). When an official heading is shown,
   the catalog and mapping titles for the same section are kept in ``label.other_sources`` with whether they agree.
1. The legal section catalog (``data/structured/manifests/legal_section_catalog.json``): canonical name, description,
   aliases and concepts. An exact (statute, section) entry, else the entry for the base section (``309(4)`` ->
   ``309``) when the catalog lists the base section itself.
2. The IPC-BNS mapping's CYTRAIN rows (``data/processed/ipc_bns/ipc_bns_mapping.csv``, the file
   ``load_ipc_bns.py --source cytrain`` loads): the BNS description for a BNS section, and the IPC description for an
   IPC section listed on its own (rows keyed by an IPC group label such as "415 to 420" give no IPC title). The
   mapping's NCRB rows are not used: NCRB prints crime-head names that cover several sections, not section titles.

All sources are UNREVIEWED for legal review, so a "verified" title is only as good as they are.

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
from typing import Any

from backend.app.core.config import REPO_ROOT
from backend.app.models.common import OtherSourceTitle, SectionLabel, SectionReference
from backend.app.services.judgment_sections import canonical_section, prepare_judgment_text
from backend.app.services.legal_section_prediction import load_section_catalog
from backend.app.services.query_analysis import extract_sections, extract_statutes

MAPPING_PATH = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_mapping.csv"
HEADINGS_DIR = REPO_ROOT / "data/structured/statute_headings"
OFFICIAL_SOURCE = "official_heading"
CATALOG_SOURCE = "section_catalog"
MAPPING_SOURCE = "ipc_bns_mapping"
GENERATED_CONTEXT = "generated_from_grounded_answer"

# A substantive code and its procedural companion in the same regime.
COMPANION_STATUTE = {"BNS": "BNSS", "BNSS": "BNS", "IPC": "CrPC", "CrPC": "IPC", "Evidence Act": "BSA", "BSA": "Evidence Act"}

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
# Step 26: the Bharatiya Sakshya Adhiniyam is not one of the extractor's statutes (query_analysis.py also serves
# retrieval and is not changed here), so the resolver reads "Section 63 BSA" / "BSA Section 63" itself.
_BSA = re.compile(r"\b(?:BSA|Bharatiya\s+Sakshya\s+Adhiniyam(?:,\s*2023)?)\b", re.IGNORECASE)
_BSA_SECTIONS = re.compile(rf"\b(?:Sections?|Sec\.?|S\.)\s*({_NUMBER_LIST})", re.IGNORECASE)
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

    official: dict[tuple[str, str], list[TrustedEntry]] = field(default_factory=dict)
    catalog: dict[tuple[str, str], list[TrustedEntry]] = field(default_factory=dict)
    mapping: dict[tuple[str, str], list[TrustedEntry]] = field(default_factory=dict)

    def entries(self, statute: str, section: str) -> list[TrustedEntry]:
        """Official headings first, then the catalog, then the mapping (each exact, then the base section); never mixed."""
        base = canonical_section(section) or section
        for table in (self.official, self.catalog, self.mapping):
            for key in ((statute, section), (statute, base)):
                if key in table:
                    return table[key]
        return []

    def lower_entries(self, statute: str, section: str) -> list[TrustedEntry]:
        """The catalog and mapping entries for a section (exact, then base), for review next to an official heading."""
        base = canonical_section(section) or section
        found: list[TrustedEntry] = []
        for table in (self.catalog, self.mapping):
            for key in ((statute, section), (statute, base)):
                if key in table:
                    found.extend(table[key])
                    break
        return found

    def has_number(self, statute: str, section: str) -> list[TrustedEntry]:
        """Any entry of ``statute`` whose base section is the same number (including sub-section entries)."""
        base = canonical_section(section) or section
        found = []
        for table in (self.official, self.catalog, self.mapping):
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


def build_sources(catalog: list[dict] | None = None, mapping_rows: list[dict] | None = None,
                  heading_rows: list[dict] | None = None) -> LabelSources:
    sources = LabelSources()
    for row in heading_rows if heading_rows is not None else load_heading_rows():
        heading = clean_title(row.get("heading") or "")
        if (row.get("status") or "in_force") != "in_force" or not heading:
            continue  # omitted or repealed sections are recorded in the data, never shown as a title
        key = (row["statute"], normalize_section(row["section"]))
        add_unique(sources.official, key, TrustedEntry(key[0], key[1], heading, OFFICIAL_SOURCE, content_words(heading)))
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


def load_heading_rows(directory: Path = HEADINGS_DIR) -> list[dict]:
    """Every row of every ``<act>.csv`` (columns: statute, section, heading, status); none when the folder is absent."""
    rows: list[dict] = []
    for path in sorted(directory.glob("*.csv")) if directory.is_dir() else []:
        with path.open(encoding="utf-8", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


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
    if not mentions and _BSA.search(normalized):
        for match in _BSA_SECTIONS.finditer(normalized):
            for number in re.findall(_NUMBER, match.group(1)):
                key = ("BSA", normalize_section(number))
                if key not in mentions:
                    mentions.append(key)
        normalized = _BSA.sub(" ", normalized)
    label = _SECTION_WORDS.sub(" ", normalized)
    label = _STATUTE_WORDS.sub(" ", label)
    label = re.sub(r"\s+", " ", label).strip(_EDGE_PUNCTUATION)
    label = re.sub(r"^\(|\)$", "", label).strip(_EDGE_PUNCTUATION)
    if label.count("(") > label.count(")"):
        label += ")"
    return ParsedProvision(mentions, label or None)


def label_matches_section(label: str | None, sources: LabelSources, statute: str, section: str) -> bool:
    """Step 26b rule: the label agrees with *any* trusted entry for the statute and section number.

    "Clearly does not match" is the negation: the label shares no content word (``agrees``: stop words and generic
    legal words ignored, words compared on their stem) with the official heading, nor with any catalog title,
    description, alias or concept, nor with any mapping description, of that statute's section with this number
    (sub-section entries included).
    """
    return agrees(label, sources.has_number(statute, section))


def _single_title(entries: list[TrustedEntry]) -> TrustedEntry | None:
    return entries[0] if entries and len({comparable(entry.title) for entry in entries}) == 1 else None


def resolve_section(statute: str, section: str, label: str | None, sources: LabelSources | None = None) -> SectionReference:
    """Resolve one model-named section (step 25 states; step 26/26b rules). The model's label is always kept."""
    sources = sources or default_sources()
    original = label.strip() if label and label.strip() else None
    label = meaningful(label)
    stated = sources.entries(statute, section)
    sister = COMPANION_STATUTE.get(statute)
    matches_named = bool(label) and label_matches_section(label, sources, statute, section)
    # Wrong statute: the label clearly does not match the named section, and it matches the sister statute's section.
    if label and not matches_named and sister:
        other = sources.has_number(sister, section)
        if agrees(label, other):
            exact = _single_title(sources.entries(sister, section))
            note = (f"The answer cited this as {statute} {section} (\"{original}\"); that label does not match "
                    f"{statute} {section}, and it matches {sister} {section}.")
            return SectionReference(
                statute=sister, section=section, context=GENERATED_CONTEXT,
                label=SectionLabel(
                    state="corrected_statute",
                    title=exact.title if exact else None,
                    source=exact.source if exact else other[0].source,
                    source_key=f"{sister} {exact.section if exact else other[0].section}",
                    model_label=original, statute_corrected_from=statute, note=note, correction_reason="label",
                    other_sources=other_source_titles(sources, sister, section, exact) if exact and exact.source == OFFICIAL_SOURCE else [],
                ),
            )
    if stated:
        if len({comparable(entry.title) for entry in stated}) > 1:
            return SectionReference(
                statute=statute, section=section, context=GENERATED_CONTEXT,
                label=SectionLabel(state="conflict", source=stated[0].source, source_key=f"{statute} {stated[0].section}",
                                   model_label=original,
                                   note="The trusted sources give different titles for this section, so none is shown."),
            )
        entry = stated[0]
        differs = bool(label) and not matches_named
        notes = []
        if differs:
            notes.append("The answer's own label for this section does not match its trusted title; the trusted title is shown.")
        reference_label = SectionLabel(state="verified", title=entry.title, source=entry.source,
                                       source_key=f"{statute} {entry.section}", model_label=original,
                                       model_label_differs=differs)
        # Step 26b: a catalog title for the exact sub-section is the primary title, with the section's official heading
        # alongside ("Common intention" for BNS 3(5), "General explanations" for section 3).
        sub = sources.catalog.get((statute, section)) if section != (canonical_section(section) or section) else None
        if entry.source == OFFICIAL_SOURCE and sub and _single_title(sub):
            reference_label = reference_label.model_copy(update={
                "title": sub[0].title, "source": CATALOG_SOURCE, "source_key": f"{statute} {section}",
                "section_heading": entry.title, "section_heading_source": OFFICIAL_SOURCE,
                "section_heading_key": f"{statute} {entry.section}",
            })
        elif entry.source == OFFICIAL_SOURCE:
            others = other_source_titles(sources, statute, section, entry)
            if any(not other.agrees for other in others):
                notes.append("A lower-trust source gives a different title; the official heading is shown.")
            reference_label = reference_label.model_copy(update={"other_sources": others})
        return SectionReference(statute=statute, section=section, context=GENERATED_CONTEXT,
                                label=reference_label.model_copy(update={"note": " ".join(notes) or None}))
    return SectionReference(
        statute=statute, section=section, context=GENERATED_CONTEXT,
        label=SectionLabel(state="unverified", model_label=label or original,
                           note="No trusted title is available for this section; the label is the answer's own."),
    )


def other_source_titles(sources: LabelSources, statute: str, section: str, official: TrustedEntry | None) -> list[OtherSourceTitle]:
    """Catalog and mapping titles for a section shown with its official heading, and whether each agrees with it."""
    return [OtherSourceTitle(source=entry.source, source_key=f"{statute} {entry.section}", title=entry.title,
                             agrees=agrees(entry.title, [official]) or agrees(official.title, [entry]))
            for entry in sources.lower_entries(statute, section)]


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
        if label.section_heading:
            return f"{head} — {label.title} (sub-section, catalog); {label.section_heading} (section heading, official)"
        # Step 26c: a differing answer label is kept in the data (model_label, model_label_differs), not in the display.
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


# ---------------------------------------------------------------------------
# Step 26c: document-evidence statute correction (docs/SECTION_LABELS.md, frozen before it was tested)
# ---------------------------------------------------------------------------

_FULL_NAME_THEN_ABBREVIATION = re.compile(
    r"(\b(?:Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|Bharatiya\s+Nyaya\s+Sanhita|Bharatiya\s+Sakshya\s+Adhiniyam|"
    r"Indian\s+Penal\s+Code|Code\s+of\s+Criminal\s+Procedure|Indian\s+Evidence\s+Act)(?:,?\s*\d{4})?)\s*\(\s*[A-Za-z.\s]{2,12}\)")


def document_citations(chunks: list[Any]) -> dict[tuple[str, str], str]:
    """(statute, section number) -> the first private chunk id citing it, read from the uploaded document's text."""
    found: dict[tuple[str, str], str] = {}
    for chunk in chunks:
        text = _FULL_NAME_THEN_ABBREVIATION.sub(lambda m: m.group(1), getattr(chunk, "text", "") or "")
        prepared = prepare_judgment_text(text)
        cited = [(signal.statute, signal.section) for signal in extract_sections(prepared, extract_statutes(prepared)) if signal.statute]
        if _BSA.search(text):
            for sentence in re.split(r"(?<=[.;])\s+|\n", text):
                if _BSA.search(sentence):
                    cited += [("BSA", number) for match in _BSA_SECTIONS.finditer(sentence) for number in re.findall(_NUMBER, match.group(1))]
        for statute, section in cited:
            base = canonical_section(normalize_section(section)) or normalize_section(section)
            found.setdefault((statute, base), getattr(chunk, "private_chunk_id", None) or "")
    return found


def document_evidence(reference: SectionReference, citations: dict[tuple[str, str], str],
                      sources: LabelSources | None = None) -> SectionReference:
    """The reference corrected to the sister statute when the document cites its number only there (step 26c)."""
    label = reference.label
    sister = COMPANION_STATUTE.get(reference.statute)
    if sister is None or label is None or label.state == "corrected_statute" or label.model_label_differs:
        return reference
    base = canonical_section(reference.section) or reference.section
    if (reference.statute, base) in citations or (sister, base) not in citations:
        return reference
    sources = sources or default_sources()
    exact = _single_title(sources.entries(sister, reference.section))
    evidence_id = citations[(sister, base)]
    return SectionReference(
        statute=sister, section=reference.section, context=reference.context,
        label=SectionLabel(
            state="corrected_statute", title=exact.title if exact else None,
            source=exact.source if exact else None, source_key=f"{sister} {exact.section}" if exact else None,
            model_label=label.model_label, statute_corrected_from=reference.statute,
            correction_reason="document_evidence", document_evidence_id=evidence_id,
            note=(f"The answer cited this as {reference.statute} {reference.section}; the uploaded document cites section "
                  f"{base} only under the {sister} [{evidence_id}]."),
            other_sources=other_source_titles(sources, sister, reference.section, exact) if exact and exact.source == OFFICIAL_SOURCE else [],
        ),
    )


def resolve_provisions(values: list[str], sources: LabelSources | None = None, document_chunks: list[Any] | None = None) -> list[SectionReference]:
    """Resolve the answer's provisions; with ``document_chunks`` (an uploaded document) the step 26c rule applies too."""
    citations = document_citations(document_chunks) if document_chunks else None
    references: list[SectionReference] = []
    for value in values:
        for reference in resolve_provision(value, sources):
            if citations:
                reference = document_evidence(reference, citations, sources)
            if all((existing.statute, existing.section) != (reference.statute, reference.section) for existing in references):
                references.append(reference)
    return references
