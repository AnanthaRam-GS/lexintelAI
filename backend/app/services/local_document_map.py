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
- `legal_ner.extract_deterministic_entities` for parties/dates/statutes/
  sections/courts - already deterministic, already used elsewhere in
  LegalAI, no InLegalBERT or any other model dependency.
- `token_budget.estimate_tokens` for bounding.

Additive and outside the 5 frozen files - it only imports read-only from
`legal_ner.py`/`query_analysis.py` (neither is frozen) and from
`private_pdf_rag.py` (this project's own prior additive module).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.app.services.legal_ner import extract_deterministic_entities
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
    ("material_facts", "material facts and incident description"),
    ("parties_intent", "accused and complainant parties"),
    ("investigation_excerpts", "procedural history and investigation"),
    ("charges", "charges offences statutory sections"),
    ("witness_excerpts", "witness statements"),
    ("medical_forensic_excerpts", "medical forensic electronic documentary evidence"),
    ("defence_or_accused_position", "defence accused explanation alibi"),
    ("findings_or_orders", "court findings reasoning"),
    ("evidence_excerpts", "relief order sentence bail"),
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

_DOCUMENT_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FIR", ("first information report", "fir no", "f.i.r")),
    ("chargesheet", ("chargesheet", "charge sheet", "final report under section 173")),
    ("judgment", ("judgment", "judgement", "in the court of", "before the hon'ble", "j u d g m e n t")),
    ("appeal", ("memorandum of appeal", "criminal appeal no", "appellant")),
    ("petition", ("petition under", "petitioner", "writ petition")),
    ("order", ("order sheet", "this order", "ordered accordingly")),
)

_MAX_ENTRIES_PER_FIELD = 6
_MAX_EXCERPT_CHARS = 500
_MAX_PARTIES = 10
_MAX_DATES = 10
_MAX_SECTIONS = 15


@dataclass(frozen=True)
class MapExcerpt:
    private_evidence_id: str
    pages: str
    excerpt: str


@dataclass(frozen=True)
class LocalDocumentMap:
    """Compact, request-local, bounded structured summary of an uploaded
    private document, built entirely without any provider call. Statutory
    sections here are sections *explicitly mentioned in the document* -
    never asserted as verified applicable law; that determination remains
    the trusted corpus's job."""

    document_type: str
    parties: list[str] = field(default_factory=list)
    important_dates: list[str] = field(default_factory=list)
    explicit_sections: list[str] = field(default_factory=list)
    material_facts: list[MapExcerpt] = field(default_factory=list)
    allegations: list[MapExcerpt] = field(default_factory=list)
    charges: list[MapExcerpt] = field(default_factory=list)
    evidence_excerpts: list[MapExcerpt] = field(default_factory=list)
    witness_excerpts: list[MapExcerpt] = field(default_factory=list)
    medical_forensic_excerpts: list[MapExcerpt] = field(default_factory=list)
    investigation_excerpts: list[MapExcerpt] = field(default_factory=list)
    defence_or_accused_position: list[MapExcerpt] = field(default_factory=list)
    findings_or_orders: list[MapExcerpt] = field(default_factory=list)
    important_chunk_ids: list[str] = field(default_factory=list)
    important_pages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Document type heuristic (section 9) - filename/text patterns only.
# ---------------------------------------------------------------------------


def detect_document_type(filename: str, chunks: list[PrivateChunk]) -> str:
    haystack = filename.lower() + " " + " ".join(chunk.text.lower() for chunk in chunks[:3])
    for doc_type, markers in _DOCUMENT_TYPE_PATTERNS:
        if any(marker in haystack for marker in markers):
            return doc_type
    return "unknown"


# ---------------------------------------------------------------------------
# Deterministic entity/section extraction (sections 7, 8) - reuses the
# existing deterministic NER, never InLegalBERT, never an LLM.
# ---------------------------------------------------------------------------


def _statute_suffix_after(text: str, end: int) -> str | None:
    window = text[end : end + 40]
    match = _STATUTE_SUFFIX_PATTERN.match(window)
    return match.group(1) if match else None


def extract_sections_and_entities(chunks: list[PrivateChunk]) -> tuple[list[str], list[str], list[str]]:
    """Returns (explicit_sections, parties, important_dates), each deduped
    and capped, extracted purely via `legal_ner.extract_deterministic_entities`
    (regex/pattern-based, no model, no provider call)."""
    sections: list[str] = []
    parties: list[str] = []
    dates: list[str] = []
    seen_sections: set[str] = set()
    seen_parties: set[str] = set()
    seen_dates: set[str] = set()

    for chunk in chunks:
        result = extract_deterministic_entities(chunk.text)
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
    claimed_indexes: set[int] = set()
    by_field: dict[str, list[MapExcerpt]] = {name: [] for name in _ALLOCATABLE_FIELDS}
    used_tokens = 0

    for field_name, intent_text in _INTENTS:
        if field_name == "parties_intent":
            continue  # parties come from deterministic NER, not intent retrieval
        if used_tokens >= token_budget_tokens:
            break
        remaining_budget = token_budget_tokens - used_tokens
        candidates = select_query_focused_private_evidence(
            chunks,
            intent_text,
            dense_provider=dense_provider,
            top_k=_CANDIDATES_PER_INTENT,
            token_budget_tokens=remaining_budget,
        )
        for item in candidates:
            if item.chunk.chunk_index in claimed_indexes:
                continue
            if len(by_field[field_name]) >= _MAX_ENTRIES_PER_FIELD:
                break
            claimed_indexes.add(item.chunk.chunk_index)
            by_field[field_name].append(
                MapExcerpt(
                    private_evidence_id=item.chunk.private_chunk_id,
                    pages=_page_range(item.chunk),
                    excerpt=_bounded_excerpt(item.chunk.text),
                )
            )
            used_tokens += item.chunk.token_count

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
    document_type = detect_document_type(filename, chunks)
    sections, parties, dates = extract_sections_and_entities(chunks)
    by_field = select_multi_intent_evidence(chunks, dense_provider=dense_provider, token_budget_tokens=token_budget_tokens)

    all_selected_ids = [excerpt.private_evidence_id for entries in by_field.values() for excerpt in entries]
    all_selected_pages = sorted(
        {excerpt.pages for entries in by_field.values() for excerpt in entries if excerpt.pages != "unknown"}
    )

    return LocalDocumentMap(
        document_type=document_type,
        parties=parties,
        important_dates=dates,
        explicit_sections=sections,
        material_facts=by_field["material_facts"],
        allegations=by_field["charges"][: _MAX_ENTRIES_PER_FIELD // 2],
        charges=by_field["charges"],
        evidence_excerpts=by_field["evidence_excerpts"],
        witness_excerpts=by_field["witness_excerpts"],
        medical_forensic_excerpts=by_field["medical_forensic_excerpts"],
        investigation_excerpts=by_field["investigation_excerpts"],
        defence_or_accused_position=by_field["defence_or_accused_position"],
        findings_or_orders=by_field["findings_or_orders"],
        important_chunk_ids=sorted(set(all_selected_ids), key=lambda cid: int(cid[1:])) if all_selected_ids else [],
        important_pages=all_selected_pages,
    )


_EXCERPT_FIELDS = (
    "material_facts",
    "allegations",
    "charges",
    "evidence_excerpts",
    "witness_excerpts",
    "medical_forensic_excerpts",
    "investigation_excerpts",
    "defence_or_accused_position",
    "findings_or_orders",
)


def render_local_document_map(document_map: LocalDocumentMap) -> str:
    lines = [
        f'<PRIVATE_DOCUMENT_MAP document_type="{document_map.document_type}" '
        f'chunks="{",".join(document_map.important_chunk_ids)}">',
        "This is a locally built (no AI-generated summarization), compact map of the "
        "uploaded private document. It describes the document only, is not legal "
        "authority, and any statutory sections below are mentions found explicitly in "
        "the document text, not verified applicable law.",
    ]
    if document_map.parties:
        lines.append("parties: " + "; ".join(document_map.parties))
    if document_map.important_dates:
        lines.append("important_dates: " + "; ".join(document_map.important_dates))
    if document_map.explicit_sections:
        lines.append("statutory_sections_explicitly_mentioned: " + "; ".join(document_map.explicit_sections))
    for field_name in _EXCERPT_FIELDS:
        entries: list[MapExcerpt] = getattr(document_map, field_name)
        if not entries:
            continue
        lines.append(f"{field_name}:")
        for entry in entries:
            lines.append(f'- [{entry.private_evidence_id}, pages {entry.pages}] {entry.excerpt}')
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
    enriched = " ".join(part for part in parts if part).strip()
    return enriched or fallback_query


def local_map_metrics(document_map: LocalDocumentMap) -> dict[str, Any]:
    """Safe, aggregate-only metrics for observability - never document text."""
    excerpt_count = sum(len(getattr(document_map, name)) for name in _EXCERPT_FIELDS)
    return {
        "document_type": document_map.document_type,
        "parties_count": len(document_map.parties),
        "dates_count": len(document_map.important_dates),
        "sections_count": len(document_map.explicit_sections),
        "excerpt_count": excerpt_count,
        "estimated_map_tokens": estimate_tokens(render_local_document_map(document_map)),
    }
