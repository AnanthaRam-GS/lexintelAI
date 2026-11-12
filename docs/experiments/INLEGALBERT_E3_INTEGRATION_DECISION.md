# InLegalBERT E3: where NER output is consumed, and the integration points (decided before measuring)

Written on 2026-11-12, after inspecting the code on `main` (`5be9d5e`, with E1 merged) and before writing any
integration code or running any E3 measurement. The E3 criteria in `INLEGALBERT_PLAN.md` are unchanged.

## 1. Where NER runs today

There are only two callers of `legal_ner.extract_deterministic_entities` in the product (`backend/app`).

### 1a. Query understanding (every query)

- **Where:** `legal_query_understanding.understand_legal_query()` puts its output in
  `LegalQueryUnderstanding.entities`. The query API calls it with `section_ranking_mode="deterministic"`
  (`api/query.py`).
- **Types used:** all 14 canonical types are stored. **Nothing reads `entities` afterwards.**
  - **Retrieval.** `legal_rag_retrieval.retrieve_legal_evidence()` sends only `understanding.query`, the original
    text, to the frozen hybrid + rerank stack. Its summary declares `retrieval_query_policy="original_query_only"` and
    `query_expansion_enabled=False`.
  - **Prompts and answer generation.** They read `explicit_sections`, `legal_regime`, `offence_families`,
    `procedural_posture`, `predicted_sections` and `normalized_query`. These come from `query_analysis` and the regime
    resolver, not from NER.
  - **API response and frontend.** The entity list is not exposed.
- **What a richer entity set would change: nothing** with the current code.
  - Entities could affect retrieval only through query enrichment (adding entity text to the retrieval query).
  - That was tested in T1-B (`docs/RETRIEVAL_TUNING_DECISION.md`). Every expansion variant lowered broad P@5
    (0.870 → 0.850) and nDCG@5 (0.723 → 0.700–0.716), and it was rejected.
  - The retrieval configuration (`retrieval_selected_configuration.json`) and `legal_rag_retrieval.py` are
    hash-pinned.
  - Adding enrichment now would be a new retrieval policy chosen after seeing E1, not the frozen E3 test.
- **Pinned file.** `legal_query_understanding.py` itself is hash-pinned in `legal_answer_eval.json`
  (`component_hashes`), so it cannot be edited.

### 1b. Private-PDF document map (professional PDF brief and whole-document mode)

- **Where:** `local_document_map.extract_sections_and_entities()` calls the NER once per private chunk. The types it
  reads go into three fields:

| NER types | Field | Where the field goes |
|---|---|---|
| SECTION, STATUTE | `explicit_sections` | the map's `statutory_sections_explicitly_mentioned` line in the prompt, and `build_enriched_trusted_query()`, the retrieval query for trusted evidence in whole-document mode |
| PERSON, LEGAL_ROLE, ORGANIZATION | `parties`, a flat name list | the prompt's `parties:` line, but **only when `parties_and_roles` is empty**; `local_map_metrics` counts |
| DATE | `important_dates` | the prompt's `important_dates:` line, but **only when `chronology` is empty**; `local_map_metrics` counts |

- **Fields NER does not feed.** Party detection with roles (`parties_and_roles`), the chronology, procedural stages
  and evidence items come from separate regex detectors (`extract_parties_and_roles`, `extract_chronology`, …). They
  feed the brief's fields (`professional_brief.parties_and_roles`, `chronology`, `procedural_considerations`,
  `evidence_identified`) and every field of the brief fixtures' `*.expected.json`.
- **What a richer entity set would change:**
  - **`explicit_sections`: no change.** Under the frozen E1 combination policy, STATUTE and SECTION are rule-owned:
    model spans of those types are never inserted, and a model span overlapping one is dropped. So the trusted
    retrieval query in whole-document mode cannot change.
  - **`parties`: more names.** InLegalNER contributes PERSON and ORGANIZATION, where the rules find almost none
    (E1: +3 PERSON and +4 ORGANIZATION on gold). This reaches the prompt only for documents where no party with a
    role was detected.
  - **`important_dates`:** possibly better DATE boundaries (E1: DATE F1 0.44 → 0.67). This reaches the prompt only
    when the chronology is empty.

### 1c. Anything else

There is no other product consumer: `grep` over `backend/app` and `frontend`. The evaluation and trial scripts
(`backend/scripts/*`) call the deterministic NER on purpose, as the frozen D0 baseline, and are not changed.

## 2. Decision

**`LEGALAI_NER_BACKEND`:**
- **Values:** `deterministic` (the default, unchanged) or `combined`.
- **Implementation:** one module, `backend/app/services/ner_backend.py`, provides `extract_entities(text)`. With
  `deterministic` it returns exactly `extract_deterministic_entities(text)`. With `combined` it applies the E1
  combination policy unchanged: E1 seed 22's checkpoint, the frozen mapping, and `merge_hybrid_entities` in `hybrid`
  mode at threshold 0.70.

**Integration points:**
1. **Private-PDF document map (the primary point).**
   - `extract_sections_and_entities` calls `ner_backend.extract_entities` per chunk.
   - This is the only place where entity types reach a user-visible output (the brief prompt's party and date
     fallbacks).
   - The brief check (no fixture may lose an expected item) and the per-field comparison measure it.
2. **Query understanding (secondary; for consistency and to measure its cost).**
   - The query API replaces `understanding.entities` with `ner_backend.extract_entities(query)` right after
     `understand_legal_query()`, in `api/query.py`. The pinned `legal_query_understanding.py` is not edited.
   - Because nothing reads `entities`, **retrieval cannot change by construction**. The 30-query retrieval check is
     still run, flag off and on, through the real query path to confirm this.
   - The query-side model call is pure cost under the shared inference lock, which the cost measurements quantify.

**Not integrated:**
- **Query enrichment for retrieval.** It was rejected in T1-B, the retrieval files are pinned, and it would be a new
  policy chosen after E1.
- **Party-role detection from InLegalNER's native PETITIONER, RESPONDENT, JUDGE, LAWYER and WITNESS labels.**
  - The frozen E1 mapping collapses these to PERSON or ORGANIZATION. Using them for roles would be a new, unfrozen
    mapping, and it would need its own gold.
  - Recorded as an open option for the user.
- **Changes to `explicit_sections`.** They are protected by the policy, so none happen.

**Runtime rules for `combined`:**
- **Checkpoint and integrity.** Load `models/inlegalbert_ner/seed-22/` (gitignored). Before loading, check
  `model.safetensors` against sha256 `427c3fd99c8b98c73b4adc161794e49ef39c852052a28ac6ed7c2d8ec9be0a4c`.
- **Device and lock.** The device comes from `LEGALAI_MODEL_DEVICE` (MPS, with CPU fallback via
  `model_device.DeviceFallbackModel`), in fp32 as trained. Every load and every inference holds the step-18
  inference lock.
- **Warm-up.** When `LEGALAI_MODEL_WARMUP` is on, the model loads and runs one tiny inference at startup.
- **Windowing.** It is the same as E1: 256-token windows, stride 64, batches of 32 windows, and the label taken from
  the window where the token is most central.
- **Fallback.** A missing or mismatched checkpoint, a failed load, a missing dependency, a lock timeout or an
  inference error falls back to the deterministic entities, with a logged warning. `/health` reports it under
  `ner`. A query never fails because of NER.

**The default stays `deterministic`.** The recommendation on the default follows the measurements, in
`INLEGALBERT_E3_RESULTS.md`.
