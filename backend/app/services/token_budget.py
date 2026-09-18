"""Application-level context/token budgeting for generative answer calls.

This module is deliberately provider-agnostic and does not live inside the
frozen `legal_answer_generation.py` (see
`data/structured/manifests/legal_answer_eval.json`'s `component_hashes`).
It only ever *estimates* how large a prompt is and decides, before any
provider is invoked, how much room is left for private-PDF evidence — it
never assumes a provider's advertised maximum context window is a safe
application-level budget (a provider or a rate-limited account tier may
accept far less in practice than a model's nominal context length).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.config import Settings
from backend.scripts.process_judgment_corpus import estimated_tokens

# Reuse the same word-count-based approximation already used everywhere else
# in the ingestion/chunking pipeline (backend/scripts/process_judgment_corpus.py),
# rather than inventing a second, inconsistent estimator. It intentionally
# does not need to match a specific provider's real tokenizer exactly - it
# only needs to bias toward *overestimating*, which the JSON/XML structural
# overhead multiplier below reinforces further.
_STRUCTURAL_OVERHEAD_MULTIPLIER = 1.15


def estimate_tokens(text: str) -> int:
    """Conservative, deterministic, offline token estimate for arbitrary text.

    Biases high on purpose: legal/statutory text, JSON structure, and XML
    prompt tags all tend to tokenize denser than plain prose, and a safety
    margin is cheaper than a provider-side rejection.
    """
    if not text:
        return 0
    return max(1, round(estimated_tokens(text) * _STRUCTURAL_OVERHEAD_MULTIPLIER))


@dataclass(frozen=True)
class TokenBudget:
    """Resolved, request-independent token budget for one generative call."""

    context_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    private_pdf_ceiling_tokens: int
    trusted_evidence_ceiling_tokens: int

    @property
    def available_input_tokens(self) -> int:
        """Total input budget after reserving output and a safety margin."""
        return max(0, self.context_tokens - self.reserved_output_tokens - self.safety_margin_tokens)

    def private_pdf_budget(self, *, already_used_tokens: int) -> int:
        """How many tokens remain for private-PDF evidence.

        `already_used_tokens` is the *measured* size of everything else that
        will share the same request (system prompt, schema instructions,
        trusted evidence, user question) - not a guess. The private budget is
        bounded by both the configured ceiling and by whatever room is
        actually left in the overall input budget, whichever is smaller.
        """
        remaining = self.available_input_tokens - already_used_tokens
        return max(0, min(self.private_pdf_ceiling_tokens, remaining))


def resolve_token_budget(settings: Settings) -> TokenBudget:
    return TokenBudget(
        context_tokens=settings.legalai_product_max_input_tokens,
        reserved_output_tokens=settings.legalai_llm_reserved_output_tokens,
        safety_margin_tokens=settings.legalai_llm_context_safety_margin_tokens,
        private_pdf_ceiling_tokens=settings.private_pdf_input_budget_tokens,
        trusted_evidence_ceiling_tokens=settings.trusted_evidence_input_budget_tokens,
    )
