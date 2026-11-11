# InLegalBERT bounded experiment: feasibility, data audit and frozen protocol (step E0)

**Status: E0 complete. No model has been trained or fine-tuned.** This document freezes the protocol and the pass
thresholds before any training. Evidence (hashes, counts, timings, leakage) is in
`experiments/inlegalbert/manifest.json`; the probes are `experiments/inlegalbert/timing_probe.py` and
`experiments/inlegalbert/leakage_check.py`. Product code, prompts, data, Chroma, BM25, the database and the frozen
files are unchanged.

## 1. Why

The build plan specifies a fine-tuned InLegalBERT for NER and a multi-label IPC/BNS section classifier. The product
uses deterministic NER (exact entity F1 0.788 on 36 gold examples, `docs/LEGAL_NER_SELECTION_DECISION.md`) and a BGE
cross-encoder section ranker over a bounded 62-entry catalog (`docs/LEGAL_SECTION_RANKING_SELECTION_DECISION.md`).
This experiment tests, within a fixed budget, whether a fine-tuned InLegalBERT beats those baselines.

## 2. Checkpoint

| Item | Value |
|---|---|
| Hub ID (verified via the Hub API and search) | `law-ai/InLegalBERT` (IIT Kharagpur; the original, 2022) |
| Revision | `b5ecfed8ed6cf9d25a3cb8225a8c52f161f7401a` |
| License | MIT, not gated |
| Architecture | BERT-base (12 layers, 768 hidden, 12 heads), ~110M parameters; LEGAL-BERT-SC further pre-trained 300K steps (MLM + NSP) on ~5.4M Indian court documents (1950-2019) |
| Tokenizer | uncased WordPiece, 30,522 tokens (LEGAL-BERT's) |
| Maximum sequence length | 512 |
| Citation | Paul, Mandal, Goyal, Ghosh. *Pre-trained Language Models for the Legal Domain: A Case Study on Indian Law.* ICAIL 2023. arXiv:2209.06049 |
| Local copy | `models/inlegalbert/` (gitignored); `pytorch_model.bin` SHA-256 `4c5b1308…f4c5`, equal to the Hub's LFS hash |
| MPS check | loads in 0.5 s; batch 8 x 512 forward 262 ms, finite outputs, 430 MiB MPS; fill-mask on a Section 302 sentence returns "offence, offences, charge, rape, murder" |

The vocabulary predates the BNS/BNSS (2023): "BNS" tokenizes as `b ##n ##s`, and the pre-training corpus ends in
2019. Every BNS/BNSS input is therefore out of the pre-training distribution.

The weights are a PyTorch pickle (`pytorch_model.bin`); transformers 5 loads them with `weights_only` safety. Only
this pinned revision may be used.

## 3. Public datasets

| Dataset | Task | Source | Size | Schema | License, access | Usable? |
|---|---|---|---|---|---|---|
| **InLegalNER** (OpenNyAI) | NER | `opennyaiorg/InLegalNER` on the Hub, linked from the authors' `Legal-NLP-EkStep/legal_NER` | train 9,435 judgment sentences (17,485 entities) + 1,560 preambles (12,479 entities); dev and test files | 14 types: COURT, PETITIONER, RESPONDENT, JUDGE, LAWYER, DATE, ORG, GPE, STATUTE, PROVISION, PRECEDENT, CASE_NUMBER, WITNESS, OTHER_PERSON | MIT; **gated (auto): needs a Hub login and accepting terms** (HTTP 401 without) | **Stopped: needs your decision** |
| **ILSI** (LeSICiN, AAAI 2022) | statute identification, multi-label | Zenodo `10.5281/zenodo.6053791`, the authors' record | train 42,835, dev 10,200, test 13,039 cases; facts median 458-579 words (p90 ~2,900) | 100 IPC section labels, 3.7-3.9 per case | CC-BY-4.0, open | **Yes**, downloaded outside the repo, MD5s verified |
| IL-TUR (Exploration-Lab) | benchmark incl. NER and statute identification | `Exploration-Lab/IL-TUR` | — | — | CC-BY-NC-SA-4.0; **gated (manual)** | Stopped |
| Hanno-Labs IPC statute identification | facts -> one IPC section | the Hub, Clause Logic Inc. (2026) | 40,001 rows, ~14,900 cases, 320 IPC sections | facts with citations masked | CC-BY-4.0, open | Secondary only: source judgments not named; not downloaded |
| AjayMukundS Indian_Legal_NER | NER | the Hub | — | — | MIT tag, no provenance | Excluded: unverified re-upload |

**Mapping to our schemas.**
- InLegalNER -> `legalai-ner-schema-v1`: COURT, DATE and STATUTE map directly; PROVISION -> SECTION; ORG ->
  ORGANIZATION (their ORG also covers police stations); GPE -> LOCATION; PRECEDENT -> CASE_NAME / CASE_CITATION;
  PETITIONER, RESPONDENT, JUDGE, LAWYER, WITNESS and OTHER_PERSON -> PERSON. **No source label** exists for OFFENCE,
  LEGAL_PROCEDURE, LEGAL_ROLE or FIR_NUMBER: 34 of our 89 gold entities. A fine-tuned model can only add the other
  types; the deterministic NER keeps those four.
- ILSI -> our sections: `Section N in The Indian Penal Code` -> (IPC, N). It covers **22 of the 60 positive labels**
  in our section gold set (12 of 15 distinct IPC sections; missing 361, 378, 408) and **none** of the BNS, BNSS,
  CrPC or special-Act labels. 15 of 36 gold queries have at least one expressible positive; 7 have only expressible
  positives.

**No usable public dataset exists for a BNS/BNSS section classifier.** The only open statute-identification data is
IPC-only.

## 4. Our evaluation assets (held-out test sets only)

| Asset | File | Content | Guidelines | Scoring |
|---|---|---|---|---|
| NER gold | `data/structured/manifests/legal_ner_gold_template.json` | 36 short authored examples (median 60 characters, not judgment text), 89 entities in 14 types: STATUTE 16, OFFENCE 12, LEGAL_PROCEDURE 12, COURT 11, LEGAL_ROLE 9, SECTION 8, DATE 4, ORGANIZATION 4, LOCATION 4, PERSON 3, POLICE_STATION 2, CASE_CITATION 2, FIR_NUMBER 1, CASE_NAME 1; 2 zero-entity examples; one reviewer | `docs/LEGAL_NER_ANNOTATION_GUIDELINES.md`, `docs/LEGAL_NER_GOLD_LABELS.md` | `backend/scripts/evaluate_deterministic_legal_ner.py`: **exact** match on (start, end, type), micro P/R/F1 and per type; hybrid via `evaluate_hybrid_legal_ner.py` |
| Section gold | `data/structured/manifests/legal_section_eval.json` | 36 authored queries (median 55 characters), 36 primary + 24 relevant + 1 uncertain labels over 44 distinct sections in 7 statutes (IPC 25, CrPC 10, BNS 8, BNSS 6, NDPS 5, POCSO 4, SC/ST 2); 3 zero-positive queries | `docs/LEGAL_SECTION_GOLD_LABELS.md` | `evaluate_legal_section_baseline.py` and the reranker trial: P@k, recall@k, hit@k, MRR, nDCG@5, primary and explicit recall@5, zero-positive FP rate; uncertain excluded |
| Retrieval benchmark | frozen `legalai-retrieval-eval-v1` | 30 queries, 695 labels | `docs/RETRIEVAL_EVALUATION_RESULTS.md` | P@5 0.873, nDCG@5 0.819 (hybrid + rerank) |

**Held-out confirmation.** Both gold sets were authored for evaluation and have never been used for training,
threshold fitting or model selection (`docs/LEGAL_SECTION_RANKING_SELECTION_DECISION.md`, "Frozen Gold"; NER
decision doc). In this experiment they are **test sets only**: no example is used for training, early stopping,
threshold or checkpoint choice, and each trained model is evaluated on them **once**, after selection on the public
dev split.

**Leakage check** (`leakage_check.py`, counts only):
- ILSI vs our corpus: 5 ILSI cases are corpus judgments by Indian Kanoon ID (train 3, dev 1, test 1), and 3,707 train
  / 945 dev / 1,233 test cases share at least one 13-word passage with the corpus (much of it boilerplate).
- ILSI vs gold: 0 shared 13-word passages, and none of the 72 gold texts appears verbatim in any ILSI case.
- **Rule:** before training, exclude every public instance whose ID is a corpus document or that shares a 13-word
  shingle with the corpus or gold texts. InLegalNER gets the same check after download. Gold texts are short, so the
  verbatim check is the decisive one for them.

## 5. Compute estimate

Measured on this Mac (Apple M5, 24 GiB, MPS) with **forward passes only** on synthetic token IDs. The planned
few-hundred-step training probe was blocked by the repository's ml-pipeline hook (it treats any `loss.backward()` as
training; see decisions). A training step is estimated as 3 x the forward time.

| Head | Batch x length | Forward | Estimated training step | Examples/s |
|---|---|---:|---:|---:|
| NER (29 BIO labels) | 16 x 128 | 0.119 s | 0.36 s | ~45 |
| NER | 8 x 256 | 0.123 s | 0.37 s | ~22 |
| Classifier (100 labels) | 8 x 512 | 0.258 s | 0.77 s | ~10 |
| Classifier | 16 x 256 | 0.254 s | 0.76 s | ~21 |

- **E1 (NER on InLegalNER):** ~9,435 sentences at 128 tokens (~3.5 min) + 1,560 preambles at 512 (~2.5 min) is
  ~6 minutes per epoch; 5 epochs x 3 seeds ~ 1.5 hours.
- **E2 (classifier on ILSI):** ~39,000 leakage-filtered cases at 256 tokens ~ 31 minutes per epoch; 3 epochs x 3
  seeds ~ 4.7 hours (at 512 tokens, about double).
- **Memory:** forward 1.0 GiB MPS; weights + gradients + AdamW states 1.6 GiB (computed); activations add a few GiB
  (unmeasured). These are estimates, uncertain by about 50%, until a real step is timed.
- **Backend:** stop it during training. Both use the 24 GiB of unified memory and the same GPU, so running them
  together risks memory pressure and makes the timings meaningless. Never train on the same day as UAT, the demo or
  a provider evaluation.

## 6. Protocol

**Experiments.**
- **E1, NER (minimum viable).** InLegalBERT token classification on InLegalNER (leakage-filtered), labels mapped to our
  schema before training. Select on InLegalNER dev. Test once on our 36 examples: standalone (L) and hybrid with the
  deterministic NER (H), using the existing frozen merge policy with deterministic types protected and the confidence
  threshold fixed at 0.70 in advance.
- **E2, IPC statute classifier (exploratory).** Multi-label InLegalBERT classifier on ILSI (leakage-filtered), first
  256 tokens of the facts. Select on ILSI dev. Test on ILSI test (in-domain sanity) and once on our section gold, as an
  extra candidate source inside the protected cross-encoder hybrid (never a replacement).
- **E3, retrieval effect.** Use the E1/E2 predictions as supplementary query signals in an **offline copy** of query
  understanding and retrieval (the pinned product files are not touched), on the frozen 30-query benchmark.

**Splits and seeds.** Train and dev are the public datasets' own splits after the leakage filter; the test sets are
our gold sets. Seeds 13, 42 and 20261111 for each run; the decision uses the median-scoring seed. Bootstraps use
10,000 resamples of examples with seed 20261111. Hyperparameters are fixed in advance: AdamW, learning rate 3e-5,
warm-up 10%, weight decay 0.01; E1 batch 16, up to 5 epochs; E2 batch 16, up to 3 epochs; early stopping on dev with
patience 2.

**Metrics.**
- E1: exact entity-level P/R/F1 overall and per type (our scorer), standalone and hybrid; span-only F1 reported.
- E2: on ILSI test, micro- and macro-F1 (threshold 0.5 fixed in advance) and recall@1/3/5; on our gold, recall@1/3/5,
  micro/macro F1 on the expressible labels, P@1, MRR, nDCG@5, primary recall@5 and the zero-positive FP rate, for
  all 36 queries and for the 15 expressible ones.
- E3: P@5 and nDCG@5 on the 30-query benchmark.

### Pass thresholds (frozen 2026-11-11, before any training)

**Baselines and their uncertainty** (bootstrap 95% CI): NER D0 exact F1 **0.788 [0.700, 0.865]** (65 TP, 11 FP,
24 FN). Section HX1 over the 33 queries with positives: P@1 0.879 [0.758, 0.970], MRR 0.909 [0.818, 0.985],
nDCG@5 0.831 [0.739, 0.910], recall@5 0.854 [0.747, 0.944]. On the 15 ILSI-expressible queries: P@1 0.867
[0.667, 1.0], MRR 0.933 [0.833, 1.0].

**E1 passes only if all hold** (median seed, hybrid H vs D0):
1. exact F1 >= **0.838** (D0 + 0.05);
2. the paired bootstrap 95% CI of F1(H) - F1(D0) has a lower bound **> 0**;
3. precision >= **0.805** (D0 0.855 - 0.05);
4. **no per-type F1 loss** on the types the query understanding and the professional brief rely on: STATUTE, SECTION,
   COURT, DATE, LEGAL_ROLE, LEGAL_PROCEDURE, POLICE_STATION, FIR_NUMBER;
5. **zero false positives** on the 2 zero-entity examples.
The standalone model L is reported but cannot pass on its own (it has no labels for 34 of the 89 gold entities).

**E2 passes only if all hold:**
1. on ILSI test, micro-F1 beats a TF-IDF + logistic-regression baseline trained on the same split by >= **0.05**
   (sanity: the model learned the task);
2. on our gold, as an extra candidate source in the protected hybrid: primary recall@5 over all 36 queries **not below**
   HX1, zero-positive FP rate **0**, explicit recall@5 not below HX1;
3. on the 15 expressible queries, recall@5 >= HX1 + **0.10** with a paired-bootstrap lower bound **> 0**.

**E3 passes** with no regression (P@5 >= 0.873, nDCG@5 >= 0.814, i.e. frozen - 0.005). An *improvement* may be
claimed only with ΔnDCG@5 >= **+0.02** and a paired-bootstrap lower bound > 0 over the 30 queries.

**Why these numbers.** +0.05 F1 is about 4 more correct entities out of 89: the smallest change worth a model in the
product. Alone it is inside the baseline's CI width (0.17), which is why the paired bootstrap must also exclude zero;
pairing removes the between-example variance that dominates the unpaired interval. The precision floor and the
per-type rule encode the Phase 0 lesson: the general BERT candidate raised recall but added false positives. E2's
in-domain baseline guards against a broken model being judged on 15 queries.

**What the test sets can show, and what they cannot.**
- They can show a *large* improvement (several entities, or several queries ranked better) and catch regressions on
  protected types.
- They cannot show small effects: with 36 short authored examples, a real +0.02 F1 gain is indistinguishable from
  noise.
- They are short queries, not judgments or FIRs: a model that is better on judgment text may not be better here, and
  the reverse.
- The section set's expressible subset (15 queries) is already near ceiling for the current ranker, so E2 can
  realistically only show "no harm".
- One reviewer labelled both sets.
A pass is therefore evidence for adoption in this product; it is not a general claim about InLegalBERT.

### Stopping rules and time budget
- **Hard caps:** E1 3 hours of training wall time (all seeds); E2 7 hours; E3 2 hours. Exceeding a cap by 50% stops
  that experiment and it is reported as not completed.
- Stop a run if dev F1 is below **0.70** after 2 epochs (InLegalNER dev entity F1) or below the TF-IDF baseline (ILSI
  dev micro-F1). That points to a pipeline bug, not a result.
- No re-runs with new hyperparameters after seeing a gold result. A gold set is scored once per model.
- Stop on any leakage finding, license change or a pre-training corpus overlap that cannot be filtered.

### Decision tree
```
E1 (NER)
├─ pass  -> E3 with E1 entities -> no regression -> propose a hybrid NER integration (separate step, your approval)
│                                -> regression   -> keep deterministic NER; record E1 as "better NER, no retrieval benefit"
└─ fail  -> stop. Keep deterministic NER; record the negative result.
E2 (IPC classifier), only after E1 and only if you want it
├─ pass  -> E3 with E2 candidates -> same rules as above (adoption limited to IPC)
└─ fail / inconclusive -> stop; the cross-encoder ranker stays.
```

## 7. Risks
- **Label-schema mismatch:** InLegalNER has no OFFENCE, LEGAL_PROCEDURE, LEGAL_ROLE or FIR_NUMBER, and its PRECEDENT
  span differs from our CASE_NAME/CASE_CITATION split. ILSI is IPC-only, 100 sections.
- **Domain shift:** both datasets are judgment text (sentences, preambles, long facts); our gold sets are short
  queries, and the product sees FIRs, charge sheets and questions. InLegalBERT's corpus ends in 2019, before the BNS.
- **Small test sets:** see above; results are coarse.
- **Licenses and access:** InLegalNER is MIT but gated; IL-TUR is non-commercial and manually gated; ILSI is
  CC-BY-4.0 (attribution required in any write-up).
- **Leakage:** ILSI shares judgments with our corpus; filtered by rule above.
- **Product drift:** any integration touches pinned files (`legal_query_understanding.py`) and needs its own approved,
  re-pinned step; this experiment never changes them.

## 8. Recommendation

- **Feasible as scoped for NER only (E1), once InLegalNER access is granted.** It fits in about 1.5 hours of training
  and has a clean held-out test, but only 55 of our 89 gold entity types are learnable from it, so the realistic
  target is the hybrid: better PERSON, ORGANIZATION, LOCATION, CASE_NAME and COURT recall with the deterministic types
  protected.
- **The classifier (E2) is not feasible as specified.** No public dataset covers BNS/BNSS (or CrPC and special Acts).
  ILSI covers 37% of our gold labels, and the current ranker is already near ceiling on those queries. The honest
  smallest alternative is to run E2 as an IPC-only, exploratory, "no-harm" check, or skip it and record that the
  BGE cross-encoder ranker remains the section component.
- **Minimum viable version:** E1 (3 seeds, about 1.5 hours) plus E3 with E1's entities, judged by the frozen
  thresholds above.
