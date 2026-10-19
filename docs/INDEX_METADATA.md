# Index Metadata (`index_metadata_v1`)

Plan §2.4 asks for document type and cited sections in the retrieval
indexes. PostgreSQL is canonical: these fields are derived from it and copied
into the metadata of every chunk in Chroma (`legalai_trusted_judgments_v1`)
and BM25 (`records[].metadata`). Retrieval does not use them yet; ranking,
query enrichment, filtering and reranking are unchanged.

Code: `backend/app/services/index_metadata.py`.

## Fields

| Field | Level | Type | Source |
|---|---|---|---|
| `doc_type` | document | string | `documents.doc_type` |
| `cited_sections` | document | list of strings | `document_sections` rows of the document, as labels such as `"IPC 302"` |
| `offence_sections` | document | list of strings | the subset of `cited_sections` that `services/provision_types.py` classifies as `offence` |
| `chunk_sections` | chunk | list of strings | sections cited in this chunk: the `document_sections` extractor (`judgment_sections.extract_section_mentions`) applied to the chunk's PostgreSQL text |
| `cited_section_count`, `offence_section_count`, `chunk_section_count` | as above | integer | length of each list |
| `index_metadata_version` | chunk | string | `index_metadata_v1` |
| `effective_legal_regime` | document | string | existing field; see below |
| `effective_offence_family` | document | string | existing field; see below |

Labels use the analytics contract, `"<statute> <section>"`, and are sorted by
statute, then section number, then letter suffix (`IPC 34`, `IPC 120`,
`IPC 120B`, `IPC 302`).

## Representation

Chroma 1.5.9 accepts list metadata: a non-empty list of one scalar type. It
is stored one element per row in `embedding_metadata_array`, and is
filterable with `$contains`, which matches a whole element exactly:

```python
collection.get(where={"offence_sections": {"$contains": "IPC 302"}})
collection.query(..., where={"$and": [{"chunk_sections": {"$contains": "IPC 302"}}, {"doc_type": "judgment"}]})
```

`"IPC 3"` does not match `"IPC 302"`, so no delimited-string workaround is
needed. Chroma rejects empty lists. An empty list is therefore an **absent
key** in both indexes, and the matching count field is `0`. Every chunk
always carries `doc_type`, the three counts and `index_metadata_version`.
BM25 stores the same values as JSON, with the same absent-key rule, so both
indexes hold identical metadata.

## `effective_legal_regime` and `effective_offence_family`

- **Curated corpus (70 documents):** both fields come from the reviewed
  acquisition manifest (`process_judgment_corpus.py`), which PostgreSQL does
  not hold. They are kept as they are. Enrichment never changes an existing
  value, because retrieval filters on these fields.
- **Admin uploads:** `effective_legal_regime` is derived from the cited
  statutes' regimes (`judgment_sections.regime_for`):
  - IPC/CrPC only gives `ipc_crpc`;
  - BNS/BNSS only gives `bns_bnss`;
  - both give `mixed_or_transition`;
  - neither gives `unknown`.

  Special Acts and the Evidence Act are regime-neutral. Enrichment fills
  the field only where it is absent.
- `effective_offence_family` **is not derivable.** No code maps sections to
  the corpus vocabulary (`homicide`, `cheating_and_fraud`, ...). The query
  side's family rules match query text and use a different vocabulary. Admin
  uploads leave it empty. This is the remaining part of N2.

For reference, on the curated corpus the derived regime agrees with the
manifest value for 66 of 70 documents. The other 4 are: 2 `unknown` derived
as `ipc_crpc`, 1 `bns_bnss` derived as `mixed_or_transition`, and 1
`ipc_crpc` derived as `unknown`. Nothing was changed.

## Writing and checking

| Path | What it does |
|---|---|
| `backend/scripts/enrich_index_metadata.py` | Adds the fields to existing chunks, from PostgreSQL. Chroma `collection.update(ids, metadatas)` merges keys and leaves embeddings and documents alone. BM25 changes only `records[].metadata`, and refuses to write if anything else (statistics, term frequencies, lengths, index metadata, fingerprint) would change. Dry runs read Chroma through read-only SQLite. `--confirm-dev` is required for the repository's stores. Idempotent. |
| Admin ingestion (`services/ingestion.py`) | Derives the fields from the new document's chunks before any index write, and writes `document_sections` and outcomes in the same PostgreSQL transaction (`docs/INGESTION_RELIABILITY.md`). |
| `backend/scripts/verify_store_consistency.py` | Checks every chunk's fields in both indexes against what PostgreSQL derives; `effective_legal_regime` must be present and valid, and must equal the derived value for admin uploads; both `effective_*` fields must be the same across a document's chunks. Any mismatch exits 1. |

A full index rebuild from the curated chunk files (`build_vector_index.py`,
`build_lexical_index.py`) does not carry these fields. Run
`enrich_index_metadata.py` after a rebuild; the verifier reports the gap
until then.

## Dev results (2026-10-19)

- 1,356 of 1,356 chunks in Chroma and in BM25 carry `doc_type` (all
  `judgment`), the three counts and the version.
- `cited_sections` is present on 1,356 chunks, `offence_sections` on 1,355
  (one document cites no offence provision), and `chunk_sections` on 710.
  The other 646 chunks cite no section themselves.
- Embedding vectors, chunk texts, the BM25 statistics and the fingerprint
  (`af2b9ee3…`) are identical before and after. The top-10 hybrid + rerank
  results for 5 fixed queries are identical in IDs, order and scores.
- A second run makes 0 changes. The verifier reports CONSISTENT.
