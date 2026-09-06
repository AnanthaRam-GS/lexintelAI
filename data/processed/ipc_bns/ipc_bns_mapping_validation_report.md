# IPC to BNS Mapping Validation Report

## Source
- Primary source: NCRB/CYTRAIN IPC-BNS correspondence table
- URL: https://cytrain.ncrb.gov.in/staticpage/web_pages/SectionTableBNS.html
- Complete BNS text source: https://cytrain.ncrb.gov.in/staticpage/web_pages/ChaptersBNS.html
- Retrieval date: 2026-09-04
- India Code URL supplied by the project was checked separately and returned HTTP 404.
- BPR&D comparative PDF was reachable and retained as a secondary cross-check.

## Exact validation results
- Total mapping rows: 370
- Unique IPC sections: 73
- Unique BNS sections: 284
- NCRB non-null IPC section universe: 73
- Coverage against NCRB IPC universe: 100.00%
- Duplicate (ipc_section, bns_section) mappings: 0
- Mappings with a BNS section but no authoritative BNS description in CYTRAIN: 0
- Unmapped IPC sections: none
- Unresolved/manual-review rows: 0
- DIRECT: 367
- SPLIT: 0
- MERGED: 0
- REPEALED: 3
- NO_DIRECT_EQUIVALENT: 0

## Change-type interpretation
`DIRECT` is used for an individual row-level correspondence published by CYTRAIN. The source table does not itself assert that every grouped or multi-row NCRB label is a legal split, so this report does not infer `SPLIT` merely from multiple correspondence rows. `REPEALED` is reserved for source rows marked `Deleted`.

## Model compatibility
The CSV uses exactly the existing `IpcBnsMapping` fields: `ipc_section`, `ipc_description`, `bns_section`, `bns_description`, and `change_type`. No `similarity_score` was invented or added. Repeated IPC values represent one-to-many correspondence rows; null BNS values are reserved for source-marked repealed/no-equivalent entries.

## Status
PASS
