# IPC → BNS Mapping Source Documentation

## Scope
This dataset documents authoritative IPC-to-BNS section correspondences used for legal and analytics alignment in Phase 0.4. It is intentionally limited to section relationships that are directly supported by official comparative materials and the project’s preserved NCRB reporting structure.

## Primary authoritative sources

### 1) NCRB / CYTRAIN Section Table
- Source name: NCRB CYTRAIN Section Table BNS
- Official URL: https://cytrain.ncrb.gov.in/staticpage/web_pages/SectionTableBNS.html
- Retrieval/access date: 2026-09-04
- Used for: cross-checking official IPC/BNS comparators used in NCRB crime reporting; validating common section-level equivalences for analytics mapping.
- Methodology / limitations: The page was accessed live and checked for response status and cross-reference content. It was used as a practical official comparator for section mapping when section-level equivalences were clear and consistent with the governing BNS text and the BPR&D comparative material. This page is a comparative reference, not a statutory enactment text.

### 2) NCRB / CYTRAIN complete BNS text
- Source name: CYTRAIN Compendium of New Criminal Laws, BNS chapters and sections
- Official URL: https://cytrain.ncrb.gov.in/staticpage/web_pages/ChaptersBNS.html
- Retrieval/access date: 2026-09-04
- Used for: exact BNS section and subsection descriptions, including subsection-level entries such as 189(2), 191(2), and 194(2).
- Methodology / limitations: The section anchors and their visible statutory text were matched by BNS section/subsection code. No description was inferred from the IPC description or generated from a secondary source.

### 3) Ministry of Home Affairs / BPR&D comparative material
- Source name: Bharatiya Nyaya Sanhita comparative material (BPR&D)
- Official URL: https://bprd.nic.in/uploads/pdf/BNS_English_30-04-2024.pdf
- Retrieval/access date: 2026-09-04
- Used for: confirming statute-level correspondence and change-type classification where the same IPC provision was carried forward, split, or structurally modified under the BNS.
- Methodology / limitations: The PDF was accessed successfully and used as the legal benchmark for section correspondence. It is a government comparative document and is treated as authoritative for phase-0 analytics mapping, while statutory interpretation remains bounded to the actual enacted text.

### 4) India Code – BNS text
- Source name: India Code, Bharatiya Nyaya Sanhita
- Official URL: https://www.indiacode.nic.in/bitstream/123456789/20062/1/a202345.pdf
- Retrieval/access date: 2026-09-04
- Used for: attempted cross-check against the official BNS statutory text.
- Methodology / limitations: The specific URL returned HTTP 404 at the time of retrieval. Because the supplied official URL was unavailable, it was not used as a primary source for the mapping CSV. This is documented explicitly so that future updates can substitute the correct official India Code link if the statute file is republished under a new location.

## Source hierarchy used by this phase
1. Official NCRB/CYTRAIN comparative table
2. Official CYTRAIN complete BNS text
3. Official BPR&D comparative material
4. India Code official BNS text (used only if reachable and stable)
5. Secondary references used only for cross-checking, not as primary legal authority

## Mapping principles applied
- No IPC-to-BNS entries were invented.
- Only provisions supported by the referenced authorities were included.
- Where an exact one-to-one continuation was not clearly supported, the row was either classified as modified/split/merged or left out of the final record set.
- The dataset preserves the original legal structure of the source rather than forcing all mappings into a simplistic one-to-one abstraction.
- Similarity scores were not added.

## Change-type vocabulary
- DIRECT: IPC provision continues with a corresponding BNS provision without substantial structural change.
- MODIFIED: IPC provision survives under BNS with a changed legal description or changed statutory framing.
- SPLIT: One IPC provision corresponds to multiple BNS provisions.
- MERGED: Multiple IPC provisions are consolidated into one BNS provision or vice versa.
- REPEALED: IPC provision is repealed and no operative BNS equivalent remains.
- NEW: New BNS provision created without a direct IPC antecedent.
- NO_DIRECT_EQUIVALENT: The source indicates no direct legal equivalent.

## Review status (step 15b, 2026-10-23)

**UNREVIEWED: pending legal review.** `build_ipc_bns_mapping.py` took its IPC labels from the old
`ncrb_stats_2024_complete.csv`, which was found to be wrong and was replaced in step 15. Seven section pairs
printed in the corrected NCRB table have no row here. Regeneration from CYTRAIN is blocked while
`cytrain.ncrb.gov.in` is unreachable. See `docs/analytics/NCRB_CORRECTION.md`.

## Step 19 (2026-10-26): CYTRAIN retry and printed-pair cross-check

**TLS.** `backend/scripts/build_ipc_bns_mapping.py` no longer disables certificate verification. It used to set
`ssl._create_default_https_context = ssl._create_unverified_context` for the whole process; it now fetches with
`ssl.create_default_context(cafile=certifi.where())` (chain and host name checked).

**Retry (one attempt, 2 of the 3 allowed requests, verified TLS):**

| UTC | Request | Result |
|---|---|---|
| 2026-10-26T04:47:30Z | `GET https://cytrain.ncrb.gov.in/staticpage/web_pages/SectionTableBNS.html` through the script's `fetch()` | DNS resolves to 45.127.75.90; `URLError: <urlopen error timed out>` (`TimeoutError`) after 60 s |
| 2026-10-26T04:48:46Z | bare TCP connect to 45.127.75.90:443 (no TLS) | `TimeoutError` after 30 s |

The connection never reached a TLS handshake, so this is not a certificate problem. CYTRAIN stayed unreachable (as in
step 15b, 2026-10-23), so the mapping was **not regenerated** and `ipc_bns_mapping.csv` is unchanged (370 rows).

**Printed pairs.** Every IPC/BNS correspondence printed in the corrected NCRB Table 1A.4 was checked against the
mapping (`backend/scripts/crosscheck_ipc_bns_pdf_pairs.py`; report `docs/analytics/IPC_BNS_PDF_CROSSCHECK.md`). Rows
for the printed pairs the mapping lacks are prepared in `data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv`
with their PDF attribution, but **not loaded**: `ipc_bns_mapping.change_type` is NOT NULL and must be one of DIRECT,
SPLIT, MERGED, REPEALED, NO_DIRECT_EQUIVALENT, no source gives a change type for these rows, and the table has no
column for a row's source. See the proposed migration in `docs/analytics/NCRB_CORRECTION.md`.

## Data quality note
This dataset is a legal-mapping reference for Phase 0.4 analytics ingestion. It is not a substitute for full statutory interpretation or a final legal opinion. It intentionally excludes unsupported or uncertain mappings rather than guessing.
