# Embedding And Vector Index Foundation

This phase validates dense embedding/index infrastructure over trusted 0.5A chunks only. It does not implement BM25, hybrid retrieval, reranking, RAG generation, Gemini, Ollama, or InLegalBERT.

## Scope

- documents: 70
- chunks: 1356
- build mode: `mock_validation_only`
- model: `deterministic-mock`
- BGE-M3 locally available: False

## Configuration

- `EMBEDDING_MODEL=BAAI/bge-m3`
- `EMBEDDING_DEVICE=cpu`
- `EMBEDDING_BATCH_SIZE=16`
- `EMBEDDING_NORMALIZE=true`
- `CHROMA_COLLECTION_NAME=legalai_trusted_judgments_v1`
- `CHROMA_PERSIST_DIR=./chroma_store`

## Indexing

Chunks are indexed with deterministic chunk IDs and fingerprints based on chunk ID, chunk text hash, embedding model/config, and index version. Re-running unchanged inputs skips unchanged vectors.

Chroma metadata nulls are represented reversibly: page/date absence uses sentinel metadata values plus flags such as `has_page_provenance`; source text remains the stored document content.

Score semantics: the offline JSON validation store uses cosine similarity where larger is better. Chroma distance semantics must be documented when real Chroma is enabled.

## CLI

```bash
python3 backend/scripts/build_vector_index.py --dry-run
python3 backend/scripts/build_vector_index.py --rebuild
python3 backend/scripts/build_vector_index.py --stats
```
