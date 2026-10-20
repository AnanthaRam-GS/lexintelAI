"""Professional brief fields built from extractive sources (BRIEF-001, BRIEF-002).

The LLM output schema (``legal_answer_generation.ProfessionalLegalBrief``) is
frozen and hash-pinned, so the response layer fills the case-file fields that
the model does not produce, from sources that cannot invent content:

| Field | Source |
|---|---|
| ``parties_and_roles`` | local document map party detection (role, name, P# reference) |
| ``chronology`` | local document map dated entries: parseable dates only, sorted, one per date and event |
| ``procedural_considerations`` | local document map procedural-stage detection, then the model's ``procedural_posture`` |
| ``evidence_identified`` | local document map evidence detection (witnesses, documents, medical/forensic, electronic, recoveries) |
| precedents | retrieved trusted evidence: metadata, reranker score, bounded excerpt, provenance |

Without an uploaded document (text queries, question-focused PDF queries)
the document fields are empty; nothing is inferred from the query text.

Precedent relevance is a *relative* score within one query: the reranker's
raw scores of the returned precedents, min-max scaled so the top precedent is
1.0 and the lowest 0.0, ``(score - min) / (max - min)``. It ranks precedents
against each other; it is not an absolute probability. (A sigmoid of the raw
``BAAI/bge-reranker-v2-m3`` logits was tried first, but live logits of 4-6
all mapped to 0.98-1.0, so it did not discriminate.) The raw score is kept in
``reranker_score``. Relevance is ``None`` when a precedent has no reranker
score, when there is only one scored precedent, or when all scores are equal,
because no meaningful relative number exists then.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from backend.app.models.query import ProfessionalPrecedent
from backend.app.services.local_document_map import (
    EVIDENCE_CATEGORY_LABELS,
    LocalDocumentMap,
    parse_date_iso,
)
from backend.app.services.private_pdf_rag import PrivateChunk
from backend.app.services.retrieval.bm25 import tokenize_legal_text

RELEVANCE_SCORE_METHOD = "min-max of reranker_score within the query (relative)"
ELLIPSIS = "..."


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def evidence_reference(evidence_id: str | None, page_start: int | None, page_end: int | None) -> str:
    """"[P2, p. 3]", "[P2, pp. 3-4]" or "[P2]"."""
    if not evidence_id:
        return ""
    if page_start is None:
        return f"[{evidence_id}]"
    if page_end is None or page_end == page_start:
        return f"[{evidence_id}, p. {page_start}]"
    return f"[{evidence_id}, pp. {page_start}-{page_end}]"


# ---------------------------------------------------------------------------
# Document fields (BRIEF-001)
# ---------------------------------------------------------------------------


def parties_and_roles(document_map: LocalDocumentMap | None) -> list[str]:
    """"Complainant: Meera Placeholder [P1, p. 1]" for each detected party with a name."""
    if document_map is None:
        return []
    items: list[str] = []
    for party in document_map.parties_and_roles:
        if not party.name:
            continue
        reference = evidence_reference(party.private_evidence_id, party.page_start, party.page_end)
        item = f"{party.role[:1].upper()}{party.role[1:]}: {party.name} {reference}".strip()
        if item not in items:
            items.append(item)
    return items


def validated_llm_parties(candidates: Iterable[Any], chunks: list[PrivateChunk]) -> list[str]:
    """Parties proposed by the model, kept only when backed by a P# reference whose text contains the name.

    The frozen ``ProfessionalLegalBrief`` schema has no parties field, so today
    the model cannot propose any; this guard applies if the schema gains one.
    """
    texts = {chunk.private_chunk_id: _normalized(chunk.text) for chunk in chunks}
    pages = {chunk.private_chunk_id: (chunk.page_start, chunk.page_end) for chunk in chunks}
    accepted: list[str] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        name = str(candidate.get("name") or "").strip()
        role = str(candidate.get("role") or "").strip()
        evidence_id = str(candidate.get("evidence_id") or candidate.get("private_evidence_id") or "").strip()
        if not (name and role and evidence_id in texts and _normalized(name) in texts[evidence_id]):
            continue
        item = f"{role[:1].upper()}{role[1:]}: {name} {evidence_reference(evidence_id, *pages[evidence_id])}"
        if item not in accepted:
            accepted.append(item)
    return accepted


def chronology(document_map: LocalDocumentMap | None) -> list[str]:
    """Dated events only, sorted by date: "2024-03-04 - FIR registered: <context> [P1, p. 2]".

    Dates that cannot be parsed are left out. When a date has a labelled event,
    unlabelled mentions of the same date are dropped.
    """
    if document_map is None:
        return []
    entries = [(parse_date_iso(entry.date), position, entry) for position, entry in enumerate(document_map.chronology)]
    entries = [item for item in entries if item[0]]
    labelled_dates = {iso for iso, _, entry in entries if entry.event}
    items: list[str] = []
    seen: set[tuple[str, str]] = set()
    for iso, _position, entry in sorted(entries, key=lambda item: (item[0], item[1])):
        if not entry.event and iso in labelled_dates:
            continue
        key = (iso, entry.event or _normalized(entry.context or "")[:60])
        if key in seen:
            continue
        seen.add(key)
        label = f"{entry.event[:1].upper()}{entry.event[1:]}" if entry.event else "Dated entry"
        context = f": {entry.context}" if entry.context else ""
        reference = evidence_reference(entry.private_evidence_id, entry.page_start, entry.page_end)
        items.append(f"{iso} - {label}{context} {reference}".strip())
    return items


def procedural_considerations(document_map: LocalDocumentMap | None, posture: Iterable[str] = ()) -> list[str]:
    """Procedural stages stated in the document ("Bail: <sentence> [P1]"), then the model's procedural posture."""
    items: list[str] = []
    if document_map is not None:
        for stage in document_map.procedural_stages:
            labels = "; ".join(stage.stages)
            reference = evidence_reference(stage.private_evidence_id, stage.page_start, stage.page_end)
            items.append(f"{labels[:1].upper()}{labels[1:]}: {stage.text} {reference}".strip())
    for item in posture:
        cleaned = item.strip()
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items


def evidence_identified(document_map: LocalDocumentMap | None) -> list[str]:
    """Evidence named in the document, by category: "Witnesses: <sentence> [P1, p. 1]"."""
    if document_map is None:
        return []
    items: list[str] = []
    for item in document_map.evidence_items:
        labels = ", ".join(EVIDENCE_CATEGORY_LABELS[name] for name in item.categories)
        reference = evidence_reference(item.private_evidence_id, item.page_start, item.page_end)
        items.append(f"{labels}: {item.text} {reference}".strip())
    return items


def document_limitations(document_map: LocalDocumentMap | None) -> list[str]:
    return list(document_map.missing_or_unclear_information) if document_map is not None else []


# ---------------------------------------------------------------------------
# Precedents (BRIEF-002)
# ---------------------------------------------------------------------------


def relative_relevance(scores: list[float | None]) -> list[float | None]:
    """Min-max scale raw reranker scores within one result set (top = 1.0); None where not meaningful."""
    present = [score for score in scores if score is not None and math.isfinite(score)]
    if len(present) < 2 or max(present) == min(present):
        return [None] * len(scores)
    low, high = min(present), max(present)
    return [
        round((score - low) / (high - low), 6) if score is not None and math.isfinite(score) else None
        for score in scores
    ]


_EXCERPT_SENTENCE = re.compile(r"(?<=[.?!;])\s+")


def precedent_excerpt(text: str, query: str, max_chars: int) -> str:
    """A snippet of at most ``max_chars`` characters around the chunk's most query-relevant sentence.

    The snippet is a verbatim span of the chunk text (whitespace collapsed),
    with "..." where text was cut.
    """
    flat = " ".join(text.split())
    if max_chars <= len(ELLIPSIS) * 2:
        raise ValueError("max_chars is too small for an excerpt")
    if len(flat) <= max_chars:
        return flat
    terms = set(tokenize_legal_text(query))
    sentences: list[tuple[int, int]] = []
    start = 0
    for match in _EXCERPT_SENTENCE.finditer(flat):
        sentences.append((start, match.start()))
        start = match.end()
    sentences.append((start, len(flat)))

    def overlap(span: tuple[int, int]) -> int:
        return len(terms & set(tokenize_legal_text(flat[span[0]:span[1]])))

    best = max(range(len(sentences)), key=lambda index: (overlap(sentences[index]), -index))
    budget = max_chars - len(ELLIPSIS) * 2
    left, right = sentences[best]
    if right - left > budget:
        right = left + budget
    else:
        before, after = best - 1, best + 1
        while True:  # widen by whole neighbouring sentences while they fit
            grown = False
            if after < len(sentences) and sentences[after][1] - left <= budget:
                right, after, grown = sentences[after][1], after + 1, True
            if before >= 0 and right - sentences[before][0] <= budget:
                left, before, grown = sentences[before][0], before - 1, True
            if not grown:
                break
    snippet = flat[left:right]
    if right < len(flat) and " " in snippet and not snippet.endswith((".", "?", "!", ";")):
        snippet = snippet.rsplit(" ", 1)[0]
    return f"{ELLIPSIS if left > 0 else ''}{snippet.strip()}{ELLIPSIS if left + len(snippet) < len(flat) else ''}"


def _court_name(court: Any) -> str | None:
    if isinstance(court, dict):
        return court.get("court_name") or court.get("name")
    return str(court) if court else None


def _year(value: Any) -> int | None:
    text = str(value or "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def precedents_from_retrieval(
    retrieval: Any,
    *,
    max_chars: int,
    query: str | None = None,
    cited_evidence_ids: set[str] | frozenset[str] = frozenset(),
) -> list[ProfessionalPrecedent]:
    """One precedent per retrieved document, from its best-ranked evidence chunk, in rank order.

    Every value comes from the retrieved trusted evidence (``LegalEvidenceChunk``):
    identifiers, case name, court, date, source URL, page/paragraph
    provenance, the chunk text for the excerpt, and the reranker score. The
    excerpt is centred on the passage most relevant to the retrieval query.
    ``cited_in_answer`` is true when any of the document's retrieved chunks is
    in ``cited_evidence_ids`` (E# IDs of validated citations).
    """
    if retrieval is None:
        return []
    query = retrieval.query if query is None else query
    cited_documents = {item.document_id for item in retrieval.evidence if item.citation_id in cited_evidence_ids}
    best: list[Any] = []
    seen: set[str] = set()
    for evidence in sorted(retrieval.evidence, key=lambda item: item.rank):
        if evidence.document_id not in seen:
            seen.add(evidence.document_id)
            best.append(evidence)
    relevance = relative_relevance([evidence.reranker_score for evidence in best])
    precedents: list[ProfessionalPrecedent] = []
    for evidence, relative in zip(best, relevance):
        precedents.append(
            ProfessionalPrecedent(
                document_id=evidence.document_id,
                chunk_id=evidence.chunk_id,
                case_name=evidence.case_name or evidence.document_id,
                court=_court_name(evidence.court),
                year=_year(evidence.judgment_date),
                relevance_score=relative,
                reranker_score=evidence.reranker_score,
                cited_in_answer=evidence.document_id in cited_documents,
                excerpt=precedent_excerpt(evidence.text, query, max_chars) if evidence.text.strip() else None,
                source_url=evidence.source_url,
                page_start=evidence.page_start,
                page_end=evidence.page_end,
                paragraph_start=evidence.paragraph_start,
                paragraph_end=evidence.paragraph_end,
            )
        )
    return precedents
