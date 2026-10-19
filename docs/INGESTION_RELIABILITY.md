# Ingestion Reliability

This document covers how admin corpus ingestion (`POST /ingest/upload`) keeps
PostgreSQL, Chroma and BM25 consistent. PostgreSQL is canonical; Chroma
(`CHROMA_COLLECTION_NAME`, default `legalai_trusted_judgments_v1`) and BM25 are
derived indexes. `backend/scripts/verify_store_consistency.py` is the
acceptance check: it exits 0 only when the three stores agree.

Implementation: `backend/app/services/ingestion.py`.

## Outcome guarantee (BE-001)

Every ingestion job ends in exactly one of two states:

| Job status | Stores |
|---|---|
| `COMPLETED` | The document and all its chunks are in PostgreSQL, Chroma and BM25. |
| `FAILED` | Nothing for the document is left in any store. If cleanup itself failed, `needs_reconciliation=true` is set and the message says so. |

A job never reports success unless the PostgreSQL commit, which happens last,
succeeded.

## Ordering: PostgreSQL commits last

1. **Read-only stages** (`EXTRACTING`, `CHUNKING`, `EMBEDDING`) write nothing:
   parse the PDF, chunk it, analyse it, embed it. Analysis (step 9) runs the
   `document_sections` extractor (`produce_analytics_data.desired_sections`)
   on the chunks and adds the index metadata fields
   (`docs/INDEX_METADATA.md`) and the derived `effective_legal_regime` to
   every chunk, so the indexes receive them with the first write.
2. **Write phase** (`INDEXING`), under a process-wide lock:
   1. Re-check that no document with this checksum exists.
   2. Upsert the chunks into Chroma.
   3. Upsert them into BM25 (temp-write, validate, atomic replace).
   4. In **one PostgreSQL transaction**, insert the document and its chunks,
      run the analytics producer for the document
      (`produce_analytics_data.produce_document`: `document_sections`,
      outcome columns and evidence, court level), and set the job to
      `COMPLETED`. The producer is the same code the batch producer runs, so
      the `document_sections` rows equal the sections in the index metadata.
3. **On any failure in the write phase:**
   1. Roll back the PostgreSQL transaction.
   2. Run compensating cleanup: remove the document's BM25 records (statistics
      and metadata are recomputed) and its Chroma vectors, both by
      `source_document_key`.
   3. Mark the job `FAILED`.

   If PostgreSQL already holds a committed document with that key, cleanup is
   skipped, because the index entries belong to that document. This happens
   when a concurrent upload of the same file won the race.

### Why this order

- PostgreSQL is canonical. Committing it last means no reader ever sees a
  PostgreSQL document whose chunks are missing from an index.
- Committing the job status in the same transaction as the document removes
  the "document committed but job not updated" state.
- The indexes are written first, and their writes can be undone by key, so
  every failure has a defined cleanup.

**Trade-off.** During the write phase, which takes seconds, the indexes hold
chunks that PostgreSQL does not have yet. A query in that window could
retrieve them. If the process dies in that window, the stale-job reaper
removes them (below).

The write-phase lock is in-process (`threading.Lock`). A deployment with
several backend processes needs a shared lock, for example a PostgreSQL
advisory lock. This matches the existing BM25 lock note in `API_CONTRACTS.md`.

## Document identity and metadata parity

| Property | Value |
|---|---|
| `checksum` | SHA-256 of the uploaded file (unique in PostgreSQL, migration 0005) |
| `source_document_key` | `admin:<sha256>` |
| Chunk IDs (`chunks.chroma_id`, Chroma ID, BM25 ID) | `admin:<sha256>:chunk:<nnnn>`, the corpus format `<document_id>:chunk:<nnnn>` |

Chroma and BM25 metadata are built with the same `metadata_for_chroma`
function and the same `index_fingerprint` as the curated corpus. Each admin
chunk carries:
- document ID, provider (`admin_upload`) and source document ID;
- source URL and case title;
- court (`{"court_level": ...}` from the upload form);
- decision year (from the form) and decision date (empty; see below);
- page provenance: a missing page is stored as `-1` with
  `has_page_provenance=false`;
- paragraph provenance;
- chunk index, text source type, raw SHA-256, and normalizer and chunker
  versions.

Derived during ingestion (step 9, `docs/INDEX_METADATA.md`):
- `doc_type`, `cited_sections`, `offence_sections`, `chunk_sections`, their
  counts and `index_metadata_version`;
- `effective_legal_regime`, from the cited statutes (`ipc_crpc`, `bns_bnss`,
  `mixed_or_transition`, `unknown`).

Not supplied by the upload and never inferred:
- court name;
- decision date (the upload form has no field for it);
- offence family: no code maps sections to the corpus's offence-family
  vocabulary, so `effective_offence_family` stays empty for admin uploads.

PostgreSQL chunk rows store the same text and provenance values as the
indexes, so the consistency verifier can compare them directly.

## Duplicates (DATA-003)

`POST /ingest/upload` computes the file's SHA-256. If a document with that
checksum (or key) exists, it returns **409** with:

```json
{"detail": {"code": "DOCUMENT_ALREADY_INGESTED", "message": "This document has already been ingested.", "document_id": 123}}
```

The check happens before the upload is saved, before any job is created, and
before any store write. The write phase re-checks under its lock (job error
code `DUPLICATE_DOCUMENT`). The unique index on `documents.checksum` is the
final guard: a commit-time `IntegrityError` becomes `DUPLICATE_DOCUMENT`, and
the winner's index entries are kept. A raw `IntegrityError` is never surfaced.

## Stale jobs (BE-005)

`reap_stale_jobs()` marks jobs `FAILED` (code `STALE_JOB`) when they are still
`QUEUED`, `EXTRACTING`, `CHUNKING`, `EMBEDDING` or `INDEXING` after
`INGESTION_STALE_JOB_MINUTES` (default 30), measured from `started_at`, or
`created_at` if the job never started.

It runs:
- at backend startup (FastAPI lifespan);
- on every `GET /ingest/status/{job_id}`.

Only `INDEXING` jobs can have written index entries. For those, the reaper
recomputes `admin:<sha256>` from the stored upload
(`data/raw/uploads/<job_id>_<name>`) and runs the same compensating cleanup.
If the upload is missing, or cleanup fails, the job is flagged
`needs_reconciliation`.

The reaper takes the write-phase lock and re-reads each job first, so it never
fails a job that finished while it waited. A job reaped while it was still
embedding stops at the start of its write phase, before writing anything.

## Errors (SEC-007)

`ingestion_jobs.error_message` holds only a sanitized message, and
`ingestion_jobs.error_code` holds the internal code (migration 0006). Raw
exception text goes to the server log (`legalai.ingestion` logger) with no
document text and no SQL parameters.

| `error_code` | Message |
|---|---|
| `PARSE_FAILED` | The PDF could not be read. |
| `PDF_NO_TEXT` | The PDF has no extractable text. Scanned PDFs are not supported. |
| `CHUNKING_FAILED` | The document text could not be split into chunks. |
| `EMBEDDING_FAILED` | Embeddings could not be generated for this document. |
| `DUPLICATE_DOCUMENT` | This document has already been ingested. |
| `VECTOR_INDEX_FAILED` | The vector index could not be updated. |
| `LEXICAL_INDEX_FAILED` | The keyword index could not be updated. |
| `DATABASE_WRITE_FAILED` | The document could not be saved to the database. |
| `ANALYTICS_FAILED` | Cited sections and outcomes could not be derived for this document. |
| `STALE_JOB` | Ingestion did not finish within the time limit and was stopped. |
| `INGESTION_FAILED` | Ingestion failed unexpectedly. |

When cleanup did not complete, the message gains the suffix
` Cleanup did not complete; the stores need reconciliation.` and
`needs_reconciliation` is `true`. Run `verify_store_consistency.py` and the
reconciliation inventory (`docs/reconciliation/`) for that document.

## Store status (BE-002)

`GET /ingest/corpus/stats` (admin only) reports real store health. Health
values follow the frontend contract: `healthy`, `degraded` or `down`.

| Field | Meaning |
|---|---|
| `postgres_status` | `healthy` if PostgreSQL answers, else `down` |
| `chroma_status` | `healthy` if the configured collection exists, has dimension 1024, and its count equals the PostgreSQL chunk count; `degraded` on a count mismatch; `down` if the store or collection is missing or the dimension is wrong |
| `chroma_detail`, `chroma_collection`, `chroma_record_count` | Reason, collection name, entry count |
| `bm25_status`, `bm25_detail`, `bm25_record_count` | Same rules for the BM25 index (also `degraded` if its metadata disagrees with its records) |
| `postgres_chunk_count` | Rows in `chunks` |
| `reconciliation_job_count`, `reconciliation_jobs` | Jobs with `needs_reconciliation`: the total, and the 20 most recent (`job_id`, `error_code`, `error_message`, `completed_at`) |

The admin status page (`/admin`) shows each store's health with its reason,
the Chroma count next to the PostgreSQL chunk count, the BM25 record count,
and the jobs that need reconciliation. The ingestion page shows a failed
job's sanitized message with its `error_code`.

The check never creates a store or a collection. `/health` stays a cheap,
public database check.

## Read paths never create the collection

`ChromaVectorStore(..., create_if_missing=False, expected_dimension=1024)` is
used by the query path (`retrieve_legal_evidence.make_service`) and by the
status check. It raises `VectorStoreUnavailable` if `chroma.sqlite3` is
missing (without creating it), if the collection is missing (`get_collection`,
never `get_or_create_collection`), or if the dimension differs.

The query path opens the store before loading the BGE models. The query
endpoints map the error to **503**
`{"code": "RETRIEVAL_INDEX_UNAVAILABLE", "message": "The legal evidence index is temporarily unavailable."}`.

Only ingestion (`trusted_vector_store`) and the index-build scripts may
create the collection.
