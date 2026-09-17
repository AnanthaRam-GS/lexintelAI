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

These are response contracts only. SQL queries, storage access, and dashboard
implementation belong to later phases.

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
