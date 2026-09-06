# NCRB Table 1A.4 — Structured Extraction Notes

## 1. Source & Scope
- **Source Document:** *Crime in India 2024*, Volume I, published by the National Crime Records Bureau (NCRB), Ministry of Home Affairs, Government of India.
- **Table Number:** Table 1A.4
- **Table Title:** *IPC/BNS Crimes (Crime Head-wise & State/UT-wise) - 2024*
- **Authoritative Input File:** `data/raw/ncrb/crime_in_india_2024_volume1_table_1A4.pdf`
- **File Properties:**
  - File Size: 21,979,613 bytes
  - Total Pages: 47 pages
  - Printed Pagination: `TABLE 1A.4 Page 1 of 79` through `TABLE 1A.4 Page 47 of 79`
- **Scope Covered in this Extraction:**
  The 47 pages encompass the complete first four major crime groups of the report:
  1. **Group 1: Offences against Women and Child** (Pages 1–15, Columns [3] to [147], Crime Heads 1–29)
  2. **Group 2: Offences affecting Human Body** (Pages 15–38, Columns [148] to [377], Crime Heads 30–75)
  3. **Group 3: Offences against State** (Pages 39–40, Columns [378] to [395], Crime Heads 76–78)
  4. **Group 4: Offences against Public Tranquillity** (Pages 40–47, Columns [396] to [469], Crime Heads 79–96)

---

## 2. Table Layout & Grid Structure
- **Columns (Horizontal Grid):**
  - Columns [1] and [2] are metadata: `SL` (Serial Number) and `State/UT` (Name).
  - Columns [3] to [469] represent 467 individual data columns across the 47 pages.
  - In 44 out of 47 pages, each page features exactly 2 Crime Heads, with 5 sub-columns each:
    1. `IPC` — Cases registered under the Indian Penal Code (1860)
    2. `BNS` — Cases registered under the Bharatiya Nyaya Sanhita (2023)
    3. `Total` — Total Cases registered (`IPC + BNS`)
    4. `V` — Total Victims recorded
    5. `R` — Crime Rate per 100,000 population
  - **Special Page Structures:**
    - **Page 25 & Page 26 (Simple Hurt):** Contains 3 Crime Heads per page, each with 3 sub-columns (`IPC`, `V`, `R` or `IPC+BNS`, `V`, `R`) because Simple Hurt data was compiled specifically for pre-BNS enforcement.
    - **Page 40 (Unlawful Assembly):** Crime Head 2 (`Unlawful Assembly`) has 4 sub-columns (`IPC`, `BNS`, `Total`, `R`). The `V` (Victims) column is omitted by NCRB because unlawful assembly offenses do not specify individual victims in this table.
- **Rows (Vertical Grid):**
  - Exactly 39 distinct rows per page:
    - Rows 1 to 28: 28 States (Andhra Pradesh to West Bengal)
    - Row 29: `TOTAL STATE(S)`
    - Rows 30 to 37: 8 Union Territories (A&N Islands to Puducherry)
    - Row 38: `TOTAL UT(S)`
    - Row 39: `TOTAL ALL INDIA`

---

## 3. Mathematical Identities & Checksums
Table 1A.4 contains built-in cross-verification checksums that ensure 100% mathematical fidelity:
1. **Horizontal Sum Identity:**
   For all dual-statute crime heads:
   $$\text{Total Cases} = \text{Cases under IPC} + \text{Cases under BNS}$$
2. **Vertical State Sum Identity:**
   $$\sum_{i=1}^{28} \text{State}_i = \text{TOTAL STATE(S)}$$
3. **Vertical UT Sum Identity:**
   $$\sum_{j=1}^{8} \text{UT}_j = \text{TOTAL UT(S)}$$
4. **National Sum Identity:**
   $$\text{TOTAL ALL INDIA} = \text{TOTAL STATE(S)} + \text{TOTAL UT(S)}$$

---

## 4. Footnotes & Qualitative Annotations
- **Page 25 Footnote:**
  - Text: `* Simple Hurt data pertains to the Cases before introduction of BNS`
  - Context: With the coming into force of the Bharatiya Nyaya Sanhita (BNS) on July 1, 2024, definitions of Simple Hurt and Grievous Hurt underwent statutory restructuring. In Table 1A.4, Simple Hurt sub-categories (Columns [246] to [260]) report IPC cases before July 1, 2024. Grievous Hurt categories (Pages 27–31) report both IPC and BNS.
- **Header Footnote:**
  - `* As per data provided by States/UTs` (standard administrative caveat of the NCRB).

---

## 5. Extraction Methodology & Verification
- The input PDF contains vector path renderings of text glyphs (0 extractable text characters via standard font decoders).
- Extraction was executed using high-resolution rasterization (200 DPI) coupled with deep neural optical character recognition (`RapidOCR` with ONNX runtime).
- Bounding boxes were segmented using precise vertical coordinate bands (calibrated to the 39 physical rows) and horizontal column boundaries.
- All extracted figures were tested against the horizontal and vertical checksum identities. Seven OCR glyph confusions (e.g. `9` read as `6`, or adjacent digit bounding box merges on aggregate totals) were isolated and corrected strictly to match the original printed PDF numerals.
