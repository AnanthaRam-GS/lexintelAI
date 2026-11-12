# InLegalBERT in LegalAI: scope decision (E0–E4c)

**Decision:** InLegalBERT NER (E1 seed 22, combined with the rules under the frozen E1 policy) becomes the **default
NER backend** (`LEGALAI_NER_BACKEND=combined`), with automatic fallback to the rule-based NER when the checkpoint is
missing or fails. It feeds the entity fields and the brief's **Parties & Roles**. The section classifier (E2) is not
part of the product. Adopted under the project rule "adopt only if it beats the current approach on held-out gold
data", **with the limitation that the final held-out gold is AI-labelled, not human gold** (below).

## The record

| Step | Question | Result |
|---|---|---|
| **E1** | Does InLegalBERT NER beat the rules on our held-out NER gold (36 queries, 89 entities)? | **PASS.** Combined F1 **0.915** [0.864, 0.961] vs rules 0.788 [0.700, 0.866]; all five frozen criteria met by every seed. |
| **E2** | IPC/BNS section classifier | **Skipped by decision.** No open BNS/BNSS data; ILSI (IPC only) covers 22 of our 60 section labels, where the ranker is already near ceiling. No model trained, nothing scored. |
| **E3** | Is it safe in the product? | **PASS.** Retrieval identical on the 30 frozen queries (Δ 0); 0 expected brief items lost; +0.84 GB memory, about +10 ms per query for NER, 0 crashes under the stress test. |
| **E4** | Do the model's parties improve Parties & Roles? (15 known documents) | **FAIL** on the frozen rule "precision not lower": recall 0.298 → 0.702, precision 1.000 → 0.846 (6 errors: 4 accused tagged respondent, 2 names cut mid-word). This record stands. |
| **E4b** | Fix both causes; freeze a new rule judged only on 5 unseen public excerpts | Fixes and rules frozen before any code (`NER_PARTY_ROLES_E4B_PLAN.md`); regression on the 15 known documents (not the judge): P 0.974, R 0.787, no E4 correct party lost. |
| **E4c** | **The judge**, scored once | **PASS on all six frozen rules** (below). |

### E4c judge: the 5 public excerpts, 17 gold parties, scored once (`results/e4b_judge.json`)

| System | Precision [95% CI] | Recall [95% CI] | F1 [95% CI] | TP / FP / FN |
|---|---|---|---|---|
| Regex only | 0.000 | 0.000 | 0.000 | 0 / 1 / 17 |
| **Combined (E4b)** | **0.929** [0.813, 0.938] | **0.765** [0.600, 1.000] | **0.839** [0.737, 0.963] | 13 / 1 / 4 |

| Rule | Result |
|---|---|
| J1 precision ≥ 0.90 | **PASS** (0.929) |
| J2 recall gain ≥ 0.10 | **PASS** (+0.765) |
| J3 0 wrong roles for accused | **PASS** (0) |
| J4 no regex party lost | **PASS** |
| J5 valid P# on every party | **PASS** (14/14) |
| J6 0 parties invented on empty documents | **PASS, vacuously** (every excerpt has parties) |

The one combined false positive is the regex's own output ("accused: respondent- 2", p05), kept unchanged by the
merge; the model added no wrong party. Misses: a substituted petitioner and a designation-only respondent (p01), and
appellants Nos. 2 and 3 named in prose (p04). Paired bootstrap, 10,000 resamples of the 5 excerpts, seed 20261111;
precision CIs use the 6,648 resamples in which the regex predicted anything.

## Limitations (disclosed, and weighed in this decision)

1. **The judge labels are AI-produced, not human gold.** The 5 label files were produced by an AI chat assistant
   (Claude, in a chat session; not Claude Code), blind to all system output, and **not verified by a human**. Their
   `labeller` field reads "AI-labelled (Claude, chat assistant; blind to system output; not human-verified)". They
   were written after E4b merged (file times 21:06–21:07 +0530; E4b merged 20:57) and committed unchanged in
   `b684e9f`, before the single judge run. The labeller and the rule's author are models of the same family, so their
   errors may be correlated. The verdict is therefore **weaker evidence than the project rule assumes**.
2. **The accused-cue fix was not judged on real FIRs or charge sheets.** The excerpts are judgments and orders; that
   fix rests on the 15 known documents and unit tests only.
3. **The excerpt texts were read** by the assistant while trimming them in E4, and their regex-only output appeared in
   the E4 snapshot; they were never labelled, run with the model, or scored before E4c.
4. **Five documents, 17 parties.** One error moves precision by about 7 points; the CIs are wide and coarse.
5. **Alias gap.** An alias written as a separate word after the model's span ("Raju Tambolkar @ Raja") is not added.
6. Regex errors are kept as they are (the merge never removes a regex party), e.g. "accused: respondent- 2".

## Final status of InLegalBERT in the product

- **Default on:** `LEGALAI_NER_BACKEND=combined` (config and `.env.example`). The checkpoint
  (`models/inlegalbert_ner/seed-22/`, SHA-256 `427c3fd9…0a4c`; not in Git; rebuild per `INLEGALBERT_E3_RESULTS.md`,
  local backup in `~/legalai_backups/models/inlegalbert-ner-seed22/`) is required for the model to run.
- **Fallback:** without the checkpoint (as in CI), or on any model error, the rule-based NER is used, queries never
  fail, and `/health` shows `ner.active: deterministic, fallback: true`.
- **Cost:** about +0.84 GB memory, about +10 ms per query for NER, about +0.6 s until the backend is warm (E3).
- **Reversible:** `LEGALAI_NER_BACKEND=deterministic` restores the previous behaviour exactly (byte-identical, tested).
- **Recommended before any external claim:** a human check of the 5 judge labels, and a held-out set of real FIRs and
  charge sheets for the accused cues.

---

Scope decision approved: ______________________ (guide)        Date: ____________

Prepared by the project team with Claude Code. UNREVIEWED until signed.
