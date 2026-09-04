# NCRB Table 1A.4 — Structured Data Validation Report

**Project:** LegalAI / LexIntelAI  
**Owner:** Roshinee (Backend / Database / Analytics Lead)  
**Phase:** Phase 0.4 — Structured Analytics Data Extraction & Validation  
**Date of Extraction & Audit:** September 3, 2026  
**Status:** **PASS (All Structural, Statistical & Mathematical Checksums Verified)**  

---

## 1. Executive Summary & Provenance
- **Source Authority:** National Crime Records Bureau (NCRB), Ministry of Home Affairs, Government of India.
- **Publication:** *Crime in India 2024*, Volume I.
- **Source Table:** Table 1A.4: *IPC/BNS Crimes (Crime Head-wise & State/UT-wise) - 2024*.
- **Authoritative Input File:** `data/raw/ncrb/crime_in_india_2024_volume1_table_1A4.pdf` (21,979,613 bytes).
- **Scope Processed:** Exactly 47 pages (`TABLE 1A.4 Page 1 of 79` through `TABLE 1A.4 Page 47 of 79`).
- **Major Crime Groups Covered:**
  1. *Offences against Women and Child* (Pages 1–15, Columns [3]–[147], Crime Heads 1–29)
  2. *Offences affecting Human Body* (Pages 15–38, Columns [148]–[377], Crime Heads 30–75)
  3. *Offences against State* (Pages 39–40, Columns [378]–[395], Crime Heads 76–78)
  4. *Offences against Public Tranquillity* (Pages 40–47, Columns [396]–[469], Crime Heads 79–96)

---

## 2. Dataset Structure Summary

| Metric | Raw Dataset (`ncrb_2024_table_1A4_raw.csv`) | Standardized Dataset (`ncrb_stats_2024.csv`) |
| :--- | :--- | :--- |
| **Total Rows** | 3,744 | 3,744 |
| **Total Columns** | 14 | 7 |
| **Distinct Crime Heads** | 96 | 96 |
| **Individual States & UTs** | 36 (28 States + 8 UTs) | 36 (28 States + 8 UTs) |
| **Documented Aggregate Rows** | 3 (`TOTAL STATE(S)`, `TOTAL UT(S)`, `TOTAL ALL INDIA`) | 3 (`TOTAL STATE(S)`, `TOTAL UT(S)`, `TOTAL ALL INDIA`) |
| **Calendar Year** | 2024 (100% compliant) | 2024 (100% compliant) |
| **Duplicate Logical Rows** | 0 | 0 |
| **Negative Values** | 0 | 0 |
| **Non-Integer Values in Counts** | 0 | 0 |

---

## 3. Strict Audit of Missing Values vs. Explicit Zeroes
In strict accordance with Rules 4, 5, 6, and 7, missing cells are never conflated with zeroes:
- **Explicit Zeroes (`case_count = 0`):** **1,217 records**. These represent states/UTs that explicitly reported zero registered cases for the corresponding crime category in 2024 (e.g., organ harvesting, foeticide in smaller UTs).
- **Missing Values (`case_count = NULL`):** **41 records**. Represent cells where the table omitted or withheld specific counts.
- **Statutory Section Nullability:**
  - **Rows with IPC Section:** 3,120 rows (83.3%).
  - **Rows without IPC Section:** 624 rows (16.7%). These strictly represent offenses newly created under the Bharatiya Nyaya Sanhita (BNS) without IPC predecessors (e.g. Section 69 deceitful sexual intercourse, Section 103(2) Mob Lynching, Section 111 Organised Crime, Section 152 Sovereignty of India), or high-level group totals (e.g. *Offences affecting Human Body (Total)*).
- **Judicial Disposal Dispositions:**
  - `conviction_count`: **100% NULL** (3,744 rows).
  - `acquittal_count`: **100% NULL** (3,744 rows).
  - *Rationale:* Table 1A.4 is strictly an FIR / Police incidence table. Court disposal metrics reside in Court Disposal tables (Table 4A series) and are not invented or inferred.

---

## 4. Mathematical Checksum Verifications
Table 1A.4's internal arithmetic identities were programmatically verified across all 47 pages:

### A. Horizontal Identity ($\text{Total Cases} = \text{Cases}_{\text{IPC}} + \text{Cases}_{\text{BNS}}$)
- Evaluated on all dual-statute crime heads across all 39 rows.
- **Pass Rate:** **100%** after resolving 7 visual OCR ambiguities against the source PDF.

### B. Vertical Sum Identities
1. **State Aggregates:**
   $$\sum_{i=1}^{28} \text{State}_i = \text{TOTAL STATE(S)}$$
   Verified with 100% accuracy on all 96 Crime Heads.
2. **Union Territory Aggregates:**
   $$\sum_{j=1}^{8} \text{UT}_j = \text{TOTAL UT(S)}$$
   Verified with 100% accuracy on all 96 Crime Heads.
3. **National Totals:**
   $$\text{TOTAL STATE(S)} + \text{TOTAL UT(S)} = \text{TOTAL ALL INDIA}$$
   Verified with 100% accuracy on all 96 Crime Heads.

---

## 5. Quality Control & OCR Resolution Log
During extraction, high-resolution raster inspection at 200 DPI combined with horizontal/vertical checksum validation detected exactly 7 OCR character confusions. Each was visually inspected against the authoritative printed PDF and certified:

| Page | Entity / State | Crime Head | Field | Raw OCR Value | Verified Ground Truth | Verification Evidence & Rationale |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- |
| **9** | Uttarakhand | Dowry Death | `cases_bns` | `6` | **`9`** | Visual inspection confirms printed digit `9`. Verified by identity: $32 (\text{IPC}) + 9 (\text{BNS}) = 41 (\text{Total})$. |
| **15** | TOTAL STATE(S) | A. Offences against Woman and Child (Total) | `cases_bns`, `total`, `victims` | Merged box `1110642` | **BNS: `111064`, Total: `273616`, V: `276776`** | Visual inspection confirms tight spacing between adjacent 6-digit columns. Sum of 28 states independently confirms 111,064 and 273,616. |
| **19** | TOTAL ALL INDIA | Deaths due to road accidents - ii) Other | `cases_bns`, `total` | Merged box `52066109270` | **BNS: `52066`, Total: `109270`** | OCR concatenated BNS and Total bounding boxes. Verified visually and by $57204 + 52066 = 109270$. |
| **24** | Jammu & Kashmir | Terrorist act | `cases_bns` | `6` | **`9`** | Visual inspection confirms digit `9`. Verified by identity: $0 (\text{IPC}) + 9 (\text{BNS}) = 9 (\text{Total})$. |
| **27** | TOTAL ALL INDIA | Grievous Hurt (Total a to i) | `cases_ipc`, `cases_bns` | Merged box `71040184643` | **IPC: `71040`, BNS: `184643`** | Visual inspection confirms two distinct columns. Verified by vertical sum of States + UTs ($70267 + 773 = 71040$). |
| **27** | TOTAL ALL INDIA | Grievous Hurt - a) Voluntarily Causing Grievous Hurt | `cases_total` | `2123265` | **`123265`** | Visual inspection confirms stray boundary mark read as `2`. Verified by $52873 + 70392 = 123265$. |
| **35** | Haryana | K&A in order to Murder | `cases_bns` | `6` | **`9`** | Visual inspection confirms printed digit `9`. Verified by identity: $4 (\text{IPC}) + 9 (\text{BNS}) = 13 (\text{Total})$. |

---

## 6. PostgreSQL Schema Alignment
The standardized dataset `data/processed/ncrb/ncrb_stats_2024.csv` matches the existing SQLAlchemy model (`NcrbStat`) in `backend/app/db/models.py`:
- Column names: `year`, `state`, `offense_category`, `ipc_section`, `case_count`, `conviction_count`, `acquittal_count`.
- Composite uniqueness: `(year, state, offense_category, ipc_section)`.
- No database tables or migrations were modified during Phase 0.4.

---

## 7. Deliverables Checklist

- [x] `data/raw/ncrb/crime_in_india_2024_volume1_table_1A4.pdf` (Verified authoritative source)
- [x] `data/processed/ncrb/ncrb_2024_table_1A4_raw.csv` (Faithful raw machine-readable CSV)
- [x] `data/processed/ncrb/ncrb_stats_2024.csv` (Standardized PostgreSQL-ready dataset)
- [x] `data/processed/ncrb/table_1A4_extraction_notes.md` (Technical and structural notes)
- [x] `data/processed/ncrb/table_1A4_validation_report.md` (Formal validation report)
- [x] `data/raw/ncrb/SOURCES.md` (Provenance documentation)
- [x] `data/processed/ncrb/data_dictionary.md` (Full data dictionary)
- [x] `backend/scripts/validate_ncrb_1a4.py` (Automated audit script)
