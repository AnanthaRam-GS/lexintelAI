# Parties & Roles E4b: regression check on the 15 known documents — NOT THE JUDGE

Status: **UNREVIEWED. This is a regression check, not the E4b verdict.** The judge is the 5 public excerpts, scored
once after a teammate labels them (`NER_PARTY_ROLES_E4B_PLAN.md` sections 2 and 6). These 15 documents (5 fixtures,
10 synthetic) are the ones E4's errors were found on, so a good result here says nothing about generalisation. E4's
own record (FAIL on R2) is unchanged.

Raw results: `experiments/inlegalbert/results/e4b_regression.json`
(`.venv/bin/python experiments/inlegalbert/e4b_party_roles.py regression --out experiments/inlegalbert/results`; it
never opens the public label files). Seed 22 checkpoint on MPS, 15 combined calls, 0 fallbacks. No LLM calls.

## Results (strict scoring, 47 gold parties)

| System | Precision [95% CI] | Recall [95% CI] | F1 [95% CI] | TP | FP | FN |
|---|---|---|---|---|---|---|
| Regex only | 1.000 [1.000, 1.000] | 0.298 [0.121, 0.524] | 0.459 [0.215, 0.688] | 14 | 0 | 33 |
| E4 combined (for reference) | 0.846 | 0.702 | 0.767 | 33 | 6 | 14 |
| **E4b combined** | **0.974 [0.923, 1.000]** | **0.787 [0.640, 0.923]** | **0.871 [0.771, 0.952]** | 37 | 1 | 10 |

E4b vs regex: Δ precision −0.026 [−0.077, 0.000], Δ recall +0.489 [0.244, 0.721], Δ F1 +0.412 [0.180, 0.679]
(paired document bootstrap, 10,000 resamples, seed 20261111). Partial credit: precision 0.987, recall 0.798.

**Required by the plan (section 5):**
- **No E4 correct party lost:** all 33 gold parties E4 matched strictly are still matched.
- **E4's six errors:** none of the six E4 outputs is produced any more.

| E4 error | E4b output | Status |
|---|---|---|
| `f_chargesheet` accused: Dev Fake | snapped to "Dev Fakename", merged with the regex party (same person) | resolved |
| `s03` respondent: Manoj Gaikar @ Bunty | accused: Manoj Gaikar @ Bunty | resolved |
| `s03` respondent: Farhan Shaikhwadi | accused: Farhan Shaikhwadi | resolved |
| `s03` respondent: Kavita Dongrekar | accused: Kavita Dongrekar | resolved |
| `s03` respondent: Raju Tam | accused: **Raju Tambolkar** | role and cut word resolved; still a strict false positive, because the model's span stops before the alias ("@ Raja") and gold is "Raju Tambolkar @ Raja" (partial credit 0.5) |
| `s07` appellant: Bharat Ninave @ Bha | appellant: Bharat Ninave @ Bhau | resolved |

So both error causes are fixed (no wrong role, no name cut inside a word). The one remaining false positive is a
different error: an alias that is a separate word and that the model left out of its span. Fix 1 does not add whole
words, by design.

Applying the judge rules J1–J6 to these 15 documents (information only): all would hold (precision 0.974,
recall +0.489, 0 wrong accused roles, no regex party lost, 38/38 valid references, 0 invented on the two empty documents). **This is not a pass of E4b.**

## Per document (TP / FP)

| Document | Gold | Regex | E4 combined | E4b combined |
|---|---|---|---|---|
| `f_chargesheet` | 3 | 3 / 0 | 3 / 1 | 3 / 0 |
| `f_fir` | 2 | 2 / 0 | 2 / 0 | 2 / 0 |
| `f_judgment` | 2 | 2 / 0 | 2 / 0 | 2 / 0 |
| `f_petition` | 3 | 3 / 0 | 3 / 0 | 3 / 0 |
| `f_unknown` | 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `s01_fir_multi_accused` | 4 | 1 / 0 | 1 / 0 | 1 / 0 |
| `s02_fir_org_complainant` | 5 | 2 / 0 | 2 / 0 | 2 / 0 |
| `s03_chargesheet_four_accused` | 5 | 1 / 0 | 1 / 4 | 4 / 1 |
| `s04_chargesheet_company_accused` | 4 | 0 / 0 | 3 / 0 | 3 / 0 |
| `s05_petition_bail` | 4 | 0 / 0 | 4 / 0 | 4 / 0 |
| `s06_petition_quashing_multi` | 5 | 0 / 0 | 5 / 0 | 5 / 0 |
| `s07_judgment_criminal_appeal` | 5 | 0 / 0 | 3 / 1 | 4 / 0 |
| `s08_order_bail_cancellation` | 3 | 0 / 0 | 2 / 0 | 2 / 0 |
| `s09_order_cheque_complaint` | 2 | 0 / 0 | 2 / 0 | 2 / 0 |
| `s10_unknown_legal_aid_minutes` | 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Per role, E4b F1 (TP/FP/FN): accused 0.690 (10/1/8), appellant 1.000 (3/0/0), applicant 1.000 (3/0/0), complainant
0.933 (7/0/1), informant 1.000 (1/0/0), petitioner 1.000 (3/0/0), respondent 0.952 (10/0/1).

## Remaining misses (information only; nothing was changed after this run)

- `s01`: the accused-list lines are recognised (FIR, three list lines under "Details of known accused:"), but the
  model returns no entity at or above the frozen 0.70 threshold for the three names, so there is nothing to label.
- `s02`: the model finds the three accused, but the narrative ("Rakesh Bhosrekar, managing director of ...") has no
  cue, so the E4 rule does not use them.
- `s04` (company accused), `s07` (complainant who is PW-1), `s08` ("opposite party No. 2"), and the `s03` alias: as in
  E4.

## What the judge will exercise

The 5 public excerpts are judgments and orders, not FIRs or charge sheets, so the judge exercises fix 1 and the E4
rule, and **not fix 2** (plan section 7). Fix 2 is supported only by this regression check and the unit tests.
