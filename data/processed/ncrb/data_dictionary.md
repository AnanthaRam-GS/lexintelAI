# LegalAI Analytics Data Dictionary — NCRB 2024 (Table 1A.4)

## 1. Overview
This data dictionary documents the schemas, data types, source derivations, and integrity constraints for the datasets generated from Table 1A.4 (*Crime in India 2024*, Volume I):
- **Raw Dataset:** `data/processed/ncrb/ncrb_2024_table_1A4_raw.csv`
- **Standardized Analytics Dataset:** `data/processed/ncrb/ncrb_stats_2024.csv`

---

## 2. Standardized Dataset Schema (`ncrb_stats_2024.csv`)
Target relational mapping: PostgreSQL `ncrb_stats` table.

| Field Name | Data Type | Nullable | Primary Key Component | Description | Source Derivation / Mapping | Example |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `year` | Integer | No | Yes | Calendar year of crime incidence | Table publication reporting year (2024) | `2024` |
| `state` | Text / Varchar | No | Yes | Name of State, Union Territory, or Aggregate | Column [2] `State/UT` of Table 1A.4 | `"Andhra Pradesh"`, `"Delhi"` |
| `offense_category` | Text / Varchar | No | Yes | Specific Crime Head or Category Name | Table 1A.4 Crime Head header | `"Rape"`, `"Murder - a) Mob Lynching"` |
| `ipc_section` | Text / Varchar | Yes | Yes | Indian Penal Code (IPC) statutory section | Extracted from Table 1A.4 sub-header if explicitly specified | `"376"`, `"302"`, `""` |
| `case_count` | Integer | Yes | No | Total registered crime incidence count | Column `Total` (or `IPC + BNS` incidence) | `441`, `1171`, `0` |
| `conviction_count` | Integer | Yes (Always NULL) | No | Number of convictions secured | N/A for Table 1A.4 (see justification below) | `""` (NULL) |
| `acquittal_count` | Integer | Yes (Always NULL) | No | Number of acquittals ordered | N/A for Table 1A.4 (see justification below) | `""` (NULL) |

---

## 3. Data Grain & Methodological Justification: NULL Disposals
> [!IMPORTANT]
> **Why `conviction_count` and `acquittal_count` are Strictly NULL in Table 1A.4:**
> 
> 1. **Table Purpose & Statistical Grain:**
>    - Table 1A.4 is strictly an **Incidence / Police Case Registration Table**. It records First Information Reports (FIRs) and cases booked across Indian states during the calendar year 2024.
>    - Disposal statistics (such as convictions, acquittals, compounding, and discharges) are **Judicial / Court Disposals**. In the *Crime in India* report structure, court disposals are reported in entirely separate tables (specifically **Table 4A series: Disposal of IPC/BNS Crimes by Courts**).
> 2. **Temporal Mismatch / Cohort Integrity:**
>    - A case registered in 2024 takes months or years to reach judicial disposal. Court disposals in 2024 reflect trials concluded for cases registered across multiple preceding years.
>    - Conflating court disposal figures onto an incidence table or guessing disposal numbers would violate fundamental data integrity principles.
> 3. **Non-Invention Rule:**
>    - In accordance with non-negotiable project rules, `conviction_count` and `acquittal_count` are stored as SQL `NULL` (`""` in CSV). They are never filled with synthetic data or defaulted to zero.

---

## 4. Distinction Between Zero (`0`) and Missing (`NULL`)
- **Zero (`0`):** Indicates that the state/UT reported exactly 0 cases registered for that crime head in 2024. Stored as integer `0`.
- **Missing (`NULL` / `""`):**
  - For `ipc_section`: Indicates that the crime head is either newly created under the Bharatiya Nyaya Sanhita (BNS) without an IPC predecessor (e.g., Section 69 BNS, Section 103(2) BNS Mob Lynching, Section 152 BNS), or represents a composite grouping (e.g., "A. Offences against Woman and Child (Total)").
  - For `conviction_count` / `acquittal_count`: Indicates that the source table does not report court disposal metrics.

---

## 5. Raw Dataset Schema (`ncrb_2024_table_1A4_raw.csv`)

| Field Name | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `year` | Integer | Reference year | `2024` |
| `state` | Text | Name of State, UT, or Aggregate row | `"Assam"`, `"TOTAL ALL INDIA"` |
| `crime_group` | Text | Major crime grouping (Group 1 to 4) | `"Offences against Women and Child"` |
| `offense_category` | Text | Specific Crime Head title | `"Attempt to Commit Rape"` |
| `ipc_section` | Text | IPC section text from report | `"376 r/w 511"` |
| `bns_section` | Text | BNS section text from report | `"64-68,70-71 r/w 62"` |
| `cases_ipc` | Integer/Text | Cases registered under IPC | `40` |
| `cases_bns` | Integer/Text | Cases registered under BNS | `36` |
| `source_incidence_value` | Integer | Total registered cases (`IPC + BNS`) | `76` |
| `victims` | Integer/Text | Column `V`: Total Victims recorded | `79` |
| `rate` | Float/Text | Column `R`: Crime Rate per 100,000 population | `9.9` |
| `source_pdf_page` | Integer | PDF page index (1 to 47) | `1` |
| `source_report_page` | Text | Printed table page | `"Page 1 of 79"` |
| `is_aggregate_row` | Boolean | `TRUE` for regional/national totals, `FALSE` for states | `FALSE` |
