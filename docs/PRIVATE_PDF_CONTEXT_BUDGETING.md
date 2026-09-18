# Private PDF Context Budgeting & Hierarchical Brief Generation

## The problem this replaces

**OLD:** `POST /query/public/pdf` and `POST /query/professional/pdf` selected private
PDF excerpts by simple keyword overlap, then truncated the combined excerpt text to a
fixed character limit (12,000 chars, ~8 chunks) with no awareness of how large the
trusted-evidence portion of the prompt already was. Uploaded PDF text + trusted-corpus
retrieval evidence + system prompt + structured-output schema could together exceed the
configured generative model's practical context budget, surfacing as an opaque
provider-side rejection (e.g. Groq's `413 Request too large` / tokens-per-minute limit).

**NEW:**

```
PDF → temporary chunking → bounded private retrieval → context budgeting
    → (whole-document professional brief mode only) hierarchical analysis
```

Every private-PDF request now measures its own size and fits within an
application-level budget *before* calling the provider, rather than hoping the
provider accepts whatever was concatenated.

## Architectural boundary

Private PDFs are chunked and (optionally) embedded entirely **in-memory, for the
duration of one request**. They never:

- get added to the global ChromaDB collection or the global BM25 index
- become an ingestion job
- get treated as trusted corpus / precedent authority
- get persisted as raw text in query history (query history stores only the
  question text and the structured response, unchanged from before)
- get reused across requests, users, or sessions

`backend/app/services/private_pdf_rag.py` never imports anything from
`backend/app/services/ingestion.py` or the vector-store/BM25-mutation code paths -
this is enforced by tests (`test_no_global_chroma_or_bm25_mutation`,
`test_professional_pdf_does_not_mutate_global_corpus_or_ingestion`).

### P# vs E#

| | `P#` (e.g. `P1`, `P2`) | `E#` (e.g. `E1`, `E2`) |
|---|---|---|
| Source | The uploaded, temporary PDF | The trusted, retrievable legal corpus |
| Lifetime | One request | Permanent (indexed corpus) |
| May be cited as legal authority? | **No, never** | Yes - the only source of precedent |
| Role | Describes the uploaded document's own facts/arguments/procedural history | Grounds legal claims, precedent, and statutory analysis |

The two id spaces never merge. Every private-evidence block rendered into a prompt
carries an explicit instruction that `P#` evidence is untrusted, user-provided, and
must never be cited as precedent (`render_private_evidence_block` in
`private_pdf_rag.py`). Statutory sections *mentioned inside* an uploaded document are
recorded as document mentions only, never asserted as verified applicable law -
that determination still comes exclusively from trusted retrieval (`E#`) and the
existing (frozen) legal-regime resolver.

## Token budgeting

`backend/app/services/token_budget.py` resolves a `TokenBudget` from `Settings`,
independent of any provider's advertised maximum context - a provider, or a
rate-limited account tier, may accept far less than a model's nominal context in
practice (this is exactly what happened with the Groq account this was built
against: an 8,000 tokens-per-minute tier limit, well under the model's real context
window).

| Setting | Default | Meaning |
|---|---|---|
| `LEGALAI_PRODUCT_MAX_INPUT_TOKENS` | 40000 | Total app-level context budget for one generative call |
| `LEGALAI_LLM_RESERVED_OUTPUT_TOKENS` | 6000 | Reserved for the model's response |
| `LEGALAI_LLM_CONTEXT_SAFETY_MARGIN_TOKENS` | 4000 | Extra buffer, since token estimation is approximate |
| `PRIVATE_PDF_INPUT_BUDGET_TOKENS` | 18000 | Ceiling on private-PDF evidence in one request |
| `TRUSTED_EVIDENCE_INPUT_BUDGET_TOKENS` | 10000 | Informational ceiling on trusted-evidence size (see limitation below) |
| `PRIVATE_PDF_TOP_K` | 10 | Max private chunks selected in question-focused mode |
| `PRIVATE_PDF_MAX_CHUNKS_PER_BATCH` | 8 | Max chunks per Stage-1 hierarchical batch |

These are starting points, not model-specific truths - inspect your actual
prompt/schema size and your provider/account tier before changing them. They are
never hardcoded into business logic; every consumer reads them from `Settings`.

**Token estimator:** `estimate_tokens()` reuses the same word-count-based
approximation already used throughout the trusted-corpus chunking pipeline
(`backend/scripts/process_judgment_corpus.py::estimated_tokens`, ~1.25 tokens/word),
with an additional 1.15x structural-overhead multiplier (JSON/XML tags tokenize
denser than prose). It does not need to exactly match Groq's or Gemini's real
tokenizer - it only needs to bias toward overestimating, which the multiplier
reinforces. No online tokenizer service is used or required.

**Budgeting is measured, not guessed:** `run_frozen_query_pipeline()` in
`backend/app/api/query.py` builds the trusted-evidence prompt first (via the frozen
`build_legal_answer_prompt`), *then* invokes a `private_context_builder(prompt_text)`
callback with that prompt's real estimated token count. The private-PDF budget is
computed as whatever room is actually left (`TokenBudget.private_pdf_budget`), capped
by `PRIVATE_PDF_INPUT_BUDGET_TOKENS` - not a static split decided before trusted
retrieval even ran.

**Update - trusted-evidence budgeting is now actively enforced.** This section
previously reported `TRUSTED_EVIDENCE_INPUT_BUDGET_TOKENS` as informational-only,
because the code that *renders* trusted evidence into the prompt
(`legal_answer_prompt.py`, `legal_rag_retrieval.py`) is frozen-hash-pinned and
couldn't be edited to truncate it. That gap is now closed additively, without
touching either frozen file: `backend/app/services/product_context_budget.py`
bounds `retrieval.evidence` itself - in strict rank order, excerpting an
individual oversized chunk at a paragraph/sentence boundary rather than dropping
it - *before* `build_legal_answer_prompt` ever sees it. See
`docs/PRODUCT_CONTEXT_BUDGETING.md` for the full design; this is what fixed
plain text queries (no PDF at all) that were retrieving large trusted evidence
and exceeding a rate-limited account's real capacity.

## Public PDF flow (`POST /query/public/pdf`)

Always question-focused - the user explicitly asked a question, so targeted
retrieval is preferred over whole-document analysis:

```
query + PDF → temporary parse/chunk → rank chunks against the query
   (BGE-M3 embeddings reused in-memory from the existing retrieval service,
    falling back to lexical keyword scoring if no embedding provider is available)
   → bounded, budgeted P# selection → trusted retrieval (unchanged)
   → LLM → public grounded answer
```

## Professional PDF flow (`POST /query/professional/pdf`)

New `analysis_mode` form field (`"question"` default, or `"brief"`):

- **`analysis_mode=question`** - identical targeted-retrieval approach to public PDF.
- **`analysis_mode=brief`** - whole-document hierarchical analysis (used by the
  Professional Upload Brief page, which never collects a specific question).

### Hierarchical whole-document brief mode

```
Stage 1 (local document map):
  private chunks → bounded batches (count-capped AND token-budget-capped)
    → one adapter call per batch → compact structured extraction
      (material facts, parties, procedural history, legal issues,
       statutory mentions, arguments, findings, relief, dates,
       evidentiary observations)
  → deterministic reduction (dedupe + cap each field at 25 entries)
    into one compact PrivateDocumentMap

Stage 2 (final brief):
  compact document map + a handful of representative excerpts (one per batch)
    + trusted corpus retrieval (unchanged, frozen)
  → the existing (frozen) grounded-answer generation pipeline, unchanged
  → normal ProfessionalLegalBrief response
```

Reduction is a **deterministic structural merge**, not another provider call - the
batch summaries are already compact structured lists, so deduping and capping them
keeps growth bounded without adding more generative round-trips or making the
pipeline depend on a second live call to test.

If, after this bounded hierarchical processing, the compact document map still
cannot fit the private-PDF budget (a pathological configuration - the map is already
capped), the request fails cleanly with `PDF_CONTEXT_TOO_LARGE` rather than sending
an oversized request and hoping.

## Error codes

| Code | Meaning | HTTP |
|---|---|---|
| `PDF_NO_TEXT` | PDF has no extractable text (e.g. scanned/image-only) | 422 |
| `PDF_PARSE_FAILED` | PDF is unreadable/corrupt/wrong type | 422 |
| `PDF_CHUNKING_FAILED` | Parsed but could not be chunked | 422 |
| `PDF_CONTEXT_TOO_LARGE` | Bounded/hierarchical processing genuinely could not fit the budget (rare) | 413 |
| `MODEL_PROVIDER_QUOTA_EXCEEDED` | 429 from the provider | 429 |
| `MODEL_PROVIDER_AUTH_ERROR` | 401/403 from the provider | 503 |
| `MODEL_PROVIDER_TIMEOUT` | Provider did not respond in time | 503 |
| `MODEL_PROVIDER_UNAVAILABLE` | Upstream 5xx / network failure | 503 |
| `MODEL_PROVIDER_ERROR` | Other provider/schema failure | 503 |

`PDF_NO_TEXT` and `PDF_PARSE_FAILED` were previously the same code
(`PDF_PARSE_FAILED`) - they are now distinguished by parse-failure message content
in `http_exception_for_pdf_parsing_error()`.

## Provider compatibility

Everything in `private_pdf_rag.py` and `token_budget.py` is provider-agnostic - it
builds plain prompt text and calls whatever `LegalAnswerModelAdapter`-shaped adapter
it is given (`GeminiAnswerAdapter` or `GroqAnswerAdapter`). Stage 1 reuses the exact
same generic `adapter.generate_structured_answer()` / `parse_model_payload()`
machinery the frozen pipeline already uses for any Pydantic schema, so no
provider-specific code exists in the hierarchical pipeline. The frozen Phase-0
Gemini-only grounded-answer benchmark is untouched and unaffected - this feature is
part of the product runtime pipeline (`backend/app/api/query.py`), not the benchmark
harness (`backend/scripts/run_grounded_answer_eval_generation.py`).

## Observability

`log_private_pdf_metrics()` in `query.py` logs, per request, only bounded counts and
token estimates: PDF page count, extracted text length, private chunk count,
selected chunk count, estimated private tokens, the frozen prompt's measured token
count, the private budget, and the Stage-1 batch count. It never logs PDF content,
chunk text, prompts, or API keys.
