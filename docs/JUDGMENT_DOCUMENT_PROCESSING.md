# Judgment Document Processing

This phase processes only trusted human-approved judgments: accepted balanced development records plus accepted bulk-audit records. Rejected, needs-review, and unaudited bulk records are excluded.

No embeddings, vector stores, BM25 indexes, reranking, RAG generation, LLM calls, or acquisition are produced in this step.

## Pipeline

1. Build `trusted_judgment_processing_manifest.json` from human review manifests.
2. Load local PDF, HTML/text, or fallback text sources.
3. Normalize Unicode, whitespace, soft hyphens, control characters, and safe line wraps.
4. Segment text into paragraph/block records with heading context and page provenance where available.
5. Chunk contiguous paragraph ranges with configurable estimated-token target, max, and overlap.
6. Write ignored normalized/chunk JSON outputs and tracked summary manifests.

## Defaults

- target estimated tokens: 650
- max estimated tokens: 900
- overlap estimated tokens: 100
- token counts are lightweight estimates, not model tokenizer counts.

## Provenance

PDF chunks include 1-based page ranges when native text extraction provides page identity. Non-PDF and fallback chunks use null page ranges and retain `text_source_type` plus paragraph ranges.

Chunk IDs use `<provider>:<source_document_id>:chunk:<zero-padded-index>` and are deterministic for unchanged input/version.

## CLI

```bash
python3 backend/scripts/process_judgment_corpus.py --dry-run
python3 backend/scripts/process_judgment_corpus.py --force
python3 backend/scripts/process_judgment_corpus.py --document-id indian_kanoon:1291057
```

## Current Run Summary

- input documents: 70
- processed/skipped: 70
- failed: 0
- paragraphs: 4195
- chunks: 1356

## Known Limitations

- No OCR; PDFs without native text fail or warn.
- Fallback JSON wrapper records can only use locally retained fallback/evidence text.
- Header/footer removal is conservative and requires repeated structural evidence.
- Train/test splits and retrieval evaluation are intentionally not defined here.
