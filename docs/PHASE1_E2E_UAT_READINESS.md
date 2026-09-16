# Phase 1 E2E / UAT Readiness

This guide prepares the shared Phase 1 branch for first integration smoke checks
and supervised UAT. It does not perform live Gemini calls, mutate production
indexes, or touch benchmark artifacts.

## Readiness Matrix

| Area | Backend status | Frontend status | UAT readiness |
| --- | --- | --- | --- |
| Backend boot and health | `/health` is registered and accepts `ok` or `degraded` database state | N/A | Ready for smoke validation |
| Auth | `/auth/login`, `/auth/logout`, and `/auth/me` are registered; auth uses HttpOnly cookies with bearer fallback for API clients/tests | `/login` uses backend-derived roles, cookie credentials, `/auth/me` refresh, and no client-side JWT storage | Code-complete; needs live DB/session validation |
| Public query | `/query/public` accepts anonymous text requests through the frozen retrieval/generation path | `/public` posts text queries to `/query/public` through `apiFetch` | Ready when API keys/indexes are configured |
| Professional text query | `/query/professional` requires lawyer/admin auth and saves sanitized history | `/professional/query` posts `{ text, session_id? }` through the shared cookie-based API client and renders structured briefs | Code-complete; needs live RAG/provider validation |
| Professional PDF query | `/query/professional/pdf` requires lawyer/admin auth and accepts temporary private PDF context | `/professional/upload` sends private multipart `query`, `file`, and optional `session_id`; it does not call ingestion | Code-complete; needs live PDF/provider validation |
| Admin ingestion | `/ingest/upload`, `/ingest/status/{job_id}`, and `/ingest/corpus/stats` are registered; ingestion updates vector and BM25 stores after validation | `/admin` and `/admin/ingest` call the live cookie-auth ingestion API through the shared frontend client | Code-complete; live DB validation pending |
| Analytics | analytics route family is registered behind lawyer/admin auth | `/professional/analytics` calls the protected analytics endpoints and renders Recharts visualizations/tables | Code-complete; needs live DB-backed validation |
| Query history | `/query/history` and legacy `/query-history` are registered behind lawyer/admin auth | `/professional/history` calls `/query/history?limit=` and renders user-scoped stored briefs | Code-complete; needs live DB-backed validation |

## Startup Procedure

1. Create or refresh the local backend environment.

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. Configure backend environment variables.

   Required for ordinary local integration:

   - `DATABASE_URL`
   - `JWT_SECRET_KEY`
   - `GEMINI_API_KEY`
   - `GEMINI_MODEL`
   - `LEGALAI_LLM_PROVIDER=gemini`
   - `FRONTEND_ORIGIN=http://127.0.0.1:3000`

   Do not print or commit real secret values. In production-like runs,
   `JWT_SECRET_KEY` must be explicitly set.

3. Start local services.

   ```bash
   uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
   cd frontend
   npm install
   NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
   ```

4. Run the backend readiness smoke check before shared UAT.

   ```bash
   .venv/bin/python backend/scripts/run_integration_smoke.py
   ```

   A local database outage may report `/health` as `degraded`; that is acceptable
   for route-surface readiness but not for full authenticated UAT.

## Smoke Checks

Run these before handing the branch to reviewers:

```bash
python3 -m compileall backend/app backend/scripts
.venv/bin/python backend/scripts/run_integration_smoke.py
.venv/bin/python -m unittest backend.scripts.tests.test_integration_readiness_smoke
.venv/bin/python -m unittest backend.scripts.tests.test_query_api backend.scripts.tests.test_document_processing_services backend.scripts.tests.test_bm25_ingestion_update
.venv/bin/python -m unittest discover backend/scripts/tests
python3 backend/scripts/validate_corpus.py
python3 backend/scripts/validate_section_catalog_coverage.py
python3 backend/scripts/validate_legal_section_gold.py
cd frontend && npm run test:run
cd frontend && npm run lint
cd frontend && npm run format:check
cd frontend && npx tsc --noEmit
```

## First-Review UAT Checklist

Use a controlled local database and non-production indexes.

1. Confirm `/health` returns HTTP 200 and record whether status is `ok` or
   `degraded`.
2. Log in through `/login` as a lawyer/admin; confirm the response sets an
   HttpOnly session cookie and `/auth/me` derives the role from the backend.
3. Submit a public text query from `/public`; confirm the UI sends cookies and no
   bearer token, and the response does not expose professional-only fields.
4. Submit a professional text query through `/professional/query`; confirm
   lawyer/admin auth is required and sanitized history is written.
5. Submit a professional PDF query through `/professional/upload`; confirm
   invalid file types are rejected and private PDF text is not stored in
   history.
6. Upload a trusted-corpus document through admin ingestion API tooling; confirm
   job status reaches `COMPLETED` only after vector and BM25 updates succeed.
7. Open `/professional/analytics` as lawyer/admin and as an unauthenticated
   client; confirm protected routes reject unauthenticated access.
8. Open `/professional/history` and call legacy `/query-history`; confirm
   pagination and role protection.
9. Review browser console and backend logs for stack traces, secret leakage, or
   unexpected provider calls.

## Known Blockers

- Admin ingestion frontend is code-complete against the live API; validation still needs a live admin session plus PostgreSQL/Chroma/BM25-backed ingestion run.
- Full authenticated UAT requires a reachable PostgreSQL database with seeded
  test users and role assignments.
- Live answer generation requires a valid Gemini configuration and available
  quota. The smoke checks in this task do not call Gemini.
- Professional, history, and analytics frontends are compile-clean but not yet
  live-validated against a running backend, database, and provider quota.
- The frozen benchmark generation/review artifacts are out of scope for this
  readiness task.

## Fallback Plan

If shared UAT cannot run end-to-end, use this reduced demo path:

1. Show backend boot and route readiness with
   `.venv/bin/python backend/scripts/run_integration_smoke.py`.
2. Demonstrate the public frontend against mocked or quota-available backend
   responses.
3. Demonstrate `/login`, professional text/PDF, analytics, and history with
   seeded local users if PostgreSQL and Gemini quota are available.
4. Demonstrate admin ingestion through the live admin frontend with real storage
   services available.
