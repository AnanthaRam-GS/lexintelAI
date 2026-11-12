# InLegalBERT E3: flagged NER integration, retrieval, briefs and cost

Status: **UNREVIEWED**, measured on 2026-11-12. No LLM calls were made, and nothing was retrained or retuned. The
default stays `LEGALAI_NER_BACKEND=deterministic`. The E3 criteria in `INLEGALBERT_PLAN.md` (section 6) are unchanged.

**Summary:**

| Check | Rule | Result |
|---|---|---|
| Retrieval, 30 frozen queries | no drop in P@5 or nDCG@5; a gain needs ΔnDCG@5 ≥ +0.02 with CI > 0 | **PASS** (no drop); **no gain**: rankings identical, Δ = 0 |
| Briefs, 5 fixtures + scanned FIR | no fixture loses an expected item | **PASS**: 0 lost and 0 gained expected items |
| Cost | no crash; impact stated | **PASS**: 0 crashes in 5 × 45 stress requests; +~10–13 ms per query; +~0.84 GB process footprint; startup unchanged |
| **Recommendation** | | **keep `deterministic` as the default** (section 7) |

## 1. Integration, decided before measuring

The decision, with the inspection behind it, is in `INLEGALBERT_E3_INTEGRATION_DECISION.md`. Commit order:

| Commit | What |
|---|---|
| `919d5fe` | inspection and integration-point decision (docs only) |
| `a92c99f` | the flag, the integration and its unit tests |
| later | measurement scripts, results, this document |

**Where NER output goes today:**
- **Query understanding** stores entities that nothing reads. Retrieval sends only the original query
  (`original_query_only`; entity-based expansion was rejected in T1-B). The prompts use `query_analysis` fields, not
  NER.
- **The private-PDF document map** uses:
  - SECTION and STATUTE for `explicit_sections`;
  - PERSON, LEGAL_ROLE and ORGANIZATION for a flat `parties` list, which reaches the prompt only when no party with a
    role was found;
  - DATE for `important_dates`, which reaches the prompt only when the chronology is empty.

  The brief's own fields (parties and roles, chronology, stages, evidence) come from regex detectors, not NER.

**The flag:**
- **Values:** `LEGALAI_NER_BACKEND` = `deterministic` (default) | `combined`. New module:
  `backend/app/services/ner_backend.py`.
- **Wired into:**
  - the document map (`local_document_map.extract_sections_and_entities`);
  - the query API (`api/query.py` replaces `understanding.entities` after `understand_legal_query`; the hash-pinned
    `legal_query_understanding.py` is untouched);
  - `/health` (`ner`) and the startup warm-up (`main.py`).
- **What `combined` does:**
  - **Checkpoint:** loads E1 seed 22 from `models/inlegalbert_ner/seed-22/`, after checking `model.safetensors` against
    sha256 `427c3fd9…0a4c`.
  - **Device and lock:** runs on `LEGALAI_MODEL_DEVICE` (MPS, with CPU fallback via `DeviceFallbackModel`) in fp32.
    Every load and inference holds the step-18 inference lock.
  - **Windowing:** E1's (256 tokens, stride 64, batches of 32 windows, label from the most central window).
  - **Policy:** applies the frozen E1 mapping and `merge_hybrid_entities` (hybrid, 0.70).
- **Fidelity to E1.** The backend's predictions equal E1's `predict_entities` exactly on 35 non-gold texts (the 30
  retrieval queries and the 5 brief fixtures, including multi-window ones), with 62 entities in total.
- **Fallback.** A missing or mismatched checkpoint, a load failure, a missing dependency, a lock timeout or an
  inference error each produce the deterministic entities, a `legalai.ner` warning and `/health`
  `ner.fallback = true`. NER never fails a query.
- **Tests:** `backend/scripts/tests/test_ner_backend.py`, 16 tests with a mocked model:
  - flag off: unchanged result, no model loaded, query understanding object untouched;
  - flag on: the frozen policy applied, rule-owned SECTION and STATUTE kept, the party rule, the threshold,
    CASE_NUMBER dropped;
  - fallbacks: missing checkpoint, hash mismatch, load failure, inference error, lock timeout (per call and while
    loading);
  - warm-up;
  - lock usage, with a tiny real torch model: the load and every window batch hold `inference_slot`;
  - central-window decoding;
  - the document map following the flag.

**Erratum to the decision document and the E1 protocol.** The E1 protocol says model spans of rule-owned types "are
never inserted". In fact the unchanged merge lets a model span with *exactly the same boundaries* replace a
non-protected rule entity when its type has higher priority (`should_replace_same_span`).
- E1's scores were computed with this same code, so they stand.
- Example: on query eval-q010, "criminal conspiracy section 120B IPC", the rule OFFENCE "criminal conspiracy" became a
  model STATUTE.
- The decision document's claim that `explicit_sections` "cannot change" is therefore not guaranteed. It did not
  change on any brief fixture (section 3).

## 2. Retrieval check (frozen 30 queries, no LLM)

**Script:** `experiments/inlegalbert/e3_retrieval.py`; result in `experiments/inlegalbert/results/e3_retrieval.json`.
- **Path:** each query goes through the product query path (`understand_legal_query` + `with_backend_entities`).
  What the product sends to retrieval is retrieved by the frozen stack with the frozen pooling (MPS; reranker fp16, as
  in production).
- **Scoring:** the frozen metric code and labels.
- **CIs:** bootstrap over the 30 queries, 10,000 resamples, seed 20261111. The paired difference uses the same
  resamples.

**Flag off against the frozen benchmark (hybrid + rerank): identical.**
- Rankings are the same on 30/30 queries.
- P@5 0.873333, R@5 0.290110, R@20 0.723272, MRR@5 0.961111 and nDCG@5 0.819445 equal the frozen values exactly.

**Flag on against flag off:**

| Metric | `deterministic` [95% CI] | `combined` [95% CI] | Paired Δ [95% CI] |
|---|---|---|---|
| P@5 | 0.873 [0.800, 0.940] | 0.873 [0.800, 0.940] | 0.000 [0.000, 0.000] |
| R@5 (pooled) | 0.290 [0.265, 0.320] | 0.290 [0.265, 0.320] | 0.000 [0.000, 0.000] |
| R@20 (pooled) | 0.723 [0.674, 0.767] | 0.723 [0.674, 0.767] | 0.000 [0.000, 0.000] |
| MRR@5 | 0.961 [0.900, 1.000] | 0.961 [0.900, 1.000] | 0.000 [0.000, 0.000] |
| nDCG@5 | 0.819 [0.754, 0.878] | 0.819 [0.754, 0.878] | 0.000 [0.000, 0.000] |

- **Rank changes per query:** none. The top 20 is identical on 30/30 queries, and on every query the text sent to
  retrieval is the original query.
- **Entities:** the combined NER changed the entities of 1 of 30 queries (eval-q010, see the erratum). Nothing reads
  them.
- **Frozen E3 rule:**
  - No drop: P@5 0.873 ≥ 0.873 and nDCG@5 0.819 ≥ 0.814, so **PASS**.
  - Gain: ΔnDCG@5 = 0.000 [0.000, 0.000] < +0.02, so **no gain claimed**.

This is the expected outcome. Retrieval does not consume entities, by design and by the frozen configuration, so the
NER backend cannot move it.

## 3. Brief check (5 fixtures + scanned FIR, no LLM)

**Script:** `experiments/inlegalbert/e3_briefs.py`; result in `experiments/inlegalbert/results/e3_briefs.json`.
- **Inputs:** each fixture goes through the product parser, chunker and `build_local_document_map`. The dense
  provider is BGE-M3, the same for both runs. The scanned FIR goes through OCR and is compared with
  `fir.expected.json`.
- **Comparison:** expected items are checked as the fixture tests check them.

**Expected items found, per fixture and field.** The value is the same with the flag off and on, and equals the
expected count in every cell:

| Fixture | document type | parties (role + name) | dated events | procedural stages | evidence present | evidence absent | Lost | Gained |
|---|---|---|---|---|---|---|---|---|
| judgment | 1/1 | 2/2 | 4/4 | 4/4 | 0/0 | 3/3 | 0 | 0 |
| FIR | 1/1 | 2/2 | 2/2 | 2/2 | 3/3 | 1/1 | 0 | 0 |
| charge sheet | 1/1 | 3/3 | 6/6 | 5/5 | 4/4 | 1/1 | 0 | 0 |
| petition | 1/1 | 3/3 | 5/5 | 4/4 | 2/2 | 2/2 | 0 | 0 |
| unknown | 1/1 | 0/0 | 1/1 | 0/0 | 0/0 | 5/5 | 0 | 0 |
| FIR (scanned, OCR) | 1/1 | 2/2 | 2/2 | 2/2 | 3/3 | 1/1 | 0 | 0 |

- **Brief fields** (`parties_and_roles`, `chronology`, `procedural_considerations`, `evidence_identified`): identical
  off and on, on 6/6 fixtures.
- **Trusted retrieval query** built from the map: identical on 6/6. `explicit_sections` and `explicit_statutes` are
  unchanged on all six.

**Where the flag does change the map** (the NER-derived fields only):

| Fixture | `parties`, the flat list (gained) | `important_dates` | Rendered map sent to the model |
|---|---|---|---|
| judgment | NEELAM @ NEERAJ, STATE OF MADHYA PRADESH | — | unchanged (roles were found, so the list is not rendered) |
| FIR, scanned FIR | Meera Placeholder, Ravi Sampleton, Kiran Exampleton | — | unchanged |
| charge sheet | Asha Testwoman, Dev Fake, Sunil Mockwala | +10.01.2023, 20.01.2023, 02.02.2023 | unchanged (the chronology exists) |
| petition | Nikhil Placeholder, State of Fictionaland, Priya Testcase, "Police\nStation Hilltop" | +12.05.2024, 20.05.2024 | unchanged |
| unknown | Maple Grove Housing Society | "2024" → "07-07-2024" | **+1 line: `parties: Maple Grove Housing Society`** |

- **Gains.**
  - The flat list now holds real names. The rules contribute only role words, such as "Complainant" and "Accused".
  - The dates are more complete and better bounded: "07-07-2024" instead of "2024".
- **New spurious items.**
  - "Police\nStation Hilltop" (petition): a police station that InLegalNER labels ORG, kept as a "party" name.
  - "Maple Grove Housing Society" (unknown) is a named organisation, not strictly a party. It is the **only change
    that reaches the model's input** in the six fixtures.
- **Rule result: no fixture lost an expected item, so PASS.** No expected item was gained either.

## 4. Cost (real models on MPS, warm; no LLM)

**Setup:** `experiments/inlegalbert/e3_cost.py` and `backend/scripts/dev/stress_inference.py`.
- **Machine and stack:** Apple Silicon, 24 GB, torch 2.14.0. The backend ran with the startup warm-up on, the fake
  LLM, real BGE-M3 and reranker, and the rehearsal DB with copies of the stores.
- **Isolation:** no training or other jobs ran. The development backend was stopped during all measurements.
- **Results:** `results/e3_cost.json`, `e3_cost_ner_stage.json`, `e3_stress_{deterministic,combined}.json`.

| | `deterministic` | `combined` | Impact |
|---|---|---|---|
| Startup: process start to first `/health` | 0.93 s | 0.97 s | none |
| Startup: to fully warm (query models + NER) | 7.14 s | 6.50 s | none within noise; the NER loads beside the query models |
| NER model load (incl. sha256 of 436 MB) / warm-up inference | — | 3.48 s / 85 ms | |
| Memory, idle: resident set (`ps`) | 2,628 MB | 2,585 MB | none visible (MPS memory is not in RSS) |
| Memory, idle: physical footprint (incl. Metal) | 5,275 MB | 6,114 MB | **+839 MB (+16%)** |
| Memory, peak during 30 queries: footprint | 6,387 MB | 6,176 MB | noisy (MPS allocator caching) |
| System swap used: idle / peak during queries | 2,317 / 2,317 MB | 2,301 / 2,301 MB | none |
| NER stage alone, in-process, warm (30 calls): p50 / p95 | 0.30 / 0.40 ms | 9.4 / 13.6 ms | +~9–13 ms |
| NER stage over HTTP (`ner_backend_ms`): p50 / p95 | — | 13.4 / 20.2 ms | |
| Understanding + NER + retrieval (10 queries × 3): p50 / p95 | 903 / 1,010 ms | 961 / 995 ms | within run-to-run retrieval variance (±40 ms) |
| Full request, fake LLM (10 × 3): p50 / p95 | 914 / 1,035 ms | 982 / 1,014 ms | |
| **Step-18 stress** (5 repetitions × [10 concurrent during warm-up + 3 rounds of 10 + 5 sequential]) | 0 crashes, 225/225 × 200 | **0 crashes, 225/225 × 200** | |
| Stress concurrent latency p50 / p95 | 9.26 / 16.73 s | 8.35 / 15.22 s (first run: 8.16 / 15.97) | none measurable |
| Stress single latency p50 | 1.52 s | 1.31 s | none measurable |

**Notes:**
- **Model use under stress.** In the combined stress run, `/health` showed `ner.active = combined` on MPS at the end
  of every repetition, with 45 combined calls and 0 fallbacks each.
- **Concurrency.** The NER model shares the single inference lock, so a query's NER call waits behind other queries'
  embedding and reranking. That waiting is included in the stress latencies.
- **Document map.** For PDFs, the NER runs once per private chunk. On the one-chunk fixtures the map took about
  +40 ms, but long documents scale with their chunk count.
- **Plain statement:** the combined backend costs about 10–20 ms per query and about 0.8 GB of process memory (unified
  memory on this machine), plus a 436 MB checkpoint on disk. It does not slow startup or destabilise concurrency.

**End-to-end journeys.** In local real mode (`run_e2e_local_real.sh`: real retrieval, fake LLM), 15/15 passed with
the flag off and 15/15 with `LEGALAI_NER_BACKEND=combined`. The Playwright API server inherits the environment. CI
runs the journeys with the flag off, the default.

## 5. Reproducing the checkpoint

The checkpoint is E1 seed 22: `models/inlegalbert_ner/seed-22/`, gitignored and not uploaded anywhere.

| File | sha256 |
|---|---|
| `model.safetensors` (435,679,140 bytes) | `427c3fd99c8b98c73b4adc161794e49ef39c852052a28ac6ed7c2d8ec9be0a4c` (checked at load) |
| `config.json` | `316dbb9d2285b0046977adf540bf7b0f329353148f2ce369cd259249966a367a` |
| `tokenizer.json` | `da6e2f936693e0e0d2d3edb22ff23bc497978a436095ee5e6572d4ac1cdf5a67` |
| `tokenizer_config.json` | `26a625a4a190d929da9fc2332a5ee99498a559c2906ba2e3fb8a31d01ba5b24e` |

**Data access.**
- **Account.** A Hugging Face account that has accepted the gated terms of `opennyaiorg/InLegalNER`, with a read
  token in `HF_TOKEN`. Never print or commit it.
- **Base model.** InLegalBERT is public (MIT).
- **Revisions and hashes.** The dataset revision and the zip hashes are in `experiments/inlegalbert/manifest.json`.

```bash
# 1. Base model at the pinned revision (into the gitignored models/)
.venv/bin/hf download law-ai/InLegalBERT --revision b5ecfed8ed6cf9d25a3cb8225a8c52f161f7401a \
    --local-dir models/inlegalbert

# 2. InLegalNER train and dev at the pinned revision, outside the repository (token from .env, not echoed)
set -a; . ./.env; set +a
D=~/legalai_datasets/inlegalner_2e32a46e6714
.venv/bin/hf download opennyaiorg/InLegalNER NER_TRAIN.zip NER_DEV.zip README.md --repo-type dataset \
    --revision 2e32a46e6714424979db8677b39dbc0aa7e308e7 --local-dir "$D"
shasum -a 256 "$D"/NER_TRAIN.zip "$D"/NER_DEV.zip   # compare with the manifest (8cf1ba0d…, 10df6cfd…)
unzip -o "$D"/NER_TRAIN.zip -d "$D"/train && unzip -o "$D"/NER_DEV.zip -d "$D"/dev

# 3. The leakage exclusion (IDs only): the committed list, so the training set does not depend on today's corpus
cp experiments/inlegalbert/inlegalner_excluded_ids.json "$D"/excluded_ids.json
#    (or recompute: .venv/bin/python experiments/inlegalbert/leakage_check.py --inlegalner "$D", which uses the corpus)

# 4. Train seed 22 with the frozen recipe (about 73 minutes on Apple MPS; stop the backend first)
cd experiments/inlegalbert && caffeinate -i ../../.venv/bin/python train_ner.py --seed 22
#    -> models/inlegalbert_ner/seed-22/ (best dev epoch kept); curves in runs/seed-22.json
```

- **The exclusion list.** `inlegalner_excluded_ids.json` holds 108 train and 23 dev item IDs, sha256
  `7659e472…a375`, identical to the list E1 used.
- **Bit-for-bit reproduction is not guaranteed.** MPS kernels are not fully deterministic, so a rebuild may not
  reproduce the exact hash. Expect E1's dev exact F1 for seed 22 (0.8120 at epoch 4; runs/seed-22.json).
- **Using a rebuilt checkpoint.** It needs a deliberate change of `CHECKPOINT_SHA256` in `ner_backend.py`, and the
  E1 gold scoring is not repeated for it. Prefer distributing the original artifact (below).

## 6. Storage for deployment (recommendation only; nothing was uploaded)

**Licences:**
- **InLegalBERT is MIT.** The fine-tuned weights are a derivative work. MIT permits distribution if the copyright and
  licence notice are kept, so ship a copy of InLegalBERT's MIT notice with the checkpoint.
- **InLegalNER is MIT but gated.** The weights are not the dataset, and MIT does not restrict trained models. However,
  the access conditions accepted on the dataset page are separate from the licence. Re-read them before any **public**
  release of the weights. A private, team-only copy raises no such question.
- **Citations.** Cite both: Paul et al. 2023 (InLegalBERT) and Kalamkar et al., NLLP 2022 (InLegalNER).

**Options:**

| Option | Pros | Cons |
|---|---|---|
| **Private Hugging Face model repo** (recommended) | versioned (pin a commit, as for the other models); LFS-backed; access control by account/org; `hf download --revision <sha>` into `models/inlegalbert_ner/seed-22/`; model card can carry the licences, citations, recipe and hash | needs a token on each deployment machine |
| Private GitHub release asset on this repository | same access control as the code; 436 MB is under the 2 GB asset limit | not content-addressed (pin by the sha256 the backend already checks); no model card; manual upload/download |
| Git LFS in this repository | — | against the project rule (no weights in Git); LFS quota; every clone pays for it |
| Rebuild on each machine (section 5) | no storage | ~75 min of MPS time, gated data access on each machine, not bit-reproducible |

**Recommendation.** If `combined` is ever enabled, keep the seed 22 artifact in a **private Hugging Face model repo**:
- pinned by commit;
- with the MIT notice, citations and the sha256 above in its card;
- downloaded into the gitignored path, where the backend's hash check guards it.

## 7. Verdicts and recommendation

**Retrieval: PASS** (frozen E3 rule).
- No drop: every metric is identical, and the rankings are identical on 30/30 queries.
- **No gain**: ΔnDCG@5 = 0.000 [0.000, 0.000].

**Briefs: PASS.**
- No fixture lost an expected item, and none gained one. The brief's fields are identical.
- The only model-visible change is one extra `parties:` line on the "unknown" fixture.
- One spurious party-list item: a police station read as an organisation.

**Cost: PASS** (no crash).
- 0 crashes in the step-18 stress test with the flag on: 225/225 responses were 200.
- The latency and memory impact:
  - +~10–13 ms of NER per query (p95 ~20 ms over HTTP), which disappears in retrieval variance;
  - about **+0.84 GB of process memory** (footprint);
  - unchanged startup;
  - a 436 MB checkpoint that must be distributed.

**Recommendation: keep `LEGALAI_NER_BACKEND=deterministic` as the default.**
- **The E1 gain has no consumer today.** E1's gain (F1 0.915 against 0.788) is real but sits in entity types
  (PERSON, ORGANIZATION, LOCATION, CASE_NAME) that nothing downstream uses:
  - retrieval reads only the query text;
  - the brief's fields come from separate detectors;
  - the document map shows NER parties and dates only as fallbacks.
- **So the trade is all cost for almost no benefit.** On the frozen checks it buys no measurable benefit (0 retrieval
  change, 0 brief change, 1 extra prompt line in 6 fixtures), for about 0.8 GB of memory, about 10–20 ms per query and
  a gated-data-derived artifact to store and maintain.
- **Keep the flag.** It is a safe, tested switch for later work.

**Decisions for the user:**
1. **The default.** Keep it `deterministic` (recommended), or enable `combined` knowing it changes nothing measured
   here.
2. **Whether to give the entities a consumer.** This would be new work with its own gold and evaluation. For example:
   - party detection with roles from InLegalNER's native PETITIONER, RESPONDENT, WITNESS and JUDGE labels (an unfrozen
     mapping);
   - or showing the extracted entities in the brief.

   Without a consumer, E1's improvement cannot reach users.
3. **Storage.** If `combined` is kept for later, create the private HF model repo (section 6).
4. **The E1 protocol wording.** The same-span replacement erratum (section 1) is a documentation fix. Fixing the
   behaviour itself would change the frozen policy and need a new evaluation.
