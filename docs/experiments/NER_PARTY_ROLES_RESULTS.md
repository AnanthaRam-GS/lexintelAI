# NER-powered Parties & Roles in briefs: results and verdict (step E4)

Status: **UNREVIEWED.** Plan and frozen rules: `NER_PARTY_ROLES_PLAN.md`. Gold set:
`experiments/inlegalbert/party_gold/`. Raw results: `experiments/inlegalbert/results/e4_party_roles.json`. No LLM
calls were made.

## Summary

| | |
|---|---|
| **Verdict (fixtures + synthetic, 15 documents, provisional)** | **FAIL**: R2 (precision not lower) fails; R1, R3, R4, R5 and R6 pass |
| Recall | 0.298 -> **0.702** (+0.404, paired 95% CI [0.158, 0.659]) |
| Precision | 1.000 -> **0.846** (-0.154, CI [-0.342, 0.000]) |
| F1 | 0.459 -> 0.767 (+0.308, CI [0.054, 0.603]) |
| Public excerpts (5) | **pending**: not labelled yet, so not run and not scored |
| Recommendation | **keep `deterministic` as the default** (unchanged) |

The model finds many parties the regular expressions miss (19 more correct parties out of 47). But it adds 6 wrong
ones, on a baseline that makes no errors on these documents, so the frozen rule "precision is not lower" fails. The
6 errors have two causes, both visible below; neither is fixed here, because the rule and the gold set were frozen
before this run.

## 1. Commit order

| Commit | Content |
|---|---|
| `f3957e2` | gold set (fixtures, 10 synthetic by construction, 5 public excerpts with empty labels), labelling guide, scorer, frozen plan, **before any flag-on run** |
| `60eabb7` | flag-off snapshot of today's output on the 20 documents, from the code before the change |
| `3996174` | integration (flag on only) and unit tests; plan amendment to rule 5 (name filter) and a list-continuation clarification, both **before any flag-on run** |
| `871c74d` | measurement script and results (the first flag-on run on these documents) |
| this commit | results, verdict, E1 erratum, checkpoint backup note |

## 2. Results (strict scoring)

Both systems run through the upload path (PDF -> parse -> chunk -> local document map). S1 used the seed 22
checkpoint on MPS: 15 combined calls, 0 fallbacks. Bootstrap: 10,000 paired resamples of documents, seed 20261111.

| Set | Docs | Gold | System | Precision [95% CI] | Recall [95% CI] | F1 [95% CI] | TP | FP | FN |
|---|---|---|---|---|---|---|---|---|---|
| **fixtures + synthetic** | 15 | 47 | regex | 1.000 [1.000, 1.000] | 0.298 [0.121, 0.524] | 0.459 [0.215, 0.688] | 14 | 0 | 33 |
| | | | combined | 0.846 [0.659, 1.000] | 0.702 [0.527, 0.879] | 0.767 [0.600, 0.919] | 33 | 6 | 14 |
| | | | Δ | -0.154 [-0.342, 0.000] | **+0.404 [0.158, 0.659]** | +0.308 [0.054, 0.603] | | | |
| fixtures | 5 | 10 | regex | 1.000 | 1.000 | 1.000 | 10 | 0 | 0 |
| | | | combined | 0.909 [0.786, 1.000] | 1.000 | 0.952 [0.880, 1.000] | 10 | 1 | 0 |
| synthetic | 10 | 37 | regex | 1.000 | 0.108 [0.000, 0.212] | 0.195 [0.000, 0.350] | 4 | 0 | 33 |
| | | | combined | 0.821 [0.576, 1.000] | 0.622 [0.429, 0.833] | 0.708 [0.500, 0.898] | 23 | 5 | 14 |
| public excerpts | 5 | — | — | pending | pending | pending | | | |

Partial credit (secondary): combined precision 0.859, recall 0.713 (one name truncation earns 0.5); regex unchanged.
No duplicates were produced.

### Verdict per rule (fixtures + synthetic)

| Rule | Result | Evidence |
|---|---|---|
| R1 recall +0.10, CI lower bound > 0 | **PASS** | +0.404 [0.158, 0.659] |
| R2 precision not lower | **FAIL** | 0.846 < 1.000 (6 false positives) |
| R3 no correctly found regex party lost | **PASS** | all 14 regex hits kept; on every document the regex items are the first items of the combined output, unchanged |
| R4 no role worse | **PASS** | every role's F1 is equal or higher (table below) |
| R5 every party has a valid P# | **PASS** | 39/39 combined parties cite a chunk of their document that contains the name |
| R6 nothing invented on documents with no party | **PASS** | 0 parties on `f_unknown` and `s10_unknown_legal_aid_minutes` |
| **Overall** | **FAIL** | |

On the 5 fixtures alone (reported, not the evaluation set): no recall gain (the regex already finds all 10), one false
positive, so precision and the "accused" F1 (1.000 -> 0.857) drop.

### Per role (fixtures + synthetic; TP and FN by the gold role, FP by the predicted role)

| Role | Regex F1 (TP/FP/FN) | Combined F1 (TP/FP/FN) |
|---|---|---|
| accused | 0.286 (3/0/15) | 0.538 (7/1/11) |
| appellant | 0.000 (0/0/3) | 0.667 (2/1/1) |
| applicant | 0.500 (1/0/2) | 1.000 (3/0/0) |
| complainant | 0.769 (5/0/3) | 0.933 (7/0/1) |
| informant | 1.000 (1/0/0) | 1.000 (1/0/0) |
| petitioner | 0.500 (1/0/2) | 1.000 (3/0/0) |
| respondent | 0.429 (3/0/8) | 0.800 (10/4/1) |

### Per document

| Document | Type | Gold | Regex TP / FP | Combined TP / FP | Added by the model |
|---|---|---|---|---|---|
| `f_chargesheet` | charge sheet | 3 | 3 / 0 | 3 / 1 | accused: Dev Fake |
| `f_fir` | FIR | 2 | 2 / 0 | 2 / 0 | — |
| `f_judgment` | judgment | 2 | 2 / 0 | 2 / 0 | — |
| `f_petition` | petition | 3 | 3 / 0 | 3 / 0 | — |
| `f_unknown` | unknown | 0 | 0 / 0 | 0 / 0 | — |
| `s01_fir_multi_accused` | FIR | 4 | 1 / 0 | 1 / 0 | — |
| `s02_fir_org_complainant` | FIR | 5 | 2 / 0 | 2 / 0 | — |
| `s03_chargesheet_four_accused` | charge sheet | 5 | 1 / 0 | 1 / 4 | respondent: Manoj Gaikar @ Bunty; respondent: Farhan Shaikhwadi; respondent: Kavita Dongrekar; respondent: Raju Tam |
| `s04_chargesheet_company_accused` | charge sheet | 4 | 0 / 0 | 3 / 0 | complainant: Testgarh Agricultural Produce Market Committee; accused: Harshad Malvankar; accused: Jitendra Sawlekar |
| `s05_petition_bail` | petition | 4 | 0 / 0 | 4 / 0 | applicant: Vikas Rangnekar @ Vicky; respondent: State of Fictionaland; respondent: Shabana Mulani; accused: Ajay Phadtare |
| `s06_petition_quashing_multi` | petition | 5 | 0 / 0 | 5 / 0 | petitioner: Neha Saraswat; petitioner: Anil Saraswat; respondent: State of Fictionaland; respondent: Fictional Housing Finance Ltd; respondent: Rohit Jadhavkar |
| `s07_judgment_criminal_appeal` | judgment | 5 | 0 / 0 | 3 / 1 | appellant: Gopal Ninave; respondent: State of Fictionaland; appellant: Sitaram Ninave; appellant: Bharat Ninave @ Bha |
| `s08_order_bail_cancellation` | order | 3 | 0 / 0 | 2 / 0 | applicant: Kamini Bhagwat; respondent: State of Fictionaland |
| `s09_order_cheque_complaint` | order | 2 | 0 / 0 | 2 / 0 | complainant: Sunrise Fictional Traders; accused: Mahesh Tidke |
| `s10_unknown_legal_aid_minutes` | unknown | 0 | 0 / 0 | 0 / 0 | — |

## 3. Error analysis (information only; nothing was changed after the run)

**The 6 false positives.**
- **Wrong default role (4, `s03`).** The charge sheet lists the accused as "A-1 Manoj Gaikar @ Bunty", "A-2 ...". The
  model tags all four as RESPONDENT, "A-1" is not one of the frozen cue words, so rule 4 gives them the default role
  "respondent"; the gold role is "accused". The names are right; the role is wrong, so each is both a false positive
  and a miss.
- **Truncated names (2).** "Dev Fake" for "Dev Fakename" (`f_chargesheet`) and "Bharat Ninave @ Bha" for
  "Bharat Ninave @ Bhau" (`s07`). This is the WordPiece-boundary decoding error already noted in E1 (the decoder can
  end an entity inside a word). "Dev Fake" is also not recognised as the same person as the regex's "Dev Fakename"
  (the word "Fake" is not "Fakename"), so it is added as a second accused.

**The 14 misses.** The 4 role errors above; the numbered accused list of `s01` ("(i) Suresh Kotwalkar @ Sonu; ...")
and the narrative accused of `s02` ("Rakesh Bhosrekar, managing director of ...") have no frozen cue and were not
tagged as party types (6); the company accused of `s04` (1); the complainant who is PW-1 in `s07` and the truncated
"Bhau" (2); "opposite party No. 2, namely, Sameer Lonkar" in `s08` ("opposite party" is not a cue word) (1).

**What this suggests, for a separate, newly frozen step only:** expanding model spans to whole words before use, and
a cue for "A-N"-style accused numbering or a document-type default (a RESPONDENT entity in an FIR or charge sheet
is usually the accused). Both were found by looking at these results, so they cannot be judged on these 15 documents;
they would need data not yet used (for example the 5 public excerpts, with the revised rule frozen before they are
scored).

## 4. What these 15 documents can and cannot show

- They show a **large recall effect** with a CI that excludes zero, and they show the R2 failure directly (6 named
  false positives). R3, R5 and R6 are per-document checks and hold on every document.
- The precision comparison is against a baseline with **no errors on these documents** (CI [1.0, 1.0]), because the
  regex finds only 14 parties, all in labelled lines and simple cause titles. Any added error therefore fails R2.
  Whether the regex is as precise on real documents is not measured here.
- 10 of the 15 documents are synthetic and were written by the same author (the assistant) who wrote the rule, before
  the run. The fixtures use artificial names ("Dev Fakename") that may be harder for a model trained on real
  judgments; one of the 6 errors is on such a name.
- No scanned document and no document longer than 2 pages; the gold comes from construction or from the fixtures'
  expectation files, with no second labeller. A PASS or FAIL here is about this brief field on documents like these.
- The verdict is **provisional** until the 5 public excerpts are labelled; the plan requires a PASS on all 20 for a
  recommendation to switch.

## 5. Cost

The party rule reuses the inference the combined backend already runs for the document map's entity fields (one call
per chunk, shared; E3 measured that call). Map build time on these 1–2-page documents: median 5.7 ms (regex only) vs
42.9 ms (combined), at most 172 ms. No new model, no extra memory.

## 6. Recommendation

**Keep `LEGALAI_NER_BACKEND=deterministic` as the default.** The frozen rule set fails on R2. The recall gain is large
and real on these documents, so the feature stays available behind the flag, but switching the default would add
wrong parties (wrong roles, truncated names) to briefs that today contain none on this data. A switch should wait for:
(1) the 5 public excerpts to be labelled and scored, and (2) if wanted, a separate step that fixes the two error causes
under a newly frozen rule and is judged on data not used here.

## 7. Public excerpts: pending

`public/*.labels.json` are empty (`label_status: "unlabelled"`). The scorer accepts them once a teammate has filled
them (`LABELLING_GUIDE.md`; `score_parties.py --self-test` validates them). Then run
`.venv/bin/python experiments/inlegalbert/e4_party_roles.py --out experiments/inlegalbert/results`: it scores the
public excerpts separately and with the other 15 (sets `public` and `all`) and applies the same rules.

## 8. Other items in this step

- **E1 erratum.** `INLEGALBERT_PLAN.md` gains a dated "Errata" section and `INLEGALBERT_E1_RESULTS.md` a dated note:
  a model entity with the same span can replace a lower-priority, non-protected rule entity; the one known case is
  eval-q010 in the E3 retrieval benchmark; E1's scores already include this behaviour (same merge code), and on the
  36 E1 test examples no such replacement occurred for any seed. The frozen threshold section is unchanged: its
  sha256 (lines 131–174) is `497f183e8c5129d985bd406b23e60e73591170828136a94e19a4bb4bbd944596` before and after;
  the whole-file hash changes from `4cc202f6…` to `68ed4d1b…` because the erratum is appended.
- **Checkpoint backup.** The seed 22 checkpoint was copied to `~/legalai_backups/models/inlegalbert-ner-seed22/` on the
  project owner's machine (directory mode 700, files 600) with a `SHA256SUMS` file; `shasum -c` passes for all four
  files, `model.safetensors` matches the pinned `427c3fd9…0a4c`, and the backend loads and runs it from there with
  `LEGALAI_NER_CHECKPOINT_DIR` set to it. This is a second copy on the same machine, not off-site storage (the storage
  decision from E3 is still open).
