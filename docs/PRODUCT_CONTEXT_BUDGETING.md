# Product-Wide Generation Context Budgeting

## The regression this fixes

The bounded private-PDF work (`docs/PRIVATE_PDF_CONTEXT_BUDGETING.md`) bounded the
*extra* context a PDF upload adds on top of whatever trusted-evidence prompt the
(frozen) retrieval pipeline built - but it never bounded the trusted-evidence prompt
itself. Live browser testing then showed an ordinary **text-only** professional
query, with no PDF involved at all, could still fail:

> "The document or retrieved context is too large for the configured answer provider."

Example: `"What is POCSO Act and what are the sections related to it"`.

Traced (no live provider call, `backend/app/services/token_budget.estimate_tokens`
only) for this exact query against the real trusted corpus:

| Component | Estimated tokens |
|---|---|
| user query | 17 |
| trusted evidence (E1-E5, ~700-980 each) | 4630 |
| prompt overhead (system rules, XML tags, query context) | 952 |
| structured-output schema (`ProfessionalLegalBrief`) | 471 |
| **total** | **~6070** |

This is dominated by **A: trusted evidence** (4630 of ~6070 tokens), not schema or
prompt overhead, which are both comparatively small and roughly constant regardless
of query. Whether this specific total actually gets rejected depends on the
provider account's real capacity at that moment (a rolling tokens-per-minute limit,
not a fixed per-request wall) - but nothing was bounding it beforehand either way.

## The fix

`backend/app/services/product_context_budget.py` (new, additive, outside the 5
frozen files) bounds the **already-retrieved, already-reranked** top-5 trusted
evidence to a product-wide budget, in `run_frozen_query_pipeline()`
(`backend/app/api/query.py`) - which every one of the four query paths
(`/query/public`, `/query/professional`, `/query/public/pdf`,
`/query/professional/pdf`) funnels through. Retrieval, RRF fusion, and reranking
are completely unchanged (frozen); this only decides how much of the *already-
ranked* result a live generation call actually receives.

```
candidate retrieval depth 20 -> RRF -> BGE reranker -> top 5   (frozen, unchanged)
                                                          |
                                                          v
                              bound_trusted_evidence(budget)   (new, additive)
                                                          |
                                                          v
                        build_grounded_evidence_packet -> prompt   (frozen, unchanged)
                                                          |
                                                          v
                                    generate_legal_answer   (frozen, unchanged)
```

### How `legal_rag_retrieval.LegalRetrievalResult` is bounded without editing it

`LegalRetrievalResult` and `LegalEvidenceChunk` are frozen-file Pydantic models -
but *using* a frozen class (constructing a new instance, or `.model_copy()`-ing an
existing one) doesn't touch the file that defines it, so its hash is unaffected.
`bound_trusted_evidence()` takes the retrieval result exactly as
`retrieve_legal_evidence()` (frozen) returned it, and produces a **new** copy whose
`.evidence` list is trimmed/excerpted - the original is never mutated. That
trimmed copy is used for *both* prompt construction (`build_grounded_evidence_packet`)
and generation (`generate_legal_answer`), so the frozen citation-validation logic
(`validate_legal_answer_citations`) automatically and correctly rejects any
citation to evidence that wasn't actually supplied - for free, with zero changes to
the frozen validator.

### Rank order is never touched

Evidence is included strictly in existing rank order - E1, then E2, then E3, ... -
until the budget runs out. A higher-ranked item is never dropped to make room for a
lower-ranked one. If an item doesn't fit whole, it is excerpted (see below) and
that's where inclusion stops; the next-ranked item after a partial excerpt is never
reached, since the budget is already spent. Scores and rankings themselves are
never recomputed or altered.

### Excerpting an oversized chunk

Never an arbitrary `text[:N]`. `excerpt_at_boundary()` prefers, in order:

1. Complete paragraphs (split on blank lines) that fit the remaining budget.
2. Complete sentences (regex sentence-boundary split) that fit.
3. Only if neither structural boundary exists within budget (e.g. one giant
   unbroken paragraph) - a bounded character cutoff, as a last resort.

Source metadata (`case_name`, `court`, `source_url`, `paragraph_start/end`, the
citation id itself) is always preserved unchanged on an excerpted item - only
`.text` is shortened.

## Product context budget

`ProductContextBudget` (`product_context_budget.py`), resolved from `Settings`:

| Setting | Meaning |
|---|---|
| `LEGALAI_PRODUCT_MAX_INPUT_TOKENS` | Total app-level input budget for one generative call - independent of the model's advertised context |
| `LEGALAI_LLM_RESERVED_OUTPUT_TOKENS` | Reserved for the model's response (shared with the private-PDF budget) |
| `LEGALAI_LLM_CONTEXT_SAFETY_MARGIN_TOKENS` | Extra buffer, since token estimation is approximate (shared) |
| `PROMPT_OVERHEAD_RESERVE_TOKENS` | Fixed reserve covering system-prompt + XML-tag overhead *and* the structured-output schema - both are roughly query-independent, so a conservative constant avoids a chicken-and-egg measurement problem (the schema/overhead size is known ahead of building the prompt; the trusted-evidence size is what actually varies per query) |
| `TRUSTED_EVIDENCE_INPUT_BUDGET_TOKENS` | Ceiling on trusted evidence for one request - now **actively enforced**, not informational (see the update note in `docs/PRIVATE_PDF_CONTEXT_BUDGETING.md`) |

`available_input_tokens = max_input_tokens - reserved_output - safety_margin - prompt_overhead_reserve`,
and `trusted_evidence_budget = min(TRUSTED_EVIDENCE_INPUT_BUDGET_TOKENS, available_input_tokens - query_tokens)`.

**These are generic starting defaults, not a Groq-specific constant.** `8000` is
never hardcoded anywhere in this module or in business logic - it was simply the
real capacity observed on the account this was built against (Groq's free
on-demand tier). A deployment on a larger tier, or on Gemini, should raise
`LEGALAI_PRODUCT_MAX_INPUT_TOKENS` accordingly; inspect your own account's actual
capacity rather than copying the numbers below.

### Deriving conservative local values

Given the measured composition above (prompt overhead ~950, schema ~470, so
`PROMPT_OVERHEAD_RESERVE_TOKENS≈1500` covers both with margin) and a target of
staying comfortably under an ~8,000-token account ceiling:

```
LEGALAI_PRODUCT_MAX_INPUT_TOKENS=7200
LEGALAI_LLM_RESERVED_OUTPUT_TOKENS=1200
LEGALAI_LLM_CONTEXT_SAFETY_MARGIN_TOKENS=300
PROMPT_OVERHEAD_RESERVE_TOKENS=1500
TRUSTED_EVIDENCE_INPUT_BUDGET_TOKENS=4000
PRIVATE_PDF_INPUT_BUDGET_TOKENS=1500
```

→ `available_input_tokens = 4200`, `trusted_evidence_budget ≈ 4000` - enough for
all 5 trusted chunks in the POCSO example (they needed 4630 combined; the 5th is
excerpted to fit), keeping the total request at ~5400-6600 tokens including
overhead and schema, safely under the observed ~8,000 ceiling.

## Combining private-PDF and trusted-evidence budgets

Both budgets draw from the **same** underlying pool: `run_frozen_query_pipeline()`
bounds trusted evidence *first*, builds the resulting (now-bounded) prompt, then
invokes the private-PDF `private_context_builder` callback with that prompt's real
measured size - so the private-PDF budget (`token_budget.TokenBudget`) is
automatically computed against whatever room the (already-bounded) trusted
evidence actually left, not an independent, unlimited assumption on either side.
`private evidence + trusted evidence + prompt/schema` is checked against one
shared ceiling by construction, not by a separate reconciliation step.

## Adaptive context tiers - one bounded retry, never a loop

`ContextTier.NORMAL` is tried first. If the provider still rejects the resulting
(already-bounded) request as too large - its account limits may differ from our
estimate - `run_frozen_query_pipeline()` detects any provider warning code ending
in `_REQUEST_TOO_LARGE` and retries **exactly once** with `ContextTier.REDUCED`:
trusted-evidence ceiling halved, and any optional private-PDF content dropped
entirely (it's supplementary to trusted grounding, not the primary answer source).
No further retries, no silent provider switch, no change to retrieval ranking.

If the REDUCED-tier retry also fails, the sanitized `MODEL_PROVIDER_REQUEST_TOO_LARGE`
(413) error is the final safety net - see Error Copy below.

## Error copy

The previous message ("The document or retrieved context is too large...") was
misleading for a text-only query with no document at all. It's now:

> "The legal research context exceeded the current AI provider capacity. LegalAI
> has reduced the evidence automatically; please retry if the provider remains busy."

This should rarely surface in practice, since automatic bounding plus the one
reduced-tier retry already try to prevent it - it is a final safety net, not the
normal budgeting mechanism. The separate `PDF_CONTEXT_TOO_LARGE` code (whole-
document professional brief mode only, when even the bounded hierarchical summary
genuinely cannot fit) keeps its document-specific wording, since that case really
is about one specific document.

## Observability

`log_product_context_metrics()` logs, per request: provider, model, `context_tier`
(`normal`/`reduced`), trusted-evidence count and estimated tokens, provider status,
and latency. It never logs query text, evidence text, PDF content, or API keys.

## Frozen benchmark

Unaffected. `product_context_budget.py` only *constructs new instances* of frozen
Pydantic models via their public constructors - it never edits
`legal_answer_prompt.py`, `legal_answer_generation.py`,
`legal_citation_validation.py`, `legal_rag_retrieval.py`, or
`legal_query_understanding.py`. All 5 component hashes in
`data/structured/manifests/legal_answer_eval.json` remain valid.
