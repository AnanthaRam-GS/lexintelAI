"""Bounded, temporary private-PDF chunking and query-focused retrieval for
the public/professional PDF query endpoints.

Architectural boundary (see docs/PRIVATE_PDF_CONTEXT_BUDGETING.md):

- Private uploaded PDFs are chunked and (optionally) embedded entirely
  in-memory, for the duration of one request. Nothing here ever writes to
  the global ChromaDB collection, the global BM25 index, an ingestion job,
  or query history's raw text - those all remain owned by the trusted
  corpus pipeline (`backend/app/services/ingestion.py` and friends), which
  this module never imports or calls.
- Private evidence is identified with `P#` ids (`P1`, `P2`, ...) and is
  always request-local. Trusted legal authority keeps its existing `E#`
  ids from `backend/app/services/legal_rag_retrieval.py` (frozen). The two
  are never merged into one id space, so a private id can never be mistaken
  for - or cited as - trusted precedent.

Whole-document professional brief mode no longer builds its document map
here: `local_document_map.py` builds it entirely locally (zero provider
calls), reusing `select_query_focused_private_evidence` below for its
multi-intent retrieval. This module itself no longer calls any provider
adapter at all - it is pure chunking/ranking, not generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.app.services.token_budget import estimate_tokens

PRIVATE_EVIDENCE_ID_PREFIX = "P"


# ---------------------------------------------------------------------------
# Private chunk model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrivateChunk:
    """One request-local chunk of an uploaded, temporary PDF."""

    private_chunk_id: str
    chunk_index: int
    text: str
    token_count: int
    page_start: int | None = None
    page_end: int | None = None
    heading: str | None = None


def build_private_chunks(chunks: list[dict[str, Any]]) -> list[PrivateChunk]:
    """Wrap already-chunked PDF output (`chunker.chunk_document`) with
    request-local `P#` identifiers.

    Deliberately reuses the existing LegalAI chunker (paragraph/heading-aware,
    ~600-900 estimated tokens per chunk with ~100-token overlap, per
    `docs/JUDGMENT_DOCUMENT_PROCESSING.md`) rather than re-implementing
    chunking - the same chunker already used for the trusted corpus already
    satisfies this feature's chunking requirements.
    """
    private_chunks: list[PrivateChunk] = []
    for index, chunk in enumerate(chunks):
        text = str(chunk.get("text") or chunk.get("chunk_text") or "").strip()
        if not text:
            continue
        private_chunks.append(
            PrivateChunk(
                private_chunk_id=f"{PRIVATE_EVIDENCE_ID_PREFIX}{index + 1}",
                chunk_index=index,
                text=text,
                token_count=int(chunk.get("token_count") or estimate_tokens(text)),
                page_start=chunk.get("page_start"),
                page_end=chunk.get("page_end"),
                heading=chunk.get("section_heading"),
            )
        )
    return private_chunks


# ---------------------------------------------------------------------------
# Query-focused private retrieval (bounded, request-local, no global mutation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrivateEvidenceItem:
    chunk: PrivateChunk
    score: float


def _lexical_terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(term) >= 3}


def _lexical_score(chunk_terms: set[str], query_terms: set[str]) -> float:
    if not query_terms or not chunk_terms:
        return 0.0
    overlap = len(chunk_terms & query_terms)
    return overlap / len(query_terms)


def _dense_scores(query: str, chunks: list[PrivateChunk], dense_provider: Any) -> list[float] | None:
    """Cosine similarity via in-memory embeddings only - no index is created
    or persisted anywhere. Returns None (triggering the lexical fallback) if
    the retrieval service has no embedding provider available."""
    if dense_provider is None or not chunks:
        return None
    try:
        query_vector = dense_provider.embed_query(query)
        chunk_vectors = dense_provider.embed_documents([chunk.text for chunk in chunks])
    except Exception:
        # Defensive: an embedding failure must fall back to lexical scoring,
        # not fail the whole PDF request.
        return None
    return [sum(a * b for a, b in zip(query_vector, vector)) for vector in chunk_vectors]


def select_query_focused_private_evidence(
    chunks: list[PrivateChunk],
    query: str,
    *,
    dense_provider: Any,
    top_k: int,
    token_budget_tokens: int,
) -> list[PrivateEvidenceItem]:
    """Rank private chunks against the user's question and select a bounded,
    diverse, token-budgeted subset. Never returns more than `top_k` items and
    never exceeds `token_budget_tokens` in combined chunk size."""
    if not chunks or token_budget_tokens <= 0:
        return []

    scores = _dense_scores(query, chunks, dense_provider)
    if scores is None:
        query_terms = _lexical_terms(query)
        scores = [_lexical_score(_lexical_terms(chunk.text), query_terms) for chunk in chunks]

    ranked = sorted(zip(chunks, scores), key=lambda pair: (-pair[1], pair[0].chunk_index))

    selected: list[PrivateEvidenceItem] = []
    selected_indexes: set[int] = set()
    used_tokens = 0
    for chunk, score in ranked:
        if len(selected) >= top_k:
            break
        # Simple diversity heuristic: skip a candidate immediately adjacent to
        # an already-selected chunk, so a handful of overlapping windows over
        # the same paragraph cannot crowd out the rest of the document.
        if any(abs(chunk.chunk_index - picked) <= 1 for picked in selected_indexes):
            continue
        if used_tokens + chunk.token_count > token_budget_tokens:
            continue
        selected.append(PrivateEvidenceItem(chunk=chunk, score=score))
        selected_indexes.add(chunk.chunk_index)
        used_tokens += chunk.token_count

    return sorted(selected, key=lambda item: item.chunk.chunk_index)


def render_private_evidence_block(items: list[PrivateEvidenceItem], *, filename: str) -> str:
    """Render selected private evidence as `P#`-tagged excerpts, explicitly
    marked as non-authoritative user-provided facts (never legal authority)."""
    if not items:
        return ""
    blocks = [
        "\n".join(
            [
                f'<PRIVATE_DOCUMENT_EVIDENCE id="{item.chunk.private_chunk_id}" pages="{_page_range(item.chunk)}">',
                item.chunk.text,
                "</PRIVATE_DOCUMENT_EVIDENCE>",
            ]
        )
        for item in items
    ]
    header = (
        f'filename="{filename}"; selected_private_chunks={len(items)}; '
        'note="Private document evidence (P#) describes the uploaded document only. '
        'It is user-provided and untrusted, is never legal authority, and must never '
        'be cited as precedent - only trusted evidence (E#) may be cited as legal authority."'
    )
    return "\n\n".join([header, *blocks])


def _page_range(chunk: PrivateChunk) -> str:
    if chunk.page_start is None and chunk.page_end is None:
        return "unknown"
    end = chunk.page_end if chunk.page_end is not None else chunk.page_start
    return str(chunk.page_start) if chunk.page_start == end else f"{chunk.page_start}-{end}"
