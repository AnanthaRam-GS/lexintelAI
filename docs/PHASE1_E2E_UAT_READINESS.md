# Phase 1 E2E / UAT Readiness

This guide prepares the shared Phase 1 branch for first integration smoke checks
and supervised UAT. It does not perform live Gemini calls, mutate production
indexes, or touch benchmark artifacts.

## Readiness Matrix

| Area | Backend status | Frontend status | UAT readiness |
| --- | --- | --- | --- |
| Backend boot and health | `/health` is registered and returned `ok` with local PostgreSQL 18.6 reachable | N/A | WORKING |
| Auth | `/auth/login`, `/auth/logout`, and `/auth/me` are covered by PostgreSQL-backed tests; auth uses HttpOnly cookies with bearer fallback for API clients/tests | `/login` uses backend-derived roles, cookie credentials, `/auth/me` refresh, and no client-side JWT storage | WORKING |
| Public query | `/query/public` accepts anonymous text requests through the frozen retrieval/generation path | `/public` posts text queries to `/query/public` through `apiFetch` | PARTIAL: contract covered; live provider quota still separate |
| Professional text query | `/query/professional` requires lawyer/admin auth and saves sanitized history in PostgreSQL-backed tests | `/professional/query` posts `{ text, session_id? }` through the shared cookie-based API client and renders structured briefs | WORKING |
| Professional PDF query | `/query/professional/pdf` requires lawyer/admin auth and accepts temporary private PDF context without ingestion mutation in tests | `/professional/upload` sends private multipart `query`, `file`, and optional `session_id`; it does not call ingestion | WORKING |
| Admin ingestion | `/ingest/upload`, `/ingest/status/{job_id}`, and `/ingest/corpus/stats` pass PostgreSQL-backed ingestion tests; vector and BM25 failure paths are covered | `/admin` and `/admin/ingest` call the live cookie-auth ingestion API through the shared frontend client | WORKING |
| Analytics | analytics route family is registered behind lawyer/admin auth and passes PostgreSQL-backed route/service tests | `/professional/analytics` calls the protected analytics endpoints and renders Recharts visualizations/tables | WORKING |
| Query history | `/query/history` and legacy `/query-history` pass PostgreSQL-backed user-scoping and persistence tests | `/professional/history` calls `/query/history?limit=` and renders user-scoped stored briefs | WORKING |

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
   for route-surface readiness but not for full authenticated UAT. With the
   local PostgreSQL development database running, the smoke check should report
   health `ok`.

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

- Full authenticated UAT requires the local PostgreSQL service to remain running
  and the development users to be seeded.
- Live answer generation requires a valid Gemini configuration and available
  quota. The smoke checks in this task do not call Gemini.
- Live browser demonstration still requires starting both backend and frontend
  dev servers; the automated validation covered API/backend contracts and
  frontend regression suites, not a manual browser walkthrough.
- The frozen benchmark generation/review artifacts are out of scope for this
  readiness task.

## Fallback Plan

If shared UAT cannot run end-to-end, use this reduced demo path:

1. Show backend boot and route readiness with
   `.venv/bin/python backend/scripts/run_integration_smoke.py`.
2. Demonstrate the public frontend against mocked or quota-available backend
   responses.
3. Demonstrate `/login`, professional text/PDF, analytics, and history with
   seeded local users. Use provider stubs for first-review DB/session demo if
   Gemini quota is unavailable.
4. Demonstrate admin ingestion through the live admin frontend with real storage
   services available.
