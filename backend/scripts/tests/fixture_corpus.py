"""The synthetic trusted-judgment corpus for tests and the end-to-end runs (no real judgments).

``fixtures/corpus/synthetic_judgments.json`` holds six invented judgments, three passages each. ``fixture_chunks()``
turns them into rows in the legal chunker's output schema (the same fields as ``data/processed/judgment_chunks``),
one chunk per passage, so the retrieval, brief and index code can run without the gitignored real corpus.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURE_CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "corpus" / "synthetic_judgments.json"
PROVIDER = "synthetic_fixture"


def document_id(key: str) -> str:
    return f"{PROVIDER}:{key}"


@lru_cache(maxsize=1)
def fixture_documents() -> tuple[dict[str, Any], ...]:
    payload = json.loads(FIXTURE_CORPUS_PATH.read_text(encoding="utf-8"))
    documents = []
    for source in payload["documents"]:
        text = "\n\n".join(source["passages"])
        documents.append({
            **source,
            "document_id": document_id(source["key"]),
            "source_url": f"https://example.invalid/legalai-synthetic/{source['key']}",
            "decision_year": int(source["decision_date"][:4]),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return tuple(documents)


def fixture_chunks() -> list[dict[str, Any]]:
    chunks = []
    for document in fixture_documents():
        for index, passage in enumerate(document["passages"]):
            chunks.append({
                "chunk_id": f"{document['document_id']}:chunk:{index:04d}",
                "document_id": document["document_id"],
                "provider": PROVIDER,
                "source_document_id": document["key"],
                "source_url": document["source_url"],
                "case_title": document["case_title"],
                "court": dict(document["court"]),
                "decision_date": document["decision_date"],
                "decision_year": document["decision_year"],
                "effective_offence_family": document["offence_family"],
                "effective_legal_regime": document["legal_regime"],
                "chunk_index": index,
                "paragraph_start": index,
                "paragraph_end": index,
                "page_start": 1,
                "page_end": 1,
                "heading_path": [],
                "text_source_type": "pdf_native",
                "raw_sha256": document["sha256"],
                "chunk_text": passage,
                "estimated_token_count": max(1, len(passage) // 4),
                "normalizer_version": "legalai-judgment-normalizer-v1",
                "chunker_version": "legalai-legal-chunker-v1",
            })
    return chunks


def fixture_document_ids() -> tuple[str, ...]:
    return tuple(document["document_id"] for document in fixture_documents())
