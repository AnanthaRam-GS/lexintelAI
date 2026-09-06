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

## Acquisition & Provenance
- **Local Input File:** `data/raw/ncrb/crime_in_india_2024_volume1_table_1A4.pdf`
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
