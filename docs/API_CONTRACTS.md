# LegalAI Phase 0 API Contracts

This document freezes the first backend API data contracts for Phase 0. It is
intended for frontend and backend development against shared mock responses
before live APIs exist.

## Authentication

Protected professional surfaces are available to `lawyer` and `admin` roles.
Public Mode is anonymous and does not require login or JWT authentication.

Login accepts email and password only. The backend derives the user's role from
stored user data; clients must not send a role selector. Authentication will use
a secure HttpOnly cookie for the JWT, so the login JSON response does not need
to expose the token.

The root route sends users to `/login`. Public use remains available through an
explicit "Continue as guest" action that opens `/public`.

Registration is public and creates `public` users only:

```json
{ "email": "user@example.com", "password": "minimum-length-password", "full_name": "Optional Name" }
```

`POST /auth/register` sends a six-digit email verification OTP to a new
address. Role injection from the client is ignored. OTPs are hashed before
persistence, expire after the configured window, are single-use, and are
attempt-limited. `POST /auth/verify-email` accepts `{ "email": "...",
"otp": "123456" }`; `POST /auth/resend-verification` accepts `{ "email": "..."
}` and supersedes previous active OTPs after the configured cooldown.

**No account enumeration (step 13, SEC-003).** These responses do not reveal
whether an email has an account:
- `POST /auth/register` always returns **201**
  `{ "email", "message", "email_verification_required", "dev_verification_otp" }`
  with the same message. It no longer returns `user`, and it never returns 409.
  For an email that already has an account, no account or code is created;
  instead the owner is emailed an "account already exists" notice.
  `dev_verification_otp` is only ever set for a new account, and only with
  `APP_ENV` development/test and `EXPOSE_DEV_VERIFICATION_TOKENS=true`.
- `POST /auth/resend-verification` always returns **200**
  `{ "email_verified": false, "message": "If this email needs verification, a new code has been sent." }`
  for unknown, already-verified and cooling-down emails alike. It no longer
  returns 429 `OTP_RESEND_COOLDOWN` or `expires_at`; the cooldown is enforced
  silently.
- `POST /auth/verify-email` answers an unknown email with the same
  **400** `INVALID_OR_EXPIRED_OTP` as an expired code.
- `POST /auth/login` returns the same **401** `"Invalid email or password"` for
  an unknown email, a wrong password and a deactivated account (SEC-004). It
  verifies against a dummy hash for unknown emails, so timing matches.

**Login throttling (SEC-003).** Failed logins are counted per email and per
client IP (`LOGIN_MAX_FAILURES_PER_ACCOUNT`, default 5;
`LOGIN_MAX_FAILURES_PER_IP`, default 20; within
`LOGIN_FAILURE_WINDOW_SECONDS`, default 900). Once either limit is reached,
login returns **429** with a `Retry-After` header and
`{"error": "Too many sign-in attempts. Please wait ...", "code": "LOGIN_THROTTLED", "detail": {"retry_after": N}}`
until `LOGIN_LOCKOUT_SECONDS` (default 900) pass, even with the right password.
Unknown emails are throttled exactly like real ones. A successful login clears
the email's count.

**Sessions.** Every authenticated request reloads the user from PostgreSQL.
A missing or deactivated user (`is_active = 0`) gets **401**
`INVALID_SESSION`, the same body as an invalid token, and the role
always comes from the database, never from the token's `role` claim. The cookie
is `HttpOnly`, has an explicit `SameSite` (`AUTH_COOKIE_SAMESITE`, default
`lax`), and is `Secure` in production. Cookie-authenticated `POST`, `PUT`,
`PATCH` and `DELETE` requests from an origin outside the CORS allow-list get
**403** `CSRF_ORIGIN_REJECTED` (see `docs/SECURITY.md`).

Email delivery is abstracted behind `EMAIL_DELIVERY_MODE`. `smtp` uses
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`,
and `SMTP_USE_TLS`. `console` is for local development/test only and is disabled
in production.

Lawyer access is granted only through credential review. Authenticated,
email-verified public users may submit one active application through
`POST /lawyer-applications` with multipart/form-data fields for bar council,
enrollment number, enrollment year, jurisdiction, optional organization, and a
PDF/JPEG/PNG proof document. Proof uploads are private verification material:
they are not corpus ingestion inputs, are not indexed in BM25 or Chroma, and
are not supplied to public/professional RAG queries.

Applicants can read their current state from `GET /lawyer-applications/me`.
Admins review applications through:

- `GET /admin/lawyer-applications`
- `GET /admin/lawyer-applications/{application_id}`
- `POST /admin/lawyer-applications/{application_id}/approve`
- `POST /admin/lawyer-applications/{application_id}/reject`
- `POST /admin/lawyer-applications/{application_id}/request-resubmission`

Only admin approval promotes the associated account to the `lawyer` role.
Pending, rejected, and resubmission-requested applicants remain `public` users
and must be denied professional-only APIs by backend authorization.

## Professional Query

Professional users may submit either text or a temporary PDF, one input form at
a time. PDF upload endpoints use multipart/form-data rather than embedding
uploaded files in JSON schemas.

`POST /query/professional` accepts authenticated lawyer/admin JSON text
requests:

```json
{ "text": "Research anticipatory bail under BNSS", "session_id": "optional-session-id" }
```

`POST /query/professional/pdf` accepts authenticated lawyer/admin
multipart/form-data requests:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | yes | Original professional legal query, max 5000 characters. |
| `file` | PDF upload | yes | One temporary private PDF. |
| `session_id` | string | no | Optional history session id. |

The PDF route returns the same `ProfessionalQueryResponse` shape as the JSON
text route. The uploaded PDF is parsed and chunked locally for that request,
then a deterministic bounded private context is supplied to the professional
answer prompt. The PDF remains factual query context only; cited authorities
must come from retrieved trusted-corpus evidence.

Professional query uploads are temporary analysis inputs. They are not
automatically ingested into the global corpus. They do not create ingestion
jobs, Chroma upserts, or BM25 index writes. Successful history saves may record
the authenticated user, original query, session id, answer metadata, and
response JSON, but must not persist PDF bytes, full extracted text, temporary
chunks, or server temp paths.

PDF upload errors use safe HTTP responses for unsupported extension/MIME,
invalid PDF header, empty upload, configured size limit, parse failures, and
chunking failures. Error payloads must not leak local paths, stack traces, or
provider secrets.

The professional response is structured into:

- identified statutory sections
- retrieved precedents with provenance metadata
- a structured case brief containing summary, applicable law, key issues,
  procedural considerations, precedent analysis, and limitations

Citation metadata must come from retrieved backend metadata, not from
LLM-generated citation details.

**Precedents** (`precedents[]`) are built from the retrieved trusted evidence
the answer was generated from, one per retrieved document, in rank order:

| Field | Source |
|---|---|
| `document_id`, `chunk_id` | the retrieved trusted chunk |
| `case_name`, `court`, `year`, `source_url` | retrieved chunk metadata |
| `page_start`, `page_end`, `paragraph_start`, `paragraph_end` | retrieved chunk provenance |
| `reranker_score` | the BGE reranker's raw score for that chunk, or `null` |
| `relevance_score` | **relative relevance within this query**: the returned precedents' raw reranker scores, min-max scaled so the top precedent is `1.0` and the lowest `0.0`. It is `null` when the precedent has no reranker score, when there is only one scored precedent, or when all scores are equal. It is not an absolute probability (a sigmoid of the BGE logits saturated at 0.98-1.0 live). The UI labels it "relative relevance". |
| `excerpt` | a verbatim span of the chunk text, at most `PRECEDENT_EXCERPT_MAX_CHARS` (default 400) characters, centred on the passage most relevant to the retrieval query; `...` marks a cut |

The model's `retrieved_authorities` are not turned into precedents. Every
retrieved document is listed. `cited_in_answer` is `true` when the answer
cites one of the document's retrieved chunks (E#) through a citation that
passed citation validation, and `false` when the document was only retrieved.

**Case-brief field sources.** `parties_and_roles`, `chronology`,
`procedural_considerations` and `evidence_identified` are lists of strings,
and every document-derived item ends with its uploaded-document reference,
for example `[P2, p. 3]`:

| Field | Source |
|---|---|
| `summary`, `material_facts`, `statutory_provisions`, `key_issues`, `applicable_law`, `precedent_analysis`, `recommended_research_questions` | the model |
| `parties_and_roles` | brief mode: local document-map party detection, `"<Role>: <name> [P#, p. N]"` |
| `chronology` | brief mode: dated events only, sorted by date, `"<YYYY-MM-DD> - <event>: <sentence> [P#, p. N]"` |
| `procedural_considerations` | brief mode: procedural stages stated in the document (FIR registration, arrest, investigation, bail, charge sheet filing, framing of charges, trial, appeal, revision, petition/quashing), `"<stage>: <sentence> [P#, p. N]"`; then the model's procedural posture |
| `evidence_identified` | brief mode: evidence named in the document by category (Witnesses, Documents, Medical/forensic, Electronic, Recoveries/seizures), `"<categories>: <sentence> [P#, p. N]"` |
| `limitations` | the model's uncertainties, then the document map's missing-information notes |

Professional PDF queries build the local document map in both `analysis_mode`
values. Brief mode sends the map to the model; question mode sends the
question-focused P# excerpts. Both fill `parties_and_roles`, `chronology`,
procedural stages and `evidence_identified` from the map. Text queries have
no document, so those fields are empty: nothing is inferred from the query
text. No field copies another.

Query history keeps the professional response without any item quoted from
the uploaded document: P#-referenced items are dropped and a limitation
notes it. Model content and precedents are kept.

**Debug.** Every query response has a `debug` field, `null` unless the
backend sets `LEGALAI_QUERY_DEBUG=true`. When enabled it holds:
- `endpoint`;
- `timings_ms`, per stage in milliseconds: `parse_ms`, `document_map_ms`,
  `query_understanding_ms`, `dense_retrieval_ms`, `bm25_retrieval_ms`,
  `fusion_ms`, `rerank_ms`, `retrieval_total_ms`, `context_assembly_ms`,
  `generation_ms` (provider calls, including any fallback),
  `answer_parse_and_citation_validation_ms` and `total_ms`;
- `backend`: provider, model, `fallback_used`, primary, fallback and
  `fallback_reason`;
- `model_devices`: `{"embedder": "mps/fp32", "reranker": "mps/fp16"}`, the
  device and precision actually in use (after any CPU fallback), or `null`
  if the models are not loaded.

The same timings, backend and devices are always logged, without query or
document text. Public responses also gain `debug` (`null` by default).

**Health.** `GET /health` also returns `models`:
- `status`: `not_loaded`, `loading` (startup warm-up running), `loaded` or
  `failed` (warm-up failed; queries load the models on demand);
- when loaded: `devices`, plus `load_ms` and `warmup_ms` from the warm-up;
- `error`: the exception type, when failed;
- `warm_up` (step 18): `loading`, `ready`, `failed`, or `not_started` (warm-up disabled);
- `inference` (step 18): `{active, waiting}`, the model calls holding and waiting for the process-wide model lock.

The top-level `status` still reflects the database only.

## Public Query

**No-coverage answers (prompt v2).** When no retrieved evidence is relevant,
the answer starts with "The available sources do not cover this question."
and the response carries no provisions (`sections: []`), no sources and only
generic guidance to consult a professional.

**Answer errors.**
- `502 MODEL_OUTPUT_MISSING_CITATIONS`: the model returned no structured
  claims (and the answer is not a no-coverage answer).
- `502 MODEL_OUTPUT_TRUNCATED`: the model stopped at the configured output
  token limit.

Neither answer is shown, and neither triggers the provider fallback.

**Sources are validated citations only.** `sources[]` (and the fallback
`sections[]` built when the answer names no provision) come only from
citations that passed citation validation. If no citation validates,
`sources` is `[]`; it never falls back to unvalidated citations or to a
placeholder link. The frontend then says it could not verify a source for the
answer.

Public Mode requires no login. Public users may submit either text or a
temporary PDF, one input form at a time. PDF upload endpoints will use
multipart/form-data.

`POST /query/public` accepts anonymous JSON text requests:

```json
{ "text": "Can the police arrest me without notice?" }
```

`POST /query/public/pdf` accepts anonymous multipart/form-data requests:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | yes | Public legal question or document explanation request. |
| `file` | PDF upload | yes | One temporary private PDF. |

Public query uploads are temporary analysis inputs and are not automatically
ingested into the global corpus. Public PDFs are parsed and chunked in a
temporary directory for the request only; they do not create ingestion jobs,
Chroma writes, BM25 writes, or trusted-corpus documents. Uploaded text is
treated as untrusted user-provided facts, not legal authority, and legal
citations remain restricted to trusted-corpus evidence.

The public response contains a plain-language explanation, cited statutory
sections, and public-facing sources.

## Scanned PDFs: OCR (step 14, RAG-005)

Both PDF query routes and admin ingestion read scanned pages with Tesseract
OCR (`docs/OCR.md`). A page is OCR'd when its native text is shorter than
`OCR_MIN_CHARS_PER_PAGE` and it contains an image.

- **New response field:** `PublicQueryResponse.limitations` (list of strings,
  default `[]`). Like `case_brief.limitations` in the professional response, it
  carries the OCR warning when any OCR'd page has a mean Tesseract confidence
  below `OCR_LOW_CONFIDENCE_THRESHOLD` (default 80): "Parts of this document were
  read by OCR (text recognition from a scan) with low confidence, so names, dates
  and figures taken from it may contain errors. Check them against the original."
- **422 `OCR_LIMIT_EXCEEDED`:** more pages need OCR than `OCR_MAX_PAGES_QUERY`
  (default 10), or OCR exceeded its page or document time limit. Nothing partial
  is answered.
- **503 `OCR_UNAVAILABLE`:** pages need OCR but Tesseract (or its language data)
  is not available. Text PDFs are unaffected.
- `PDF_NO_TEXT` now means no text even after OCR.
- `GET /health` adds `ocr`: `{enabled, available, version, languages, language}`,
  or `{available: false, reason}`.

## Corpus Ingestion

Corpus ingestion is admin-only and separate from professional or public query
uploads. Ingestion upload endpoints will use multipart/form-data for PDFs with
associated metadata.

Ingestion is asynchronous and persistent. Upload acceptance returns a job id and
initial status. Status endpoints report job progress, document id, chunk count,
and any failure message.

Successful admin ingestion updates both retrieval stores before the job is
marked complete: dense chunks are upserted into Chroma/vector storage and the
same trusted chunks are upserted into the BM25 lexical index using the frozen
`legalai-bm25-index-v1` / `legalai-legal-tokenizer-v1` configuration. BM25
persistence uses a temp-write, validate, atomic-replace pattern guarded by a
process-local lock. If BM25 maintenance fails after dense indexing, the job is
marked `FAILED` rather than falsely `COMPLETED`; the previous BM25 artifact is
left in place. Multi-process deployments may need a stronger shared file lock.

Ingestion is all-or-nothing: a job is `COMPLETED` only when the document is in
PostgreSQL, Chroma and BM25. A `FAILED` job leaves nothing behind, or sets
`needs_reconciliation` if cleanup could not finish. The full design is in
`docs/INGESTION_RELIABILITY.md`.

- `POST /ingest/upload` returns **413** (was 400) when the file is larger than
  `MAX_UPLOAD_SIZE_MB`. The file is read in 1 MB chunks and reading stops as
  soon as the limit is passed. Any request whose `Content-Length` exceeds the
  limit plus 1 MB is answered **413** `REQUEST_TOO_LARGE` before its body is read.
- `POST /ingest/upload` returns **409**
  `{"error": "This document has already been ingested.", "code": "DOCUMENT_ALREADY_INGESTED", "detail": {"document_id": <id>}}`
  when a document with the same file SHA-256 exists, before any write.
- `GET /ingest/status/{job_id}` keeps its fields. `error` is a sanitized
  message. Since step 14 an `error_code` can also be `OCR_LIMIT_EXCEEDED`
  (more than `OCR_MAX_PAGES_INGESTION`, default 200, or a timeout) or
  `OCR_UNAVAILABLE`. New optional fields: `error_code` (for example
  `LEXICAL_INDEX_FAILED`, `DUPLICATE_DOCUMENT`, `STALE_JOB`, and since step 9
  `ANALYTICS_FAILED`) and
  `needs_reconciliation` (boolean). Jobs stuck in a non-terminal state past
  `INGESTION_STALE_JOB_MINUTES` are reaped to `FAILED` / `STALE_JOB`.
- `GET /ingest/corpus/stats` reports `postgres_status`, `chroma_status` and
  `bm25_status` as `healthy`, `degraded` or `down`, from real checks of the
  configured collection (existence, dimension 1024, count against PostgreSQL
  chunks) and of the BM25 index. Optional detail fields: `chroma_detail`,
  `chroma_collection`, `chroma_record_count`, `bm25_detail`,
  `bm25_record_count`, `postgres_chunk_count`. Since step 9 it also returns
  `reconciliation_job_count` (integer) and `reconciliation_jobs` (the 20 most
  recent jobs with `needs_reconciliation`: `job_id`, `error_code`,
  `error_message`, `completed_at`).
- Since step 14 a completed ingestion records `documents.extraction_method`
  (`native`, `ocr`, `mixed`), `documents.ocr_pages` and
  `documents.ocr_mean_confidence` (migration `0009_document_extraction`; NULL
  for earlier documents). Chroma and BM25 metadata are unchanged.
- Since step 9 a completed admin ingestion also writes the document's
  `document_sections`, outcome columns and index metadata
  (`docs/INDEX_METADATA.md`) in the same all-or-nothing write.
- Query endpoints return **503** `RETRIEVAL_INDEX_UNAVAILABLE` if the
  configured collection is missing or has the wrong dimension. The query path
  never creates it.

Frozen ingestion states:

- `QUEUED`
- `EXTRACTING`
- `CHUNKING`
- `EMBEDDING`
- `INDEXING`
- `COMPLETED`
- `FAILED`

## Analytics

Analytics contracts define response rows for:

- offense frequency by section and year
- outcome distribution by section and court level
- section co-occurrence
- IPC to BNS mappings
- NCRB statistics

Data sources, production methods and reconciliation are described in
`docs/ANALYTICS_DATA.md`.

- **Section labels** in offence frequency, outcome distribution and
  co-occurrence are statute-qualified: `"<statute> <section>"`, for example
  `"IPC 302"` or `"BNS 103"`, as the frontend expects. Bare numbers would
  merge different provisions (IPC 302 and BNS 302). The `section` filter
  accepts a full label or a bare section number (all statutes).
- **Offence provisions only by default.** `offense-frequency`,
  `outcome-distribution` and `section-cooccurrence` count only offence
  provisions (`backend/app/services/provision_types.py`). Procedural (CrPC,
  BNSS), evidentiary, definitional/general (e.g. IPC 2, general exceptions)
  and liability-linking provisions (e.g. IPC 34, 149, 511) are left out.
  Query parameter `include_all_sections=true` (default `false`) returns
  every cited section.
- **`ipc-bns-map` rows** (step 19b, migration 0011; also `/analytics/ipc-bns`):
  `{ipc_section, ipc_description, bns_section, bns_description, change_type, source, source_page}`.
  - `source`: `CYTRAIN` (the NCRB/CYTRAIN correspondence table) or `NCRB_CII_2024_T1A4` (a correspondence printed in
    NCRB Crime in India 2024, Vol. I, Table 1A.4); `source_page` is the printed table page of an NCRB row, else `null`.
  - `change_type`: `DIRECT`, `SPLIT`, `MERGED`, `REPEALED`, `NO_DIRECT_EQUIVALENT`, or **`null`** when the source gives
    none (NCRB rows only; a CYTRAIN row always has one, enforced by a database check). It is never guessed.
  - Filters: `ipc_section`, `bns_section` (exact), `change_type` (a value above, or `NOT_SPECIFIED` for `null`),
    `source` (either source). An unknown value is `400 INVALID_ANALYTICS_FILTER`.
  - Every row is UNREVIEWED for legal review (`docs/analytics/NCRB_CORRECTION.md`).
- **`ncrb-stats` aggregate rows excluded by default.** State/UT/all-India
  total rows and subtotal or group-total crime heads are left out, so sums
  over the response do not double count. Query parameter
  `include_aggregates=true` (default `false`) returns them.
- **`ncrb-stats` row fields** (added in step 8): `bns_section` (string or
  `null`), `is_aggregate` (boolean), `aggregate_type` (`state_total`,
  `ut_total`, `all_india_total`, `subtotal_head`, `group_total`, or `null`
  for a base row). The same applies to `/analytics/ncrb`.
- **`ncrb-stats` `case_count`** is `null` when NCRB reports no count. It is
  never `0` for missing data.
- **`ncrb-stats` section labels and display label** (step 15b):
  - `ipc_section` and `bns_section` are the printed text ("305/306");
  - `ipc_section_labels` and `bns_section_labels` are the parsed statute-qualified lists (`["IPC 305", "IPC 306"]`),
    or `null` when nothing parses;
  - `offense_category` is the crime head exactly as printed;
  - `display_offense_category` is the label to show, which differs only for a documented printing error
    (`docs/analytics/NCRB_CORRECTION.md`).

  The `ipc_section` query parameter matches the label lists. It accepts "IPC 305", "BNS 108", or a bare "305",
  which means IPC. A value that does not parse returns `[]`. The same applies to `/analytics/ncrb`.
- **Empty data:** every endpoint returns `200 []`, never an error.

## Rate Limits And Capacity (step 13, SEC-001)

All limits are in-memory, per process (see `docs/SECURITY.md`).

- `POST /query/public` and `POST /query/public/pdf` share a per-client-IP budget:
  `PUBLIC_QUERY_LIMIT_PER_MINUTE` (default 5) and `PUBLIC_QUERY_LIMIT_PER_DAY`
  (default 100).
- `POST /query/professional` and `POST /query/professional/pdf` share a
  per-user budget: `PROFESSIONAL_QUERY_LIMIT_PER_MINUTE` (default 10) and
  `PROFESSIONAL_QUERY_LIMIT_PER_DAY` (default 300). Authentication is checked
  first, so an anonymous call gets 401 and is not counted.
- Over a limit, the route returns **429** with `Retry-After` (seconds) and
  `{"error": "... Please wait about N minutes and try again.", "code": "RATE_LIMITED", "detail": {"retry_after": N}}`.
  The request never reaches retrieval or the answer provider.
- At most `LLM_MAX_CONCURRENT_GENERATIONS` (default 4) answer generations run
  at once per process. A request waits up to `LLM_GENERATION_WAIT_SECONDS`
  (default 10) for a slot, then gets **503** with `Retry-After: 15` and
  `{"error": "Many people are asking questions right now. Please try again in a moment.", "code": "MODEL_BUSY", "detail": {"retry_after": 15}}`.
- Local model calls (query embedder, reranker, ingestion embedder, warm-up) run one at a time per process (step 18).
  A query waits up to `LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS` (default 30) for the models, then gets **503** with
  `Retry-After`: `MODELS_LOADING` (`Retry-After: 10`) while the startup warm-up is running, otherwise `MODEL_BUSY`
  (`Retry-After: 15`), same body shape as above.
- The client IP is the TCP peer. `X-Forwarded-For` is used only when the peer
  is listed in `TRUSTED_PROXIES` (IPs or CIDRs); then the right-most entry that
  is not itself a trusted proxy is the client.

## Error Format

Every error response (any status ≥ 400, from any route, middleware or the framework) has this body (step 16,
BE-003; `backend/app/core/errors.py`):

```json
{
  "error": "Some of the submitted information is missing or invalid.",
  "code": "VALIDATION_ERROR",
  "detail": {"fields": [{"field": "body.email", "message": "Field required", "type": "missing"}]}
}
```

| Field | Type | Meaning |
|---|---|---|
| `error` | string | A safe, human-readable message. It never contains a stack trace, a file path, a submitted value or the text of an unexpected exception. |
| `code` | string | The stable machine code, `UPPER_SNAKE_CASE`. Clients branch on `code`, never on `error`. |
| `detail` | object or `null` | Optional structured data, listed per code below. `null` when there is none. |

- Every response, success or error, carries an **`X-Request-ID`** header. An incoming `X-Request-ID` of 1–64
  characters from `A-Z a-z 0-9 . _ -` is reused; anything else is replaced by a generated one. `legalai.*` log
  lines written while the request is handled end in `[request_id=...]`.
- Headers that belong to an error are kept: `Retry-After` on rate limits, `MODEL_BUSY` and `MODELS_LOADING`, `Allow` on 405.
- A **500** is always `INTERNAL_ERROR` with a generic `error` and `detail: {"request_id": ...}`. The exception is
  logged with the same request ID, never returned. The 500 is produced inside CORS, so a browser can read it.
- Request validation is `VALIDATION_ERROR` with the failing fields. The submitted values are not echoed.
- `backend/scripts/tests/test_error_contract.py` calls every registered route in every way it can fail and checks
  this shape. It also rejects an `HTTPException` without a `{code, message}` dict, and a `JSONResponse` built
  outside `core/errors.py`.

### Error-code catalogue

`detail` is `null` unless a field is listed.

**Framework and cross-cutting**

| Code | Status | Meaning | `detail` |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body, query or form fields are missing or invalid. | `fields`: list of `{field, message, type}` (`field` like `body.email`) |
| `NOT_FOUND` | 404 | No such path. | |
| `METHOD_NOT_ALLOWED` | 405 | The path exists but not for this method (`Allow` header lists the methods). | |
| `INTERNAL_ERROR` | 500 | Unexpected server error. | `request_id` |
| `REQUEST_TOO_LARGE` | 413 | `Content-Length` over the upload limit plus 1 MB; rejected before the body is read. | |
| `CSRF_ORIGIN_REJECTED` | 403 | Cookie-authenticated write from an origin that is not allowed. | |
| `BAD_REQUEST`, `CONFLICT`, `UNSUPPORTED_MEDIA_TYPE`, `SERVICE_UNAVAILABLE`, `HTTP_<status>` | as named | Fallback for an `HTTPException` raised without a code (e.g. by a library). No route raises these. | |

**Authentication and access**

| Code | Status | Meaning | `detail` |
|---|---|---|---|
| `NOT_AUTHENTICATED` | 401 | No session cookie or bearer token. | |
| `SESSION_EXPIRED` | 401 | The session token has expired. | |
| `INVALID_SESSION` | 401 | Invalid token, token without a subject, or a missing or deactivated account (one body for all, SEC-004). | |
| `FORBIDDEN` | 403 | Signed in, but the role may not use this route. The role is not named. | |
| `INVALID_CREDENTIALS` | 401 | `POST /auth/login`: wrong email or password, or a deactivated account. | |
| `LOGIN_THROTTLED` | 429 | Too many failed sign-ins for this email or IP; `Retry-After` set. | `retry_after` (seconds) |
| `WEAK_PASSWORD` | 422 | Registration password blank or padded with whitespace. | |
| `INVALID_EMAIL` | 422 | Registration email is not a valid address. | |
| `EMAIL_DELIVERY_FAILED` | 503 | The verification email could not be sent. | |
| `INVALID_OTP` | 422 / 400 | 422: the code is not all digits. 400: the code is wrong. | |
| `INVALID_OR_EXPIRED_OTP` | 400 | No active code for this email (an unknown email gets the same answer, SEC-003), or it expired. | |
| `OTP_ATTEMPTS_EXCEEDED` | 429 | Too many attempts for this code; request a new one (no `Retry-After`). | |

**Lawyer verification**

| Code | Status | Meaning |
|---|---|---|
| `ALREADY_VERIFIED` | 409 | The account is already a verified lawyer. |
| `EMAIL_VERIFICATION_REQUIRED` | 403 | Verify the email before applying. |
| `APPLICATION_ALREADY_PENDING` | 409 | An application is already pending. |
| `INVALID_PROOF_TYPE` | 400 | Proof is not a PDF, PNG or JPEG. |
| `INVALID_PROOF_HEADER` | 400 | Proof file content does not match its declared type. |
| `PROOF_TOO_LARGE` | 413 | Proof file over the upload limit. |
| `APPLICATION_NOT_FOUND` | 404 | No such application. |
| `APPLICATION_ALREADY_VERIFIED` | 409 | Approve on an application that is already verified. |
| `APPLICATION_NOT_APPROVABLE`, `APPLICATION_NOT_REJECTABLE`, `APPLICATION_NOT_REVIEWABLE` | 409 | The application is not in a reviewable state. |
| `REJECTION_REASON_REQUIRED`, `RESUBMISSION_REASON_REQUIRED` | 422 | The review action needs a reason. |

**Uploads: corpus ingestion (`/ingest/*`) and query PDFs (`/query/*/pdf`)**

| Code | Status | Meaning | `detail` |
|---|---|---|---|
| `INVALID_PDF_EXTENSION` | 400 | The file name does not end in `.pdf`. | |
| `INVALID_PDF_MIME_TYPE` | 400 | The declared content type is not a PDF. | |
| `EMPTY_UPLOAD` | 400 | The file is empty. | |
| `INVALID_PDF_HEADER` | 400 | No `%PDF-` signature. | |
| `PDF_TOO_LARGE` | 413 | Over `MAX_UPLOAD_SIZE_MB`. | `limit_mb` (ingestion only) |
| `DOCUMENT_ALREADY_INGESTED` | 409 | A document with the same SHA-256 is already in the corpus. | `document_id` |
| `INGESTION_JOB_NOT_FOUND` | 404 | `GET /ingest/status/{job_id}`: no such job. | `job_id` |
| `PDF_PARSE_FAILED` | 422 | The PDF could not be read. | |
| `PDF_NO_TEXT` | 422 | The PDF has no readable text. | |
| `PDF_CHUNKING_FAILED` | 422 | The text could not be split into sections. | |
| `OCR_LIMIT_EXCEEDED` | 422 | A scanned PDF over the OCR page limit. | |
| `OCR_UNAVAILABLE` | 503 | A scanned PDF, and Tesseract is not available. | |
| `PDF_CONTEXT_TOO_LARGE` | 413 | The document's extracted context is too large for one answer. | |
| `LOCAL_DOCUMENT_ANALYSIS_FAILED` | 500 | The local document map could not be built. | |

**Queries (`/query/*`)**

| Code | Status | Meaning | `detail` |
|---|---|---|---|
| `RATE_LIMITED` | 429 | Per-IP (public) or per-user (professional) query limit; `Retry-After` set. | `retry_after` (seconds) |
| `MODEL_BUSY` | 503 | All answer-generation slots busy, or the local models stayed busy past `LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS`; `Retry-After: 15`. | `retry_after` |
| `MODELS_LOADING` | 503 | The local models are still warming up at startup and were not free in time; `Retry-After: 10` (step 18). | `retry_after` |
| `INVALID_QUERY_REQUEST` | 422 | The question could not be processed. | |
| `QUERY_PIPELINE_UNAVAILABLE` | 503 | The query pipeline failed unexpectedly. | |
| `RETRIEVAL_UNAVAILABLE`, `RETRIEVAL_INDEX_UNAVAILABLE` | 503 | The evidence index is unavailable. | |
| `INSUFFICIENT_RETRIEVED_AUTHORITY` | 424 | Not enough retrieved authority for a grounded answer. | |
| `MODEL_UNAVAILABLE` | 503 | No answer model is configured or reachable. | |
| `MODEL_PROVIDER_UNAVAILABLE`, `MODEL_PROVIDER_ERROR`, `MODEL_PROVIDER_TIMEOUT`, `MODEL_PROVIDER_AUTH_ERROR` | 503 | The answer provider failed. | |
| `MODEL_PROVIDER_QUOTA_EXCEEDED` | 429 | The provider's own usage limit was reached. | |
| `MODEL_PROVIDER_REQUEST_TOO_LARGE` | 413 | The request is too large for the provider. | |
| `MODEL_OUTPUT_VALIDATION_FAILED`, `MODEL_OUTPUT_MISSING_CITATIONS`, `MODEL_OUTPUT_TRUNCATED`, `PUBLIC_SCHEMA_MISMATCH`, `PROFESSIONAL_SCHEMA_MISMATCH`, `ANSWER_GENERATION_FAILED` | 502 | The provider's answer was invalid or incomplete. | |

**Analytics and history**

| Code | Status | Meaning |
|---|---|---|
| `INVALID_ANALYTICS_FILTER` | 400 | An analytics filter value is invalid (`error` says which). |
| `INVALID_HISTORY_REQUEST` | 400 | The history request is invalid. |

## Contract-First Development

Frontend developers may build against mock responses matching the schemas in
`backend/app/models/` before live API routes exist. Backend implementation must
preserve these contracts unless a later explicit contract revision is approved.
