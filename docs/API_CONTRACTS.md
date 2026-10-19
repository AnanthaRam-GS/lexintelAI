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

`POST /auth/register` returns the created public user and sends a six-digit
email verification OTP. Role injection from the client is ignored. OTPs are
hashed before persistence, expire after the configured window, are single-use,
and are attempt-limited. `POST /auth/verify-email` accepts `{ "email": "...",
"otp": "123456" }`; `POST /auth/resend-verification` accepts `{ "email": "..."
}` and supersedes previous active OTPs after the configured cooldown.

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
| `relevance_score` | `1 / (1 + e^-reranker_score)` (logistic sigmoid, monotonic, 0-1), or `null` when there is no reranker score. Never a constant. |
| `excerpt` | a verbatim span of the chunk text, at most `PRECEDENT_EXCERPT_MAX_CHARS` (default 400) characters, centred on the passage most relevant to the retrieval query; `...` marks a cut |

The model's `retrieved_authorities` are not turned into precedents.

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

Text queries and question-focused PDF queries have no document map, so
`parties_and_roles`, `chronology` and `evidence_identified` are empty there:
nothing is inferred from the query text. No field copies another.

## Public Query

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

- `POST /ingest/upload` returns **409**
  `{"detail": {"code": "DOCUMENT_ALREADY_INGESTED", "message": "...", "document_id": <id>}}`
  when a document with the same file SHA-256 exists, before any write.
- `GET /ingest/status/{job_id}` keeps its fields. `error` is a sanitized
  message. New optional fields: `error_code` (for example
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
- **Empty data:** every endpoint returns `200 []`, never an error.

## Error Format

```json
{
  "error": "...",
  "code": "...",
  "detail": "..."
}
```

## Contract-First Development

Frontend developers may build against mock responses matching the schemas in
`backend/app/models/` before live API routes exist. Backend implementation must
preserve these contracts unless a later explicit contract revision is approved.
