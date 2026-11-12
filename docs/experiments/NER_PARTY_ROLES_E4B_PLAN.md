# Parties & Roles, step E4b: name-boundary and accused-role fixes, judged on held-out excerpts (plan)

Status: **frozen 2026-11-12, before any code change.** E4b is a new experiment, separate from E4. **E4's record is
unchanged: E4 failed its frozen rule R2** (`NER_PARTY_ROLES_RESULTS.md`). All outputs are UNREVIEWED. The default
stays `LEGALAI_NER_BACKEND=deterministic`; nothing here changes it.

## 1. Question

E4's six errors on the 15 known documents had two causes: model names cut inside a word ("Dev Fake",
"Bharat Ninave @ Bha") and accused listed as "A-1 ..." given the role "respondent". With both fixed, does
`combined` beat regex-only on documents that were never used to build or tune the party rule?

## 2. The judge: the 5 public excerpts, scored once

- **Judge:** the 5 trimmed public judgment excerpts in `experiments/inlegalbert/party_gold/public/`
  (`p01_gujarat_hc_2021` ... `p05_allahabad_hc_2019`), with labels from a teammate following `LABELLING_GUIDE.md`.
  When this plan was frozen, all five label files were still the empty files committed in E4 (`f3957e2`); this was
  checked by git blob id, without opening them.
- **Scored once,** after all five are labelled, with the single command in section 6. The scoring script refuses to
  run while any file is unlabelled and refuses to overwrite an existing judge result. No result on the excerpts
  feeds back into the rule: whatever they show is the E4b verdict.
- **Not opened in E4b:** the label files are not opened, read or scored in this step. The flag-on system is not run
  on the excerpts. (The existing flag-off byte-identity test renders the excerpt *texts* through today's regex path;
  E4b changes that test helper so it no longer reads the label files.)
- **Disclosure of earlier exposure.** In E4 the assistant (Claude), which writes the E4b rule, read the excerpt texts
  while trimming them (before any rule existed), and the E4 flag-off snapshot shows regex-only output on them. They
  have never had labels, never been run with the model, and never been scored. The fixes below come from E4's errors
  on the 15 known documents and from the step E4b brief; the excerpts were not reopened to design them.

## 3. Systems

- **S0, regex only:** `LEGALAI_NER_BACKEND=deterministic`, unchanged (byte-identical to the E4 snapshot).
- **S1, regex + model (E4b):** the E4 rule (`NER_PARTY_ROLES_PLAN.md` section 3, including its rule-5 amendment),
  with exactly two changes, both only with `combined`:

**Fix 1: whole-word spans.** Before a model entity is used as a party candidate, its span is snapped to whole words
using the original chunk-text offsets:
- leading and trailing whitespace and punctuation are trimmed off the span;
- the start moves left and the end moves right while the neighbouring character is a word character (a letter or
  digit, `\w`), or an apostrophe or hyphen with a word character on its far side ("Co-operative", "D'Souza");
- the name is then taken from the snapped span.
So "Dev Fake|name" becomes "Dev Fakename" and "Bharat Ninave @ Bha|u" becomes "Bharat Ninave @ Bhau". The snapping is
applied only in the party extraction (`local_document_map`). The E1 decoder (`ner_backend.decode_windows`), the
entities of the combined NER used by the other document-map fields and by query understanding, E1's scored results and
its 0.70 threshold are not changed.

**Fix 2: accused cues in FIRs and charge sheets.** Only when the document's detected type
(`detect_document_type_with_confidence`) is `FIR` or `chargesheet` (final and police reports are detected as
`chargesheet`). A candidate gets the role **accused** when:
- **prefix cue:** on the same line, the text just before the entity (up to 80 characters) ends with an accused number,
  optionally followed by filler (":", "-", ".", ")", ",", or an honorific): `A-1`, `A1`, `A 1`, `A-1.`, `Accused No. 1`,
  `Accused No.1`, `Accused 1` (case-insensitive; one or more digits); or
- **heading or list context:** the entity is the first candidate on a list line under an accused heading. An
  accused heading is a line that contains the word "accused" and ends with ":" (e.g. "Details of known accused:",
  "Accused charge-sheeted:"). Its list lines are the lines right after it that start with a list marker: "(i)" or
  "i)" (roman numerals), "1." or "1)" or "(1)", "-", "•", "*", or an accused number as above. The list ends at the
  first line that does not start with a marker.
- **Precedence:** in these two document types the accused cue decides the role for every candidate type
  (PETITIONER, RESPONDENT, OTHER_PERSON, ORG), before the E4 cue rules and the RESPONDENT/PETITIONER defaults. A
  candidate without an accused cue follows the E4 rule unchanged. In all other document types nothing changes.
- An OTHER_PERSON or ORG entity with an accused cue becomes a candidate (as with any E4 role cue).

Everything else is E4's: candidates, the E4 cues, the same-person merge (regex parties first and unchanged), the cap
of 10, references to the chunk. Witnesses, judges and lawyers are never parties.

## 4. Pass rules on the judge (S1 vs S0, the 5 excerpts, strict scoring of `score_parties.py`)

**E4b passes only if all hold:**

| # | Rule | Exact test |
|---|---|---|
| J1 | Absolute precision >= 0.90 | strict micro precision of S1 >= **0.90** (point estimate) |
| J2 | Recall gain >= 0.10 | strict micro recall: R(S1) - R(S0) >= **0.10** (point estimate) |
| J3 | 0 wrong roles for accused persons | no S1 party whose normalized name equals that of a gold party with "accused" as its role or an alternative role has a role outside that party's acceptable roles; count must be **0** |
| J4 | No correctly found regex party lost | every gold party S0 matches strictly is matched strictly by S1, on every excerpt |
| J5 | Valid P# on every party | every S1 party cites a chunk of that excerpt whose text contains the name (case- and whitespace-insensitive); 100% |
| J6 | Nothing invented on documents with none | 0 S1 parties on every excerpt whose gold has no party (vacuous, and reported as such, if every excerpt has parties) |

Paired bootstrap 95% CIs (10,000 resamples of the 5 excerpts, seed 20261111) are reported for precision, recall and
F1 and their differences. They are information only: the rules use the point estimates, as written.

**Why these numbers.** E4's R2 compared against a regex that made no error on the known documents, so one wrong party
failed it. E4b asks instead for an absolute precision a lawyer would accept in a brief (at most about 1 wrong party in
10). Recall still has to gain at least 0.10. J3 targets the error E4 found, and J4–J6 are E4's grounding rules,
unchanged.

## 5. The 15 known documents: regression check only, not the judge

S0 and S1 are run on the 5 fixtures and 10 synthetic documents of E4. This is reported, and labelled "not the judge".
It is expected to show:
- **no E4 correct party lost:** every gold party E4's S1 matched strictly (33) is still matched strictly;
- **both error causes fixed:** the four "A-N" accused in `s03` get the role accused, and "Dev Fake" and
  "Bharat Ninave @ Bha" become the full names (the first then merges with the regex's "Dev Fakename" as the same
  person).
These documents were used to find the errors, so whatever they show says nothing about E4b's generalisation.

## 6. Scoring the judge (next step, after a teammate labels the excerpts)

```bash
.venv/bin/python experiments/inlegalbert/e4b_party_roles.py judge --out experiments/inlegalbert/results
```

It checks that all five label files are labelled and valid, runs S0 and S1 on the five excerpts (S1 with the seed 22
checkpoint), scores them, applies J1–J6, and writes `results/e4b_judge.json` once. It refuses to run if any file is
unlabelled or if `e4b_judge.json` already exists. The regression check of section 5 is
`e4b_party_roles.py regression --out ...` (it never opens the public label files).

## 7. What 5 documents can and cannot show

- **Can show:** whether the fixed system is usable on real judgment text of this kind, at a coarse level; any J3, J4,
  J5 or J6 violation (one document is enough); a large recall gain.
- **Cannot show:** a precise precision or recall. With perhaps 10–20 gold parties, one error moves precision by
  5–10 points. A document bootstrap over 5 items gives very wide intervals, and with 5 documents there are only
  126 distinct resamples, so the "95% CI" is coarse. A pass at 0.90 could be one lucky document away from a fail.
- **Not representative:** the 5 excerpts are a seeded sample of appeal, revision and petition judgments from High
  Courts and the Supreme Court. They contain no FIR or charge sheet, so **Fix 2 is not exercised by the judge at
  all**; it is checked only by the regression documents and the unit tests. Excerpts are short openings, not whole
  judgments.
- **One labeller,** no agreement figure. The labeller follows a guide written before E4b.
- **Earlier exposure** (section 2) is a residual risk of bias that the commit order limits but does not remove.
A pass is evidence that the fixed rule is worth trying as an opt-in on real judgments. It would not by itself justify
switching the default; that decision stays with the project owner.

## 8. Procedure and commit order

1. This plan, committed before any code change.
2. The two fixes (flag on only), the test-helper change so no test reads the public label files, and unit tests
   (one per fix, plus the flag-off byte-identity test against the E4 snapshot).
3. The regression check on the 15 known documents (results file and report, labelled "not the judge").
4. Judge scoring: a later step, with the command of section 6, after the teammate's labels are committed.

## 9. Not done in E4b

No retraining or retuning; E1's decoder, mapping, threshold and results are unchanged. No change to prompts,
retrieval, data, Chroma, BM25 or frozen or pinned files. No LLM calls. The public label files are not opened and the
excerpts are not scored. The flag default stays `deterministic`.
