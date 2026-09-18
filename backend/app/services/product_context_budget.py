"""Product-wide generation context budgeting for trusted (E#) evidence.

This closes the gap the bounded private-PDF work (private_pdf_rag.py,
token_budget.py) deliberately left open: that work only bounded the extra
context a PDF upload adds on *top of* whatever trusted-evidence prompt
`legal_rag_retrieval.retrieve_legal_evidence` (frozen) already built - it
never bounded the trusted-evidence prompt itself. A plain text query with no
PDF at all can retrieve five large trusted chunks and still exceed a
provider account's real capacity (observed: an ~8k-tokens-per-request Groq
free-tier limit), which is exactly the "POCSO Act" regression this module
fixes.

Like `private_pdf_rag.py`, this module is additive and deliberately outside
the 5 files pinned by the frozen grounded-answer benchmark's component-hash
manifest (`data/structured/manifests/legal_answer_eval.json`). It only
*constructs new instances* of frozen Pydantic models (`LegalRetrievalResult`,
`LegalEvidenceChunk`) via their public constructors/`.model_copy()` - it
never edits `legal_rag_retrieval.py` itself, so that file's hash (and the
frozen benchmark's retrieval behavior) is untouched. Retrieval, ranking, and
reranking are unchanged: this only decides how much of the *already-ranked*
top-5 evidence a live generation call actually receives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from backend.app.core.config import Settings
from backend.app.services.legal_rag_retrieval import LegalEvidenceChunk, LegalRetrievalResult
from backend.app.services.token_budget import estimate_tokens

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class ContextTier(str, Enum):
    """Deterministic product-runtime context tiers (section 16). NORMAL is
    tried first; REDUCED is used for at most one retry if the provider
    itself still rejects a NORMAL-tier request as too large (its account
    limits may differ from our estimate). Never a silent provider switch,
    never a retry loop."""

    NORMAL = "normal"
    REDUCED = "reduced"


@dataclass(frozen=True)
class ProductContextBudget:
    """Resolved, request-independent product-wide budget for one generative
    call, covering trusted evidence specifically (private-PDF evidence is
    budgeted separately by `token_budget.TokenBudget`, against whatever room
    is left after this trusted-evidence budget is spent - see
    `docs/PRODUCT_CONTEXT_BUDGETING.md` for how the two compose)."""

    max_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    prompt_overhead_reserve_tokens: int
    trusted_evidence_ceiling_tokens: int

    @property
    def available_input_tokens(self) -> int:
        return max(
            0,
            self.max_input_tokens
            - self.reserved_output_tokens
            - self.safety_margin_tokens
            - self.prompt_overhead_reserve_tokens,
        )

    def trusted_evidence_budget(self, *, query_tokens: int) -> int:
        remaining = self.available_input_tokens - query_tokens
        return max(0, min(self.trusted_evidence_ceiling_tokens, remaining))

    def reduced(self) -> "ProductContextBudget":
        """The REDUCED tier: half the trusted-evidence ceiling. Everything
        else (overhead reserves, output reserve, safety margin) is
        unchanged, since those don't shrink just because evidence does."""
        return ProductContextBudget(
            max_input_tokens=self.max_input_tokens,
            reserved_output_tokens=self.reserved_output_tokens,
            safety_margin_tokens=self.safety_margin_tokens,
            prompt_overhead_reserve_tokens=self.prompt_overhead_reserve_tokens,
            trusted_evidence_ceiling_tokens=max(1, self.trusted_evidence_ceiling_tokens // 2),
        )


def resolve_product_context_budget(settings: Settings) -> ProductContextBudget:
    return ProductContextBudget(
        max_input_tokens=settings.legalai_product_max_input_tokens,
        reserved_output_tokens=settings.legalai_llm_reserved_output_tokens,
        safety_margin_tokens=settings.legalai_llm_context_safety_margin_tokens,
        prompt_overhead_reserve_tokens=settings.prompt_overhead_reserve_tokens,
        trusted_evidence_ceiling_tokens=settings.trusted_evidence_input_budget_tokens,
    )


def excerpt_at_boundary(text: str, max_tokens: int) -> str:
    """Bound `text` to approximately `max_tokens`, preferring paragraph and
    then sentence boundaries over an arbitrary character cutoff, so the
    excerpt reads as complete legal prose rather than a mid-word/mid-clause
    fragment. Falls back to a raw character cutoff only when no structural
    boundary exists within budget (e.g. one enormous unbroken paragraph)."""
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) > 1:
        kept: list[str] = []
        used = 0
        for paragraph in paragraphs:
            cost = estimate_tokens(paragraph)
            if used + cost > max_tokens:
                break
            kept.append(paragraph)
            used += cost
        if kept:
            return "\n\n".join(kept)

    sentences = [s for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]
    if len(sentences) > 1:
        kept = []
        used = 0
        for sentence in sentences:
            cost = estimate_tokens(sentence)
            if used + cost > max_tokens:
                break
            kept.append(sentence)
            used += cost
        if kept:
            return " ".join(kept)

    # No structural boundary available within budget - bounded character
    # cutoff is the last resort, not the primary strategy.
    approx_chars = max(1, max_tokens * 4)
    return text[:approx_chars].rstrip()


def bound_trusted_evidence(
    retrieval: LegalRetrievalResult,
    *,
    budget_tokens: int,
) -> LegalRetrievalResult:
    """Return a copy of `retrieval` whose `.evidence` fits `budget_tokens`,
    without ever re-ranking or reordering: evidence is included strictly in
    existing rank order (E1, then E2, then E3, ...) until the budget runs
    out. Higher-ranked evidence is never dropped to make room for a
    lower-ranked item. An individual chunk too large to include even alone
    is excerpted at a paragraph/sentence boundary rather than dropped
    outright or naively sliced, and keeps its original citation id and
    source metadata so citation validation and the UI are unaffected.

    Never mutates the input; `retrieval.evidence` is only ever read from.
    """
    if budget_tokens <= 0 or not retrieval.evidence:
        return retrieval.model_copy(update={"evidence": []})

    bounded: list[LegalEvidenceChunk] = []
    used = 0
    for item in retrieval.evidence:
        remaining = budget_tokens - used
        if remaining <= 0:
            break
        item_tokens = estimate_tokens(item.text)
        if item_tokens <= remaining:
            bounded.append(item)
            used += item_tokens
            continue
        # This item doesn't fit whole. If it doesn't fit *at all* (remaining
        # budget too small to be a useful excerpt), stop here rather than
        # including a near-empty fragment - later, lower-ranked evidence is
        # never promoted ahead of this still-higher-ranked item.
        if remaining < 40:
            break
        excerpt = excerpt_at_boundary(item.text, remaining)
        if not excerpt.strip():
            break
        bounded.append(item.model_copy(update={"text": excerpt}))
        used += estimate_tokens(excerpt)
        break  # the next-ranked item after a partial excerpt would exceed budget too

    return retrieval.model_copy(update={"evidence": bounded})


def evidence_metrics(retrieval: LegalRetrievalResult) -> dict[str, Any]:
    """Safe, aggregate-only metrics for observability - never includes
    evidence text."""
    return {
        "evidence_count": len(retrieval.evidence),
        "evidence_ids": [item.citation_id for item in retrieval.evidence],
        "estimated_evidence_tokens": sum(estimate_tokens(item.text) for item in retrieval.evidence),
    }
