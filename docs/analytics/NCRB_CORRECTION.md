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
  build `ipc_bns_mapping`. That data was not regenerated in this step.
- The old CSVs and reports under `data/processed/ncrb/` are kept unchanged for this diff.
