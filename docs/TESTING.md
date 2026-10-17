# Testing

LegalAI's Python tests live in `backend/scripts/tests` and run with `unittest`
from the repository root. Frontend tests live in `frontend` and run with Vitest.

The Python suites are split in two:

- **Non-DB suites** (55 modules) use mocks, fixtures, and temporary
  directories only.
- **DB-backed suites** (10 modules) write to PostgreSQL. They run only against
  an isolated test database through `backend/scripts/tests/db_test_bootstrap.py`.

Never point the DB-backed suites at the development database. Before this
bootstrap existed, test runs left users, ingestion jobs, and lawyer
applications in the development database.

## DB-backed modules

| Module | Writes to PostgreSQL |
| --- | --- |
| `test_analytics` | yes |
| `test_auth` | yes (seed users) |
| `test_document_processing_services` | no (patched session); uses the bootstrap for storage isolation |
| `test_ingest` | yes (jobs, documents, chunks, background ingestion) |
| `test_integration_readiness_smoke` | no (`/health` only) |
| `test_query_api` | mostly mocked sessions |
| `test_query_history` | yes |
| `test_registration_lawyer_verification` | yes (users, OTPs, applications) |
| `test_structured_data_loaders` | yes (IPC-BNS, NCRB rows) |
| `test_vector_indexing` | no; mock embeddings and temporary vector stores |

## What the bootstrap guarantees

Each DB-backed module imports `db_test_bootstrap` before any other `backend`
import. On import, the bootstrap:

1. Requires `TEST_DATABASE_URL`. It aborts before importing SQLAlchemy or
   opening any connection if the variable is unset, if its database name does
   not end in `_test`, or if it names the development database (`DATABASE_URL`
   in `.env`).
2. Sets `DATABASE_URL` from `TEST_DATABASE_URL` for the test process.
3. Runs `alembic upgrade head` against the test database.
4. Redirects Chroma, BM25, ingestion uploads (`data/raw/uploads`), and lawyer
   verification proofs to a per-process temporary directory that is deleted
   on exit. `chroma_store/`, `bm25_store/`, and `data/raw/uploads` are never
   touched.
5. Blanks Gemini, Groq, Indian Kanoon, and SMTP credentials, forces console
   email delivery, and blocks `urllib` network calls and SMTP connections.
   Tests that exercise HTTP or SMTP behaviour patch these with mocks.
6. Blocks construction of the real BGE-M3 embedder and BGE reranker unless
   `LEGALAI_ALLOW_MODEL_LOADING=1`, and sets Hugging Face to offline mode, so
   no test silently downloads or loads large models.

Every test starts from truncated tables, with the test class's `setUpClass`
fixture (for example, seeded development users) re-run, and each module ends
with the tables truncated. The suites use truncation instead of transaction
rollback because the code under test opens its own sessions, commits, and runs
FastAPI background tasks that an outer test transaction cannot contain.

## One-time setup: create the test database

Create a dedicated database owned by the application role. This needs a role
with `CREATEDB` (the application role `user` does not have it):

```bash
createdb -h /tmp -p 5432 -O user legalai_test
```

Export the connection URL for the session. Use the same host, port, and
credentials as the development `DATABASE_URL`, with the database name
`legalai_test`:

```bash
export TEST_DATABASE_URL='postgresql://<user>:<password>@localhost:5432/legalai_test'
```

Do not commit this value.

## Migrate the test database

The bootstrap migrates automatically on import. To validate the configuration
and migrate without running tests:

```bash
.venv/bin/python -m backend.scripts.tests.db_test_bootstrap
```

Expected output: `Test database 'legalai_test' validated and migrated to head.`

## Run the DB-backed suites

One process per module, with logs and a summary
(`backend/scripts/dev/run_db_suites.sh`):

```bash
backend/scripts/dev/run_db_suites.sh /tmp/legalai_db_suites
```

All 10 modules in one process:

```bash
.venv/bin/python -m unittest \
  backend.scripts.tests.test_analytics \
  backend.scripts.tests.test_auth \
  backend.scripts.tests.test_document_processing_services \
  backend.scripts.tests.test_ingest \
  backend.scripts.tests.test_integration_readiness_smoke \
  backend.scripts.tests.test_query_api \
  backend.scripts.tests.test_query_history \
  backend.scripts.tests.test_registration_lawyer_verification \
  backend.scripts.tests.test_structured_data_loaders \
  backend.scripts.tests.test_vector_indexing
```

A single module:

```bash
.venv/bin/python -m unittest -v backend.scripts.tests.test_ingest
```

Skip the vector-index module explicitly:

```bash
LEGALAI_SKIP_VECTOR_TESTS=1 .venv/bin/python -m unittest backend.scripts.tests.test_vector_indexing
```

Run the DB-backed suites in a separate process from the non-DB suites. If any
module imports `backend.app.db.session` before the bootstrap in the same
process, the bootstrap refuses to run because the engine is already bound to
another database. Do not use `unittest discover backend/scripts/tests` for the
DB-backed suites.

## Run the non-DB suites

From the repository root, run every module except the 10 above:

```bash
bash -c '
DB=" test_analytics test_auth test_document_processing_services test_ingest test_integration_readiness_smoke test_query_api test_query_history test_registration_lawyer_verification test_structured_data_loaders test_vector_indexing "
mods=()
for f in backend/scripts/tests/test_*.py; do
  b=$(basename "$f" .py)
  [[ "$DB" == *" $b "* ]] || mods+=("backend.scripts.tests.$b")
done
.venv/bin/python -m unittest "${mods[@]}"
'
```

## Frontend checks

```bash
cd frontend
npm run test:run
npm run lint
npm run format:check
npx tsc --noEmit --incremental false
```

Avoid `next build` for routine checks: it rewrites the tracked
`frontend/next-env.d.ts`.

## Verifying that a run left development state untouched

`backend/scripts/dev/snapshot_dev_state.sh` records:

- the row count of every table in the development database, in a read-only
  transaction (`SET default_transaction_read_only = on`);
- the sha256 and mtime of every file under `chroma_store/`, `bm25_store/`,
  `data/raw/uploads`, and the corpus sources (`data/processed/judgment_chunks`,
  `data/processed/judgments_normalized`, `data/processed/acquisition_runs`,
  `data/raw/judgments`, `data/structured/manifests`). Pass paths as extra
  arguments to snapshot others.

```bash
backend/scripts/dev/snapshot_dev_state.sh /tmp/before
# ... run the suites ...
backend/scripts/dev/snapshot_dev_state.sh /tmp/after
diff /tmp/before.db.txt /tmp/after.db.txt && diff /tmp/before.files.txt /tmp/after.files.txt
```

Both diffs should be empty.

## Backups and reconciliation tooling

These scripts support the data reconciliation in `docs/reconciliation/`. Each
takes the database URL from `DATABASE_URL` or `.env` and never prints it.

- `backend/scripts/dev/backup_dev_state.sh <backup_root>` writes
  `<backup_root>/<UTC timestamp>/` with a `pg_dump -Fc`, copies of
  `chroma_store/` and `bm25_store/`, `db_row_counts.txt`, and `MANIFEST.txt`
  (sha256 of every file). It refuses a destination inside the repository.
  Backups contain user data: keep them outside the repo and never commit
  them.
- `backend/scripts/dev/verify_backup_restore.sh <backup_dir> <rehearsal_db> [--clean]`
  re-checks `MANIFEST.txt`, compares the store copies with the live stores,
  and restores the dump into an existing rehearsal database (never the dev
  or a `_test` database), then compares row counts. Without `--clean` the
  target must be empty; with `--clean`, `pg_restore --clean` replaces an
  earlier rehearsal.
- `backend/scripts/reconcile_cleanup.py`, `reconcile_backfill.py` and
  `verify_store_consistency.py` remove the inventory's test pollution,
  backfill the curated corpus into PostgreSQL, and check PostgreSQL against
  Chroma and BM25. They take the database through `--database-url-env NAME`
  and explicit store paths, support `--dry-run`, and refuse the dev database
  or the repository's real stores without `--confirm-dev`. The procedure is
  in `docs/reconciliation/EXECUTION_RUNBOOK.md`.
- `backend/scripts/reconcile_inventory.py` reads PostgreSQL (read-only
  session), Chroma (SQLite `mode=ro&immutable=1`) and BM25, and writes
  `docs/reconciliation/inventory.json` and `INVENTORY_REPORT.md`. Use
  `--chroma-dir`, `--bm25-file` and `--output-dir` to point it at copies.
