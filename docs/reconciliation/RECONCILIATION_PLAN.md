# Reconciliation Plan: PostgreSQL, Chroma and BM25

Status: **design only**. Nothing in this plan has been executed. Each step is
rehearsed on `legalai_rehearsal` and on copies of the stores before it is run
against development state, and each has a rollback.

Inputs: [`INVENTORY_REPORT.md`](INVENTORY_REPORT.md) and
[`inventory.json`](inventory.json), produced by
`backend/scripts/reconcile_inventory.py` against read-only connections.

Decision in force: **PostgreSQL is canonical; Chroma and BM25 are derived
indexes** (Q3). Development users, jobs and lawyer applications are disposable
test pollution once a verified backup exists (Q4).

## 1. What the inventory shows

| Store | Total | corpus | test_pollution | admin_ingested | orphan |
|---|---:|---:|---:|---:|---:|
| `postgres:documents` | 66 | 0 | 66 | 0 | 0 |
| `postgres:chunks` | 88 | 0 | 88 | 0 | 0 |
| `chroma:legalai_trusted_judgments_v1` | 1356 | 1356 | 0 | 0 | 0 |
| `chroma:judgments` | 1 | 0 | 1 | 0 | 0 |
| `bm25:legalai_trusted_judgments_bm25_v1` | 1363 | 1356 | 7 | 0 | 0 |

The findings this plan is built on:

1. **PostgreSQL contains none of the curated corpus.** All 66 documents and 88
   chunks are fixtures from `backend/scripts/tests/test_ingest.py`
   (`test.pdf`, `test_judgment.pdf`, and "State vs Sample" with checksum
   `abc123sha256`), each written 22 times by earlier un-isolated test runs.
   The curated 70 judgments and 1,356 chunks exist only in the chunk files and
   the two indexes.
2. **The indexes agree with the curated chunk files.** The main Chroma
   collection and BM25 hold all 1,356 curated chunks. Provenance fields and
   text hashes match. Null pages are stored as `-1` with
   `has_page_provenance=False`, as `vector_store.metadata_for_chroma` intends.
3. **Test pollution reached the indexes.** BM25 holds `doc:1:chunk:0000` to
   `doc:1:chunk:0005` and `doc:3:chunk:0000`. The `judgments` Chroma
   collection holds only `doc:3:chunk:0000` (a 32-dimension mock vector).
   PostgreSQL documents 1 and 3 are test fixtures.
4. **The 21 "duplicate checksums" are the 22 copies of the fake
   `abc123sha256` checksum.** No corpus document is duplicated in any store.
5. **The 5 validator duplicates need no data change.** They are within-manifest
   repeats that the manifests already resolve:
   - in `development_judgments.json`, `dev-56114413` (validated) vs
     `dev-21564716` (`excluded_duplicate`), neither in the curated corpus;
   - in `balanced_development_judgments.json`, `v2-173395727` (validated, in
     the corpus) vs two `reject` records.
6. **Metadata coverage for a backfill:**

   | Field | Source coverage |
   |---|---|
   | `court_name`, `court_level`, `year`, `source_url`, `checksum` | 70/70, from the trusted manifest |
   | `decision_date` | 42/70 |
   | `case_number` | 0/70 |
   | Outcome columns | 0/70 |
   | `document_sections` | 0/70. Acquisition rows carry only statute names such as `IPC` (66 docs), not sections |

7. **Non-document tables:**
   - users: 2 seed accounts, 218 test-fixture accounts, and **1 unclassified
     public account** (user `123`, `gmail.com`, unverified, no history or
     applications);
   - every ingestion job belongs to test fixtures or has no document;
   - all 46 lawyer applications belong to test-fixture users;
   - all 14 query-history rows belong to the seed lawyer account.
8. **Extra artefacts:** `chroma_store/judgments.json` and
   `chroma_store/legalai_trusted_judgments_v1.json` are JsonVectorStore files
   with 1,356 mock (`deterministic-mock`) embeddings each. Only
   `build_vector_index.py --store json` writes them; the query path never
   reads them.

## 2. Target state

- PostgreSQL holds exactly the 70 curated documents and 1,356 chunks, plus
  seed or explicitly kept accounts. No fixtures.
- Each PostgreSQL chunk's `chroma_id` equals its curated `chunk_id`
  (`indian_kanoon:<id>:chunk:<nnnn>`), which is already the ID in both indexes.
- Chroma and BM25 contain exactly the chunk IDs in PostgreSQL, with matching
  text hashes and provenance. BM25's `chunk_universe_fingerprint` equals
  `af2b9ee39ffc4a2a65694111aabcbb523cbe2a267c609cb0c4ffc3a2ea9ae5e5`, the
  fingerprint of the 1,356 curated chunks. The current value covers 1,363
  records.
- The ingestion path and the query path use the same Chroma collection (N1).
- Ingestion cannot leave a document partly indexed (BE-001).
- `reconcile_inventory.py` reports, for every store: `test_pollution=0`,
  `orphan=0`, all corpus chunks present, and no provenance or text-hash
  mismatches.

## 3. Common rehearsal and rollback procedure

All steps reuse this procedure.

**Backup.** `backend/scripts/dev/backup_dev_state.sh ~/legalai_backups`
creates a timestamped folder with:
- `pg_dump -Fc` of the dev database;
- full copies of `chroma_store/` and `bm25_store/`;
- `db_row_counts.txt`;
- `MANIFEST.txt` (sha256 of every file).

`backend/scripts/dev/verify_backup_restore.sh <backup> legalai_rehearsal`
re-checks the manifest, compares the store copies with the live stores, and
restores the dump into an empty `legalai_rehearsal`, comparing row counts.
The current backup is `~/legalai_backups/20261017T060134Z`.

**Rehearsal.**
1. Restore the latest backup into an empty `legalai_rehearsal`.
2. Copy `chroma_store/` and `bm25_store/` from the backup into a scratch
   directory outside the repo.
3. Run the step's script against `legalai_rehearsal` and the scratch copies.
   Every step script must take `--database-url-env`, `--chroma-dir` and
   `--bm25-file` and must refuse to run against the dev database unless
   `--apply-to-dev` is given.
4. Run `DATABASE_URL=<rehearsal url> reconcile_inventory.py --chroma-dir
   <copy> --bm25-file <copy> --output-dir <scratch>` and compare with the
   step's expected inventory deltas.
5. Run the DB-backed and non-DB test suites (`docs/TESTING.md`) and a
   retrieval smoke query against the copies.

**Execution on dev.**
1. Take a fresh backup.
2. Take a `snapshot_dev_state.sh` snapshot.
3. Run the same script with `--apply-to-dev`.
4. Re-run the inventory.
5. Diff the results against the rehearsal's inventory. Excluding the
   `inputs` hashes and `postgres_database`, they must be identical.

**Rollback.**
- PostgreSQL: each step runs in a single transaction, so any assertion failure
  rolls it back. After a commit, recreate the dev database from the backup
  (`pg_restore --clean --if-exists --no-owner -d <dev url> legalai_dev.dump`),
  then compare row counts with `db_row_counts.txt`.
- Stores: stop the backend, replace `chroma_store/` and `bm25_store/` with the
  backup copies (`cp -Rp`), and verify against `MANIFEST.txt`.

**Guard.** Each script receives the exact IDs it may touch (taken from
`inventory.json`) and asserts the expected counts before it commits. If the
live state differs from the inventory, it aborts.

## 4. Steps

### Step 0: Preconditions

- Verified backup, restored into `legalai_rehearsal`. Done for
  `~/legalai_backups/20261017T060134Z`: `MANIFEST.txt` re-checked, store
  copies match the live stores, and the restore matches `db_row_counts.txt`
  for all 12 tables. `legalai_rehearsal` now holds that restore, so each later
  rehearsal must first recreate it empty, or restore with `--clean`.
- No backend server or ingestion running during steps 1–5.
- Decisions:
  - user `123`;
  - the 14 seed-lawyer history rows;
  - whether the seed accounts survive (SEC-002);
  - the JSON mirror files;
  - whether to add a unique constraint on `documents.checksum`.

### Step 1: Remove PostgreSQL test pollution

Needs N2? No. Needs N1? No.

**Change.** One transaction that deletes:
- the 66 test-pollution documents by ID. FKs cascade to `chunks` and
  `document_sections`, and set `ingestion_jobs.document_id` to null;
- the 154 ingestion jobs (all test-only: 23 COMPLETED and 43 FAILED for test
  documents, 44 FAILED and 44 QUEUED with no document);
- the 218 test-fixture users by ID. This cascades to their OTPs, tokens and 46
  lawyer applications; `query_history.user_id` is set to null.

Seed accounts and user `123` stay unless decided otherwise. The 14
query-history rows stay with the seed lawyer unless decided otherwise.

**Expected deltas:**

| Table | Before | After |
|---|---:|---:|
| documents | 66 | 0 |
| chunks | 88 | 0 |
| ingestion_jobs | 154 | 0 |
| users | 221 | 3 |
| lawyer_verification_applications | 46 | 0 |
| email_verification_otps | 221 | 1 (belongs to user `123`) |
| email_verification_tokens | 18 | 0 |

**Rehearsal.** Run on `legalai_rehearsal`. The inventory must show
`postgres:documents` and `postgres:chunks` totals of 0. The test suites must
still pass, because they use `legalai_test`.

**Rollback.** Transaction rollback, or a restore from the backup.

### Step 2: Remove index test pollution

Needs N1 first, or at the same time. While `CHROMA_COLLECTION_NAME=judgments`
is set locally, the next admin ingest recreates the stray collection.

**Change.**
- BM25: `Bm25LexicalIndex.delete_document("1")` and `delete_document("3")`
  remove the 7 records (`doc:1:chunk:0000`–`0005`, `doc:3:chunk:0000`). Then
  recompute the statistics and persist through the existing
  temp-write/validate/replace path.
- Chroma: delete the `judgments` collection, whose only entry is
  `doc:3:chunk:0000`.
- JSON mirrors: move both files into the backup folder, if approved.

**Acceptance.**
- BM25: `chunk_count` = 1356, `document_count` = 70,
  `chunk_universe_fingerprint` = `af2b9ee3…`.
- Chroma: a single collection, `legalai_trusted_judgments_v1`, with 1,356
  entries.
- The inventory shows `test_pollution=0` in every store.

**Rehearsal.** On scratch copies of the stores. Afterwards, run a retrieval
smoke query (dense, BM25, hybrid) with real models enabled and check that it
returns corpus IDs only.

**Rollback.** Restore the store copies from the backup.

### Step 3: N1, one collection name for ingestion and query

This is a product-code PR. It needs neither N2 nor the earlier steps, but it
must land before step 2 runs on dev.

**Change.**
- `backend/app/api/query.py` currently passes the module constants
  `CHROMA_PERSIST_DIR`, `DEFAULT_COLLECTION` and `BM25_PERSIST_DIR` to
  `make_service`. It should take them from `Settings` (`chroma_persist_dir`,
  `chroma_collection_name`, plus a BM25 directory setting), matching what
  `ingestion.process_ingestion_job` already does.
- Add a startup check in `/health` or `ingest/corpus/stats`. It opens the
  configured collection, checks that it exists, that its `dimension` is 1024,
  and that `index_version` matches. This replaces the import-only
  `chroma_status` (BE-002).
- Set the local `.env` to `CHROMA_COLLECTION_NAME=legalai_trusted_judgments_v1`,
  matching `.env.example`. This is your file; I will not edit it.

**Test.** With temp directories, an ingested document must be retrievable
through the same `RetrievalService` that the query endpoint builds.

**Rollback.** Revert the PR.

### Step 4: Backfill PostgreSQL from the curated corpus

Needs step 1. Does not need N2 for the fields below.

**Change.** A new script, `backend/scripts/backfill_corpus_postgres.py`, reads
the trusted manifest and the chunk files and inserts 70 documents and 1,356
chunks in one transaction. It is idempotent by checksum: rows already present
are skipped and their values verified.

**Document fields:**

| PG column | Source |
|---|---|
| `doc_type` | constant `judgment` |
| `case_name` | `trusted_manifest.case_title` |
| `court_name` | `trusted_manifest.court.court_name` (70/70) |
| `court_level` | `trusted_manifest.court.court_level` (70/70) |
| `decision_date` | `trusted_manifest.decision_date` (42/70; the other 28 stay null) |
| `year` | `trusted_manifest.decision_year` (70/70) |
| `source_url` | `trusted_manifest.source_url` (70/70) |
| `file_path` | `trusted_manifest.raw_path` |
| `checksum` | `trusted_manifest.sha256` (70/70) |
| `case_number` | no source: stays null |
| `case_disposition`, `conviction_status`, `appeal_result` | no source: stay null until N2 (step 6) |

**Chunk fields:**

| PG column | Source |
|---|---|
| `chunk_index` | chunk file `chunk_index` |
| `text` | `chunk_text` |
| `chroma_id` | curated `chunk_id` |
| `token_count` | `estimated_token_count` |
| `page_start`, `page_end`, `paragraph_start`, `paragraph_end` | same fields (null pages stay null) |
| `section_heading` | `" > ".join(heading_path)`, as in `services/chunker._ingestion_chunk` |

**Schema decisions needed first:**
- **Unique `documents.checksum`.** This is a migration that fixes DATA-003. It
  is only possible after step 1 removes the 22 fake copies.
- **Where the external document key lives.** The key is
  `indian_kanoon:<id>`. The options are a new `documents.source_document_key`
  column, or deriving it from `source_url`/`checksum` with no schema change.
  I recommend the column, because the inventory and the indexes join on it.

**Acceptance.**
- The inventory shows `postgres:documents` corpus=70 and `postgres:chunks`
  corpus=1356, with `corpus_chunks_missing_from_postgres` empty.
- The text hash of each PG chunk equals its index text hash. The inventory
  gains this check in the same PR.

**Rehearsal and rollback.** Use the common procedure, run on the rehearsal
database after step 1.

### Step 5: Verify, or re-derive, the indexes from PostgreSQL

Needs step 4.

**BM25: re-derive.** Rebuild BM25 from the PG chunks with the frozen
configuration (`legalai-bm25-index-v1`, `k1=1.5`, `b=0.75`, tokenizer
`legalai-legal-tokenizer-v1`). The fingerprint must equal `af2b9ee3…` and the
record set must equal the step-2 result. This is cheap and deterministic, and
it proves BM25 is derivable from PostgreSQL.

**Chroma: verify only (recommended).** The 1,356 BGE-M3 vectors (1,024
dimensions) are already correct for their text: the hashes match. Re-embedding
needs BGE-M3 on CPU, so it would cost time and change nothing.
- Verify that IDs, text hashes and provenance equal PostgreSQL.
- Add a reverse check to the inventory: every PG chunk must be in Chroma
  (`postgres_chunk_ids_missing_from_chroma` is empty).
- A full re-embed stays available through `build_vector_index.py --rebuild`
  run against a copy.

**Metadata gap left for later.** Chroma chunks still lack the document type
and cited IPC/BNS sections, which the verification-pass acceptance check
requires. The document type can be added now with metadata-only updates
(`collection.update(ids, metadatas)`; no re-embedding). Sections wait for N2.

**Rollback.** Restore the store copies.

### Step 6: Sections and outcomes (N2)

Needs an N2 producer, which does not exist yet.

- `document_sections` and the outcome columns have no source today, and
  `detected_statutes` holds only statute names. N2 must:
  - extract statute and section pairs from the chunk text (the deterministic
    legal NER and section components exist);
  - extract the outcome (disposition, conviction, appeal result);
  - record provenance;
  - pass human review before anything is written.
- **Blocked on N2:**
  - outcome backfill;
  - `document_sections` backfill;
  - section metadata in Chroma;
  - acceptance of the analytics endpoints that depend on these tables
    (offence frequency, outcome distribution, section co-occurrence).
- **Not blocked on N2:** the IPC-BNS mapping and NCRB loaders (DATA-002) use
  existing CSVs and can run as a separate rehearsed step.

### Step 7: BE-001, compensating cleanup in ingestion

This is a product-code PR. It needs step 3 and does not need N2.

The current flow commits the `Document` and `Chunk` rows before the vector and
BM25 writes. On failure, `db.rollback()` cannot undo those commits, and vectors
already upserted remain.

**Change:**
1. Before writing, look up the checksum. If a completed document has it,
   return the existing document; if an incomplete one has it, resume the
   ingestion. With the unique constraint from step 4, this also fixes the
   duplicate path.
2. On any failure after the first commit, run compensation in reverse order:
   - `bm25.delete_document(doc_id)`, if BM25 was updated;
   - `vector_store.delete_document(doc_id)`, if vectors were upserted;
   - delete the PG document (cascading its chunks);
   - set the job to `FAILED` with a sanitized message and record which
     compensation steps succeeded.
3. If compensation itself fails, mark the job `FAILED_NEEDS_CLEANUP`. That
   value needs an enum and migration change, which needs approval; the
   alternative is `FAILED` plus a flag column. The reconciliation inventory
   then reports such documents as `orphan`.
4. Add a stale-job reaper (BE-005). Jobs in a non-terminal state with no
   progress for longer than a timeout become `FAILED`, after running
   compensation.

**Tests.**
- Fault injection at each stage: parse, chunk, embed, PG chunk commit, Chroma
  upsert, BM25 update, cache invalidation. Each test asserts that PG has no
  document, Chroma has no vectors and BM25 has no records for that document,
  using temp stores.
- A test that re-uploading the same file is idempotent.

## 5. Order and dependencies

| Order | Step | Depends on | Product code? |
|---:|---|---|---|
| 0 | Preconditions and decisions | rehearsal database | no |
| 1 | PG pollution cleanup | 0 | no |
| 2 | Index pollution cleanup | 0, 3 (before running on dev) | no |
| 3 | N1 collection-name fix | — | yes |
| 4 | PG corpus backfill (plus checksum migration) | 1 | migration |
| 5 | Re-derive BM25, verify Chroma | 4 | no |
| 6 | Sections and outcomes | N2 producer, human review | yes |
| 7 | BE-001 compensation and reaper | 3, 4 (unique checksum) | yes |

Steps 1 and 3 can proceed in parallel. Steps 4 and 5 make PostgreSQL
canonical. Step 6 is the only step that needs N2.

## 6. Decisions needed before execution

1. Rehearsal reset: because `verify_backup_restore.sh` requires an empty
   target, either drop and recreate `legalai_rehearsal` before each rehearsal
   (which needs a role with `CREATEDB`), or allow the step scripts to
   `pg_restore --clean` into it.
2. User `123` (`gmail.com`, public, unverified): keep it or delete it?
3. The 14 query-history rows on the seed lawyer account: keep them or delete
   them?
4. Seed accounts: keep them until SEC-002 is fixed, or delete them now?
5. JSON mirror files in `chroma_store/`: archive them to the backup, or keep
   them?
6. Schema: approve the unique `documents.checksum` and a
   `documents.source_document_key` column?
7. The 28 corpus documents without a `decision_date`: accept null, or source
   the date (for example by re-reading the raw PDFs)?
8. `case_number` has no source for any corpus document: accept null, or add
   extraction (N2-like)?
