# NCRB Data Source Documentation

## Authority
- **Agency:** National Crime Records Bureau (NCRB)
- **Ministry:** Ministry of Home Affairs, Government of India
- **Headquarters:** New Delhi, India

## Publication
- **Report Title:** Crime in India 2024
- **Volume:** Volume I
- **Publication Year:** 2024
- **Report Language:** English

## Selected Table Details
- **Table Number:** Table 1A.4
- **Full Table Title:** IPC/BNS Crimes (Crime Head-wise & State/UT-wise) - 2024
- **Table Scope:**
  - State/UT-wise breakdown (29 State entities + 7 Union Territory entities + Regional/National Totals)
  - Detailed Crime Head-wise breakdown covering transitional IPC and BNS statutory regimes
  - Cases registered under IPC, BNS, Total Incidence, Total Victims (V), and Crime Rate per lakh population (R)

## Source file (step 15, current)
- **File:** `data/raw/ncrb/vol1-crimeinindia2024.pdf`, the full *Crime in India 2024, Volume I* (604 pages).
  Not committed: `data/raw/ncrb/*.pdf` is gitignored.
- **Download URL:** `https://www.ncrb.gov.in/uploads/files/11CrimeinIndia2024-VolumeI.pdf`, the "Volume I" link on
  the official publication page `https://www.ncrb.gov.in/crime-in-india-year-wise.html?year=2024` (English view).
  NCRB serves every page and file through one redirect to its MHA host, `https://www.ncrb.mha.gov.in/...`. No
  mirror, cache or third-party copy was used.
- **Downloaded:** 2026-10-23T13:39:59Z.
- **Size:** 17,970,562 bytes. **SHA-256:** `5c119c907c8b194e0bcde8cf6ef63392ff9923dfb159a8780607f54719a79cb8`.
- **PDF metadata:** created 2026-04-07, modified 2026-05-13 (a revised upload). Cover (PDF page 3): "Crime in India
  2024, Statistics, Volume I, National Crime Records Bureau (Ministry of Home Affairs)".
- **Table 1A.4, "IPC/BNS Crimes (Crime Head-wise & State/UT-wise) - 2024":** 79 table pages. Its page mapping was
  verified from every page's printed footer:
  - table page *n* = PDF page *n* + 47;
  - table page 1 = PDF page 48, table pages 1-47 = PDF 48-94, table pages 48-79 = PDF 95-126;
  - PDF page 108 is table page 61 (it follows page 60 and continues the column numbering at `[600]`), although NCRB
    printed its footer as "Page 51 of 79".

  The earlier scripts assumed table page 1 = PDF page 46 and 48-79 = PDF 93-124. This volume has two more front pages.
- **Not to be confused with** a *City-wise* table also titled "TABLE 1A.4" (PDF pages 160-238). It is not used.
- **Table 1A.1** (PDF page 45) gives each State/UT's 2024 IPC, BNS and total cognizable crimes. The validator
  cross-checks against it.
- **Extraction:** `backend/scripts/extract_ncrb_table.py` writes `data/processed/ncrb/ncrb_stats_2024_v2.csv` and
  `ncrb_2024_table_1A4_v2_cells.csv`. It refuses any other file by SHA-256.
- **Validation:** `backend/scripts/validate_ncrb_table.py`.
- **Correction report:** `docs/analytics/NCRB_CORRECTION.md`.

Only this PDF was downloaded for step 15.

## Earlier acquisition (superseded)
The 47-page extract below is **superseded** by the full volume above. Its outputs
(`ncrb_stats_2024_complete.csv` and the other files listed under "Processing Outputs") are kept only for the
correction diff. They carry swapped and invented crime-head labels (heavily from table page 48 on), dropped
rows and cell errors; see `docs/analytics/NCRB_CORRECTION.md`.

- **Local Input File:** `data/raw/ncrb/crime_in_india_2024_volume1_table_1A4.pdf` (superseded; not present)
- **Subset Description:**
  - The local PDF file is an authoritative, verified extraction containing the first 47 pages of Table 1A.4 (spanning Table 1A.4 Page 1 of 79 through Page 47 of 79) from Volume I of Crime in India 2024.
  - It is an extracted subset of the original NCRB publication, intentionally compiled and verified for the first four major crime groups:
    1. Group 1: Offences against Women and Child (Pages 1–15, Columns 3–147)
    2. Group 2: Offences affecting Human Body (Pages 15–38, Columns 148–377)
    3. Group 3: Offences against State (Pages 39–40, Columns 378–395)
    4. Group 4: Offences against Public Tranquillity (Pages 40–47, Columns 396–469)
- **Verification Status:** Manually and programmatically verified against the original publication. Zero synthetic or third-party web replacements were used.

## Processing Outputs
From `crime_in_india_2024_volume1_table_1A4.pdf`, the following assets were generated:
1. `data/processed/ncrb/ncrb_2024_table_1A4_raw.csv` — Complete machine-readable preservation of all source columns (IPC, BNS, Total, Victims, Rate, Page numbers, Aggregate flags).
2. `data/processed/ncrb/ncrb_stats_2024.csv` — Standardized analytics dataset strictly aligned with the PostgreSQL `ncrb_stats` table schema.
3. `data/processed/ncrb/table_1A4_extraction_notes.md` — Detailed structural and methodology documentation.
4. `data/processed/ncrb/data_dictionary.md` — Complete data dictionary and column definitions.
5. `data/processed/ncrb/table_1A4_validation_report.md` — Comprehensive validation report and checksum audit.
6. `backend/scripts/validate_ncrb_1a4.py` — Automated verification script.
