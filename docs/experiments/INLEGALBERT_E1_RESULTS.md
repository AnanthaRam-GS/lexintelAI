# InLegalBERT E1 (NER): results

Status: **UNREVIEWED**. Scored once on 2026-11-12. The protocol (`INLEGALBERT_E1_PROTOCOL.md`), the plan
(`INLEGALBERT_PLAN.md`) and their thresholds were frozen before training and were not changed. Nothing in the
product was changed.

**Verdict: PASS.** The median seed's combined system meets all five criteria. Each of the three seeds passes on its
own as well. The test set is small (36 short authored queries, 89 entities) and has one reviewer. A pass is evidence
for proposing integration in this product, not a general claim about InLegalBERT (plan, "What the test sets can
show").

## 1. Data

- **Training data:** InLegalNER, `opennyaiorg/InLegalNER`, revision `2e32a46e6714424979db8677b39dbc0aa7e308e7`,
  MIT licence (gated; terms accepted).
  - Downloaded through the Hub with the project token.
  - Stored outside the repo at `~/legalai_datasets/inlegalner_2e32a46e6714/`.
  - File hashes and counts are in `experiments/inlegalbert/manifest.json`.
  - Only the train and dev splits were used. The official test split was not downloaded.
- **Leakage check** (`leakage_check.py --inlegalner`):
  - What it compares: each item against the 70-judgment corpus and the 36 gold texts, by source Indian Kanoon
    document, shared 13-word passages, and verbatim containment.
  - **Removed: 108 train items and 23 dev items.** Each shares a 13-word passage with the corpus.
  - No source document is in the corpus, and no item overlaps the gold set.
  - **Remaining: 10,887 train items and 1,051 dev items** (11,457 training windows, 717 steps per epoch).
- **Validation:** the authors' official dev split, which is fixed. Each seed shuffles the training order.
- **Test:** the 36 gold examples only, scored once per seed.

## 2. Mapping and combination policy

Both were frozen and committed before any training code ran.

| Commit | Time (IST) | What it contains |
|---|---|---|
| `ba7204a` | 22:03 | data pin and leakage check |
| `7d1b530` | 22:04 | label mapping, combination policy and recipe |
| `d4f6ab0` | 22:06 | training script |
| — | 22:06:07 | training starts |
| `8b70568` | 22:07 | gold scorer, before any model was scored |

**Mapping:**
- COURT, DATE and STATUTE map to the same types. PROVISION→SECTION, ORG→ORGANIZATION, GPE→LOCATION,
  PRECEDENT→CASE_NAME.
- JUDGE, LAWYER, WITNESS and OTHER_PERSON map to PERSON.
- PETITIONER and RESPONDENT map to ORGANIZATION or PERSON by a fixed word rule.
- CASE_NUMBER is dropped.

**Combined system:** the product's own `merge_hybrid_entities`, used unchanged.
- Mode `hybrid`, threshold 0.70.
- Confidence is the mean label probability over the entity's tokens.
- Rule-owned types are protected.

## 3. Recipe and training

**Recipe:**
- Base model: `law-ai/InLegalBERT` at `b5ecfed8…`.
- Labels: BIO tags over 29 labels; windows of 256 tokens with a stride of 64.
- Optimiser: AdamW, learning rate 3e-5, weight decay 0.01, 10% warm-up, gradient clipping 1.0, batch 16.
- fp32 on MPS (torch 2.14.0, transformers 5.16.1).
- Up to 5 epochs, with early stopping on dev exact F1 (patience 2). Seeds 11, 22 and 33.

**Run conditions:**
- Training ran under `caffeinate -i`.
- The LegalAI backend was stopped throughout: nothing was listening on :8000 and no uvicorn process was running.
- Checkpoints are in `models/inlegalbert_ner/seed-<n>/`, which is gitignored. Their hashes are in the manifest.

**Wall clock:** 22:06:07 to 01:35:45 IST, **3 h 29.6 min** for all three seeds.

| Seed | Epochs run | Best epoch | Best dev exact F1 | Train time per epoch (s) | Dev pass (s) | Total |
|---|---|---|---|---|---|---|
| 11 | 5 | 5 | 0.8142 | 742 / 780 / 757 / 767 / 766 | 13–14 | 64.7 min |
| 22 | 5 | 4 | 0.8120 | 811 / 856 / 866 / 876 / 872 | 14–17 | 72.6 min |
| 33 | 5 | 4 | 0.8118 | 965 / 874 / 800 / 810 / 806 | 13–17 | 72.1 min |

**Dev exact F1 by epoch** (InLegalNER native types; not comparable with the gold F1):

| Seed | Ep 1 | Ep 2 | Ep 3 | Ep 4 | Ep 5 |
|---|---|---|---|---|---|
| 11 | 0.757 | 0.795 | 0.804 | 0.813 | **0.814** |
| 22 | 0.742 | 0.795 | 0.808 | **0.812** | 0.812 |
| 33 | 0.725 | 0.791 | 0.805 | **0.812** | 0.811 |

**Training loss:** the mean epoch loss fell from 0.66–0.68 in epoch 1 to about 0.040 in epoch 5. The 50-step means
fell from 3.1–3.4 to about 0.04–0.05. The full curves are in `experiments/inlegalbert/runs/seed-<n>.json`.

**Early stopping:** it never fired, because patience 2 cannot trigger within 5 epochs unless the best epoch is 3 or
earlier. The plan's stop rule (dev F1 below 0.70 after 2 epochs) was not triggered.

**Time against the budget:**
- About 1.03–1.35 s per step and about 13.7 min per epoch on average.
- E0 estimated about 0.36 s per step and about 6 min per epoch. That estimate assumed a training step costs 3× a
  forward pass, because the hook blocked timing a real step. The real cost was about 2.3× the estimate.
- **Deviation:** the plan caps E1 at 3 h and stops the experiment at 150% of that (4.5 h). The brief's stop was 6 h.
  Training took 3.49 h, about 16% over the plan's cap but below both stop points, so the run counts as completed.
  Memory pressure was high during seed 22 and seed 33's first epoch: swap was about 4.4 of 5.1 GB.

## 4. Results on the 36 gold examples

Exact match on span and type, scored with `legal_ner.exact_entity_metrics`. The 95% CIs are a bootstrap over the
36 examples (10,000 resamples, seed 20261111). The deterministic baseline (D0) recomputes to exactly the frozen
0.787879.

### Overall, per seed

| Seed | System | P | R | F1 [95% CI] | TP / FP / FN |
|---|---|---|---|---|---|
| 11 | (a) model alone | 0.867 | 0.438 | 0.582 [0.468, 0.682] | 39 / 6 / 50 |
| | (b) deterministic D0 | 0.855 | 0.730 | 0.788 [0.700, 0.866] | 65 / 11 / 24 |
| | (c) combined | 0.899 | 0.899 | 0.899 [0.841, 0.951] | 80 / 9 / 9 |
| **22 (median)** | (a) model alone | 0.911 | 0.461 | 0.612 [0.496, 0.713] | 41 / 4 / 48 |
| | (b) deterministic D0 | 0.855 | 0.730 | 0.788 [0.700, 0.866] | 65 / 11 / 24 |
| | (c) combined | **0.920** | **0.910** | **0.915 [0.864, 0.961]** | 81 / 7 / 8 |
| 33 | (a) model alone | 0.907 | 0.438 | 0.591 [0.470, 0.694] | 39 / 4 / 50 |
| | (b) deterministic D0 | 0.855 | 0.730 | 0.788 [0.700, 0.866] | 65 / 11 / 24 |
| | (c) combined | 0.920 | 0.910 | 0.915 [0.864, 0.961] | 81 / 7 / 8 |
| **Mean** | (a) model alone | 0.895 | 0.446 | 0.595 | |
| | (b) deterministic D0 | 0.855 | 0.730 | 0.788 | |
| | (c) combined | 0.913 | 0.906 | 0.910 | |

### Other measures

**Paired bootstrap, F1(c) − F1(D0):**

| Seed | Mean | 95% CI |
|---|---|---|
| 11 | +0.112 | [+0.061, +0.169] |
| 22 | +0.128 | [+0.066, +0.203] |
| 33 | +0.128 | [+0.066, +0.203] |
| Mean | +0.122 | |

**Zero-entity examples:** none of the three systems predicted anything on the 2 zero-entity examples, for any
seed.

**Span-only F1** (type ignored; the plan asks for it, and it is informational, not a criterion):

| Seed | (a) model alone | (b) D0 | (c) combined |
|---|---|---|---|
| 11 | 0.627 | 0.788 | 0.899 |
| 22 | 0.657 | 0.788 | 0.915 |
| 33 | 0.652 | 0.788 | 0.915 |

**Median seed:** seeds 22 and 33 tie on combined F1, with identical counts. Seed 22 is the median by sort order,
and the verdict is the same either way.

### Per type, median seed (22)

F1 values; ★ marks a brief-relevant type, where no loss is allowed.

| Type | Gold | D0 | (a) model alone | (c) combined | Change (c) − D0 |
|---|---|---|---|---|---|
| ★ STATUTE | 16 | 1.00 | 0.90 | 1.00 | 0 |
| ★ LEGAL_PROCEDURE | 12 | 0.96 | — | 0.96 | 0 |
| OFFENCE | 12 | 0.67 | — | 0.67 | 0 |
| ★ COURT | 11 | 0.64 | 0.62 | **0.91** | +0.27 |
| ★ LEGAL_ROLE | 9 | 1.00 | — | 1.00 | 0 |
| ★ SECTION | 8 | 1.00 | 1.00 | 1.00 | 0 |
| ★ DATE | 4 | 0.44 | 0.67 | **0.67** | +0.22 |
| ORGANIZATION | 4 | 0.00 | 0.80 | **1.00** | +1.00 |
| LOCATION | 4 | 0.00 | 1.00 | **1.00** | +1.00 |
| PERSON | 3 | 0.00 | 1.00 | **1.00** | +1.00 |
| ★ POLICE_STATION | 2 | 1.00 | — | 1.00 | 0 |
| CASE_CITATION | 2 | 0.67 | — | 0.67 | 0 |
| ★ FIR_NUMBER | 1 | 1.00 | — | 1.00 | 0 |
| CASE_NAME | 1 | 0.00 | 0.67 | **1.00** | +1.00 |

A dash means the type does not exist in InLegalNER, so the model cannot predict it. **No brief-relevant type loses
F1 in any seed.**

## 5. Verdict on the combined system

Median seed 22, against the thresholds frozen in the plan.

| # | Criterion | Threshold | Value | Result |
|---|---|---|---|---|
| 1 | Exact F1 | ≥ 0.838 | 0.915 | **PASS** |
| 2 | Paired 95% CI of F1(c) − F1(D0) | lower bound > 0 | +0.128 [+0.066, +0.203] | **PASS** |
| 3 | Precision | ≥ 0.805 | 0.920 | **PASS** |
| 4 | No F1 loss on STATUTE, SECTION, COURT, DATE, LEGAL_ROLE, LEGAL_PROCEDURE, POLICE_STATION, FIR_NUMBER | no loss | none (COURT +0.27, DATE +0.22, the rest equal) | **PASS** |
| 5 | False positives on the 2 zero-entity examples | 0 | 0 | **PASS** |
| | **Overall** | | | **PASS** |

Seeds 11 and 33 also pass all five criteria on their own. Nothing was retuned after scoring: each checkpoint
predicted on the gold set once, and its predictions were written to `results/predictions-seed-<n>.json` before any
summary was computed.

## 6. Error analysis

This section is informational; it changes nothing.

**Where the gain comes from.** The combined system finds 16 more entities than D0 (81 TP against 65 for the median
seed):
- 12 come from types D0 has no rules for: ORGANIZATION +4, LOCATION +4, PERSON +3, CASE_NAME +1.
- 4 come from two shared types: COURT +3, DATE +1.
- So the improvement mostly fills types D0 does not cover. It does not improve D0's own types.

**Remaining errors** (median seed, 7 FP and 8 FN). Every remaining false positive is D0's own; the model adds none
in seeds 22 and 33.
- **OFFENCE** (D0 rules; the model has no OFFENCE type).
  - False positives: "lured away", "false promise", "lawful custody", "ganja" (gold: "ganja possession").
  - Missed: "kidnapping", "possession of heroin", "common intention".
- **Boundary errors in D0 that the merge keeps:**
  - "Can the High Court" against the gold "High Court".
  - "Before July 2024" against the gold "July 2024".
  - "2014" tagged as a DATE inside the citation "(2014) 8 SCC 273", which is itself missed.
  - The model cannot repair these:
    - In q023 and q018 it predicted no COURT or DATE span at all.
    - In q013 it tagged the citation as PRECEDENT at 0.68. That is below 0.70, and as CASE_NAME it would have the
      wrong type anyway.
- **LEGAL_PROCEDURE:** "appeal" in q003 is missed. The model has no such type.

**Seed-specific error.** Seed 11's 2 extra false positives come from one example (q005, "State of NCT of Delhi").
The model ended an ORGANIZATION span mid-word ("State of NCT of Del") and tagged the rest, "hi", as LOCATION. This is
a WordPiece boundary error: the decoder starts a new entity whenever the label type changes, even inside a word.
Word-level label voting would prevent it, but changing the decoder now would be retuning, so it is left as is.

**Model alone.** The model alone is precise (0.87–0.91) but recall stays at 0.44–0.46. It cannot express 34 of the
89 gold entities (OFFENCE, LEGAL_PROCEDURE, LEGAL_ROLE, POLICE_STATION, FIR_NUMBER, CASE_CITATION). The plan already
said it cannot pass on its own.

## 7. Limitations

- **Small test set.** The gold set has 36 short authored queries (median 60 characters) with 89 entities and one
  reviewer.
  - The four types behind most of the gain have 1–4 gold entities each.
  - The CI is wide (0.864–0.961), and the result is a large effect on a small sample.
- **Domain.** The gold texts are queries, not judgments or FIRs. Whether the model helps on retrieved judgment text
  or on the professional brief's inputs is not measured here; that is E3's job.
- **Partial training-data overlap.** InLegalNER and InLegalBERT's pre-training both come from Indian court
  judgments. The leakage check removed passages shared with our corpus. Overlap with InLegalBERT's own pre-training
  corpus cannot be checked.
- **Single scoring.** There are no repeated test runs and no hyperparameter search. Three seeds give some idea of
  seed variance: combined F1 ranged 0.899–0.915.
- **Time budget.** Training took about 16% longer than the plan's 3 h cap (see section 3).
- **Unreviewed.** These are machine results awaiting the user's review.

## 8. E2 skipped: a measured negative

The IPC/BNS section classifier (E2) was not run. The reasons were measured in E0 (`INLEGALBERT_PLAN.md`):
- **No usable training data for most of our sections.** No open dataset covers BNS or BNSS sections, or CrPC and the
  special Acts. ILSI, the only open statute-identification set, is IPC-only. It covers just **22 of the 60** positive
  labels in our section gold set (12 of 15 distinct IPC sections) and none of the BNS, BNSS, CrPC or special-Act
  ones.
- **No room to improve on the queries ILSI can express.** On the 15 queries it covers, the current ranker is already
  near ceiling: P@1 **0.867 [0.667, 1.0]**, MRR **0.933 [0.833, 1.0]**. The plan's E2 pass condition needs recall@5
  ≥ HX1 + 0.10, with a paired lower bound above 0, on those 15 queries, which is not reachable from that starting
  point.
- **Too expensive for what it could show.** The estimated 4.7 h of training (more at 512 tokens) would buy at most a
  "no harm" result on IPC alone.

E2 is therefore recorded as **not feasible as specified, and skipped by decision**. It is not a failed model: no
classifier was trained and the section gold set was not scored.

## 9. Next step

The plan's decision tree for an E1 pass is: **E3, the retrieval effect.**
- Use the combined system's entities as an extra query signal in an *offline copy* of query understanding.
- Score it on the 30-query retrieval benchmark against the frozen E3 thresholds: no regression means P@5 ≥ 0.873 and
  nDCG@5 ≥ 0.814. An improvement needs ΔnDCG@5 ≥ +0.02 with a paired lower bound above 0.

Only after E3 would a hybrid NER integration be proposed, as a separate step with the user's approval. Nothing is
integrated now.

## Files

- `experiments/inlegalbert/train_ner.py`, `score_gold.py`, `leakage_check.py`, `manifest.json`, and
  `ml_pipeline/PIPELINE.md` (the scoped override for the training hook; see the PR).
- `experiments/inlegalbert/runs/`: per-seed curves and timings (`seed-<n>.json`) and `wallclock.txt`. The console
  logs stay local and uncommitted. Their epoch lines duplicate `seed-<n>.json`, and they contain local paths.
- `experiments/inlegalbert/results/`: `e1_results.json` (all tables, per-example spans) and
  `predictions-seed-<n>.json` (raw model spans on the gold set). They contain no dataset text and no weights.
