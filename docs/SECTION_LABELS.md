# Section labels in answers and briefs (step 25)

The answer model names statutory provisions with a one-line label of its own. The citation validator checks
structured citations to retrieved evidence, not these labels, and the docs-site screenshots showed wrong ones:
"Section 309(4) BNS – offences relating to suicide attempts" (309 is robbery), "Section 115(2) BNS – provisions on
medical examination of complainant" (115 is voluntarily causing hurt) and "Section 173 BNS – registration of FIR"
(FIR registration is BNSS 173). Since step 25 every section the model names is resolved against LegalAI's trusted
sources before it reaches a response. The resolver is `backend/app/services/section_labels.py`. It runs in the
response layer (`api/query.py`); no prompt, validator, retrieval code or data changed.

## Where model labels reach a response

| Field | Model output it comes from | Resolved |
|---|---|---|
| `identified_sections[]` (professional) | `explicit_legal_provisions` + `potential_additional_provisions` | yes |
| `case_brief.statutory_provisions[]` and the new `statutory_provision_references[]` | `explicit_legal_provisions` | yes |
| `sections[].title` and the new `sections[].references[]` (public) | `possible_legal_provisions` | yes |
| free text: `applicable_law`, `precedent_analysis`, `key_issues`, the public explanation | model prose | no: section names inside sentences are not rewritten (like case names in answer text, see `docs/evaluation/EVALUATION_2026-10.md`) |

Precedents, parties, chronology, procedure and evidence are not model labels: they come from retrieved evidence or the
uploaded document's local map.

## How a provision is resolved

1. **Parse** with the existing deterministic extractor (`judgment_sections.prepare_judgment_text`,
   `query_analysis.extract_sections`). A label-only normalization runs first: no-break and narrow spaces, "Sec." and
   "§" for "Section" ("§§" for "Sections"), and a statute written before its sections ("IPC Sec. 302" -> "Sections
   302 IPC"). A string that names exactly one statute gives it to its section ("Section 113B Evidence Act"). The
   clause form is kept ("3(1)(r)"). What is left after the section and statute references is the model's label.
2. **Look up**, in order of trust (the first source with an entry wins; the two are never mixed):
   1. the legal section catalog (`data/structured/manifests/legal_section_catalog.json`, 62 entries): the exact
      section, else the base section when the catalog lists it (`309(4)` -> `309`);
   2. the IPC-BNS mapping's CYTRAIN rows (`data/processed/ipc_bns/ipc_bns_mapping.csv`, the file
      `load_ipc_bns.py --source cytrain` loads; the database rows are the same apart from the loader's "366-B" ->
      "366B", which the resolver applies too): the BNS description for a BNS section, the IPC description for an IPC
      section listed on its own. Rows keyed by an IPC group label ("415 to 420, 424, …") give no IPC title.
   The mapping's 68 NCRB rows are not used as titles: NCRB prints crime-head names that cover several sections
   ("Robbery (Section 309 (4), 309(6), 311 BNS/…)"), not section titles.
3. **Decide the state:**

| State | When | Shown |
|---|---|---|
| `verified` | a trusted title exists | the trusted title; the model's label is dropped (a note records when it disagreed) |
| `corrected_statute` | the model named one statute of a pair (BNS/BNSS, IPC/CrPC); that statute has no entry for the number or its entry disagrees with the label, and the other statute has an entry for the same number that agrees with it | the corrected statute and the reason; its trusted title when the exact section has one, else the model's label marked unverified |
| `unverified` | no trusted title | the model's label, marked "Unverified label" |
| `conflict` | the source with entries gives different titles | no title: "Title not shown: the trusted sources disagree" |

**Agreement** between a label and an entry means sharing a content word: stop words and generic legal words
("section", "punishment", "offence", "relating", statute names) are ignored, and words are compared after removing a
common suffix, on their first three to five letters. It only chooses between two trusted entries or notes a
disagreeing label; it never produces a title. A title is never invented.

**Display text** (`statutory_provisions`, public `title`): `Section 309(4) BNS — Robbery`; `Section 103 BNS — Murder
(statute corrected from BNSS)`; `Section 173 BNSS — registration of FIR (statute corrected from BNS; unverified
label)`; `Section 113B Evidence Act — … (unverified label)`; `Section 900 BNS (title not shown: trusted sources
disagree)`. The frontend renders the same states from the `label` object (`frontend/lib/section-labels.ts`,
`components/SectionLabelText.tsx`) and shows provisions from older history entries, which have no label, as
unverified.

## Coverage of the trusted sources (2026-11-08)

- **Catalog:** 62 entries (IPC 20, BNS 15, BNSS 8, CrPC 7, NDPS Act 6, POCSO Act 3, SC/ST Act 3), every one with a
  canonical name.
- **Mapping:** all 438 rows have IPC and BNS descriptions. Used as titles: 316 keys from the 370 CYTRAIN rows (BNS
  284, IPC 32). 325 CYTRAIN rows are keyed by IPC group labels. Two IPC keys have several different descriptions
  (IPC 376: 9; IPC 498A: 2), so they would be conflicts, but the catalog has both.
- **Corpus-cited sections** (`document_sections`, 920 rows, 370 distinct statute + section): 57 distinct sections
  have a trusted title (catalog 40, mapping 17) and 313 do not. By rows, 280 of 920 (catalog 236, mapping 44).

| Statute | Distinct cited | With a trusted title |
|---|---:|---:|
| IPC | 173 | 26 |
| CrPC | 105 | 5 |
| NDPS Act | 32 | 5 |
| BNS | 16 | 13 |
| POCSO Act | 17 | 3 |
| Evidence Act | 13 | 0 |
| BNSS | 12 | 5 |
| SC/ST Act | 2 | 0 |

The gaps are mostly CrPC procedure, the Evidence Act and most IPC sections outside the catalog: for those, answers
show the model's label marked unverified.

## Model labels in saved outputs (step 22-24, before the resolver)

Saved responses and answers outside the repository (step 22 live runs, the step 24 evaluation including superseded
records; no provider calls): 287 provision strings, which resolve to 123 verified, 5 corrected-statute and 172
unverified sections. **Rule:** a provision is checkable when it names one section, carries a model label, and has a
trusted title or a statute correction; it is a mismatch when the statute was corrected or the label shares no
content word with the trusted entry.

- **96 checkable, 16 mismatches** (step 22: 8, step 24: 8).
- **5 wrong statutes:** BNSS 103 "murder" (BNS 103), IPC 482 "inherent powers" (CrPC 482), BNS 173 "registration of
  FIR" (BNSS 173), BNS 528 "power to quash FIRs" (BNSS 528), BNS 531(2)(a) "saving clause" (BNSS 531).
- **11 label disagreements;** by hand, 5 are wrong labels (BNS 309(4) "suicide attempts", BNS 115(2) "false
  statements", BNS 173 "investigation report filing", NDPS 21 "procedural safeguards for search and seizure", IPC
  354B "obscene material") and 6 describe the section's use rather than its subject ("challenge to charge-sheet" for
  BNSS 528). In every case the trusted title is what is now shown.

## Limits

- Titles are only as good as the catalog and the mapping, and both are **UNREVIEWED** for legal review. Some mapping
  descriptions are statute text rather than titles ("Whoever cheats shall be punished…"), and the catalog's BNS 115
  title is "Voluntarily causing hurt or grievous hurt" for the whole section.
- Coverage is low (57 of 370 cited sections), so many labels stay unverified.
- The statute correction covers only the BNS/BNSS and IPC/CrPC pairs, and only when the other statute's entry agrees
  with the label. A wrong section number in the right statute is shown with the trusted title of the number cited.
- Section names inside free text are not resolved.
- Tests: `backend/scripts/tests/test_section_labels.py`; frontend `components/SectionLabelText.test.tsx` and
  `app/public/response-adapter.labels.test.tsx`.
