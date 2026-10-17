# Reconciliation Execution Runbook (dev)

This is the exact procedure for running the reconciliation on the development
database and stores. Every command below was rehearsed in step 4 on
`legalai_rehearsal` and on copies of `chroma_store/` and `bm25_store/` taken
from `~/legalai_backups/20261017T060134Z`.

Order: **backup → rehearse → dry-run → cleanup → migrate → backfill → verify → re-run (zero changes)**.

Run everything from the repository root on `main`, after the PR that adds
these scripts is merged.

> **[ACTION]** marks a step that needs you.

## 0. Preconditions

1. **[ACTION]** Stop the backend (`uvicorn`) and the frontend dev server. No
   ingestion may run during this procedure. The backend caches the retrieval
   service, so it must be restarted afterwards anyway.

2. **[ACTION]** Set the collection name in the repository-root `.env`:

   ```
   CHROMA_COLLECTION_NAME=legalai_trusted_judgments_v1
   ```

   As of step 4, `.env` still says `judgments` (file last modified
   2026-09-18). Check that the setting resolves; this prints only that value:

   ```bash
   .venv/bin/python -c "from backend.app.core.config import Settings; print(Settings().chroma_collection_name)"
   ```

   Expected output: `legalai_trusted_judgments_v1`.

3. Export the URLs for this shell session. Nothing is printed:

   ```bash
   export DEV_DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)"
   export REHEARSAL_DATABASE_URL="${DEV_DATABASE_URL%/*}/legalai_rehearsal"
   export DATABASE_URL="$DEV_DATABASE_URL"
   export PYTHONDONTWRITEBYTECODE=1
   ```

4. Take a snapshot of the starting state:

   ```bash
   backend/scripts/dev/snapshot_dev_state.sh /tmp/legalai_step5_before
   ```

## 1. Fresh backup and verified restore

```bash
backend/scripts/dev/backup_dev_state.sh ~/legalai_backups
export BACKUP="$(ls -d ~/legalai_backups/*/ | sort | tail -1)"; BACKUP="${BACKUP%/}"
backend/scripts/dev/verify_backup_restore.sh "$BACKUP" legalai_rehearsal --clean
```

All three checks must print `ok`, and the last line must read
`restored row counts match db_row_counts.txt for all 12 tables`.

`cat "$BACKUP/db_row_counts.txt"` should match the step 3 state, unless the
dev database has changed since: `documents|66`, `chunks|88`, `users|221`,
`ingestion_jobs|154`, `lawyer_verification_applications|46`,
`query_history|14`, `email_verification_otps|221`,
`email_verification_tokens|18`.

## 2. Rehearse against the fresh backup

```bash
export REH="$(mktemp -d /tmp/legalai_rehearsal.XXXX)"
cp -Rp "$BACKUP/chroma_store" "$BACKUP/bm25_store" "$REH/"
REH_STORES=(--chroma-dir "$REH/chroma_store" --bm25-file "$REH/bm25_store/legalai_trusted_judgments_bm25_v1.json")
CLEANUP_FLAGS=(--delete-seed-account-history --keep-user-id 123)

.venv/bin/python backend/scripts/reconcile_cleanup.py --database-url-env REHEARSAL_DATABASE_URL "${REH_STORES[@]}" \
    --archive-json-mirrors "$REH/mirror_archive" "${CLEANUP_FLAGS[@]}"
DATABASE_URL="$REHEARSAL_DATABASE_URL" .venv/bin/alembic upgrade head
.venv/bin/python backend/scripts/reconcile_backfill.py --database-url-env REHEARSAL_DATABASE_URL
.venv/bin/python backend/scripts/verify_store_consistency.py --database-url-env REHEARSAL_DATABASE_URL "${REH_STORES[@]}" \
    --collection legalai_trusted_judgments_v1
```

The cleanup must report `changes: 835` and the backfill `changes: 1426`, and
the verifier must print `CONSISTENT` (exit 0). Do not continue if any number
differs from step 4 without an explanation.

## 3. Dry-run against dev

Dry runs open PostgreSQL read-only and never modify the stores, so they do
not need `--confirm-dev`.

```bash
DEV_STORES=(--chroma-dir chroma_store --bm25-file bm25_store/legalai_trusted_judgments_bm25_v1.json)
export MIRROR_ARCHIVE="$BACKUP/json_mirrors_archive"

.venv/bin/python backend/scripts/reconcile_cleanup.py --database-url-env DEV_DATABASE_URL "${DEV_STORES[@]}" \
    --archive-json-mirrors "$MIRROR_ARCHIVE" "${CLEANUP_FLAGS[@]}" --dry-run | tee /tmp/legalai_step5_cleanup_dry.txt
```

Expected (identical to the step 4 rehearsal):

| Target | Count |
|---|---:|
| PostgreSQL documents | 66 |
| cascaded chunks | 88 |
| cascaded document sections | 0 |
| ingestion jobs | 154 |
| users | 218 |
| cascaded lawyer applications | 46 |
| cascaded OTPs | 220 |
| cascaded tokens | 18 |
| seed-account query history | 14 |
| BM25 records | 7 (`doc:1:chunk:0000`–`0005`, `doc:3:chunk:0000`) |
| Chroma collection | `judgments` (1 entry) |
| Chroma segment directory | `7bf92057-6c8b-4d59-bae2-b6c06e514223` |
| JSON mirrors archived | 2 |

Kept users: `ids=[1, 2, 123]`. Last line: `dry run: 835 changes would be made`.

**[ACTION]** Review this output before continuing.

## 4. Execute on dev

```bash
.venv/bin/python backend/scripts/reconcile_cleanup.py --database-url-env DEV_DATABASE_URL "${DEV_STORES[@]}" \
    --archive-json-mirrors "$MIRROR_ARCHIVE" "${CLEANUP_FLAGS[@]}" --confirm-dev | tee /tmp/legalai_step5_cleanup.txt

.venv/bin/alembic upgrade head          # 0004_email_otp -> 0005_corpus_keys
.venv/bin/alembic check                 # "No new upgrade operations detected."

.venv/bin/python backend/scripts/reconcile_backfill.py --database-url-env DEV_DATABASE_URL --dry-run
.venv/bin/python backend/scripts/reconcile_backfill.py --database-url-env DEV_DATABASE_URL --confirm-dev | tee /tmp/legalai_step5_backfill.txt
```

Expected:
- **Cleanup:** `changes: 835`, `bm25: 1356 records, fingerprint af2b9ee39ffc4a2a65694111aabcbb523cbe2a267c609cb0c4ffc3a2ea9ae5e5`
  and `chroma collections now: ['legalai_trusted_judgments_v1']`.
- **Migration:** if `alembic upgrade head` fails with `Cannot make documents.checksum unique`, the cleanup did not run. Stop and investigate.
- **Backfill:** `changes: 1426` (70 documents and 1,356 chunks).

## 5. Verify

```bash
.venv/bin/python backend/scripts/verify_store_consistency.py --database-url-env DEV_DATABASE_URL "${DEV_STORES[@]}"
.venv/bin/python backend/scripts/reconcile_inventory.py --output-dir /tmp/legalai_step5_inventory
```

Expected:
- **Verifier:** `CONSISTENT` (exit 0). It reads the collection from
  `CHROMA_COLLECTION_NAME`, so precondition 2 must hold.
- **Inventory:** every store reports only `corpus`:
  - `postgres:documents` total=70;
  - `postgres:chunks` total=1356;
  - `chroma:legalai_trusted_judgments_v1` total=1356;
  - `bm25` total=1356.

## 6. Idempotence

```bash
.venv/bin/python backend/scripts/reconcile_cleanup.py --database-url-env DEV_DATABASE_URL "${DEV_STORES[@]}" \
    --archive-json-mirrors "$MIRROR_ARCHIVE" "${CLEANUP_FLAGS[@]}" --confirm-dev     # changes: 0
.venv/bin/python backend/scripts/reconcile_backfill.py --database-url-env DEV_DATABASE_URL --confirm-dev   # changes: 0
```

## 7. After

```bash
backend/scripts/dev/snapshot_dev_state.sh /tmp/legalai_step5_after
cat /tmp/legalai_step5_after.db.txt
```

Expected row counts:

| Table | Rows |
|---|---:|
| documents | 70 |
| chunks | 1356 |
| users | 3 |
| email_verification_otps | 1 |
| email_verification_tokens | 0 |
| ingestion_jobs | 0 |
| lawyer_verification_applications | 0 |
| query_history | 0 |
| document_sections | 0 |
| ipc_bns_mapping | 0 |
| ncrb_stats | 0 |

Then:

1. Run the test suites as documented in `docs/TESTING.md`. They use
   `legalai_test` and must not change these counts.
2. **[ACTION]** Restart the backend and check that `/health` reports `ok`.

## Rollback

Use this if any check above fails, or if you want to return to the backup
state.

```bash
# Backend and frontend must be stopped.
pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname="$DEV_DATABASE_URL" "$BACKUP/legalai_dev.dump"

export QUARANTINE="$(mktemp -d /tmp/legalai_rollback.XXXX)"   # keep the replaced stores for inspection
mv chroma_store bm25_store "$QUARANTINE/"
cp -Rp "$BACKUP/chroma_store" "$BACKUP/bm25_store" .
```

Verify the rollback:

```bash
backend/scripts/dev/snapshot_dev_state.sh /tmp/legalai_rollback_check chroma_store bm25_store
diff <(tail -n +2 /tmp/legalai_rollback_check.db.txt) "$BACKUP/db_row_counts.txt" && echo "row counts restored"
grep -E '^[0-9a-f]{64}  \./(chroma_store|bm25_store)/' "$BACKUP/MANIFEST.txt" | sed 's#  \./#  #' | shasum -a 256 -c --quiet && echo "stores restored"
.venv/bin/alembic current   # 0004_email_otp
```

`pg_restore --clean` drops and recreates every table in the dump. That
removes the 0005 column and indexes and resets `alembic_version` to `0004`.
The JSON mirror files come back with the `chroma_store/` copy. The archived
copies in `$MIRROR_ARCHIVE` can stay.

The rehearsal of this rollback in step 4 restored all 12 tables' row counts
exactly, `alembic_version=0004_email_otp`, no `source_document_key` column,
and all 13 store files matching `MANIFEST.txt`.

## What this does not do

- No `document_sections`, outcome columns, `case_number` or missing
  `decision_date` values. N2 and the decisions in the plan cover those.
- No IPC-BNS or NCRB loading (DATA-002), no BE-001 compensation, and no
  SEC-002 seed-account change. These are later steps.
