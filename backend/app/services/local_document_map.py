"""Entirely local (non-generative) private-document analysis.

Replaces the previous Stage-1 hierarchical approach (one Groq/Gemini call per
bounded chunk batch) for professional whole-document brief mode. That
approach was context-safe but provider-expensive: a real multi-page FIR or
chargesheet could need 5-10+ Stage-1 calls before the single Stage-2 call,
rapidly exhausting a rate-limited provider account's usage within one
request. This module builds the same kind of compact, structured
intermediate document map using only local, deterministic/extractive
techniques - zero provider calls - so whole-document brief mode makes
exactly the same one final provider call as every other query path,
regardless of document length.

Reused, not reinvented:
- `private_pdf_rag.build_private_chunks` / `select_query_focused_private_evidence`
  for chunking and BGE-M3-backed (or lexical-fallback) ranking.
- `ner_backend.extract_entities` for parties/dates/statutes/sections/courts:
  the deterministic NER by default; with `LEGALAI_NER_BACKEND=combined`, the
  E1 InLegalBERT NER combined with it under the frozen policy (step E3), which
  falls back to the deterministic NER if the model is unavailable.
- Parties and roles: the regular expressions below; with `combined` only, also
  the model's party entities, added under the step E4 rule
  (docs/experiments/NER_PARTY_ROLES_PLAN.md section 3; `extract_model_parties`,
  `merge_model_parties`). With `deterministic` the output is unchanged.
- `token_budget.estimate_tokens` for bounding.

Additive and outside the 5 frozen files - it only imports read-only from
`legal_ner.py`/`query_analysis.py` (neither is frozen) and from
`private_pdf_rag.py` (this project's own prior additive module).
"""

from __future__ import annotations

from datetime import date
import re
from dataclasses import dataclass, field
from typing import Any

from backend.app.services.ner_backend import configured_backend as configured_ner_backend
from backend.app.services.ner_backend import extract_entities, extract_entities_detailed
from backend.app.services.private_pdf_rag import (
    PrivateChunk,
    PrivateEvidenceItem,
    _page_range,
    select_query_focused_private_evidence,
)
from backend.app.services.token_budget import estimate_tokens

# ---------------------------------------------------------------------------
# Multi-intent retrieval (section 5): predefined internal intents, never sent
# to any external LLM - embedded locally with BGE-M3 (or lexical fallback)
# via the existing `select_query_focused_private_evidence`.
# ---------------------------------------------------------------------------

_INTENTS: tuple[tuple[str, str], ...] = (
    ("document_overview", "document identity parties case title police station court"),
    ("material_facts", "material facts incident narrative place occurrence facts"),
    ("chronology", "chronology important dates filed registered arrest order judgment"),
    ("allegations", "complainant prosecution allegations accused offence"),
    ("charges", "offences charges statutory provisions sections acts"),
    ("witness_evidence", "witness statement saw stated examined testimony"),
    ("documentary_evidence", "documents records certificates reports mahazar panchnama"),
    ("electronic_evidence", "electronic evidence CCTV phone call data video digital"),
    ("medical_forensic_evidence", "medical forensic postmortem injury FSL DNA expert"),
    ("recovery_seizure_evidence", "recovery seizure weapon recovered seized articles"),
    ("investigation_steps", "investigation police steps arrest search seizure statement"),
    ("procedural_history", "procedural history trial appeal petition order filed"),
    ("accused_or_defence_position", "defence accused denied alibi counter submission"),
    ("arguments_or_contentions", "arguments submissions contentions grounds prayer"),
    ("court_findings", "court findings reasoning held considered satisfied"),
    ("relief_or_final_order", "relief final order disposed allowed dismissed sentence bail"),
)
_ALLOCATABLE_FIELDS = tuple(name for name, _ in _INTENTS if name != "parties_intent")
_CANDIDATES_PER_INTENT = 3

_STATUTE_ABBREVIATIONS = (
    "IPC",
    "CrPC",
    "BNS",
    "BNSS",
    "POCSO",
    "Indian Evidence Act",
    "Bharatiya Sakshya Adhiniyam",
    "Evidence Act",
)
_STATUTE_SUFFIX_PATTERN = re.compile(
    r"^\s*(?:,|read\s+with|r/w|/)?\s*(" + "|".join(re.escape(s) for s in _STATUTE_ABBREVIATIONS) + r")\b",
    re.IGNORECASE,
)

_MAX_ENTRIES_PER_FIELD = 6
_MAX_EXCERPT_CHARS = 500
_MAX_PARTIES = 10
_MAX_DATES = 10
_MAX_SECTIONS = 15
_MAX_PROCEDURAL_ITEMS = 12
_MAX_EVIDENCE_ITEMS = 12
_MAX_SENTENCE_CHARS = 220
_EVENT_WINDOW_BEFORE = 80
_EVENT_WINDOW_AFTER = 40


@dataclass(frozen=True)
class MapExcerpt:
    private_evidence_id: str
    pages: str
    excerpt: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class PartyRole:
    role: str
    name: str | None = None
    private_evidence_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class ChronologyEntry:
    date: str
    event: str | None = None
    context: str | None = None
    private_evidence_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class ProceduralStage:
    """A sentence that states a procedural step (FIR, arrest, bail, charge sheet, trial, appeal ...)."""

    stages: tuple[str, ...]
    text: str
    private_evidence_id: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class EvidenceItem:
    """A sentence that names evidence, with its categories (witnesses, documents ...)."""

    categories: tuple[str, ...]
    text: str
    private_evidence_id: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class LocalDocumentMap:
    """Compact, request-local, bounded structured summary of an uploaded
    private document, built entirely without any provider call. Statutory
    sections here are sections *explicitly mentioned in the document* -
    never asserted as verified applicable law; that determination remains
    the trusted corpus's job."""

    document_type: str
    document_type_confidence: float = 0.0
    parties: list[str] = field(default_factory=list)
    parties_and_roles: list[PartyRole] = field(default_factory=list)
    important_dates: list[str] = field(default_factory=list)
    chronology: list[ChronologyEntry] = field(default_factory=list)
    procedural_stages: list[ProceduralStage] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    explicit_statutes: list[str] = field(default_factory=list)
    explicit_sections: list[str] = field(default_factory=list)
    document_overview: list[MapExcerpt] = field(default_factory=list)
    material_facts: list[MapExcerpt] = field(default_factory=list)
    allegations: list[MapExcerpt] = field(default_factory=list)
    complainant_or_prosecution_position: list[MapExcerpt] = field(default_factory=list)
    accused_or_defence_position: list[MapExcerpt] = field(default_factory=list)
    defence_or_accused_position: list[MapExcerpt] = field(default_factory=list)
    charges: list[MapExcerpt] = field(default_factory=list)
    evidence_excerpts: list[MapExcerpt] = field(default_factory=list)
    witness_excerpts: list[MapExcerpt] = field(default_factory=list)
    witness_evidence: list[MapExcerpt] = field(default_factory=list)
    documentary_evidence: list[MapExcerpt] = field(default_factory=list)
    electronic_evidence: list[MapExcerpt] = field(default_factory=list)
    medical_forensic_excerpts: list[MapExcerpt] = field(default_factory=list)
    medical_forensic_evidence: list[MapExcerpt] = field(default_factory=list)
    recovery_seizure_evidence: list[MapExcerpt] = field(default_factory=list)
    investigation_excerpts: list[MapExcerpt] = field(default_factory=list)
    investigation_steps: list[MapExcerpt] = field(default_factory=list)
    procedural_history: list[MapExcerpt] = field(default_factory=list)
    arguments_or_contentions: list[MapExcerpt] = field(default_factory=list)
    findings_or_orders: list[MapExcerpt] = field(default_factory=list)
    court_findings: list[MapExcerpt] = field(default_factory=list)
    court_reasoning: list[MapExcerpt] = field(default_factory=list)
    relief_or_final_order: list[MapExcerpt] = field(default_factory=list)
    missing_or_unclear_information: list[str] = field(default_factory=list)
    important_chunk_ids: list[str] = field(default_factory=list)
    important_pages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Document type heuristic (section 9) - filename/text patterns only.
# ---------------------------------------------------------------------------


def detect_document_type_with_confidence(filename: str, chunks: list[PrivateChunk]) -> tuple[str, float]:
    early_text = " ".join(chunk.text for chunk in chunks[:2]).lower()
    all_text = " ".join(chunk.text for chunk in chunks[:5]).lower()
    filename_l = re.sub(r"[_\-.]+", " ", filename.lower())
    scores = {
        "judgment": 0,
        "order": 0,
        "FIR": 0,
        "chargesheet": 0,
        "petition": 0,
    }
    if re.search(r"supreme court of india", early_text):
        scores["judgment"] += 4
    # A High Court or trial-court header also heads petitions and police reports
    # filed before that court, so it is weaker evidence of a judgment on its own.
    if re.search(r"(high court of|in the court of)", early_text):
        scores["judgment"] += 2
    if re.search(r"\b(coram|judge)\b|\bj\s*\.(?=\s|\]|$)", early_text):
        scores["judgment"] += 2
    if re.search(r"\b(judg(e)?ment|criminal appeal|civil appeal|appellant\s+v(?:s\.?|\.))\b", early_text):
        scores["judgment"] += 3
    if re.search(r"\b(order|ordered accordingly|disposed of)\b", early_text):
        scores["order"] += 3
    # Charge sheets and petitions cite the FIR they arise from ("FIR No. ..."), so a
    # bare FIR number is weaker FIR evidence when such a header is present.
    report_or_petition_header = re.search(
        r"\b(charge\s*sheet|chargesheet|final report|police report|petition under|petition for)\b", early_text + " " + filename_l
    )
    if "first information report" in early_text:
        scores["FIR"] += 4
    elif re.search(r"\bf\.?i\.?r\.?\s*(no|number)\b", early_text):
        scores["FIR"] += 2 if report_or_petition_header else 4
    if re.search(r"\b(police station|informant|complainant|date of occurrence)\b", early_text):
        scores["FIR"] += 2
    if re.search(r"\bfir\s+no\b", all_text) and scores["judgment"] == 0:
        scores["FIR"] += 1
    if re.search(r"\b(charge\s*sheet|chargesheet|final report|police report)\b", early_text + " " + filename_l):
        scores["chargesheet"] += 4
    if re.search(r"\b(list of witnesses|accused list|section 173\(?(?:2)?\)?\s*cr\.?p\.?c)\b", all_text):
        scores["chargesheet"] += 2
    if re.search(r"\b(writ petition|petition under|petitioner|respondent|prayer|relief sought)\b", early_text + " " + filename_l):
        scores["petition"] += 3
    if re.search(r"\b(most respectfully|showeth|humbly prayed|it is (?:therefore )?(?:most respectfully )?prayed)\b", all_text):
        scores["petition"] += 2
    if re.search(r"\bpetition (?:under|for quashing)\b", early_text):
        scores["petition"] += 2
    doc_type, score = max(scores.items(), key=lambda item: item[1])
    if score < 3:
        return "unknown", 0.0
    confidence = min(0.95, 0.45 + (score * 0.1))
    return doc_type, round(confidence, 2)


def detect_document_type(filename: str, chunks: list[PrivateChunk]) -> str:
    return detect_document_type_with_confidence(filename, chunks)[0]


# ---------------------------------------------------------------------------
# Deterministic entity/section extraction (sections 7, 8) - reuses the
# existing deterministic NER, never InLegalBERT, never an LLM.
# ---------------------------------------------------------------------------


def _statute_suffix_after(text: str, end: int) -> str | None:
    window = text[end : end + 40]
    match = _STATUTE_SUFFIX_PATTERN.match(window)
    return match.group(1) if match else None


_SECTION_PATTERN = re.compile(
    r"\b(?:u/s|under\s+section|sections?|sec\.?)\s+"
    r"([0-9A-Za-z()/-]+(?:\s*(?:,|and|/|read\s+with|r/w)\s*[0-9A-Za-z()/-]+)*)"
    r"\s*(IPC|I\.P\.C\.|CrPC|Cr\.P\.C\.|BNS|BNSS|POCSO|Evidence Act|Indian Evidence Act|BSA|Bharatiya Sakshya Adhiniyam)?",
    re.IGNORECASE,
)
_STATUTE_PATTERN = re.compile(
    r"\b(IPC|I\.P\.C\.|CrPC|Cr\.P\.C\.|BNS|BNSS|POCSO|Evidence Act|Indian Evidence Act|BSA|Bharatiya Sakshya Adhiniyam)\b",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)
_NAME = r"([A-Z][A-Za-z0-9 .,&@'-]{2,80})"
_PARTY_NUMBER = r"(?:\s+no\.?\s*\d+)?"
_PARTY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (role, re.compile(rf"\b{role}(?:s)?{_PARTY_NUMBER}[ \t]*[:\-][ \t]*{_NAME}", re.IGNORECASE))
    for role in ("appellant", "respondent", "petitioner", "applicant", "accused", "complainant", "informant")
)
_VERSUS_PATTERN = re.compile(r"([A-Z][A-Za-z0-9 .,&@'-]{2,80})[ \t]+[vV](?:[sS]\.?|\.)?[ \t]+([A-Z][A-Za-z0-9 .,&@'-]{2,80})")
_GENERIC_PARTY_NAMES = {"accused", "complainant", "informant", "petitioner", "respondent", "appellant", "applicant", "state"}
# Text after a name that describes the person rather than naming them.
_NAME_END = re.compile(
    r"\s{2,}|\n|,|\(|\.\s|\s+(?:aged|age|resident|r/o|s/o|d/o|w/o|son of|daughter of|wife of|through)\b"
    r"|,?\s+(?:appellant|respondent|petitioner|applicant|accused)\b",
    re.IGNORECASE,
)
_LEFT_PARTY_ROLES = ("appellant", "petitioner", "applicant")


def _versus_left_role(text: str) -> str:
    """Role of the first party in "X vs Y": the document's own most frequent label, if any."""
    counts = {role: len(re.findall(rf"\b{role}s?\b", text, re.IGNORECASE)) for role in _LEFT_PARTY_ROLES}
    role, count = max(counts.items(), key=lambda item: item[1])
    return role if count else "petitioner/appellant"


def _clean_party_name(value: str) -> str | None:
    name = _NAME_END.split(value.strip(), maxsplit=1)[0]
    name = re.sub(r"\s+", " ", name).strip(" .:-")
    if not name or name.lower() in _GENERIC_PARTY_NAMES or len(name) < 3:
        return None
    return name[:120]


def _event_for_context(context: str) -> str | None:
    lower = context.lower()
    cues = (
        ("arrest", ("arrest", "arrested")),
        ("bail", ("bail",)),
        ("FIR registered", ("fir", "registered")),
        ("incident occurred", ("incident", "occurred")),
        ("incident occurred", ("occurrence",)),
        ("charge sheet filed", ("charge sheet", "chargesheet", "final report")),
        ("petition filed", ("petition", "filed")),
        ("order pronounced", ("order", "pronounced")),
        ("judgment delivered", ("judgment", "delivered")),
        ("medical examination", ("medical", "examination")),
        ("recovery/seizure", ("recovered", "seized", "recovery", "seizure")),
    )
    for label, terms in cues:
        if any(re.search(rf"\b{re.escape(term)}\b", lower) for term in terms):
            return label
    return None


def extract_sections_and_entities(chunks: list[PrivateChunk], ner_results: list[Any] | None = None) -> tuple[list[str], list[str], list[str]]:
    """Returns (explicit_sections, parties, important_dates), each deduped
    and capped, extracted via `ner_backend.extract_entities` (the deterministic
    NER by default; no provider call). ``ner_results`` (one per chunk) reuses
    entities already extracted for the chunks instead of extracting them again."""
    sections: list[str] = []
    parties: list[str] = []
    dates: list[str] = []
    seen_sections: set[str] = set()
    seen_parties: set[str] = set()
    seen_dates: set[str] = set()

    for index, chunk in enumerate(chunks):
        for match in _SECTION_PATTERN.finditer(chunk.text):
            statute = match.group(2)
            label = f"Section {match.group(1).strip()} {statute or ''}".strip()
            key = re.sub(r"\s+", " ", label.lower())
            if key not in seen_sections and len(sections) < _MAX_SECTIONS:
                seen_sections.add(key)
                sections.append(label)
        for match in _STATUTE_PATTERN.finditer(chunk.text):
            key = match.group(1).lower().replace(".", "")
            if key not in seen_sections and len(sections) < _MAX_SECTIONS:
                seen_sections.add(key)
                sections.append(match.group(1))
        result = extract_entities(chunk.text) if ner_results is None else ner_results[index]
        for entity in result.entities:
            if entity.entity_type == "SECTION":
                suffix = _statute_suffix_after(chunk.text, entity.end_char)
                label = f"{entity.text} {suffix}".strip() if suffix else entity.text
                key = label.lower()
                if key not in seen_sections and len(sections) < _MAX_SECTIONS:
                    seen_sections.add(key)
                    sections.append(label)
            elif entity.entity_type == "STATUTE":
                key = entity.normalized_text.lower()
                if key not in seen_sections and len(sections) < _MAX_SECTIONS:
                    seen_sections.add(key)
                    sections.append(entity.text)
            elif entity.entity_type in {"PERSON", "LEGAL_ROLE", "ORGANIZATION"}:
                key = entity.normalized_text.lower()
                if key not in seen_parties and len(parties) < _MAX_PARTIES:
                    seen_parties.add(key)
                    parties.append(entity.text)
            elif entity.entity_type == "DATE":
                key = entity.normalized_text.lower()
                if key not in seen_dates and len(dates) < _MAX_DATES:
                    seen_dates.add(key)
                    dates.append(entity.text)

    return sections, parties, dates


def extract_parties_and_roles(chunks: list[PrivateChunk]) -> list[PartyRole]:
    parties: list[PartyRole] = []
    seen: set[tuple[str, str | None]] = set()
    left_role = _versus_left_role(" ".join(chunk.text for chunk in chunks))
    for chunk in chunks:
        head = chunk.text[:1200]
        for left, right in _VERSUS_PATTERN.findall(head):
            pairs = ((left_role, _clean_party_name(left)), ("respondent", _clean_party_name(right)))
            for role, name in pairs:
                key = (role, (name or "").lower())
                if name and key not in seen and len(parties) < _MAX_PARTIES:
                    seen.add(key)
                    parties.append(PartyRole(role=role, name=name, private_evidence_id=chunk.private_chunk_id, page_start=chunk.page_start, page_end=chunk.page_end))
        for role, pattern in _PARTY_PATTERNS:
            for match in pattern.finditer(head):
                name = _clean_party_name(match.group(1))
                key = (role, (name or "").lower())
                if name and key not in seen and len(parties) < _MAX_PARTIES:
                    seen.add(key)
                    parties.append(PartyRole(role=role, name=name, private_evidence_id=chunk.private_chunk_id, page_start=chunk.page_start, page_end=chunk.page_end))
    return parties


# ---------------------------------------------------------------------------
# Step E4: parties from the model, with LEGALAI_NER_BACKEND=combined only
# (docs/experiments/NER_PARTY_ROLES_PLAN.md section 3, frozen before measuring)
# ---------------------------------------------------------------------------

# InLegalNER types that are parties by themselves, and types that become parties only with a role cue.
_MODEL_PARTY_TYPES = {"PETITIONER", "RESPONDENT"}
_MODEL_CUE_TYPES = {"OTHER_PERSON", "ORG"}
_PETITIONER_SIDE = {"petitioner", "appellant", "applicant", "complainant", "informant"}
_RESPONDENT_SIDE = {"respondent", "accused"}
_ROLE_WORD = r"(co-accused|appellant|respondent|petitioner|applicant|accused|complainant|informant)s?"
_CUE_NUMBER = r"(?:\s*nos?\.?\s*\d+(?:\s*(?:,|and|&)\s*\d+)*)?"
_CUE_FILLER = r"(?:\s*(?:(?:namely|viz|i\.e|the|is|was|being|shri|smt|sri|mr|mrs|ms|dr|m/s)\b\.?|[:,(\-\u2013\u2014]))*"
_CUE_BEFORE = re.compile(rf"\b{_ROLE_WORD}{_CUE_NUMBER}{_CUE_FILLER}\s*$", re.IGNORECASE)
_CUE_AFTER = re.compile(rf"^[\s.,(\-\u2013\u2014\u2026]*(?:the\s+)?{_ROLE_WORD}\b", re.IGNORECASE)
_LIST_GAP = re.compile(r"^\s*(?:,|,?\s*and|,?\s*&)\s*$", re.IGNORECASE)
_CUE_WINDOW = 80
_NAME_STRIP = " \t\n.,;:()[]{}-\u2013\u2014"


def _cue_role(word: str) -> str:
    """The role named by a cue word (the pattern keeps a plural "s" outside the group)."""
    word = word.lower()
    return "accused" if word == "co-accused" else word


def _role_cue(text: str, start: int, end: int, chain: tuple[int, str] | None) -> tuple[str | None, str | None]:
    """(role, how) from the text around an entity: "before", "list" or "after"; (None, None) without a cue."""
    line_start = text.rfind("\n", 0, start) + 1
    before = _CUE_BEFORE.search(text[max(line_start, start - _CUE_WINDOW):start])
    if before:
        return _cue_role(before.group(1)), "before"
    if chain is not None and chain[0] <= start and _LIST_GAP.match(text[chain[0]:start]):
        return chain[1], "list"
    after = _CUE_AFTER.match(text[end:end + _CUE_WINDOW])
    if after:
        return _cue_role(after.group(1)), "after"
    return None, None


def _model_party_name(value: str) -> str | None:
    name = re.sub(r"\s+", " ", value).strip(_NAME_STRIP)
    if not name or name.lower() in _GENERIC_PARTY_NAMES or len(name) < 3:
        return None
    return name[:120]


# Step E4b (docs/experiments/NER_PARTY_ROLES_E4B_PLAN.md section 3, frozen before this code).
_WORD_JOINERS = "-'\u2019"
_ACCUSED_DOCUMENT_TYPES = {"FIR", "chargesheet"}
_ACCUSED_NUMBER = r"(?:\bA\s?-?\s?\d+|\baccused\s+(?:no\.?\s*)?\d+)"
_ACCUSED_PREFIX = re.compile(
    rf"{_ACCUSED_NUMBER}(?:\s*(?:[:\-.),]|(?:shri|smt|sri|mr|mrs|ms|dr|m/s)\b\.?))*\s*$", re.IGNORECASE)
_ACCUSED_HEADING = re.compile(r"\baccused\b.*:\s*$", re.IGNORECASE)
_LIST_MARKER = re.compile(rf"^\s*(?:\(?[ivxlc]+\)|\(?\d+[.)]|[-\u2022*]|{_ACCUSED_NUMBER}[.):\-]?)(?=\s)", re.IGNORECASE)


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    """A span trimmed of edge whitespace/punctuation, then widened to whole words (E4b fix 1).

    It widens across letters and digits, and across an apostrophe or hyphen that has a word character on its far side.
    """
    while start < end and not _is_word_char(text[start]):
        start += 1
    while end > start and not _is_word_char(text[end - 1]):
        end -= 1
    if start == end:
        return start, end
    while start > 0 and (_is_word_char(text[start - 1])
                         or (text[start - 1] in _WORD_JOINERS and start >= 2 and _is_word_char(text[start - 2]))):
        start -= 1
    while end < len(text) and (_is_word_char(text[end])
                               or (text[end] in _WORD_JOINERS and end + 1 < len(text) and _is_word_char(text[end + 1]))):
        end += 1
    return start, end


def accused_list_lines(text: str) -> list[tuple[int, int]]:
    """(start, end) of the list lines under an accused heading ("Details of known accused:") (E4b fix 2)."""
    lines, offset = [], 0
    for line in text.splitlines(keepends=True):
        lines.append((offset, offset + len(line), line))
        offset += len(line)
    spans: list[tuple[int, int]] = []
    in_list = False
    for start, end, line in lines:
        if in_list and _LIST_MARKER.match(line):
            spans.append((start, end))
            continue
        in_list = bool(_ACCUSED_HEADING.search(line.rstrip("\r\n")))
    return spans


def _accused_prefix(text: str, start: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    return bool(_ACCUSED_PREFIX.search(text[max(line_start, start - _CUE_WINDOW):start]))


def extract_model_parties(chunks: list[PrivateChunk], model_entities: list[list[Any]], left_role: str,
                          document_type: str | None = None) -> list[PartyRole]:
    """Parties from the model's entities (one list per chunk, offsets in ``chunk.text``), in document order.

    PETITIONER/RESPONDENT entities are parties; OTHER_PERSON/ORG entities only with a role cue; other types never.
    A party-type entity takes the cue's role when the cue is on its side, else PETITIONER -> ``left_role`` and
    RESPONDENT -> "respondent". Each party cites the chunk it was found in.

    E4b: each candidate's span is snapped to whole words; in FIRs and charge sheets (``document_type``), an accused
    number before the entity ("A-1", "Accused No. 2") or the first candidate on a list line under an accused heading
    takes the role accused, before every other role rule.
    """
    parties: list[PartyRole] = []
    accused_documents = document_type in _ACCUSED_DOCUMENT_TYPES
    for chunk, entities in zip(chunks, model_entities):
        chain: tuple[int, str] | None = None  # (end, role) of the last candidate whose role came from a cue before it
        list_lines = accused_list_lines(chunk.text) if accused_documents else []
        lines_taken: set[int] = set()
        for entity in sorted(entities, key=lambda item: (item.start_char, item.end_char)):
            native = str((entity.metadata or {}).get("native_type", ""))
            if native not in _MODEL_PARTY_TYPES | _MODEL_CUE_TYPES:
                continue
            start, end = snap_to_words(chunk.text, entity.start_char, entity.end_char)
            if start == end:
                continue
            role, how = None, None
            if accused_documents:
                line = next((i for i, (a, b) in enumerate(list_lines) if a <= start < b), None)
                in_list = line is not None and line not in lines_taken
                if line is not None:
                    lines_taken.add(line)
                if _accused_prefix(chunk.text, start) or in_list:
                    role, how = "accused", "before"
            if role is None:
                role, how = _role_cue(chunk.text, start, end, chain)
                if native in _MODEL_PARTY_TYPES:
                    side = _PETITIONER_SIDE if native == "PETITIONER" else _RESPONDENT_SIDE
                    if role not in side:
                        role, how = (left_role if native == "PETITIONER" else "respondent"), None
            if role is None:
                continue
            chain = (end, role) if how in {"before", "list"} else chain
            name = _model_party_name(chunk.text[start:end])
            if name:
                parties.append(PartyRole(role=role, name=name, private_evidence_id=chunk.private_chunk_id,
                                         page_start=chunk.page_start, page_end=chunk.page_end))
    return parties


def _person_key(name: str) -> str:
    text = re.sub(r"\b(?:alias|urf|aka)\b", " @ ", name.casefold())
    text = re.sub(r"^(?:(?:the|shri|smt|sri|mr|mrs|ms|dr|m/s)\b\.?\s*)+", "", text.strip())
    text = re.sub(r"[^\w@\s]", " ", text).replace("@", " @ ")
    return " ".join(text.split())


def _same_person(left: str, right: str) -> bool:
    """Equal normalized names, a shared alias part, or one name's words a contiguous run of the other's."""
    a, b = _person_key(left), _person_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if {part.strip() for part in a.split("@") if part.strip()} & {part.strip() for part in b.split("@") if part.strip()}:
        return True
    ta, tb = [t for t in a.split() if t != "@"], [t for t in b.split() if t != "@"]
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return bool(short) and any(long[i:i + len(short)] == short for i in range(len(long) - len(short) + 1))


def merge_model_parties(regex_parties: list[PartyRole], model_parties: list[PartyRole]) -> list[PartyRole]:
    """Regex parties first and unchanged; then model parties in order, skipping the same person (any role); cap 10."""
    merged = list(regex_parties)
    for party in model_parties:
        if len(merged) >= _MAX_PARTIES:
            break
        if any(existing.name and party.name and _same_person(existing.name, party.name) for existing in merged):
            continue
        merged.append(party)
    return merged


def extract_chronology(chunks: list[PrivateChunk]) -> list[ChronologyEntry]:
    """One entry per date mention, with the sentence it appears in and the event that sentence names."""
    entries: list[ChronologyEntry] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        for sentence in _sentences(chunk):
            for match in _DATE_PATTERN.finditer(sentence):
                # The clause around the date names its event ("judgment dated 30.10.2013 passed by");
                # a long sentence can carry several dates with different events.
                window = sentence[max(0, match.start() - _EVENT_WINDOW_BEFORE): match.end() + _EVENT_WINDOW_AFTER]
                event = _event_for_context(window) or _event_for_context(sentence)
                key = (match.group(0).lower(), (event or sentence[:60]).lower())
                if key in seen or len(entries) >= _MAX_DATES:
                    continue
                seen.add(key)
                entries.append(
                    ChronologyEntry(
                        date=match.group(0),
                        event=event,
                        context=_bounded_sentence(sentence),
                        private_evidence_id=chunk.private_chunk_id,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                    )
                )
    return entries


_MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
)}


def parse_date_iso(value: str) -> str | None:
    """ISO date for a date string matched by _DATE_PATTERN (Indian day-first order), or None."""
    text = value.strip().lower().replace(",", " ")
    numeric = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    try:
        if numeric:
            day, month, year = (int(part) for part in numeric.groups())
            year += 2000 if year < 100 else 0
            return date(year, month, day).isoformat()
        parts = text.split()
        if len(parts) == 3 and parts[0].isdigit():  # 12 March 2024
            return date(int(parts[2]), _MONTHS[parts[1][:3]], int(parts[0])).isoformat()
        if len(parts) == 3 and parts[1].isdigit():  # March 12 2024
            return date(int(parts[2]), _MONTHS[parts[0][:3]], int(parts[1])).isoformat()
    except (KeyError, ValueError):
        return None
    return None


_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])[ \t]+(?=[A-Z0-9(])|\n+")
_LINE_WRAP = re.compile(r"(?<![.:;?!)\n])\n(?!\n)")
_ABBREVIATION = re.compile(r"\b(No|Nos|Mr|Mrs|Ms|Dr|Sr|Smt|Shri|Rs|vs|Cr|Ltd|Co|S|P|C|I|J)\.[ \t]+", re.IGNORECASE)
_KEEP_SPACE = "\x00"


def _bounded_sentence(sentence: str) -> str:
    return sentence if len(sentence) <= _MAX_SENTENCE_CHARS else sentence[:_MAX_SENTENCE_CHARS].rsplit(" ", 1)[0] + "..."


def _sentences(chunk: PrivateChunk) -> list[str]:
    """Full sentences of a chunk, with PDF line wraps joined and abbreviations kept inside a sentence."""
    return _split_sentences(chunk.text)


def _split_sentences(raw_text: str) -> list[str]:
    text = _ABBREVIATION.sub(lambda match: f"{match.group(1)}.{_KEEP_SPACE}", _LINE_WRAP.sub(" ", raw_text))
    sentences = []
    for raw in _SENTENCE_SPLIT.split(text):
        sentence = re.sub(r"\s+", " ", raw.replace(_KEEP_SPACE, " ")).strip()
        if len(sentence) >= 12:
            sentences.append(sentence)
    return sentences


# Procedural steps, by cue. One sentence may state several (labels in this order).
PROCEDURAL_STAGE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("FIR registration", r"\b(?:FIR|first information report)\b[^.]{0,120}?\b(?:was|is|has been)\s+(?:registered|lodged|recorded)\b"
                             r"|\b(?:registered|lodged)\b[^.]{0,40}?\b(?:an?|the)?\s*(?:FIR|first information report)\b"),
        ("arrest", r"\barrest(?:ed)?\b"),
        ("investigation", r"\binvestigat(?:ion|ing officer|ed)\b"),
        ("bail", r"\bbail\b"),
        ("charge sheet filing", r"\b(?:charge[- ]?sheet|final report)\b[^.]{0,80}?\b(?:is|was|has been)?\s*(?:filed|submitted|laid)\b"
                                r"|\b(?:filed|submitted)\b[^.]{0,40}?\b(?:charge[- ]?sheet|final report)\b"),
        ("framing of charges", r"\bcharges?\s+(?:were|was|is|are|have been|has been)\s+framed\b|\bframing of charges?\b"),
        ("trial", r"\b(?:trial|sessions case)\b|\bconvicted\b"),
        ("appeal", r"\bappeal\b"),
        ("revision", r"\brevision\b"),
        ("petition/quashing", r"\b(?:petition|quash(?:ing)?)\b"),
    )
)

# Evidence categories, by cue. One sentence may name several kinds of evidence.
EVIDENCE_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("witnesses", r"\b(?:eye[- ]?witness(?:es)?|witness(?:es)?|PW[- ]?\d+|LW[- ]?\d+)\b"),
        ("documents", r"\b(?:documents|documentary|agreement|bank (?:account )?statements?|certificate|panchnama|mahazar|seizure memo|annexure|receipt)\b"),
        ("medical_forensic", r"\b(?:post[- ]?mortem|medical (?:examination|report|certificate|evidence)|MLC|forensic|FSL|DNA|injury report)\b"),
        ("electronic", r"\b(?:CCTV|call detail records?|CDR|electronic (?:record|evidence)|video|WhatsApp|e-?mail|SMS|section 65B)\b"),
        ("recoveries", r"\b(?:recover(?:y|ed|ies)|seiz(?:ed|ure)|weapon)\b"),
    )
)
EVIDENCE_CATEGORY_LABELS = {
    "witnesses": "Witnesses",
    "documents": "Documents",
    "medical_forensic": "Medical/forensic",
    "electronic": "Electronic",
    "recoveries": "Recoveries/seizures",
}


def extract_procedural_stages(chunks: list[PrivateChunk]) -> list[ProceduralStage]:
    """Sentences stating a procedural step, in document order (cue-based, no model)."""
    items: list[ProceduralStage] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in _sentences(chunk):
            stages = tuple(label for label, pattern in PROCEDURAL_STAGE_RULES if pattern.search(sentence))
            key = sentence.lower()
            if stages and key not in seen and len(items) < _MAX_PROCEDURAL_ITEMS:
                seen.add(key)
                items.append(ProceduralStage(stages, _bounded_sentence(sentence), chunk.private_chunk_id, chunk.page_start, chunk.page_end))
    return items


def extract_evidence_items(chunks: list[PrivateChunk]) -> list[EvidenceItem]:
    """Sentences naming evidence, with their categories, in document order (cue-based, no model)."""
    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in _sentences(chunk):
            categories = tuple(label for label, pattern in EVIDENCE_CATEGORY_RULES if pattern.search(sentence))
            key = sentence.lower()
            if categories and key not in seen and len(items) < _MAX_EVIDENCE_ITEMS:
                seen.add(key)
                items.append(EvidenceItem(categories, _bounded_sentence(sentence), chunk.private_chunk_id, chunk.page_start, chunk.page_end))
    return items


# ---------------------------------------------------------------------------
# Multi-intent private retrieval + deduplication (sections 5, 6).
# ---------------------------------------------------------------------------


def _bounded_excerpt(text: str) -> str:
    if len(text) <= _MAX_EXCERPT_CHARS:
        return text
    return text[:_MAX_EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."


def select_multi_intent_evidence(
    chunks: list[PrivateChunk],
    *,
    dense_provider: Any,
    token_budget_tokens: int,
) -> dict[str, list[MapExcerpt]]:
    """Rank private chunks against each predefined intent (locally, via BGE-M3
    or lexical fallback - never an external LLM), then merge across intents
    under **one global token budget**: a chunk already claimed by an earlier
    intent is never claimed again by a later one, and inclusion stops for
    every remaining intent once the shared budget is spent. Broad document
    coverage is preferred over exhausting the budget on one intent."""
    by_field: dict[str, list[MapExcerpt]] = {name: [] for name in _ALLOCATABLE_FIELDS}
    candidates_by_field: dict[str, list[PrivateEvidenceItem]] = {}
    claimed_indexes: set[int] = set()
    used_tokens = 0

    for field_name, intent_text in _INTENTS:
        candidates_by_field[field_name] = select_query_focused_private_evidence(
            chunks,
            intent_text,
            dense_provider=dense_provider,
            top_k=_CANDIDATES_PER_INTENT,
            token_budget_tokens=token_budget_tokens,
        )

    def claim(field_name: str, item: PrivateEvidenceItem) -> bool:
        nonlocal used_tokens
        if item.chunk.chunk_index in claimed_indexes:
            return False
        if len(by_field[field_name]) >= _MAX_ENTRIES_PER_FIELD:
            return False
        if used_tokens + item.chunk.token_count > token_budget_tokens:
            return False
        claimed_indexes.add(item.chunk.chunk_index)
        by_field[field_name].append(
            MapExcerpt(
                private_evidence_id=item.chunk.private_chunk_id,
                pages=_page_range(item.chunk),
                excerpt=_bounded_excerpt(item.chunk.text),
                page_start=item.chunk.page_start,
                page_end=item.chunk.page_end,
            )
        )
        used_tokens += item.chunk.token_count
        return True

    # Pass 1: fair coverage. Each intent may claim at most one strong unique chunk.
    for field_name, _ in _INTENTS:
        if used_tokens >= token_budget_tokens:
            break
        for item in candidates_by_field.get(field_name, []):
            if claim(field_name, item):
                break

    # Pass 2: spend remaining budget on next-best useful chunks across intents.
    for rank in range(1, _CANDIDATES_PER_INTENT):
        if used_tokens >= token_budget_tokens:
            break
        for field_name, _ in _INTENTS:
            candidates = candidates_by_field.get(field_name, [])
            if rank < len(candidates):
                claim(field_name, candidates[rank])

    # Pass 3: deterministic ordering after global deduplication and budget trim.
    for entries in by_field.values():
        entries.sort(key=lambda entry: int(entry.private_evidence_id[1:]) if entry.private_evidence_id[1:].isdigit() else 0)
    return by_field


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_local_document_map(
    chunks: list[PrivateChunk],
    *,
    filename: str,
    dense_provider: Any,
    token_budget_tokens: int,
) -> LocalDocumentMap:
    """Build the full local document map. Zero provider calls. Empty fields
    are returned as empty lists rather than invented content when nothing
    relevant is found."""
    document_type, confidence = detect_document_type_with_confidence(filename, chunks)
    if configured_ner_backend() == "combined":
        detailed = [extract_entities_detailed(chunk.text) for chunk in chunks]  # one inference per chunk
        sections, parties, dates = extract_sections_and_entities(chunks, ner_results=[result for result, _ in detailed])
        left_role = _versus_left_role(" ".join(chunk.text for chunk in chunks))
        parties_and_roles = merge_model_parties(
            extract_parties_and_roles(chunks),
            extract_model_parties(chunks, [model for _, model in detailed], left_role, document_type))
    else:
        sections, parties, dates = extract_sections_and_entities(chunks)
        parties_and_roles = extract_parties_and_roles(chunks)
    chronology = extract_chronology(chunks)
    procedural_stages = extract_procedural_stages(chunks)
    evidence_items = extract_evidence_items(chunks)
    explicit_statutes = []
    for section in sections:
        for statute in _STATUTE_ABBREVIATIONS:
            if statute.lower() in section.lower() and statute not in explicit_statutes:
                explicit_statutes.append(statute)
    by_field = select_multi_intent_evidence(chunks, dense_provider=dense_provider, token_budget_tokens=token_budget_tokens)

    all_selected_ids = [excerpt.private_evidence_id for entries in by_field.values() for excerpt in entries]
    all_selected_pages = sorted(
        {excerpt.pages for entries in by_field.values() for excerpt in entries if excerpt.pages != "unknown"}
    )

    return LocalDocumentMap(
        document_type=document_type,
        document_type_confidence=confidence,
        parties=parties,
        parties_and_roles=parties_and_roles,
        important_dates=dates,
        chronology=chronology,
        procedural_stages=procedural_stages,
        evidence_items=evidence_items,
        explicit_statutes=explicit_statutes[:10],
        explicit_sections=sections,
        document_overview=by_field["document_overview"],
        material_facts=by_field["material_facts"],
        allegations=by_field["charges"][: _MAX_ENTRIES_PER_FIELD // 2],
        complainant_or_prosecution_position=by_field["allegations"],
        charges=by_field["charges"],
        evidence_excerpts=(
            by_field["witness_evidence"]
            + by_field["documentary_evidence"]
            + by_field["electronic_evidence"]
            + by_field["medical_forensic_evidence"]
            + by_field["recovery_seizure_evidence"]
        )[:_MAX_ENTRIES_PER_FIELD],
        witness_excerpts=by_field["witness_evidence"],
        witness_evidence=by_field["witness_evidence"],
        documentary_evidence=by_field["documentary_evidence"],
        electronic_evidence=by_field["electronic_evidence"],
        medical_forensic_excerpts=by_field["medical_forensic_evidence"],
        medical_forensic_evidence=by_field["medical_forensic_evidence"],
        recovery_seizure_evidence=by_field["recovery_seizure_evidence"],
        investigation_excerpts=by_field["investigation_steps"],
        investigation_steps=by_field["investigation_steps"],
        procedural_history=by_field["procedural_history"],
        defence_or_accused_position=by_field["accused_or_defence_position"],
        accused_or_defence_position=by_field["accused_or_defence_position"],
        arguments_or_contentions=by_field["arguments_or_contentions"],
        findings_or_orders=by_field["court_findings"],
        court_findings=by_field["court_findings"],
        court_reasoning=by_field["court_findings"],
        relief_or_final_order=by_field["relief_or_final_order"],
        missing_or_unclear_information=_missing_information(
            document_type, by_field, parties=parties_and_roles, chronology=chronology, evidence=evidence_items
        ),
        important_chunk_ids=sorted(set(all_selected_ids), key=lambda cid: int(cid[1:])) if all_selected_ids else [],
        important_pages=all_selected_pages,
    )


def _missing_information(
    document_type: str,
    by_field: dict[str, list[MapExcerpt]],
    *,
    parties: list[PartyRole] | None = None,
    chronology: list[ChronologyEntry] | None = None,
    evidence: list[EvidenceItem] | None = None,
) -> list[str]:
    missing: list[str] = []
    if parties is not None and not parties:
        missing.append("No party with a stated role (complainant, accused, petitioner, respondent ...) was identified in the uploaded document.")
    if chronology is not None and not any(parse_date_iso(entry.date) for entry in chronology):
        missing.append("No dated event was identified in the uploaded document.")
    if evidence is not None and not evidence:
        missing.append("No witness, documentary, medical/forensic, electronic or recovery evidence was identified in the uploaded document.")
    detected_medical = evidence is not None and any("medical_forensic" in item.categories for item in evidence)
    if not by_field.get("medical_forensic_evidence") and not detected_medical:
        missing.append("No medical or forensic evidence excerpt was identified in the uploaded material.")
    if not by_field.get("accused_or_defence_position"):
        missing.append("No accused or defence position excerpt was identified in the uploaded material.")
    if document_type in {"judgment", "order"} and not by_field.get("relief_or_final_order"):
        missing.append("No final relief or operative order excerpt was identified in the selected document map.")
    return missing[:8]


_EXCERPT_FIELDS = (
    "document_overview",
    "material_facts",
    "allegations",
    "complainant_or_prosecution_position",
    "charges",
    "evidence_excerpts",
    "witness_evidence",
    "documentary_evidence",
    "electronic_evidence",
    "medical_forensic_evidence",
    "recovery_seizure_evidence",
    "investigation_steps",
    "procedural_history",
    "defence_or_accused_position",
    "arguments_or_contentions",
    "court_findings",
    "relief_or_final_order",
)


class _SentenceRegistry:
    """Gives each distinct sentence a short id (s1, s2 ...) the first time it is rendered.

    A sentence repeated in a later section is rendered as "see sN" instead of
    again in full, so the map stays compact and every item keeps its P# reference.
    """

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}

    @staticmethod
    def _key(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().removesuffix("...").strip().lower()

    def _lookup(self, text: str) -> int | None:
        key = self._key(text)
        if key in self._ids:
            return self._ids[key]
        # A bounded (truncated) sentence matches the full sentence it starts.
        return next((sid for known, sid in self._ids.items() if len(known) > 40 and (key.startswith(known) or known.startswith(key))), None)

    def render(self, text: str) -> str:
        known = self._lookup(text)
        if known is not None:
            return f"see s{known}"
        sid = len(self._ids) + 1
        self._ids[self._key(text)] = sid
        return f"(s{sid}) {text}"

    def strip_known(self, excerpt: str) -> tuple[str, list[int]]:
        """Excerpt text without already-rendered sentences, and the ids of those removed."""
        kept: list[str] = []
        removed: list[int] = []
        for sentence in _split_sentences(excerpt):
            known = self._lookup(sentence)
            if known is None:
                kept.append(sentence)
            elif known not in removed:
                removed.append(known)
        return " ".join(kept), removed


def render_local_document_map(document_map: LocalDocumentMap) -> str:
    """Render the map for the prompt, without repeating any sentence across sections.

    Structured items (chronology, procedural stages, evidence) render each
    sentence once with an id (s1 ...); later repeats say "see sN". Excerpt
    fields list an excerpt once (alias fields point to it) and drop sentences
    already rendered above, naming their ids. Every item keeps its P# reference.
    """
    sentences = _SentenceRegistry()
    lines = [
        f'<PRIVATE_DOCUMENT_MAP document_type="{document_map.document_type}" '
        f'document_type_confidence="{document_map.document_type_confidence}" '
        f'chunks="{",".join(document_map.important_chunk_ids)}">',
        "This is a locally built (no AI-generated summarization), compact map of the "
        "uploaded private document. It describes the document only, is not legal "
        "authority, and any statutory sections below are mentions found explicitly in "
        "the document text, not verified applicable law. Each sentence appears once, "
        "labelled (sN); later mentions say \"see sN\".",
        "Prepare a substantive professional case-file summary based only on the uploaded-document P# evidence and trusted E# authority. "
        "Explain the factual narrative, parties and roles, chronology, explicit statutory provisions, major evidence, procedural posture, "
        "and unresolved or missing information where supported. Be comprehensive relative to supported evidence; do not pad, speculate, "
        "or replace the document summary with generic legal commentary.",
    ]
    if document_map.parties_and_roles:
        lines.append("parties_and_roles:")
        for party in document_map.parties_and_roles:
            name = party.name or "(role only)"
            evidence = f" [{party.private_evidence_id}]" if party.private_evidence_id else ""
            lines.append(f"- {party.role}: {name}{evidence}")
    # The NER summaries repeat the structured sections; render them only when those are empty.
    if document_map.parties and not document_map.parties_and_roles:
        lines.append("parties: " + "; ".join(document_map.parties))
    if document_map.important_dates and not document_map.chronology:
        lines.append("important_dates: " + "; ".join(document_map.important_dates))
    if document_map.chronology:
        lines.append("chronology:")
        for item in document_map.chronology:
            event = f" - {item.event}" if item.event else ""
            evidence = f" [{item.private_evidence_id}]" if item.private_evidence_id else ""
            context = f": {sentences.render(item.context)}" if item.context else ""
            lines.append(f"- {item.date}{event}{evidence}{context}")
    if document_map.procedural_stages:
        lines.append("procedural_stages:")
        for stage in document_map.procedural_stages:
            lines.append(f"- [{stage.private_evidence_id}] {', '.join(stage.stages)}: {sentences.render(stage.text)}")
    if document_map.evidence_items:
        lines.append("evidence_identified:")
        for item in document_map.evidence_items:
            categories = ", ".join(EVIDENCE_CATEGORY_LABELS[name] for name in item.categories)
            lines.append(f"- [{item.private_evidence_id}] {categories}: {sentences.render(item.text)}")
    if document_map.explicit_sections:
        lines.append("statutory_sections_explicitly_mentioned: " + "; ".join(document_map.explicit_sections))
    if document_map.explicit_statutes:
        lines.append("statutes_explicitly_mentioned: " + "; ".join(document_map.explicit_statutes))
    listed: dict[tuple[str, str], str] = {}
    for field_name in _EXCERPT_FIELDS:
        entries: list[MapExcerpt] = getattr(document_map, field_name)
        if not entries:
            continue
        lines.append(f"{field_name}:")
        for entry in entries:
            reference = f"[{entry.private_evidence_id}, pages {entry.pages}]"
            first_field = listed.get((entry.private_evidence_id, entry.excerpt))
            if first_field is not None:
                lines.append(f"- {reference} same excerpt as {first_field}")
                continue
            listed[(entry.private_evidence_id, entry.excerpt)] = field_name
            remaining, removed = sentences.strip_known(entry.excerpt)
            also = f" (also {', '.join(f's{sid}' for sid in removed)})" if removed else ""
            body = remaining if remaining else "all of its sentences are listed above"
            lines.append(f"- {reference} {body}{also}")
    if document_map.missing_or_unclear_information:
        lines.append("missing_or_unclear_information:")
        for item in document_map.missing_or_unclear_information:
            lines.append(f"- {item}")
    lines.append("</PRIVATE_DOCUMENT_MAP>")
    return "\n".join(lines)


def build_enriched_trusted_query(document_map: LocalDocumentMap, *, fallback_query: str) -> str:
    """Build a retrieval query for the trusted corpus from the local map,
    instead of sending the entire PDF text or a generic placeholder. Feeds
    the existing (frozen, unchanged) retrieval pipeline - it never bypasses
    or alters retrieval/ranking itself."""
    parts: list[str] = []
    if document_map.explicit_sections:
        parts.append(" ".join(document_map.explicit_sections[:5]))
    if document_map.charges:
        parts.append(" ".join(entry.excerpt[:120] for entry in document_map.charges[:2]))
    if document_map.material_facts:
        parts.append(" ".join(entry.excerpt[:120] for entry in document_map.material_facts[:2]))
    if document_map.chronology:
        parts.append(" ".join(f"{item.date} {item.event or ''}" for item in document_map.chronology[:4]))
    enriched = " ".join(part for part in parts if part).strip()
    return enriched or fallback_query


def local_map_metrics(document_map: LocalDocumentMap) -> dict[str, Any]:
    """Safe, aggregate-only metrics for observability - never document text."""
    excerpt_count = sum(len(getattr(document_map, name)) for name in _EXCERPT_FIELDS)
    return {
        "document_type": document_map.document_type,
        "document_type_confidence": document_map.document_type_confidence,
        "parties_count": len(document_map.parties),
        "parties_and_roles_count": len(document_map.parties_and_roles),
        "dates_count": len(document_map.important_dates),
        "chronology_count": len(document_map.chronology),
        "procedural_stage_count": len(document_map.procedural_stages),
        "evidence_item_count": len(document_map.evidence_items),
        "sections_count": len(document_map.explicit_sections),
        "evidence_categories_count": sum(
            1
            for name in (
                "witness_evidence",
                "documentary_evidence",
                "electronic_evidence",
                "medical_forensic_evidence",
                "recovery_seizure_evidence",
            )
            if getattr(document_map, name)
        ),
        "excerpt_count": excerpt_count,
        "estimated_map_tokens": estimate_tokens(render_local_document_map(document_map)),
    }
