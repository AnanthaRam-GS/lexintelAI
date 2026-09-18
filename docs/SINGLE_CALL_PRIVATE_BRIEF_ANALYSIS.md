# Single-Call Professional PDF Analysis

## The problem this replaces

Whole-document Professional Upload Brief analysis (`analysis_mode=brief` on
`POST /query/professional/pdf`) previously worked in two provider-calling stages:

```
PDF -> bounded chunk batches -> ONE Groq/Gemini call PER BATCH (Stage 1)
     -> deterministic reduction -> ONE Groq/Gemini call for the final brief (Stage 2)
```

This was context-safe (each batch call stayed within its own token budget), but
provider-expensive: a real multi-page FIR or chargesheet with 40+ chunks and a
`PRIVATE_PDF_MAX_CHUNKS_PER_BATCH=8` cap needed 5-10+ Stage-1 calls before the
single Stage-2 call - all within one browser request, rapidly consuming a
rate-limited provider account's usage (the same ~8k-token/request Groq free tier
this project has been tuning against throughout).

## The fix

Stage 1 is now **entirely local** - zero provider calls, regardless of document
length:

```
PDF -> parse/chunk (unchanged)
     -> local document-map construction (local_document_map.py, NEW, zero provider calls)
          - deterministic document-type heuristic (filename + text markers)
          - deterministic statutory-section/party/date extraction
            (legal_ner.extract_deterministic_entities - already existed,
             regex/pattern-based, no InLegalBERT, no model)
          - multi-intent BGE-M3 (or lexical-fallback) retrieval over 9
            predefined internal intents, reusing
            private_pdf_rag.select_query_focused_private_evidence
     -> enriched trusted-corpus retrieval query built from the map
     -> normal (frozen, unchanged) retrieval: candidate 20 -> RRF -> reranker -> top 5
     -> normal (frozen, unchanged) product-wide evidence budgeting
     -> ONE bounded generative call for the final professional brief
```

Every whole-document brief request now makes **exactly the same number of
provider calls as every other query path: one.**

## What moved where

- `backend/app/services/local_document_map.py` (new): builds the local,
  non-generative document map. Never imports or calls any
  `LegalAnswerModelAdapter` - structurally incapable of making a provider call,
  not just untested (`test_zero_provider_calls_ever` verifies the module's own
  source never references `generate_structured_answer` or an adapter).
- `backend/app/services/private_pdf_rag.py`: the old per-batch generative
  Stage-1/Stage-2 functions (`batch_private_chunks`, `generate_stage1_batch_summaries`,
  `PrivateDocumentBatchSummary`, `reduce_stage1_batches`, `PrivateDocumentMap`,
  `render_private_document_map`, `select_representative_excerpts`,
  `HierarchicalDocumentAnalysis`) are removed - they became entirely dead code.
  `build_private_chunks` and `select_query_focused_private_evidence` (question-
  focused mode, and now reused by the new multi-intent retrieval) are unchanged.
- `backend/app/api/query.py`: `build_whole_document_brief_context_builder`
  (which ran Stage 1/2) is replaced by `build_local_map_context_builder`, which
  only measures and renders an *already-built* local map - no adapter
  parameter, because it never needs one.

## Local document map contents

```python
LocalDocumentMap(
    document_type: str,               # FIR | chargesheet | judgment | appeal | petition | order | unknown
    parties: list[str],
    important_dates: list[str],
    explicit_sections: list[str],      # sections MENTIONED in the document - never asserted as applicable law
    material_facts: list[MapExcerpt],
    allegations: list[MapExcerpt],
    charges: list[MapExcerpt],
    evidence_excerpts: list[MapExcerpt],
    witness_excerpts: list[MapExcerpt],
    medical_forensic_excerpts: list[MapExcerpt],
    investigation_excerpts: list[MapExcerpt],
    defence_or_accused_position: list[MapExcerpt],
    findings_or_orders: list[MapExcerpt],
    important_chunk_ids: list[str],    # P# ids, for traceability
    important_pages: list[str],
)
```

Every field is capped (`_MAX_ENTRIES_PER_FIELD=6`, `_MAX_EXCERPT_CHARS=500`,
`_MAX_PARTIES=10`, `_MAX_DATES=10`, `_MAX_SECTIONS=15`) and empty fields are
returned as empty lists, never invented content, when nothing relevant is found.

### Multi-intent retrieval, deduplicated under one global budget

Nine predefined internal intents (material facts, parties, procedural
history/investigation, charges/offences, witnesses, medical/forensic evidence,
defence position, findings, relief/order) are each embedded and ranked locally
via the existing `select_query_focused_private_evidence` (BGE-M3, reused from
the retrieval service already loaded for trusted retrieval, or lexical fallback)
- **never sent to any external LLM**. A chunk already claimed by an earlier
intent is never claimed again by a later one, and every intent draws from the
**same** global token budget rather than each getting its own independent
allowance, so a handful of intents cannot exhaust the budget while starving the
rest of document coverage.

### Explicit sections != applicable law

Statutory sections in `explicit_sections` come from
`legal_ner.extract_deterministic_entities` - regex/pattern matching, already
used elsewhere in LegalAI, no InLegalBERT, no model call. They are sections
*mentioned in the uploaded document*, rendered with an explicit note
("not verified applicable law") - the trusted corpus (`E#`) remains the only
source of verified legal authority, exactly as before.

## Enriched trusted-retrieval query

Previously, brief mode always retrieved trusted evidence using the frontend's
generic placeholder text ("Analyze this legal document."), regardless of what
the document actually contained. Now, `build_enriched_trusted_query()` builds
the retrieval query from the local map's explicit sections, charges, and
material facts - falling back to the placeholder only if the map is empty.
This still flows into the completely unchanged (frozen) retrieval pipeline
(candidate depth 20 -> RRF -> BGE reranker -> top 5); it never bypasses or
re-ranks retrieval itself.

## Provider usage safety

- **Normal success path:** exactly 1 provider call for brief mode, question-
  focused PDF mode, public/professional text, and public PDF - verified by a
  single consolidated test (`test_all_four_query_paths_make_exactly_one_provider_call_on_success`)
  plus a dedicated brief-mode test with a 40-chunk document
  (`test_professional_pdf_whole_document_brief_mode_makes_zero_stage1_and_exactly_one_final_provider_call`).
- **429 (quota exceeded):** no automatic retry - retrying immediately after a
  quota rejection would only make things worse. Exactly 1 call, then a
  controlled, safe error.
- **413 (request too large):** the existing product-wide one-reduced-tier
  retry (from `docs/PRODUCT_CONTEXT_BUDGETING.md`) still applies - maximum 2
  provider calls total, never more, and it was already implemented before
  this change; nothing new was added for it here.

## Error handling

`LOCAL_DOCUMENT_ANALYSIS_FAILED` (500) is now distinct from `PDF_PARSE_FAILED`,
`PDF_NO_TEXT`, and any `MODEL_PROVIDER_*` code - a failure while building the
local map (parsing/NER/ranking) is neither a provider problem nor a document-
size problem, and must not be mislabeled as either.

## Privacy (unchanged)

Still never touches the global ChromaDB collection, the global BM25 index, an
ingestion job, or persists raw PDF text/bytes anywhere - `local_document_map.py`
never imports `ingestion.py` or the vector-store/BM25-mutation code paths. The
document map itself is a plain Python dataclass, built and discarded within one
request; nothing is written to disk.

## Frozen benchmark

Unaffected. `local_document_map.py` only imports read-only from `legal_ner.py`
and `query_analysis.py` (neither is frozen) and from this project's own prior
additive module `private_pdf_rag.py`. None of the 5 pinned files
(`legal_answer_prompt.py`, `legal_answer_generation.py`,
`legal_citation_validation.py`, `legal_rag_retrieval.py`,
`legal_query_understanding.py`) are touched, and their component hashes in
`data/structured/manifests/legal_answer_eval.json` remain valid.

## Known limitations

- **Document-type detection is simple keyword presence, not weighted.** A
  judgment that happens to mention "FIR No. ..." within its text (very common,
  since judgments describe the underlying case) can be misclassified as an FIR
  rather than a judgment/order. Observed live: a Supreme Court bail order was
  classified as "FIR" for this reason. This does not affect correctness of the
  final answer (the document type is descriptive metadata, not used to gate
  any other logic), but it is worth knowing about.
- **PERSON-name extraction is weaker than role-word extraction.** The
  deterministic NER reused here (`legal_ner.py`) is tuned for query-style text;
  on document prose it more reliably catches role words ("accused",
  "complainant") than proper names. Named parties are best obtained from the
  document excerpts themselves (which the final generator can read), not
  solely from the `parties` field.
- **Intent-claiming order can leave some fields empty on short documents.**
  With very few chunks, chunks claimed by earlier intents (material facts,
  investigation) may leave nothing for later intents (e.g. defence position,
  findings) even if relevant content exists nearby. This matters less on real
  multi-page documents, where there are enough chunks for broad coverage.
