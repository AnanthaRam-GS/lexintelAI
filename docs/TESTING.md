# Testing

LegalAI's Python tests live in `backend/scripts/tests` and run with `unittest`
from the repository root. Frontend tests live in `frontend` and run with Vitest.

The Python suites are split in two:

- **Non-DB suites** use mocks, fixtures, and temporary directories only.
- **DB-backed suites** (the 12 modules in `backend/scripts/dev/db_test_modules.txt`) write to PostgreSQL. They run
  only against an isolated test database through `backend/scripts/tests/db_test_bootstrap.py`.

Every test runs from a clean checkout (CI, below). Nothing reads `.env`, the real corpus, the stores or the model
cache, except the local-only tests listed under "Local-only tests".

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

The module list is `backend/scripts/dev/db_test_modules.txt`; `run_db_suites.sh` reads it.

Run the DB-backed suites in a separate process from the non-DB suites. If any
module imports `backend.app.db.session` before the bootstrap in the same
process, the bootstrap refuses to run because the engine is already bound to
another database. Do not use `unittest discover backend/scripts/tests` for the
DB-backed suites.

## Run the non-DB suites

Every `test_*.py` module not listed in `db_test_modules.txt`, in one process (extra arguments go to unittest):

```bash
backend/scripts/dev/run_nondb_suites.sh        # or: backend/scripts/dev/run_nondb_suites.sh -v
```

## Local-only tests

Four tests check committed manifests against the real trusted-judgment chunks in
`data/processed/judgment_chunks` (gitignored Indian Kanoon text). They carry `@requires_local_corpus`
(`backend/scripts/tests/local_corpus.py`) and are skipped, with that reason, when the chunks are absent (CI):

| Test | Checks |
|---|---|
| `test_retrieval_evaluation.test_query_manifest_is_balanced_and_corpus_supported` | the 30 evaluation queries have corpus support |
| `test_retrieval_eval_human_labels.test_chunk_query_and_judgment_keys_are_valid` | every labelled chunk ID exists in the corpus |
| `test_retrieval_dev_set.test_support_and_no_exact_benchmark_duplicates` | dev-set support chunks exist in the corpus |
| `test_retrieval_dev_set.test_candidates_are_unique_and_in_trusted_corpus` | dev-set candidates exist in the corpus |

Tests that need corpus-shaped data use the synthetic fixture corpus instead
(`backend/scripts/tests/fixture_corpus.py`, `fixtures/corpus/synthetic_judgments.json`: six invented judgments).

## Frontend checks

```bash
cd frontend
npm run test:run
npm run lint
npm run format:check
npx tsc --noEmit --incremental false
```

Avoid `next build` for routine checks: it rewrites the tracked
`frontend/next-env.d.ts`. Vitest does not collect `frontend/e2e/` (Playwright journeys).

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

## Continuous integration (`.github/workflows/ci.yml`)

Runs on every pull request and on pushes to `main`. It needs no secrets: no job calls an LLM provider, downloads a
model (`HF_HUB_OFFLINE=1`), or reads the real corpus or stores.

| Job | What it runs |
|---|---|
| `backend-unit` | Python 3.14 (`actions/setup-python`), Tesseract from apt, `run_nondb_suites.sh -v` with `LEGALAI_SKIP_VECTOR_TESTS=1`; fails if the OCR tests were skipped |
| `backend-db` | a `postgres:18` service with the `legalai_test` database, `TEST_DATABASE_URL` set, the bootstrap check, then `run_db_suites.sh` exactly as above; logs uploaded on failure |
| `frontend` | Node 22, `npm ci`, ESLint, Prettier check, `tsc --noEmit`, Vitest, `next build` |
| `e2e` | `postgres:18` with `legalai_e2e`, Chromium, `next build`, then `run_e2e.sh` in fake mode; the Playwright report, traces, screenshots and videos are uploaded on failure (artifact `playwright-artifacts`) |

The backend install (`.github/actions/setup-backend`) installs torch from the CPU wheel index, then
`pip install -r requirements.txt -c requirements.lock`. pip and npm downloads and the Playwright browser are cached.
The Postgres password in the workflow belongs to a throwaway service container.

## End-to-end browser tests (`frontend/e2e`)

Playwright journeys against the real backend and frontend: public questions (text, out of scope, FIR upload),
registration with OTP and a wrong password, the lawyer workspace (precedents, FIR brief, history, the five
analytics tabs), admin (store health, an ingest that raises the corpus count, a duplicate upload), access control
and a 375 px layout. One worker; traces, screenshots and video are kept on failure in `frontend/test-results`, the
HTML report in `frontend/playwright-report`.

### Fake mode (CI and local)

`LEGALAI_E2E_FAKE_PROVIDERS=1` (with `APP_ENV=test` only) wires `backend/app/testing/e2e.py`:

- a deterministic answer model that cites the retrieved evidence, or gives the no-coverage answer when no evidence
  shares enough of the question's words; a bag-of-words hashing embedder (1024 dimensions) and a word-overlap
  reranker; no model files and no network;
- Chroma, BM25 and uploads in the run's own directory (`LEGALAI_E2E_STATE_DIR`); the repository's stores are refused.

The startup check refuses the flag outside `APP_ENV=test`, and `backend/main.py` never imports `backend/app/testing`
without it (`test_e2e_fake_mode.py` proves both, including starting the app with `APP_ENV=production`).

`backend/scripts/e2e/setup_e2e.py` prepares the run: it migrates a `*_e2e` database, loads the synthetic fixture
corpus into PostgreSQL, Chroma and BM25, loads the committed IPC-BNS and NCRB CSVs, runs the analytics producer,
renders the upload fixtures (the synthetic FIR, and a synthetic judgment with a per-run line), and creates an admin
and a lawyer account with passwords generated for that run (written only to `<state>/accounts.json`, mode 600).

```bash
createdb -h /tmp -p 5432 -O user legalai_e2e      # once
DATABASE_URL='postgresql://<user>:<password>@localhost:5432/legalai_e2e' backend/scripts/e2e/run_e2e.sh
```

`run_e2e.sh` runs the setup, then `npx playwright test` (extra arguments are passed on, e.g. `--headed` or a spec
file). Playwright starts uvicorn and the frontend. Options: `E2E_SKIP_BUILD=1` reuses an existing `.next` build;
`E2E_NEXT_DEV=1` serves with `next dev` for machines that cannot reach Google Fonts during `next build`.
`next build` and `next dev` may rewrite `frontend/next-env.d.ts` (and `next dev` the block in `frontend/AGENTS.md`):
restore them before committing.

### Local real mode

The same journeys against real retrieval on this machine, without touching the development database or stores:

```bash
REHEARSAL_DATABASE_URL='postgresql://<user>:<password>@localhost:5432/legalai_rehearsal' \
  backend/scripts/e2e/run_e2e_local_real.sh [--backup <dir>] [--real-llm] [--keep-state]
```

It makes (or uses) a `backup_dev_state.sh` backup, verifies it and restores it into `legalai_rehearsal` with
`--clean`, copies the backup's Chroma and BM25 stores into a temporary state directory, and runs `run_e2e.sh` with
`E2E_MODE=real`: BGE-M3 and the BGE reranker from the local model cache (MPS when available), the fake LLM unless
`--real-llm` is given (that one uses provider quota). Test accounts, history and the ingested fixture go into the
rehearsal database and the store copies only.

## Updating `requirements.lock`

`requirements.txt` is the top-level list; `requirements.lock` pins everything it resolves to and is used as pip
constraints (`pip install -r requirements.txt -c requirements.lock`). To change a dependency:

1. Edit `requirements.txt`.
2. In a fresh venv: `python -m pip install -r requirements.txt` (no `-c`, so the change resolves).
3. Run every suite (non-DB, DB, frontend, e2e).
4. Regenerate the lock from that venv, keeping the header comment:
   `{ sed -n '/^#/p' requirements.lock; python -m pip freeze --exclude-editable; } > requirements.lock.new && mv requirements.lock.new requirements.lock`
5. Commit both files together.

## Making the CI jobs required on `main`

In GitHub: **Settings → Rules → Rulesets → New ruleset → New branch ruleset** (or the classic **Settings → Branches →
Add branch protection rule**):

1. Name it (e.g. `main`), set **Enforcement status** to *Active*, and under **Target branches** add *Include default
   branch* (or the pattern `main`).
2. Enable **Require a pull request before merging**.
3. Enable **Require status checks to pass**, tick **Require branches to be up to date before merging**, and add the
   four checks by name: `backend-unit`, `backend-db`, `frontend`, `e2e` (they appear in the search box once the
   workflow has run on a pull request).
4. Optionally enable **Block force pushes**, then **Create**.
