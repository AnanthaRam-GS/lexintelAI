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

## Professional Query

Professional users may submit either text or a temporary PDF, one input form at
a time. PDF upload endpoints will use multipart/form-data rather than embedding
uploaded files in JSON schemas.

`POST /query/professional` accepts authenticated lawyer/admin JSON text
requests:

```json
{ "text": "Research anticipatory bail under BNSS", "session_id": "optional-session-id" }
```

PDF query support remains a separate future multipart/form-data endpoint; it is
not accepted by this JSON text route.

Professional query uploads are temporary analysis inputs. They are not
automatically ingested into the global corpus.

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

PDF query support remains a separate future multipart/form-data endpoint; it is
not accepted by this JSON text route.

Public query uploads are temporary analysis inputs and are not automatically
ingested into the global corpus. Session-local follow-up conversation may be
managed by the frontend.

The public response contains a plain-language explanation, cited statutory
sections, and public-facing sources.

## Corpus Ingestion

Corpus ingestion is admin-only and separate from professional or public query
uploads. Ingestion upload endpoints will use multipart/form-data for PDFs with
associated metadata.

Ingestion is asynchronous and persistent. Upload acceptance returns a job id and
initial status. Status endpoints report job progress, document id, chunk count,
and any failure message.

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
