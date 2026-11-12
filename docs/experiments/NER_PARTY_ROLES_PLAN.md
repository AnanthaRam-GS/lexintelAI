# NER-powered Parties & Roles in briefs: plan and frozen pass rules (step E4)

Status: **frozen 2026-11-12, before any flag-on run.** Committed together with the gold set, the labelling guide and
the scorer (`experiments/inlegalbert/party_gold/`). Results go in `NER_PARTY_ROLES_RESULTS.md`. All outputs are
UNREVIEWED.

## 1. Question

E1 showed that the combined NER (InLegalBERT seed 22 + rules) finds more entities than the rules alone, and E3 showed
it is safe to run, but nothing consumes the extra entities: the brief's **Parties & Roles** come from regular
expressions only. The project's rule is to adopt a model only if it beats the current approach on held-out gold data.

> With `LEGALAI_NER_BACKEND=combined`, does adding the model's party entities to the regex parties find more of the
> parties in a document, without losing precision, losing a regex party, hurting a role, citing a bad reference or
> inventing parties?

The default stays `deterministic` whatever the result; this step only recommends.

## 2. Gold set

`experiments/inlegalbert/party_gold/` (README there):

| Set | Documents | Gold parties | Ground truth |
|---|---|---|---|
| Fixtures | 5 (judgment, FIR, charge sheet, petition, unknown) | 10 | the fixtures' `*.expected.json`, written in BRIEF-003 before this step |
| Synthetic | 10 (2 FIR, 2 charge sheet, 2 petition, 1 judgment, 2 order, 1 unknown) | 37 | by construction in `generate_gold.py` |
| Public excerpts | 5 trimmed public judgments | pending | a teammate, with `LABELLING_GUIDE.md` |

Two documents have no party (`f_unknown`, `s10_unknown_legal_aid_minutes`). The role vocabulary is the existing
`parties_and_roles` vocabulary: appellant, respondent, petitioner, applicant, accused, complainant, informant. It has
no witness role, so witnesses are not parties (section 3).

## 3. Systems compared

Both run through the product path: each document is rendered to a PDF, parsed, chunked and wrapped as an upload
(`parse_document` -> `chunk_document` -> `build_private_chunks`), then `build_local_document_map`. The output scored is
`document_map.parties_and_roles` (what `professional_brief.parties_and_roles` renders as `Role: Name [P#, p. N]`).

**S0, regex only** (`LEGALAI_NER_BACKEND=deterministic`, today's product): `extract_parties_and_roles`, unchanged.

**S1, regex + model** (`LEGALAI_NER_BACKEND=combined`). The regex parties first, unchanged, then parties from the
model, under this rule (frozen here; implemented in `local_document_map.py`, unit-tested with a mocked model):

1. **Model entities.** For each chunk, the model's own predictions mapped to the schema with the frozen E1 mapping and
   the frozen E1 threshold (confidence >= 0.70), from the same inference as the combined NER (one call per chunk). They
   are taken before the hybrid merge because the merge can drop the native InLegalNER type when a rule entity has the
   same span; the rules have no person or organisation type, so no rule entity is bypassed.
2. **Candidates.**
   - InLegalNER **PETITIONER** and **RESPONDENT** entities (party types): always candidates.
   - **OTHER_PERSON** and **ORG** entities: candidates **only with a role cue** (rule 3).
   - **WITNESS, JUDGE, LAWYER** and all other types: never parties (no such role in the vocabulary).
3. **Role cue.** One of the seven role words (singular or plural, or "co-accused"), on the same line as the entity:
   - *before* it, followed only by an optional number ("No. 2", "Nos. 1 and 2") and filler ("namely", "viz.", "i.e.",
     "the", "is", "was", "being", an honorific, ":", "-", ",", "(") up to the entity ("the accused Ravi ...",
     "Respondent No. 2: Priya ...", "petitioners No. 1 and 2, namely, A ...");
   - or *after* it, separated only by spaces, dots, commas, dashes or "(" and an optional "the", possibly on the next
     line (cause titles: "Venus Goyal and anr.\n.... Petitioners", "X (complainant)", "X, the accused");
   - or a **list continuation**: the entity follows another candidate of the same chunk that took its role from a
     cue before it, with only ",", "and" or "&" between them ("the accused A, B and C").
   The cue before the entity wins over the cue after it.
4. **Role.**
   - OTHER_PERSON / ORG: the cue's role.
   - PETITIONER / RESPONDENT: the cue's role when the cue is on the label's side (petitioner side: petitioner,
     appellant, applicant, complainant, informant; respondent side: respondent, accused); otherwise PETITIONER takes
     the document's "left party" role (the existing "X vs Y" rule: its most frequent of appellant / petitioner /
     applicant, else "petitioner/appellant") and RESPONDENT takes "respondent".
5. **Name.** The entity text with surrounding spaces and punctuation stripped, passed through the existing
   `_clean_party_name` (which drops generic words such as "accused" or "State" alone and names under 3 characters).
6. **Merge with the regex parties** (deterministic):
   - regex parties first, in their existing order, unchanged;
   - model parties appended in document order (chunk order, then position);
   - a model party is skipped when it is the **same person** as a party already in the list, whatever its role:
     equal normalized names (case, honorifics, a leading "the", punctuation, "alias" -> "@"), an alias part shared
     ("Neelam" vs "Neelam @ Neeraj"), or one name's words a contiguous run of the other's ("Sonu" vs
     "Suresh Kotwalkar @ Sonu", "Ravi" vs "Ravi Sampleton"); the earlier entry wins, so a regex party is never
     replaced or given a second role;
   - the existing cap of 10 parties applies to the merged list.
7. **Reference.** Each model party cites the chunk the entity was found in (`P#`, pages), so every party carries a
   reference.

With the flag off, the code path is unchanged and the output is byte-identical (tested against a snapshot of
today's outputs taken before the change).

## 4. Scoring (`score_parties.py`)

- **Strict (primary):** exact match of the normalized name and an acceptable role (the gold role or one of its
  `alternative_roles`), one-to-one. The same gold party predicted again with another acceptable role is a
  *duplicate* (neither TP nor FP).
- **Partial credit (secondary, reported only):** name 0.5 for an alias part or a contiguous word run covering at least
  half of the longer name; role 0.5 within a role group ({petitioner, appellant, applicant, petitioner/appellant},
  {complainant, informant}); credit = name x role.
- **Metrics:** micro precision, recall and F1 over documents; per document; per role (TP and FN under the gold role,
  FP under the predicted role).
- **Uncertainty:** paired bootstrap over documents, 10,000 resamples, seed 20261111, 95% percentile CI.

## 5. Pass rules (frozen)

Comparison: S1 (combined) vs S0 (regex only), on the evaluation set of section 6. **S1 passes only if all hold:**

| # | Rule | Exact test |
|---|---|---|
| R1 | Party recall improves by >= 0.10 | strict micro recall: ΔR >= **0.10** and the paired-bootstrap 95% CI lower bound of ΔR **> 0** |
| R2 | Precision is not lower | strict micro precision: P(S1) >= P(S0) (point estimate; CI reported) |
| R3 | No correctly found regex party is lost | for every document, every gold party S0 matches strictly is also matched strictly by S1 |
| R4 | No role becomes worse | for every role, strict F1(S1) >= F1(S0); F1_role = 2TP / (2TP + FP + FN), 1.0 when a role has no gold party and no prediction |
| R5 | Every party carries a valid P# reference | every S1 party cites a chunk of that document whose text contains the party's name (case- and whitespace-insensitive); 100% |
| R6 | Nothing invented on documents with no party | 0 S1 parties on every document whose gold has no party |

**Why these numbers.** +0.10 recall is about 5 more parties out of 47: the smallest gain worth running a 436 MB model
for one field. A gain must not come from precision, from replacing what the regex already gets right, or from one
role at the expense of another. R5 and R6 are the product's grounding rules (a party must be checkable in the
document, and nothing may be invented), so they allow no exception.

## 6. Evaluation sets and what they can show

- **Now:** fixtures + synthetic, 15 documents, 47 parties. The verdict on these 15 is **provisional**.
- **Later:** the 5 public excerpts once a teammate has labelled them. The scorer then scores them separately and
  with the other 15 (20 documents); the rules are applied to the 20. Until then they are reported as **pending**.
  A recommendation to switch the default needs a PASS on the 20.

**What about 20 documents can show:** a *large* effect (several parties more or fewer), and any violation of R3, R5
or R6, each of which needs only one document. **What they cannot show:**
- small effects: a recall change of a few points is within the bootstrap noise of 15 to 20 documents;
- the real distribution of documents: 10 of the 15 are synthetic, written by the same author (the assistant, Claude) who wrote the
  rule in section 3, before the measurement but knowing the regex. This is a source of bias in either direction; the
  commit order (gold, plan and rule before any flag-on run; no change to the rule after it) limits but does not
  remove it;
- generalisation across courts, languages and OCR quality: there are no scanned documents in the gold set;
- the fixtures use deliberately artificial names ("Meera Placeholder", "Dev Fakename") that a model trained on real
  judgments may not recognise as names, which may understate the model;
- one labeller for the public excerpts, so no agreement figure.
A PASS is evidence for this product's brief field on documents like these; it is not a general claim about the model.

## 7. Procedure and commit order

1. Gold set, labelling guide, scorer, this plan and a flag-off snapshot of today's outputs (all 20 documents),
   committed **before** any flag-on run.
2. Integration (flag on only) and unit tests with a mocked model; flag-off output byte-identical to the snapshot.
3. Measurement: S0 and S1 on the 15 documents (`experiments/inlegalbert/e4_party_roles.py`), no LLM; results in
   `experiments/inlegalbert/results/e4_party_roles.json`. The public excerpts are scored once labelled.
4. Results and verdict per rule in `NER_PARTY_ROLES_RESULTS.md`, with a recommendation on the default.

## 8. Not done in this step

No retraining or retuning; the E1 mapping, threshold and combination policy are unchanged. No change to prompts,
retrieval, data, Chroma, BM25 or frozen or pinned files. No LLM calls. The public excerpts are not labelled by the
author. The flag default stays `deterministic`.
