# LegalAI

LegalAI answers questions about Indian criminal law with answers grounded in, and cited to, real judgments. It covers
both the old regime (IPC, CrPC) and the new one (BNS, BNSS). It is a final-year project.

- **Public users** ask questions in plain language, or upload an FIR (PDF, scanned or not). They get an answer that
  cites the retrieved judgment passages. When the corpus does not cover the question, they get an explicit
  "no coverage" answer instead of a guess.
- **Verified lawyers** get a professional workspace: precedent search, a structured brief from an uploaded FIR, query
  history, and analytics. The analytics cover offence frequency, outcome distribution, section co-occurrence, the
  IPC↔BNS correspondence table and NCRB crime statistics.
- **Admins** ingest judgments, check store health, and review lawyer verification applications.

## Architecture

```
Next.js 16 (frontend/) ──HTTP, cookie auth──▶ FastAPI (backend/main.py)
                                              ├─ PostgreSQL: users, documents, chunks, analytics (Alembic migrations)
                                              ├─ Retrieval: Chroma (BGE-M3 dense vectors) + BM25 (lexical), fused,
                                              │             then reranked by the BGE reranker (local models, MPS/CPU)
                                              ├─ Query analysis: deterministic section/regime extraction, IPC↔BNS mapping
                                              ├─ Answers: Groq (gpt-oss-120b) with Gemini as fallback; citations validated
                                              └─ Uploads: PyMuPDF text, Tesseract OCR for scanned pages
```

PostgreSQL is canonical. The two indexes are built from the same curated chunks and must hold exactly the same chunk
IDs, text and metadata; `verify_store_consistency.py` checks this. For more detail, see
[docs/LEGAL_RAG_RETRIEVAL_ORCHESTRATION.md](docs/LEGAL_RAG_RETRIEVAL_ORCHESTRATION.md),
[docs/LEXICAL_AND_HYBRID_RETRIEVAL.md](docs/LEXICAL_AND_HYBRID_RETRIEVAL.md),
[docs/INDEX_METADATA.md](docs/INDEX_METADATA.md), [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md) and
[docs/ANALYTICS_DATA.md](docs/ANALYTICS_DATA.md).

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14 (tested 3.14.6) | CI uses 3.14 |
| Node.js / npm | 22 (tested 22.23.2 / npm 10.9) | CI uses Node 22 |
| PostgreSQL | 18 (tested 18.6) | a role that can create databases, or databases created for you |
| Tesseract OCR | 5 (tested 5.5.3) with English data | `brew install tesseract`; on Ubuntu, `apt install tesseract-ocr tesseract-ocr-eng`. Only needed for scanned PDFs ([docs/OCR.md](docs/OCR.md)) |
| Disk | 7 GB or more free | The Hugging Face cache: the model files the app uses take 4.3 GB for BGE-M3 and 2.2 GB for the BGE reranker; a full repository download is larger |

The setup is developed on macOS on Apple Silicon. The query embedder and reranker use the GPU through MPS when
`LEGALAI_MODEL_DEVICE=auto` (the default), and fall back to CPU elsewhere. Linux works on CPU. CI runs on Ubuntu.

## Quick start

Run every command from the repository root unless a step says otherwise.

### 1. Clone and install

```bash
git clone https://github.com/AnanthaRam-GS/lexintelAI.git
cd lexintelAI
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -c requirements.lock
.venv/bin/python -m pip check
```

`requirements.lock` pins every version (see [docs/TESTING.md](docs/TESTING.md), "Updating `requirements.lock`"). On
Linux without a GPU, install the CPU build of torch first:
`.venv/bin/python -m pip install "$(grep -E '^torch==' requirements.lock)" --index-url https://download.pytorch.org/whl/cpu`.

### 2. Configure

```bash
cp .env.example .env
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"   # run once per secret
```

Edit `.env` and fill in the values marked `[required]`:

- `APP_ENV`: `development` here (`.env.example` already sets it). It has no default: the backend refuses to start
  when it is unset or unknown;
- `DATABASE_URL`: `postgresql://<user>:<password>@localhost:5432/legalai`;
- `JWT_SECRET_KEY`: a generated secret;
- `SEED_LAWYER_PASSWORD` and `SEED_ADMIN_PASSWORD`: at least 12 characters each.

For real answers, also set `GROQ_API_KEY`: Groq serves every answer (step 22). Professional answers use
`openai/gpt-oss-120b`, public answers `openai/gpt-oss-20b`, and each falls back to the other model (`groq_backup`).
Prompt v3 keeps answers and briefs inside Groq's 8,000-token per-request limit. On the free tier the two models
sustain about 3 answers per minute; requests beyond that wait in a pacing queue (up to 90 s, the page says "High
demand — your answer is queued") and then get `MODEL_BUSY` (step 23, see
[docs/LLM_PROVIDER_CONFIGURATION.md](docs/LLM_PROVIDER_CONFIGURATION.md)). Never commit `.env`. Without
`DATABASE_URL` the backend refuses to start and says so. The full list is in
[Environment variables](#environment-variables).

The data scripts take the database from an environment variable named by `--database-url-env`. They do not read
`.env` themselves, so export the URL once for the shell session:

```bash
export DATABASE_URL="$(grep '^DATABASE_URL=' .env | cut -d= -f2-)"
```

The scripts refuse to write to the database named in `.env` unless `--confirm-dev` is passed. That flag exists to stop
accidental writes, and here the writes are intended, so the steps below pass it.

### 3. Create the database and migrate

```bash
createdb -O <user> legalai          # or have an administrator create it, owned by your application role
.venv/bin/python -m alembic upgrade head
```

### 4. Seed the development accounts

```bash
.venv/bin/python backend/scripts/seed_users.py
```

This creates `lawyer@legalai.local` and `admin@legalai.local`, with the passwords from `.env`. It refuses to run with
`APP_ENV=production`.

### 5. Load the structured data (committed CSVs)

```bash
.venv/bin/python backend/scripts/load_ipc_bns.py --database-url-env DATABASE_URL --source all --confirm-dev
.venv/bin/python backend/scripts/load_ncrb.py --database-url-env DATABASE_URL --confirm-dev
```

These load the IPC↔BNS correspondence (CYTRAIN table plus the pairs printed in NCRB *Crime in India 2024*, Table
1A.4) and the NCRB statistics. The sources are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

### 6. Get the judgment corpus

The curated corpus is 70 judgments in 1,356 chunks. The judgment text is **not in Git**: it comes from the Indian
Kanoon API, and the repository does not redistribute it (see [Corpus and licensing](#corpus-and-licensing)). The
manifests that describe it are committed.

- **Team members:** copy the 70 chunk files (`*.json`, about 5.6 MB) from the team's shared project folder into
  `data/processed/judgment_chunks/`:

  ```bash
  mkdir -p data/processed/judgment_chunks
  cp /path/to/shared/judgment_chunks/*.json data/processed/judgment_chunks/
  ```

- **Anyone else:** rebuild them from the Indian Kanoon API with your own `INDIAN_KANOON_API_TOKEN`, under Indian
  Kanoon's API terms. Follow [docs/DEVELOPMENT_CORPUS.md](docs/DEVELOPMENT_CORPUS.md), "Reconstruction", and then
  [docs/JUDGMENT_DOCUMENT_PROCESSING.md](docs/JUDGMENT_DOCUMENT_PROCESSING.md). Do a dry run first.

Then load the corpus into PostgreSQL:

```bash
.venv/bin/python backend/scripts/load_corpus.py --database-url-env DATABASE_URL --confirm-dev
```

Before writing, `load_corpus.py` checks that the chunk files are exactly the curated corpus: 70 documents, 1,356
chunks, and the chunk-universe fingerprint recorded in
`data/structured/manifests/trusted_judgment_lexical_index_summary.json`. A second run makes 0 changes.

### 7. Download the models

```bash
.venv/bin/hf download BAAI/bge-m3
.venv/bin/hf download BAAI/bge-reranker-v2-m3
```

The models go to the Hugging Face cache (`~/.cache/huggingface/hub`). The backend loads them at startup
(`LEGALAI_MODEL_WARMUP=true`). The indexes and evaluations were built with these revisions:
- BGE-M3 `5617a9f61b028005a4858fdac845db406aefb181`;
- the reranker `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.

To check yours, run `cat ~/.cache/huggingface/hub/models--BAAI--bge-m3/refs/main`. If the upstream `main` has moved
since, your vectors can differ slightly from the team's.

### 8. Produce the analytics

```bash
.venv/bin/python backend/scripts/produce_analytics_data.py --database-url-env DATABASE_URL \
    --review-dir ~/legalai_reviews --confirm-dev
```

This extracts the cited sections (`document_sections`) and the outcome fields from the judgment text with
deterministic rules. The values are marked **UNREVIEWED**. The review CSV goes to `--review-dir`, which must be
outside the repository because it quotes judgment text ([docs/ANALYTICS_DATA.md](docs/ANALYTICS_DATA.md)). Run this
before step 9: the index metadata is derived from these sections.

### 9. Build the indexes

```bash
.venv/bin/python backend/scripts/build_indexes.py --database-url-env DATABASE_URL \
    --chroma-dir chroma_store --bm25-dir bm25_store --confirm-dev
```

This is one entry point for the whole build. It:

1. checks the corpus, the database and the models;
2. builds Chroma with real BGE-M3 embeddings;
3. builds BM25;
4. adds the index metadata from PostgreSQL;
5. runs the store-consistency verifier, and exits non-zero unless it reports `CONSISTENT`.

It takes 15 to 40 minutes on CPU (13 and 38 minutes on an Apple Silicon laptop in the step 20 runs). The build summaries go to `index_build_summaries/` next to the Chroma directory;
the committed manifests are not rewritten.

### 10. Run

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health          # in another terminal
```

```bash
cd frontend
npm ci
cp .env.example .env.local                     # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                                    # http://localhost:3000
```

Keep `localhost` (not `127.0.0.1`) for the API, the same host name as the frontend. The sign-in cookie is
`SameSite=Lax`, so the browser does not send it from `localhost:3000` to `127.0.0.1:8000` (a different site): signing
in would succeed and then bounce back to the sign-in page. The seed accounts from step 4 sign in at `/login`.

`/health` reports the database, the stores and the model warm-up. To check the analytics endpoints against the
database, run `APP_ENV=test LEGALAI_MODEL_WARMUP=false .venv/bin/python backend/scripts/verify_analytics.py
--database-url-env DATABASE_URL --require-non-empty`.

## Running tests

All of this is documented in [docs/TESTING.md](docs/TESTING.md).

| Suite | Command | Needs |
|---|---|---|
| Backend, non-DB | `backend/scripts/dev/run_nondb_suites.sh` | nothing (Tesseract for the OCR tests) |
| Backend, DB-backed | `backend/scripts/dev/run_db_suites.sh <log dir>` | `TEST_DATABASE_URL` pointing at a separate `*_test` database |
| Frontend | `cd frontend && npm run test:run && npm run lint && npm run format:check && npx tsc --noEmit --incremental false` | `npm ci` |
| End-to-end, fake mode | `DATABASE_URL=<url of a *_e2e database> backend/scripts/e2e/run_e2e.sh` | a `*_e2e` database; no models, no keys, no corpus |
| End-to-end, local real mode | `REHEARSAL_DATABASE_URL=<url> backend/scripts/e2e/run_e2e_local_real.sh` | a dev setup, the models, `legalai_rehearsal` |

CI runs on every pull request (`.github/workflows/ci.yml`): backend non-DB tests, DB tests against PostgreSQL 18,
frontend checks, and the end-to-end journeys in fake mode. It uses no secrets, no models and no corpus.

## Environment variables

`.env.example` documents every variable. "Default" is the value used when the variable is unset; `.env.example`
sets the same value unless noted.

| Variable | Purpose | Default | Required |
|---|---|---|---|
| `DATABASE_URL` | PostgreSQL connection URL | none | **yes** (except `APP_ENV=test`) |
| `JWT_SECRET_KEY` | signs the auth tokens; at least 32 bytes | none | **yes** (except `APP_ENV=test`) |
| `SEED_LAWYER_PASSWORD`, `SEED_ADMIN_PASSWORD` | passwords for `seed_users.py` | none | to seed |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `NVIDIA_API_KEY` | answer providers | none | for the configured providers |
| `APP_ENV` | `development`, `test` or `production` (production: secure cookies, stricter checks, no console email) | none: startup refuses unset or unknown values; the test runners set `test` | **yes** |
| `BACKEND_HOST`, `BACKEND_PORT` | backend bind address. Deployments that must accept outside connections set `0.0.0.0` explicitly (uvicorn's `--host` binds the socket) | `127.0.0.1`, `8000` | no |
| `FRONTEND_ORIGIN` | allowed CORS origin | `http://localhost:3000` | no |
| `LEGALAI_LLM_PROVIDER`, `LEGALAI_LLM_FALLBACK_PROVIDER` | primary and fallback provider (`groq`, `gemini`, `nvidia`, `ollama`, `deepseek`, `openrouter`, `groq_backup`) | `gemini`, `gemini` (`.env.example`: `groq`, `groq_backup`) | no |
| `LEGALAI_PROMPT_VERSION` | product prompt: `v3` (v2 plus concision) or `v2` | `v3` | no |
| `GROQ_PUBLIC_MODEL` | Groq model for public answers (per-mode routing); empty uses `GROQ_MODEL` | empty (`.env.example`: `openai/gpt-oss-20b`) | no |
| `GROQ_BACKUP_MODEL`, `GROQ_BACKUP_PUBLIC_MODEL` | models of the `groq_backup` fallback for professional and public answers | empty (`.env.example`: 20b, 120b) | with `groq_backup` |
| `GROQ_MODEL`, `GROQ_BASE_URL`, `GEMINI_MODEL` | provider models and endpoint | example: `openai/gpt-oss-120b`, Groq API, `gemini-3.7-flash` | with that provider |
| `LEGALAI_LLM_MAX_OUTPUT_TOKENS`, `LEGALAI_GROQ_*`, `LEGALAI_GEMINI_*` | provider limits and tuning | see `.env.example` | no |
| `LEGALAI_LLM_PACING_ENABLED`, `LEGALAI_LLM_QUEUE_MAX_WAIT_SECONDS`, `LEGALAI_GROQ_TOKENS_PER_MINUTE`, `LEGALAI_GROQ_REQUESTS_PER_MINUTE` | answer pacing queue for rate-limited models (step 23); `/health` shows `llm_queue` | `true`, `90`, `8000`, `30` | no |
| `LEGALAI_PROFESSIONAL_PRIMARY_MAX_WAIT_SECONDS`, `LEGALAI_PROFESSIONAL_FALLBACK_ENABLED` | professional answers wait this long for gpt-oss-120b, then `MODEL_BUSY`; they never fall back to 20b unless enabled (steps 24, 24b) | `45`, `false` | no |
| `LEGALAI_GROQ_TOKENS_PER_DAY`, `LEGALAI_GROQ_REQUESTS_PER_DAY`, `LEGALAI_LLM_DAILY_USAGE_FILE` | daily budget per model over a rolling 24-hour window, and the persisted timestamped usage; when nothing can serve, `503 DAILY_CAPACITY_REACHED` (steps 24b-24c); `/health` shows `llm_daily` | `200000`, unset, `data/runtime/llm_daily_usage.json` | no |
| `LEGALAI_PRODUCT_MAX_INPUT_TOKENS` and the other `*_TOKENS` / `PRIVATE_PDF_*` budgets | context budgeting ([docs/PRODUCT_CONTEXT_BUDGETING.md](docs/PRODUCT_CONTEXT_BUDGETING.md)) | see `.env.example` | no |
| `LEGALAI_MODEL_DEVICE` | query embedder and reranker device: `auto`, `cpu`, `mps`, `cuda` | `auto` | no |
| `LEGALAI_RERANKER_FP16` | reranker half precision on GPU | `true` | no |
| `LEGALAI_MODEL_WARMUP` | load the models at startup | `true` | no |
| `LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS` | wait for the model lock before a 503 | `30` | no |
| `LEGALAI_QUERY_DEBUG` | timings in query responses (debug only) | `false` | no |
| `CHROMA_PERSIST_DIR`, `CHROMA_COLLECTION_NAME` | vector store location | `./chroma_store`, `legalai_trusted_judgments_v1` | no |
| `EMBEDDING_*`, `BGE_*`, `RERANKER_*`, `RETRIEVAL_TOP_K`, `RERANK_TOP_K` | index-build embedder and retrieval settings | see `.env.example` (`EMBEDDING_DEVICE=cpu`) | no |
| `JWT_ALGORITHM`, `JWT_EXPIRY_MINUTES`, `AUTH_COOKIE_SAMESITE` | auth tokens and cookie | `HS256`, `60`, `lax` | no |
| `LOGIN_*`, `*_QUERY_LIMIT_PER_*`, `LLM_MAX_CONCURRENT_GENERATIONS`, `LLM_GENERATION_WAIT_SECONDS` | throttling and rate limits | see `.env.example` | no |
| `TRUSTED_PROXIES` | proxies whose `X-Forwarded-For` is trusted | empty (none) | no |
| `OCR_*`, `TESSERACT_CMD` | OCR fallback ([docs/OCR.md](docs/OCR.md)) | `OCR_ENABLED=true`, `OCR_LANGUAGE=eng` | no |
| `MAX_UPLOAD_SIZE_MB`, `MAX_QUERY_LENGTH` | request limits | `10`, `5000` | no |
| `VERIFICATION_DOCUMENT_DIR` | private directory for lawyer verification proofs | `./data/private/lawyer_verification` | no |
| `EMAIL_DELIVERY_MODE` | `console` (codes in the backend log) or `smtp`; `console` is refused at startup with `APP_ENV=production` | `console` | `smtp` in production |
| `SMTP_*` | SMTP delivery | empty | with `smtp` |
| `EXPOSE_DEV_VERIFICATION_TOKENS`, `EMAIL_OTP_*` | verification codes | `false`; see `.env.example` | no |
| `LEGAL_NER_*`, `INLEGALBERT_*` | optional NER experiments; off by default | see `.env.example` | no |
| `INDIAN_KANOON_API_TOKEN`, `INDIAN_KANOON_BASE_URL` | corpus acquisition scripts only | empty, `https://api.indiankanoon.org` | to acquire |
| `NVIDIA_*` | NVIDIA API catalog profile (OpenAI-compatible): base URL, model, output limit, timeout, structured-output mode, request ceiling, streaming (`NVIDIA_STREAM`, `NVIDIA_STREAM_DEADLINE_SECONDS`) | see `.env.example` | with `nvidia` |
| `OLLAMA_*` | local Ollama profile (OpenAI-compatible `/v1`, no key): model, context (`OLLAMA_CONTEXT_TOKENS`), output limit, timeout, structured-output mode (`prompt`), reasoning (`none`) | see `.env.example` | with `ollama` |
| `DEEPSEEK_*`, `OPENROUTER_*` | profiles defined for future keys; disabled while the key is empty | empty | no |
| `TEST_DATABASE_URL` | DB-backed test suites only; a `*_test` database | none | for DB tests |
| `NEXT_PUBLIC_API_BASE_URL` (`frontend/.env.local`) | backend URL for the frontend; use the frontend's host name (`localhost`) | `http://localhost:8000` (step 10) | yes |

## Project structure

```
backend/
  main.py                  FastAPI app
  app/api/                 routes (query, auth, analytics, ingest, admin, history)
  app/services/            retrieval, reranking, query analysis, answers, ingestion, OCR, analytics
  app/db/, migrations/     SQLAlchemy models and Alembic migrations
  scripts/                 data loaders, index builders, verifiers, evaluations; tests in scripts/tests/
  scripts/dev/, scripts/e2e/   test runners, backups, end-to-end harness
frontend/                  Next.js app (app/, components/, e2e/ Playwright journeys)
data/
  structured/manifests/    committed corpus, index and evaluation manifests
  processed/ipc_bns/, ncrb/   committed CSVs loaded in step 5
  processed/judgment_chunks/  curated chunks (gitignored; see step 6)
docs/                      design notes, evaluations, data sources, testing, security
chroma_store/, bm25_store/ the indexes (gitignored; built in step 9)
```

Legacy scripts are kept for the record but are not part of the setup:

- `backend/scripts/reconcile_backfill.py`: pinned to migration 0005;
- `backend/scripts/reconcile_cleanup.py`: a one-off reconciliation.

Each says so in its header.

## Privacy: what is sent to the answer provider

Answers are written by the configured LLM provider. Each question is sent to it with the retrieved judgment excerpts.
**Content from uploaded PDFs is sent too.** A public PDF question sends the selected excerpts, and a professional
brief sends the document map, which includes names, dates and quoted sentences.

With a cloud provider (Groq, Gemini, NVIDIA, DeepSeek, OpenRouter), that text leaves this machine and is handled
under that provider's terms. Only the local `ollama` profile keeps it on the machine. PDFs uploaded with a question
are not stored by LegalAI (only admin ingestion stores documents), and no keys, prompts or document text are written to its logs. Choose the providers
(`LEGALAI_LLM_PROVIDER`, `LEGALAI_LLM_FALLBACK_PROVIDER`) with this in mind, and tell users before they upload
documents.

## Corpus and licensing

- The judgments come only from the [Indian Kanoon API](https://api.indiankanoon.org)
  ([docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)). Bulk collection must use the documented API, not scraping, and API
  credentials are never committed.
- Indian Kanoon's API terms require attribution wherever API-provided information is used in product display, RAG
  context or model fine-tuning. The manifests carry `attribution_required`, and the attribution text is "Judgment
  data sourced from Indian Kanoon API."
- No document in this repository grants a right to redistribute the judgment text. The raw files, the processed text
  and the chunks are therefore gitignored, and only manifests (IDs, hashes, counts) are committed.
- The NCRB statistics come from NCRB's *Crime in India*. Statute texts are to be taken from official government
  sources such as India Code ([docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)).
- The UI fonts (IBM Plex Sans, Libre Baskerville) are self-hosted under the SIL Open Font License 1.1
  ([frontend/app/fonts/README.md](frontend/app/fonts/README.md)).

## Known limitations

- **Provider capacity:** answers depend on an external LLM. On a base Groq account, requests are capped near 8,000
  tokens per minute, so the context budgets are tuned low. Rate limits and outages return a clear error, or fall back
  to Gemini ([docs/LLM_PROVIDER_CONFIGURATION.md](docs/LLM_PROVIDER_CONFIGURATION.md)).
- **One local inference at a time:** the embedder and reranker are serialised per process. Under load, queries wait,
  then get `503 MODEL_BUSY`.
- **English-only OCR:** scanned pages are read with Tesseract's English model. Hindi and other scripts are not
  recognised.
- **Small corpus:** 70 judgments (1,356 chunks), so many questions correctly get the "no coverage" answer.
- **Unreviewed legal extractions:** the outcome fields, the cited sections and the IPC↔BNS mapping were extracted or
  loaded without legal review, and are marked UNREVIEWED. The NCRB-printed IPC↔BNS pairs have no change type
  (none is printed).
- **Pending scope decisions:** corpus redistribution beyond the team (see above), and any further statute
  correspondence sources (the BPR&D table was not approved).

## Team and credits

| Name | Roll number | Role |
| --- | --- | --- |
| Anantha Ram G S | CB.SC.U4CSE23408 | Backend & AI Pipeline Lead |
| Rama Roshinee S V | CB.SC.U4CSE23645 | Backend Developer |
| Ravindran G | CB.SC.U4CSE23647 | Frontend Developer |
| Gugan S S | CB.SC.U4CSE23416 | Frontend Developer |

Guide: Dr. Sabarish B A, Assistant Professor, Department of CSE.

Judgment data sourced from the Indian Kanoon API. Crime statistics from the National Crime Records Bureau,
*Crime in India*. IPC↔BNS correspondence from the CYTRAIN table and NCRB *Crime in India 2024*, Table 1A.4.
Embedding and reranking models: BAAI BGE-M3 and BGE-reranker-v2-m3.
