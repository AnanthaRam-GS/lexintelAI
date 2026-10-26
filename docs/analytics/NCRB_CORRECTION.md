# NCRB Table 1A.4 Correction (step 15)

`ncrb_stats` was loaded from `data/processed/ncrb/ncrb_stats_2024_complete.csv` (6,139 rows). Step 8 found that it
does not add up. In step 15 the table was re-extracted from the official PDF, validated with the table's own
arithmetic and against an independent summary table, and reloaded. Numbers and identifiers only.

## Source and provenance

- **Publication:** National Crime Records Bureau, *Crime in India 2024*, **Volume I**.
- **Table:** **Table 1A.4**, "IPC/BNS Crimes (Crime Head-wise & State/UT-wise) – 2024", 79 table pages.
- **File:** `data/raw/ncrb/vol1-crimeinindia2024.pdf`, downloaded 2026-10-23T13:39:59Z from
  `https://www.ncrb.gov.in/uploads/files/11CrimeinIndia2024-VolumeI.pdf`. It was linked from the official 2024
  publication page and served via NCRB's MHA host `www.ncrb.mha.gov.in`.
  - Size 17,970,562 bytes; SHA-256 `5c119c907c8b194e0bcde8cf6ef63392ff9923dfb159a8780607f54719a79cb8`.
  - Gitignored and not committed. Full provenance is in `data/raw/ncrb/SOURCES.md`.
- **Page mapping**, verified from every page footer: table page *n* = PDF page *n* + 47, so table pages 1–79 are PDF
  48–126. PDF 108 is table page 61, although its footer misprints "Page 51 of 79". The old scripts assumed + 45
  (PDF 46, 93–124).
- **Not used:** a City-wise table also titled "TABLE 1A.4" (PDF 160–238).

## Root cause

The old CSV was assembled from two extractions: table pages 1–47 from a 47-page extract, and pages 48–79 from
`extract_ncrb_1a4_pages_48_79.py`. Values were placed into a list of crime-head names by position, and that list did
not match the printed table. Matching each old head's 39-row value vector against the re-extraction:

| Old heads | Count | What happened |
|---|---:|---|
| Name and values both correct | 57 | — |
| Values correct, name not as printed | 34 | Values belong to the printed head; the label was wrong or swapped. |
| Values belong to a different head | 67 | Wrong head list; values shifted by position. |

1. **Head labels swapped (pages 1–47).**
   - Murder's sub-heads were relabelled. The printed "a) Murder (Section 103 (1) BNS/Section 302 IPC)" was stored as
     "Murder - a) Mob Lynching" with BNS 103(2). The printed "b) Murder by Group (of 5 or more persons) (Section
     103 (2) BNS)", which is mob lynching, was stored as "b) Other Murder".
   - So Goa's 30 murders appeared as 30 mob lynchings.
2. **A head list that is not this table's (pages 48–79).** From the Public Tranquillity group on, the old list used
   heads from another template, then filled them with this table's values in column order.
   - The list had "Rioting (Total a to m)" with sub-heads to "p) Others", where the PDF prints a)–r).
   - It had "Total Offences against Public Tranquillity" with only three parts, where the PDF prints five
     top-level heads.
   - It had Special & Local Laws heads that are not in Table 1A.4 at all: "Prohibition Act", "Copyright Act",
     "Railway Property (Unlawful Possession) Act", "Information Technology Act", and others.
   - Their values are other printed heads' values:

     | Old head | Holds the values of (all 38 rows present match) |
     |---|---|
     | "Offences by or Relating to Public Servants - False Evidence, …" | Offences against Public Tranquillity (Total) |
     | "Total Offences by or Relating to Public Servants" | Theft – a) Household Theft |
     | "Human Trafficking" | Theft – g) Other Thefts |
     | "Mischief" | Dacoity (Total a+b) |
     | "Railway Property (Unlawful Possession) Act" | Criminal Breach of Trust |
     | "Essential Commodities Act" | Burglary (Total a+b) |
     | "Affray" | Rioting – r) Other Rioting |

     So the real Public Tranquillity total was stored under an invented head. The old "Total Offences against
     Public Tranquillity" holds some other value.

   - The cause is in the script itself. `extract_ncrb_1a4_pages_48_79.py` hard-codes `CRIME_HEAD_MAPPING`: 63 head
     names, each with a column range. It maps "Total Offences against Public Tranquillity" to printed columns
     `[495]–[499]`, which are "Promoting enmity between groups…" (PDF 97). It maps "Railway Property (Unlawful
     Possession) Act" to `[600]–[604]`, which are Criminal Breach of Trust (PDF 108).
   - It also stored the wrong sub-column: for **36 of those 63 heads** the old `case_count` equals the printed
     **BNS** column, not Total. That is why old Goa "Public Tranquillity total" = 3 and Kerala = 20, the BNS
     column of "Promoting enmity".
3. **A wrapped State/UT name dropped (pages 48–79).** "D&N Haveli and Daman & Diu" is printed over three lines and
   was lost. It has 97 of 159 rows in the old CSV.
4. **Cell-level errors (pages 1–47):**
   - a dropped leading digit: Hurt (Simple +Grievous) `TOTAL STATE(S)` 38,530 for the printed 438,530, and
     `TOTAL ALL INDIA` 41,996 for 441,996;
   - printed values left blank (41 NULL `case_count` rows): Cruelty by Husband or Relatives `TOTAL ALL INDIA`
     (printed 120,227) and A. Offences against Woman and Child (Total) `TOTAL ALL INDIA` (printed 284,530);
   - the wrong sub-column on the irregular page 40, where Unlawful Assembly has no V column: 29 of 39 rows differ,
     for example Tamil Nadu 2 for the printed 2,276;
   - misread digits: Himachal Pradesh, Attempt to Commit Rape, 1 for the printed 4.

## Method (re-extraction)

`backend/scripts/extract_ncrb_table.py` reads the table's vector grid with PyMuPDF. No OCR is involved.
- **Cell borders:** they are thin filled rectangles. Data columns are the cells between vertical borders on the
  sub-header row, each identified by its printed column index `[n]`. A head is the lowest header cell above those
  columns; wider cells above it are its parents and its crime group.
- **Values:** each value goes to the column whose cell contains it. If two values land in one cell, the extractor
  raises instead of guessing.
- **Names and sections:** State/UT and head names are kept as printed. Wrapped names are joined, and parents are
  prefixed ("Murder - a) Murder").
  - `ipc_section` and `bns_section` are re-derived from the printed "(Section … BNS/Section … IPC)" text, which is
    moved out of the name. A head with no citation inherits its parent's.
  - "e) Voluntarily Causing hurt … (Section 121(1)/121/(2) or" is cut off in the PDF itself, so it gets no sections.
  - "n) ElectriState/UT/Power Supply Disputes" is printed that way (an NCRB find-and-replace error) and is kept.
- **Aggregates:** the classification is unchanged: `load_ncrb.aggregate_type`, as in step 8.
- **Blanks:** a blank cell would stay NULL. None are blank.
- **Reproducibility:** the extractor refuses any PDF but the recorded one (by SHA-256), and the output is
  byte-reproducible (test `test_ncrb_extraction`).

Outputs: `data/processed/ncrb/ncrb_stats_2024_v2.csv` (6,201 rows) and `ncrb_2024_table_1A4_v2_cells.csv`
(30,498 printed cells, with page and column for every value). The old CSVs are kept unchanged for this diff.

## Validation (`backend/scripts/validate_ncrb_table.py`)

| Check | Checks | Exceptions |
|---|---:|---:|
| Row: Total = IPC + BNS | 5,967 | 0 |
| Column: 28 states = `TOTAL STATE(S)` (per head and count column) | 623 | 0 |
| Column: 8 UTs = `TOTAL UT(S)` | 623 | 0 |
| Column: `TOTAL STATE(S)` + `TOTAL UT(S)` = `TOTAL ALL INDIA` | 623 | 0 |
| Hierarchy: "(Total a+b+…)" subtotal = its lettered children | 624 | 0 |
| Hierarchy: "Hurt (Simple +Grievous)" = Simple + Grievous | 39 | 0 |
| Hierarchy: group "(Total)" = the group's top-level heads | 273 | 0 |
| Hierarchy: "Total Cognizable IPC/BNS crimes" = group totals + "Other IPC/BNS crimes" | 39 | 0 |
| Structure: printed letters ("a to r", "i+ii+iii") = children found | 25 heads | 0 |
| Table 1A.1 (PDF 45, an independent summary table): every row's IPC, BNS and Total of "Total Cognizable IPC/BNS crimes" | 117 | 0 |

- **No exceptions**, so none needed to be explained as a source inconsistency.
- The all-India total of 3,544,608 (1,903,047 IPC + 1,641,561 BNS) equals Table 1A.1.
- The default `/analytics/ncrb-stats` result (4,824 non-aggregate rows) also sums to exactly 3,544,608. The base
  rows partition the grand total with no double counting.

**Visual spot check.** I rendered PDF pages 63 and 99 and read the cells by eye: 20 cells per row for Goa, Kerala,
Uttar Pradesh, Delhi, D&N Haveli and Daman & Diu, and TOTAL ALL INDIA. **120 of 120 cells match** the new CSV, with
no mismatches.

## Before and after

| Example | Old | New (as printed) |
|---|---|---|
| Goa, Murder (Total a+b+c) | 30 | 30 |
| Goa, Murder a) | "Mob Lynching" (BNS 103(2)) = 30 | "a) Murder" (BNS 103(1)/IPC 302) = 30 |
| Goa, Murder b) | "Other Murder" = 0 | "b) Murder by Group (of 5 or more persons)" (BNS 103(2)) = 0 |
| Public Tranquillity total = its parts | 1 of 36 states (Mizoram) | 36 of 36 states |
| Goa, Public Tranquillity total | 3 (parts 0 + 36 + 7) | 58 = 10 + 36 + 8 + 0 + 4 |
| Kerala, Public Tranquillity total | 20 (parts 12 + 1005 + 94) | 3,704 = 1,262 + 1,005 + 65 + 0 + 1,372 |
| Uttar Pradesh, Public Tranquillity total | 51 | 2,774 |
| Affray, sections | IPC 160 / BNS 192 | BNS 194 (no IPC printed) |
| Hurt (Simple +Grievous), TOTAL ALL INDIA | 41,996 | 441,996 |
| Unlawful Assembly, TOTAL ALL INDIA | 227 | 7,074 |

## Diff

| | Old | New |
|---|---:|---:|
| Rows | 6,139 | 6,201 (159 heads × 39 rows) |
| Crime heads | 158 | 159 |
| State/UT rows | 39 (D&N on 97 heads only) | 39 (all on 159 heads) |
| NULL `case_count` | 41 | 0 |

- **By (State/UT, head):** the old CSV has 6,101 distinct keys plus 38 duplicated rows.
  - 2,494 keys exist in both: 2,426 unchanged and 68 with a changed count;
  - 3,607 keys exist only in the old CSV (renamed or invented heads);
  - 3,707 keys exist only in the new one.
- **Changed counts on same-named heads:**

  | Head | Changed cells |
  |---|---:|
  | Affray | 34 |
  | Unlawful Assembly | 29 |
  | Hurt (Simple +Grievous) | 2 |
  | Attempt to Commit Rape | 1 |
  | A. Offences against Woman and Child (Total) | 1 |
  | Cruelty by Husband or Relatives | 1 |

- **Section notation:** 855 rows now carry the printed form, for example "305/306" instead of "305, 306". The loader
  still normalises "304-A" to "304A".
- **Database effect** (`load_ncrb.py --prune`, keyed on year, state, offense_category, ipc_section):
  - 3,901 inserted, 589 updated, 3,839 deleted, 1,711 unchanged (the database key includes `ipc_section`, so a
    notation change such as "305, 306" → "305/306" is a delete plus an insert);
  - the second run makes 0 changes;
  - `--prune` deletes only rows of the source's year (2024) that are not in the source.

## Reload

| Stage | Result |
|---|---|
| Backup `~/legalai_backups/20261023T135906Z` | verified: checksums, store copies, and a restore into `legalai_rehearsal` matching all 12 tables |
| Rehearsal: `alembic upgrade head` | 0008 → 0009 |
| Rehearsal: dry run, run, second run | dry run 3,901 / 589 / 3,839 (insert / update / delete); run applied the same; second run 0 changes |
| Rehearsal: `verify_analytics.py` | RECONCILED (5 of 5 endpoints identical to SQL) |
| Rehearsal: store verifier | CONSISTENT |
| Dev: dry run | identical to the rehearsal dry run (all 12 result lines) |
| Dev: `alembic upgrade head` | 0008 → 0009; `alembic check`: no new upgrade operations |
| Dev: run, second run | same as the rehearsal; second run 0 changes |
| Dev: `verify_analytics.py` | RECONCILED |
| Dev: store verifier | CONSISTENT |
| Dev: other changes | only `ncrb_stats` changed (6,139 → 6,201); every other table count unchanged; Chroma and BM25 unchanged |

## Not changed

- **IPC↔BNS mapping:** `backend/scripts/build_ipc_bns_mapping.py` still reads the old CSV's IPC section labels to
  build `ipc_bns_mapping`. That data was not regenerated in this step, or in step 15b (see below).
- The old CSVs and reports under `data/processed/ncrb/` are kept unchanged for this diff.

## Step 15b follow-ups

### Display-label overrides

`offense_category` keeps every crime head exactly as printed. `backend/app/services/ncrb_display.py` holds a
display label, used only for UI display. The API returns `offense_category` (raw) and `display_offense_category`
side by side. An override is added only for an evident printing error, with evidence.

| Printed head (raw, unchanged) | Display label | Evidence |
|---|---|---|
| `Rioting - n) ElectriState/UT/Power Supply Disputes` | `Rioting - n) Electricity/Power Supply Disputes` | see below |

Evidence for the override:
- PDF page 95 (table page 48) is the only page of the 604-page volume that contains "ElectriState/UT".
- The State/UT-wise table was derived from the City-wise one by replacing "City" with "State/UT".
- The City-wise Table 1A.4 in the same volume (PDF page 207) prints "n) ElectriCity/Power Supply Disputes".
- The 2023 edition (`TABLE1A4.xlsx`) prints "Electricity/Power Supply Disputes".

I scanned all 159 heads for the same artefact ("State/UT" inside a word) and for other evident misprints and found no
other case of a display misprint.

**All overrides.** The printed values are always stored unchanged; an override changes only what is shown or parsed.

| Kind | Printed (stored) | Override | Head | Approved | Evidence |
|---|---|---|---|---|---|
| Display label (`ncrb_display.py`) | `Rioting - n) ElectriState/UT/Power Supply Disputes` | `… Electricity/Power Supply Disputes` | Rioting n) | step 15b | above |
| Section notation (`ncrb_sections.NOTATION_OVERRIDES`) | IPC `447-252` | parsed as `447-452` (IPC 447 … IPC 452) | Criminal Trespass | 2026-10-24 (PR #65) | "Notation overrides" below |
| Section notation (`ncrb_sections.NOTATION_OVERRIDES`) | BNS `326(f),326(G) & 327(2)` | parsed as `326(f),326(g) & 327(2)` (case only) | Arson | 2026-10-24 (PR #65) | "Notation overrides" below |

### Section labels

`ipc_section` and `bns_section` keep the printed text ("305/306", "64-68,70-71 r/w 62"). Migration
`0010_ncrb_section_labels` adds the JSON columns `ipc_section_labels` and `bns_section_labels`. `load_ncrb.py` fills
them with statute-qualified labels in the `document_sections` form ("IPC 305", "BNS 103"), via
`backend/app/services/ncrb_sections.py`.

Parsing rules:
- **Section form:** `judgment_sections.canonical_section`, with subsections dropped ("103(1)" → "BNS 103"), and the
  range check `SECTION_RANGES` (IPC ≤ 511, BNS ≤ 358).
- **Separators:** `/`, `,`, `&`, `and`, `or`, `r/w`. Read-with sections are listed, as in `document_sections`.
- **Ranges:** expanded only when ascending and at most 60 sections long ("379-382", "64 to 71"). Letter ranges expand
  the suffix ("171E to 171I" → 171E…171I).
- **Ignored:** "IT Act" (printed truncated as "IT" on two pages) and "other Crimes", since they name no IPC/BNS
  section.
- **Documented misprints** (`NOTATION_OVERRIDES`, below) are parsed in their corrected form. The printed text is still
  stored.
- **Everything else** is reported as unparsed and never guessed.

The `ipc_section` filter of `/analytics/ncrb-stats` (and `/analytics/ncrb`) matches these lists. It accepts
"IPC 305", "BNS 108", or a bare "305", which means IPC.

| Corrected table (6,201 rows) | Rows |
|---|---:|
| With any label list | 5,616 |
| With IPC labels | 4,719 (4,680 before the Criminal Trespass override) |
| With BNS labels | 5,460 |
| With neither (no section printed: totals and group heads) | 585 |
| "305/306" (Abetment of Suicide), matched by "IPC 305" and by "IPC 306" | 39 |

**Notation overrides.** Step 15b left two printed notations unparsed. Both are now documented misprints, approved
2026-10-24, and handled the same way as the display override. `ipc_section` and `bns_section` keep the printed
text; only the label lists use the corrected form. No unparsed notation remains in the table.

| Field | Printed (stored as is) | Parsed as | Head | Labels |
|---|---|---|---|---|
| IPC | `447-252` | `447-452` | Criminal Trespass | IPC 447 … IPC 452 (was none) |
| BNS | `326(f),326(G) & 327(2)` | `326(f),326(g) & 327(2)` | Arson | BNS 326, BNS 327 (unchanged; "326(G)" no longer reported) |

Evidence for `447-252` → `447-452`:
- "447-252" is a descending range, so as printed it names no section.
- It is printed the same way on PDF page 124 (State/UT-wise 1A.4), page 236 (City-wise 1A.4) and page 595 (the
  crime-head annex). It is NCRB's own notation carried through the volume, not an extraction error.
- IPC 447–452 are the criminal trespass and house-trespass sections. The BNS column prints 329(3), which is in BNS
  329 (criminal trespass and house-trespass).
- IPC 252 is a coin offence (IPC Chapter XII). The same table already prints it under "Counterfeiting - a)
  Counterfeit Coin" (`231-235, 237, 238-240 & 242-254`), so it cannot belong to Criminal Trespass.
- The 2023 edition (`data/raw/2023/TABLE1A4.xlsx`) prints "Criminal Trespass (Sec.447 to 452 IPC)".

Evidence for `326(G)` → `326(g)`:
- It is printed as a capital on PDF pages 123, 235, 267, 270 and 595, always next to a lower-case "326(f)".
- The clauses of BNS 326 are lower case, (a) to (g). The Mischief head in the same table prints
  `326(a)(b)(c)(d)`.
- BNS 326(g) is mischief by fire or explosive substance, which is arson.
- Only the letter case is changed; no meaning is inferred. Section labels drop clauses, so the label is
  "BNS 326" either way.

Without an override, `section_labels` still rejects a single capital in brackets, as `canonical_section` does for
judgments.

### IPC↔BNS mapping: source, dependency and cross-check

**Status: UNREVIEWED.** The mapping needs legal review before being relied on. It was not regenerated in step 15b.

**Source and logic** (`backend/scripts/build_ipc_bns_mapping.py`):
- The pairs come from the NCRB CYTRAIN correspondence table (`SectionTableBNS.html`), with BNS descriptions from the
  CYTRAIN BNS text (`ChaptersBNS.html`).
- The universe of IPC labels comes from the old, wrong `ncrb_stats_2024_complete.csv`. For each label, the script
  matches the label's components against the IPC references of the CYTRAIN rows.
- The script fetches with TLS certificate verification disabled (`ssl._create_unverified_context`). That should be
  fixed when it is next run.

**Dependency.** The current mapping (370 rows: 367 DIRECT, 3 REPEALED; 73 IPC labels) depends on the old CSV. All 73
labels are old-CSV labels, including labels from invented heads, for example "161-165, 165A r/w 511".

The corrected table has 79 IPC labels:
- 37 appear verbatim in the mapping;
- 42 do not. Some differ only in notation ("305/306" vs "305, 306"); others are heads whose labels were lost under
  the old invented ones ("379-382", "384-389", "406-409", "411-414", "153A");
- 36 mapping labels are not in the corrected table.

The mapping CSV keeps only the label and the descriptions, not the CYTRAIN row codes, so it cannot be remapped
offline.

**Regeneration blocked.** `cytrain.ncrb.gov.in` resolves, but HTTPS and HTTP connections time out. This was tried
three times during step 15b (2026-10-23), while `www.ncrb.gov.in` answered. No other source was substituted.

**Decision (2026-10-24).** PR #64 goes in with the mapping marked UNREVIEWED. A later data step will:
- add the 7 missing pairs straight from the printed IPC/BNS columns of the NCRB PDF, a source already held;
- retry CYTRAIN once, with certificate verification turned back on.

The BPR&D comparative PDF is not approved as a source, since it has not been verified.

**Cross-check of the current mapping against the pairs printed in the PDF** (Table 1A.4 IPC and BNS columns): 29
pairs checked, **22 match, 7 have no mapping row.**

| Result | IPC → BNS (printed head) |
|---|---|
| match | 302→103 (Murder a), 304B→80 (Dowry Death), 498A→85 (Cruelty by Husband; mapping also gives 86), 376→64 (Rape), 420→318 (Cheating), 304→105, 307→109, 304A→106, 306→108, 354D→78, 354C→77, 509→79, 354→74, 354A→75, 364→140, 364A→140, 188→223, 419→319, 326A→124, 143→189, 147→191, 313→89 |
| **no mapping row** | 384→308 (Extortion), 406→316 (Criminal Breach of Trust), 392→309 (Robbery), 396→310 (Dacoity with Murder), 379→303 (Theft), 411→317 (Stolen Property), 153A→196 (Promoting enmity) |
| not a pair | Murder b) "Murder by Group" prints BNS 103(2) with no IPC section |

No mapping row contradicts a printed pair. The 7 gaps are IPC sections that the old CSV filed under invented heads,
so the builder never looked them up.

### Old head names

The 94 head names found only in the old CSV were searched across all 647 tracked files. Nothing depends on them at
runtime:
- the frontend renders `offense_category` from the API, with no hard-coded heads;
- there are no saved filters or configurations containing head names;
- the remaining hits are the superseded `extract_ncrb_1a4_pages_48_79.py`, statute names in corpus manifests and
  `query_analysis.py`, mapping description text, the 2023 workbook, tests that use label strings deliberately, docs
  history, and a frontend co-occurrence mock ("IPC 506 (Criminal Intimidation)").

### Reload (step 15b)

No count, crime head or section text changed. Only the two label columns were filled.

| Stage | Result |
|---|---|
| Backup `~/legalai_backups/20261023T181735Z` | verified: checksums, store copies, and a `--clean` restore into `legalai_rehearsal` matching all 12 tables |
| Rehearsal: `alembic upgrade head` | 0009 → 0010; `alembic check`: no new upgrade operations |
| Rehearsal: `load_ipc_bns.py` dry run, run, second run | 0 inserted each time (370 existing) |
| Rehearsal: `load_ncrb.py --prune` dry run, run, second run | dry run and run 5,616 updated (labels) / 585 unchanged / 0 inserted / 0 deleted; second run 0 changes; unparsed `IPC: 447-252`, `BNS: 326(G)` |
| Rehearsal: `verify_analytics.py` | RECONCILED (5 of 5, label lists included); default NCRB sum 3,544,608 |
| Rehearsal: store verifier | CONSISTENT |
| Dev: dry runs | identical to the rehearsal (mapping before the migration, NCRB after it, as on the rehearsal) |
| Dev: `alembic upgrade head` | 0009 → 0010; `alembic check`: no new upgrade operations |
| Dev: runs, second runs | identical to the rehearsal; second runs 0 changes |
| Dev: `verify_analytics.py` | RECONCILED; default NCRB sum 3,544,608 |
| Dev: store verifier | CONSISTENT; Chroma (21 tables) and BM25 identical to the backup copies; every table count unchanged |
| Dev: `/analytics/ncrb-stats?ipc_section=IPC 305` | 36 rows, all "Abetment of Suicide" `305/306` (39 with `include_aggregates=true`); the same for `IPC 306`, `305` and `BNS 108` |

### Reload (notation overrides, 2026-10-24)

Only the IPC label lists of the 39 Criminal Trespass rows changed. The Arson labels were already `BNS 326`,
`BNS 327`. No count, head or printed section text changed.

| Stage | Result |
|---|---|
| Backup `~/legalai_backups/20261024T032842Z` | verified: checksums, store copies, and a `--clean` restore into `legalai_rehearsal` matching all 12 tables |
| Rehearsal (at 0010) | mapping: 0 changes in all three runs. NCRB `--prune`: dry run and run 39 updated / 6,162 unchanged / 0 inserted / 0 deleted; second run 0 changes; no unparsed notations |
| Rehearsal: `verify_analytics.py` / store verifier | RECONCILED (default NCRB sum 3,544,608) / CONSISTENT |
| Dev: dry runs, runs, second runs | each identical to the rehearsal; second runs 0 changes |
| Dev: `verify_analytics.py` / store verifier | RECONCILED (3,544,608) / CONSISTENT; Chroma (21 tables) and BM25 identical to the backup copies; every table count unchanged |
| Dev: filter | `IPC 447`, `IPC 450`, `IPC 452`: the 36 Criminal Trespass rows. `IPC 252`: only "Counterfeiting - a) Counterfeit Coin". `BNS 326`: Arson and Mischief |

## Step 19: mapping follow-ups (2026-10-26)

### CYTRAIN and TLS

`build_ipc_bns_mapping.py` now verifies TLS (certifi). One retry (2 requests) found `cytrain.ncrb.gov.in` still
unreachable at the TCP level (connect timeout to 45.127.75.90:443; no TLS handshake took place). Details are in
`data/raw/ipc_bns/SOURCES.md`. The mapping was not regenerated: still 370 rows, unchanged.

### Every printed pair against the mapping

`backend/scripts/crosscheck_ipc_bns_pdf_pairs.py` reads the labels stored in `ncrb_stats` (checked equal to the parsed
printed text on every head) and compares each crime head's printed IPC sections with the mapping. The full table, with
table and PDF pages, is in `docs/analytics/IPC_BNS_PDF_CROSSCHECK.md`.

NCRB prints a **head-level** correspondence (a set of IPC sections against a set of BNS sections). The cross-check
never pairs individual sections the PDF does not pair.

| Crime heads (159) | Count |
|---|---:|
| Every printed IPC section covered by the mapping | 90 |
| At least one printed IPC section missing from the mapping | 26 |
| A printed IPC section the mapping maps only elsewhere | 1 |
| Only one side printed (no pair) | 42 |

| IPC sections in printed pairs (346) | Count |
|---|---:|
| covered, by a single-section mapping row (exact) | 48 |
| covered, only by a group-label mapping row | 228 |
| missing from the mapping | 68 |
| maps elsewhere, only by a group-label row | 2 |
| maps elsewhere, by a single-section row (an exact contradiction) | **0** |

- **The 7 pairs from step 15b are all missing:** 379, 384, 392, 396, 406, 411 and 153A.
- **No contradiction:** IPC 255 and 256 (Counterfeiting Government Stamp, table p. 65) "map elsewhere" only through the
  group label `177 to 188, 190, 194 to 216, 219 to 229, 255, 256, 268 to 271` taken from the old CSV's invented heads.
  Such a row's BNS section belongs to one section of the group, which the stored mapping no longer records, so this is
  not evidence against the printed pair. Neither side was changed.
- **Weak coverage:** 228 of the 276 "covered" sections rest only on group-label rows, for the same reason. Regenerating
  from CYTRAIN with the corrected IPC list (single-section lookups) would make them exact.

### Rows for the missing pairs: prepared, not loaded

`data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv` has 68 rows: for each head with a missing section, the
printed IPC group with one row per printed BNS section (the mapping's own convention), the printed crime head as both
descriptions, and the attribution `NCRB Crime in India 2024, Vol. I, Table 1A.4, p. <table page>`. It includes all 7
pairs. **They are not loaded**, because the schema cannot hold them without guessing:

- `ipc_bns_mapping.change_type` is `NOT NULL` and must be one of DIRECT, SPLIT, MERGED, REPEALED,
  NO_DIRECT_EQUIVALENT (`analytics.ALLOWED_CHANGE_TYPES`; the API contract and the frontend treat it as a required
  string). The PDF gives no change type and CYTRAIN, which would, is unreachable.
- The table has no column for a row's source, so the PDF attribution would be lost.

**Proposed migration 0011 (needs your approval):** add `ipc_bns_mapping.source` (text, NOT NULL, backfilled
`CYTRAIN SectionTableBNS (2026-09-04)` for the 370 existing rows), `source_page` (integer, nullable) and make
`change_type` nullable; the API returns `change_type: null` for PDF-sourced rows, the contract and the frontend's IPC-BNS
tab (which lower-cases `change_type`) handle null, and the loader accepts a blank change type only for rows whose source is
the NCRB PDF. The 68 candidate rows would then load as `source = NCRB … p. N`, `change_type = null`.

### Review status

Every row remains **UNREVIEWED** pending legal review. Three kinds of entries are now distinguished:

| Kind | Where | Status |
|---|---|---|
| CYTRAIN correspondence rows | `ipc_bns_mapping.csv`, loaded (370) | UNREVIEWED; IPC lookup list from the old CSV (step 15b) |
| NCRB PDF-printed pairs | `ipc_bns_pdf_pair_candidates.csv` (68), not loaded | UNREVIEWED; awaiting the schema decision |
| NCRB overrides | `ncrb_display.py`, `ncrb_sections.NOTATION_OVERRIDES` | approved misprint corrections, listed above |
