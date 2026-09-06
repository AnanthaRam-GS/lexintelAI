# NCRB 2024 Complete Dataset Validation Report

## Scope
This report validates the combined NCRB dataset for 2024 created from the two validated segments:
- `data/processed/ncrb/ncrb_stats_2024.csv`
- `data/processed/ncrb/ncrb_stats_2024_pages_48_79.csv`

The final combined output is:
- `data/processed/ncrb/ncrb_stats_2024_complete.csv`

## Exact measured results
- Total rows: 6,139
- Unique states/entities: 39
- Unique individual states/UTs: 36
- Aggregate entities: 3
- Unique offense categories: 158
- Duplicate complete rows: 0
- Duplicate logical keys (year + state + offense_category + ipc_section): 0
- NULL case_count: 41
- zero case_count: 1836
- NULL conviction_count: 0
- NULL acquittal_count: 0
- Missing IPC section: 1841
- Missing BNS section: 4961
- Invalid year: 0
- Negative case_count: 0
- Non-integer case_count: 0
- Rows with year != 2024: 0
- Overlap between first and second segment offense categories: 1 (`Unlawful Assembly`)

## Interpretation of overlap
The overlap is not evidence of duplicate data. The same crime-head label is intentionally present in both segments because the first segment and the second segment are complementary parts of the same table structure. The overlap is a legitimate shared category name used across the two publication segments, not a duplicated row in the final combined dataset.

## Validation status
PASS

## Notes
- The combined dataset preserves the schema required by the existing `NcrbStat` model in `backend/app/db/models.py`.
- The `bns_section` field is retained only as enrichment metadata for Phase 0.4 and is not part of the existing PostgreSQL schema. Loading into PostgreSQL must respect the current model and map only supported fields during Phase 0.6.
- The final combined dataset was checked for logical duplicates, state/entity coverage, numeric validity, and segment overlap without altering the pre-validated source segments.
