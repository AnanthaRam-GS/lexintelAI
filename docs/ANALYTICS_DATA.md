# Analytics Data

This document covers the data behind the five analytics endpoints (plan Flow
4): where each dataset comes from, how it is validated and produced, the
dev-database numbers, and the known limitations.

**Review status: every produced value is UNREVIEWED** until a reviewer's
file is imported (see "Review"). Section citations and outcomes come from
deterministic rules, not from qualified legal review.

**Defaults (step 8):** offence frequency, outcome distribution and
co-occurrence count **offence provisions only** (see "Provision types");
`include_all_sections=true` returns every cited section. NCRB statistics
exclude **aggregate rows** (see "NCRB aggregate rows");
`include_aggregates=true` returns them.

| Endpoint | Source tables | Produced by |
|---|---|---|
| `/analytics/offense-frequency` | `document_sections` × `documents.year` | `backend/scripts/produce_analytics_data.py` |
| `/analytics/outcome-distribution` | `document_sections` × `documents` outcome columns and `court_level` | same |
| `/analytics/section-cooccurrence` | `document_sections` | same |
| `/analytics/ipc-bns-map` | `ipc_bns_mapping` | `backend/scripts/load_ipc_bns.py` |
| `/analytics/ncrb-stats` | `ncrb_stats` | `backend/scripts/load_ncrb.py` |

Reconcile the endpoints with direct SQL using
`backend/scripts/verify_analytics.py --database-url-env DATABASE_URL --require-non-empty`.

## Sources and attribution

### IPC-BNS mapping

`data/processed/ipc_bns/ipc_bns_mapping.csv` (370 rows). Full provenance is in
`data/raw/ipc_bns/SOURCES.md`:
- NCRB CYTRAIN Section Table BNS
  (https://cytrain.ncrb.gov.in/staticpage/web_pages/SectionTableBNS.html);
- the CYTRAIN BNS compendium;
- the BPR&D / MHA BNS comparative material
  (https://bprd.nic.in/uploads/pdf/BNS_English_30-04-2024.pdf);
- India Code.

All were accessed 2026-09-04. The mapping is a comparative reference, not
statutory text.

**Status: UNREVIEWED, pending legal review (step 15b).** The IPC labels it maps were taken from the old, wrong
NCRB CSV. Seven pairs printed in the corrected table have no mapping row (for example IPC 379 → BNS 303). It
could not be regenerated, because the CYTRAIN source was unreachable. The details and the cross-check are in
`docs/analytics/NCRB_CORRECTION.md`.

Step 19: CYTRAIN was retried with TLS verification and is still unreachable (TCP timeout). A full cross-check of every
pair printed in Table 1A.4 (`docs/analytics/IPC_BNS_PDF_CROSSCHECK.md`) finds 68 printed IPC sections with no mapping
row and no exact contradiction. Rows for them, with PDF attribution, are prepared in
`data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv` but not loaded until the schema can record their source
and an unknown change type (proposed migration in `NCRB_CORRECTION.md`).

Step 19b (migration 0011): the mapping now has 438 rows: 370 `source = CYTRAIN` and 68
`source = NCRB_CII_2024_T1A4` with `source_page` (the printed table page). A NULL `change_type` means the source gives
none (NCRB rows only; enforced by a database check). It is never guessed. The whole mapping remains UNREVIEWED for
legal review, and the CYTRAIN group-label rows are not split (that needs CYTRAIN). Details:
`docs/analytics/NCRB_CORRECTION.md`.

### NCRB statistics

`data/processed/ncrb/ncrb_stats_2024_v2.csv` (6,201 rows, since step 15), from National
Crime Records Bureau, *Crime in India 2024*, Volume I, **Table 1A.4**
(IPC/BNS crimes, crime head-wise and State/UT-wise). Full provenance and
extraction notes are in `data/raw/ncrb/SOURCES.md` and
`data/processed/ncrb/*_report.md`. Attribution: National Crime Records Bureau,
Ministry of Home Affairs, Government of India.

### Judgment sections and outcomes

The text is the curated trusted-judgment corpus in PostgreSQL `chunks` (70
judgments, 1,356 chunks), sourced from the Indian Kanoon API with
attribution "Judgment data sourced from Indian Kanoon API." (see the trusted
processing manifest).

## Structured loaders

Both loaders take `--database-url-env NAME`, support `--dry-run`, and refuse
the development database without `--confirm-dev`.

### Validation

Every rejected row is counted by reason; nothing is dropped silently.

| Check | IPC-BNS | NCRB |
|---|---|---|
| Required columns present | yes | yes |
| Required fields non-blank | `ipc_section`, `ipc_description`, `change_type` | `year`, `state`, `offense_category` |
| Types | `change_type` in `DIRECT`, `SPLIT`, `MERGED`, `REPEALED`, `NO_DIRECT_EQUIVALENT` | integer, non-negative counts |
| Field lengths | within column sizes | within column sizes |
| Duplicates | exact repeat loaded once | exact repeat loaded once; same key with different counts rejected (`duplicate_key_conflict`) |

### Section normalization

The loaders collapse whitespace and join hyphenated letter suffixes
(`366-B` → `366B`), the same convention as `document_sections`. Crime-head
groupings such as `147-151`, `376 r/w 511` or `64-68,70-71 r/w 62` are kept
verbatim, because they name a group of provisions, not one section.

Since step 15b, `load_ncrb.py` also stores the parsed lists `ipc_section_labels` and `bns_section_labels`, for
example "305/306" → `["IPC 305", "IPC 306"]`, in the `document_sections` form. The NCRB section filter matches
these lists. Unparseable notations are reported (`unparsed_section_notations`), not guessed. The rules and counts
are in `docs/analytics/NCRB_CORRECTION.md`.

### Idempotence

| Loader | Identity | Second run |
|---|---|---|
| IPC-BNS | the whole row | inserts 0 |
| NCRB | (year, state, offense_category, ipc_section); changed counts, BNS head or aggregate flag are updated | 0 changes |

Rows in the database that are no longer in the source are reported
(`db_rows_not_in_source`), never deleted, unless `load_ncrb.py --prune` is passed (step 15). That deletes the
source year's rows that are not in the source, in the same transaction.

### Results on the dev database (2026-10-18)

| | IPC-BNS | NCRB |
|---|---:|---:|
| CSV rows | 370 | 6,139 |
| Rejected (any reason) | 0 | 0 |
| Loaded rows | **370** | **6,139** |
| Second run changes | 0 | 0 |
| Section values normalized | 1 | 117 |

After migration 0008 the NCRB reload updated 5,120 existing rows (BNS head
and/or aggregate flag) and inserted none; the second run made 0 changes.

### NCRB correction (step 15, 2026-10-23)

The original `ncrb_stats_2024_complete.csv` did not add up. It had mislabelled heads, an invented head list from
table page 48 on, a dropped State/UT row and cell errors. It was replaced by a table-aware re-extraction from the
official PDF, `ncrb_stats_2024_v2.csv`, which passes every arithmetic check and matches Table 1A.1. Details are in
`docs/analytics/NCRB_CORRECTION.md`.

| Dev database, step 15 | NCRB |
|---|---:|
| CSV rows | 6,201 |
| Rejected | 0 |
| Inserted / updated / deleted (`--prune`) | 3,901 / 589 / 3,839 |
| Loaded rows | **6,201** |
| Second run changes | 0 |
| `case_count` NULL | 0 |
| Rows with `bns_section` | 5,460 |
| Default `/analytics/ncrb-stats` sum (non-aggregate) | 3,544,608 = the printed all-India total |

The figures in the sections below describe the original 6,139-row load and are kept for the record.

### Data-quality notes

- **NCRB `case_count`:** blank in 41 rows. Stored as NULL, never 0. Migration
  0007 made the column nullable and removed the `0` server defaults on all
  three count columns.
- **NCRB `conviction_count` and `acquittal_count`:** blank in all rows.
  Table 1A.4 reports registrations, not disposals.
- **NCRB `bns_section`: stored since migration 0008.** 4,610 of 6,139 rows
  have one. Why: Table 1A.4 is the 2024 edition, the first reported under the
  BNS, and it gives the BNS head next to the IPC head. Dropping it lost half
  of the source's own crosswalk, and BNS-only heads (organised crime, mob
  lynching) had no section at all. The loader test that asserted the column
  was absent now asserts the stored value.
- **NCRB group totals do not always equal their components in the processed
  CSV.** "Total Offences against Public Tranquillity" equals the sum of its
  rioting, unlawful assembly and affray rows in only 1 of 36 states. Some
  component values also look shifted between neighbouring heads (in Goa,
  "Murder - a) Mob Lynching" holds all 30 murders). This points to an
  extraction-alignment problem in `data/processed/ncrb/`, not in the loader.
  Totals are excluded by default, but the per-head values should be checked
  against the PDF before they are presented as authoritative.
- **IPC-BNS:** 3 `REPEALED` rows have no BNS section; that is correct, not
  missing data. 253 rows list several IPC sections in one field.

### NCRB aggregate rows

Table 1A.4 mixes base rows with totals. The loader flags them
(`is_aggregate`, `aggregate_type`) from the table's own labels:

| `aggregate_type` | Rule | Rows |
|---|---|---:|
| `state_total` | state is `TOTAL STATE(S)` | 159 |
| `ut_total` | state is `TOTAL UT(S)` | 159 |
| `all_india_total` | state is `TOTAL ALL INDIA` | 159 |
| `subtotal_head` | crime head contains `(Total …)` (e.g. "Murder (Total a+b+c)", "Offences Affecting the Human Body (Total)") or a parenthesised sum ("Hurt (Simple +Grievous)") | 504 |
| `group_total` | crime head starts with `Total ` (e.g. "Total IPC/BNS Crimes", "Total Special & Local Laws (SLL)") | 246 |
| base (`is_aggregate = false`) | everything else | 4,912 |

State-total rows take precedence over the crime-head rules. On dev, no
unflagged crime head contains "total".

**Numerical check.** Each lettered subtotal head equals the sum of its direct
components in all 39 states for Sexual Harassment, Murder, Road Accidents,
Simple Hurt and Grievous Hurt. "Hurt (Simple +Grievous)" equals Simple Hurt
plus Grievous Hurt in 37 of 39. Kidnapping & Abduction and Rioting do not add
up directly because they contain nested sub-totals (themselves flagged), not
because of mislabelling.

**Sums.** All rows: 31,285,562. Non-aggregate rows (the endpoint default):
**4,266,712**, which `verify_analytics.py` reconciles with
`SELECT sum(case_count) FROM ncrb_stats WHERE NOT is_aggregate`. Because of
the group-total caveat above, this sum is not NCRB's published total
cognizable crime figure, and it mixes IPC/BNS heads with Special & Local Laws
heads. Use it per head, not as one national total.
## Section producer (`document_sections`)

Section detection reuses the existing deterministic extractor,
`query_analysis.extract_statutes` and `extract_sections` (the same analysis
the deterministic legal NER wraps), through `services/judgment_sections.py`.
That module adds only:

1. **Pre-normalization of judgment citation forms** the query-oriented
   patterns miss: `u/s` → `Section`; `302/34` and `302 r/w 34` → `302, 34`;
   `Cr.P.C.`/`I.P.C.` → `CrPC`/`IPC`; `498-A`/`498 A` → `498A`.
2. **Canonical sections:** the base number with an uppercase letter suffix.
   Subsections are dropped (`103(1)` → `103`; NDPS `20(b)` → `20`).
3. **Precision filters.** These are rejected and counted, never stored:
   - a section number that has no explicit statute;
   - a statute outside the supported set (IPC, CrPC, BNS, BNSS, Evidence
     Act, NDPS Act, POCSO Act, SC/ST Act);
   - a number outside the statute's range (for example years);
   - `NNN(X)` with a single uppercase letter, such as `120(B)`, because it
     could be 120B or a sub-part, so it is not guessed.
4. **Regime:** the statute itself separates `ipc_crpc` (IPC, CrPC) from
   `bns_bnss` (BNS, BNSS), using the regimes in the legal section catalog.

Each row stores:
- `mention_count`: mentions in the document;
- `chunk_count`: chunks containing them;
- `evidence_chunk_id`: the first chunk that cites it;
- `extraction_method`: `query_analysis.extract_sections+judgment_v2`.

The pair (document, statute, section) is unique. The producer is idempotent,
and it only removes rows that it produced itself.

### Dev results

- **920 rows across 70/70 documents**, 0 rows without provenance.
- **By statute:** IPC or CrPC 772, BNS or BNSS 33, special Acts 115.
- **Rejected candidates:** 1,961 had no explicit statute, 63 were ambiguous
  `NNN(X)` forms, 20 were out of range.

Top 10 sections by number of documents:

| Section | Documents |
|---|---:|
| IPC 34 | 30 |
| CrPC 313 | 26 |
| IPC 302 | 23 |
| CrPC 161 | 20 |
| IPC 120B | 16 |
| IPC 420 | 15 |
| IPC 307 | 14 |
| IPC 323 | 14 |
| CrPC 482 | 13 |
| IPC 406 | 13 |

**Meaning.** `document_sections` records sections a judgment **cites**. That
includes procedural and definitional provisions (CrPC 313, CrPC 161, IPC 2,
IPC 11), not only the offences charged. Every row is kept; the analytics
endpoints filter at query time (next section).

## Provision types

`services/provision_types.py` (`provision_types_v1`) classifies each
(statute, section) by the statute's own chapters. The legal section catalog
has no provision-type field.

| Type | Rule | Examples |
|---|---|---|
| `offence` | IPC 118-120, 120B, 121-510 except 149; BNS 61, 63-358 except 190; NDPS 15-33 except 29; POCSO 3-22 except 16-18; SC/ST Act 3, 4 | IPC 302, 498A; BNS 103; NDPS 20 |
| `liability_linking` | IPC 34, 35, 37, 38, 107-117 (abetment), 149, 511 (attempt); BNS 45-60, 62, 190; NDPS 29; POCSO 16-18 | IPC 34, IPC 149 |
| `definitional_general` | IPC 1-106 except 34, 35, 37, 38 (definitions, punishments, general exceptions), 120A; BNS 1-44; NDPS 1-14, 34-40; POCSO 1-2; SC/ST 1-2, 5-9 | IPC 2, IPC 96 |
| `procedural` | all CrPC and BNSS; NDPS 41+; POCSO 23+; SC/ST 10+ | CrPC 313, CrPC 482 |
| `evidentiary` | Evidence Act | Evidence Act 27 |
| `unclassified` | outside the known ranges, or a suffixed IPC number up to 120 that does not exist (e.g. "IPC 113B") | IPC 113B |

Only `offence` is counted by default, in offence frequency, outcome
distribution and co-occurrence. `include_all_sections=true` returns every
cited section.

**Dev results (2026-10-18), offence-only default.** 166 distinct offence
provisions, 462 document citations. Excluded:

| Type | Distinct provisions | Document citations | Most cited |
|---|---:|---:|---|
| `procedural` | 135 | 310 | CrPC 313 (26), CrPC 161 (20), CrPC 482 (13) |
| `definitional_general` | 42 | 74 | IPC 2 (6), IPC 1 (5), IPC 3 (5) |
| `liability_linking` | 9 | 52 | IPC 34 (30), IPC 149 (8), IPC 511 (4) |
| `evidentiary` | 13 | 14 | Evidence Act 25 (2) |
| `unclassified` | 5 | 8 | IPC 113B (4) |

Top 10 offence provisions by number of documents: IPC 302 (23), IPC 120B
(16), IPC 420 (15), IPC 307 (14), IPC 323 (14), IPC 406 (13), IPC 326 (11),
IPC 506 (11), IPC 304 (10), IPC 324 (10).

**Known extractor limitation.** "Section 113B of the Evidence Act read with
304B IPC" is bound to IPC by the extractor in 4 documents ("IPC 113B"). No
such IPC section exists, so the classifier marks it `unclassified` and it is
not counted.

## Outcome producer

`services/judgment_outcomes.py` reads only the last two chunks (the
operative part) and applies conservative rules:

| Field | Values | Example rules |
|---|---|---|
| `appeal_result` | `allowed`, `partly allowed`, `dismissed` | "the appeal/revision is (partly) allowed / allowed in part / dismissed" |
| `conviction_status` | `acquitted`, `convicted` | "the appellants are acquitted"; "the conviction … is upheld/affirmed/maintained" |
| `case_disposition` | `appeal allowed`, `appeal partly allowed`, `appeal dismissed`, `petition allowed`, `petition dismissed`, `bail granted`, `bail refused`, `proceedings quashed`, `remanded`, `acquitted` | as above, plus bail, quashing and remand phrasing |

The values are the labels `services/analytics.py` buckets.

**Precision safeguards:**
- Only present-tense operative phrasing counts. Narrated history ("was
  dismissed"), argument and conditional phrasing ("liable to be allowed") do
  not.
- Matches inside a hypothetical or modal clause (`if`, `whether`,
  `in the event`, `would`, `should`, `may`, …) are ignored.
- "… is convicted under …" never sets a value, because appellate judgments
  narrate the trial court's conviction that way. It only marks the field
  ambiguous when another value is present.
- Conflicting values (for example co-accused with different results) make
  the field **ambiguous**, and it stays NULL.
- `case_disposition = acquitted` requires `conviction_status = acquitted`.

**Storage:** only found values are written; unknown and ambiguous fields stay
NULL. `documents.outcome_evidence` keeps `{"rule", "chunk_id"}` for every
written value, and `outcome_method` is `operative_rules_v2`. Values that
another method or a person wrote are never overwritten.

**Court level:** `court_level` is derived from `court_name` only when it is
NULL and unambiguous (Supreme Court, High Court, District/Sessions). On dev
all 70 already had a level from the trusted manifest, and none disagreed
with the court name: 48 high court, 14 Supreme Court, 8 district or sessions.

### Dev results

Every non-null value has an evidence chunk that exists in PostgreSQL.

| Column | Values | NULL (unknown or ambiguous) |
|---|---|---:|
| `conviction_status` | acquitted 9, convicted 3 | 58 |
| `appeal_result` | allowed 15, dismissed 8, partly allowed 6 | 41 |
| `case_disposition` | appeal allowed 14, petition dismissed 6, acquitted 6, appeal dismissed 6, petition allowed 5, appeal partly allowed 4, remanded 1 | 28 |

## Review

- **Review file.** `produce_analytics_data.py --review-dir <outside repo>`
  writes a CSV (mode 600) with, for each document: the key, the cited
  sections, each outcome value or status, the rule, the evidence chunk, the
  competing candidates, a short evidence excerpt, `review_status`
  (`UNREVIEWED`, or `REVIEWED` once imported), and empty reviewer columns
  `reviewer`, `corrected_conviction_status`, `corrected_appeal_result`,
  `corrected_case_disposition`, `review_notes`. It contains judgment text
  and must never be committed.
- **Reviewer workflow.**
  1. Copy the review CSV (keep it outside the repository). For each row you
     check, write your name in `reviewer` and set `review_status` to
     `CONFIRMED` (the three outcome values are right), `CORRECTED` (fill
     `corrected_<field>` for each wrong field: one of the rule labels in the
     "Outcome producer" table, or `NULL` to clear it; a blank keeps the
     produced value) or `REJECTED` (all three outcomes are cleared). Leave
     unchecked rows `UNREVIEWED`.
  2. Import it: `backend/scripts/import_analytics_review.py
     --database-url-env DATABASE_URL --review-csv <copy> --dry-run`, then
     without `--dry-run` (plus `--confirm-dev` on dev).
  3. The import is all-or-nothing. It refuses the whole file on an unknown
     `document_id`, a mismatched `source_document_key`, a duplicate row, a
     blank reviewer, an unknown status or label, corrections on a
     non-CORRECTED row, or a stale row whose produced values no longer match
     an unreviewed document. Re-importing the same file changes nothing.
  4. Imported documents get `review_status = REVIEWED`, `review_decision`,
     `reviewed_by` and `reviewed_at`. Corrected values carry the evidence
     rule `reviewer_correction`. The producer never overwrites a reviewed
     document's outcomes (`outcomes_skipped_reviewed`). Its sections and
     court level are still produced, because the review covers the three
     outcome fields only. `review_notes` stays in the CSV.

  The import has been tested on the test database only; it has not been run
  on dev.
- **ID-only summary.** `docs/analytics/REVIEW_SUMMARY.md` (from
  `--summary-out`) has keys, counts, labels and rule names only.
- **Non-expert spot check (2026-10-18).** Three errors were found in the
  first rule set and fixed:
  - narration "petitioner is convicted for …" taken as a conviction;
  - "what if the appellant is acquitted" taken as an acquittal;
  - "I would maintain the convictions" (a separate opinion) taken as a
    conviction.

  A second check then found "accused A-8 is acquitted" in a multi-accused
  trial taken as a case-level acquittal, which led to the
  `case_disposition = acquitted` safeguard. This is not legal review.

## Decisions

Decided in step 8 (2026-10-18):
1. Analytics count offence provisions only by default ("Provision types").
2. NCRB `bns_section` is stored (migration 0008).
3. NCRB aggregate rows are flagged and excluded by default ("NCRB aggregate
   rows").
4. Reviews are imported with `import_analytics_review.py` ("Review").

Open:
- Who performs the qualified legal review of the UNREVIEWED values?
- The NCRB group-total misalignment in the processed CSV (see "Data-quality
  notes") needs checking against the source PDF.
