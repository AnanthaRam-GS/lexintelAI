# Analytics Data

This document covers the data behind the five analytics endpoints (plan Flow
4): where each dataset comes from, how it is validated and produced, the
dev-database numbers, and the known limitations.

**Review status: every produced value is UNREVIEWED.** Section citations and
outcomes come from deterministic rules, not from qualified legal review.

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

### NCRB statistics

`data/processed/ncrb/ncrb_stats_2024_complete.csv` (6,139 rows), from National
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

### Idempotence

| Loader | Identity | Second run |
|---|---|---|
| IPC-BNS | the whole row | inserts 0 |
| NCRB | (year, state, offense_category, ipc_section); changed counts are updated | 0 changes |

Rows in the database that are no longer in the source are reported
(`db_rows_not_in_source`), never deleted.

### Results on the dev database (2026-10-18)

| | IPC-BNS | NCRB |
|---|---:|---:|
| CSV rows | 370 | 6,139 |
| Rejected (any reason) | 0 | 0 |
| Loaded rows | **370** | **6,139** |
| Second run changes | 0 | 0 |
| Section values normalized | 1 | 117 |

### Data-quality notes

- **NCRB `case_count`:** blank in 41 rows. Stored as NULL, never 0. Migration
  0007 made the column nullable and removed the `0` server defaults on all
  three count columns.
- **NCRB `conviction_count` and `acquittal_count`:** blank in all rows.
  Table 1A.4 reports registrations, not disposals.
- **NCRB `bns_section`:** 4,610 rows have one. It is validated but **not
  stored**: `ncrb_stats` has no BNS column by schema design (the loader tests
  assert this). Only the row's `ipc_section` and `offense_category` are kept.
  See "Decisions needed".
- **NCRB aggregate rows:** the table includes `TOTAL STATE(S)`, `TOTAL UT(S)`
  and `TOTAL ALL INDIA`, and subtotal heads such as "Murder (Total a+b+c)".
  Summing every row therefore counts each case more than once: 31,285,562
  across all rows, against 9,578,302 for state and UT rows only. The endpoint
  returns rows as published.
- **IPC-BNS:** 3 `REPEALED` rows have no BNS section; that is correct, not
  missing data. 253 rows list several IPC sections in one field.

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
IPC 11), not only the offences charged. See "Decisions needed".

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
  competing candidates, a short evidence excerpt, and
  `review_status=UNREVIEWED`. It contains judgment text and must never be
  committed.
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

## Decisions needed

1. Should offence-frequency analytics count only offence provisions (IPC,
   BNS, special Acts) rather than every cited section, which includes CrPC
   and Evidence Act procedure?
2. Should NCRB's `bns_section` be stored? That needs a migration, and a
   change to the loader test that asserts the column is absent.
3. Should NCRB aggregate rows (`TOTAL …` states and `(Total …)` heads) be
   flagged or excluded?
4. Who performs the qualified legal review of the UNREVIEWED values?
