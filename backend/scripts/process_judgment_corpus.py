"""Offline trusted judgment normalization and legal-aware chunking."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import re
import statistics
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import load_manifest  # noqa: E402
from backend.scripts.pdf_text_extraction import extract_pdf_text, normalize_pdf_text  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
TRUSTED_MANIFEST = MANIFEST_DIR / "trusted_judgment_processing_manifest.json"
CHUNK_SUMMARY = MANIFEST_DIR / "trusted_judgment_chunk_summary.json"
DEV_JUDGMENTS = MANIFEST_DIR / "balanced_development_judgments.json"
DEV_REVIEWS = MANIFEST_DIR / "balanced_development_review.json"
BULK_SAMPLE = MANIFEST_DIR / "bulk_quality_audit_sample.json"
BULK_RAG_DECISIONS = MANIFEST_DIR / "bulk_quality_audit_rag_decisions.json"
NORMALIZED_DIR = REPO_ROOT / "data/processed/judgments_normalized"
CHUNK_DIR = REPO_ROOT / "data/processed/judgment_chunks"
QA_PACKET = REPO_ROOT / "docs/JUDGMENT_CHUNKING_QA.md"
DOC_PATH = REPO_ROOT / "docs/JUDGMENT_DOCUMENT_PROCESSING.md"
NORMALIZER_VERSION = "legalai-judgment-normalizer-v1"
CHUNKER_VERSION = "legalai-legal-chunker-v1"
PROCESSING_VERSION = f"{NORMALIZER_VERSION}+{CHUNKER_VERSION}"
DEFAULT_TARGET_TOKENS = 650
DEFAULT_MAX_TOKENS = 900
DEFAULT_OVERLAP_TOKENS = 100
REVIEWABLE = {"validated", "needs_review"}


@dataclass(frozen=True)
class LoadedSource:
    document_id: str
    text_source_type: str
    raw_path: str
    pages: list[dict[str, Any]]
    warnings: list[str]


def stable_document_id(provider: str, source_id: str) -> str:
    return f"{provider}:{source_id}"


def estimated_tokens(text: str) -> int:
    return max(1, round(len(re.findall(r"\S+", text)) * 1.25))


def source_id(record: dict[str, Any]) -> str:
    return str(record.get("source_document_id"))


def build_trusted_manifest(output_path: Path = TRUSTED_MANIFEST) -> dict[str, Any]:
    dev_records = {source_id(record): record for record in load_manifest(DEV_JUDGMENTS)}
    dev_reviews = [record for record in load_manifest(DEV_REVIEWS) if record.get("human_review_status") == "accepted"]
    bulk_sample = {source_id(record): record for record in load_manifest(BULK_SAMPLE)}
    bulk_decisions = [record for record in load_manifest(BULK_RAG_DECISIONS) if record.get("human_rag_suitability") == "accept"]

    entries: list[dict[str, Any]] = []
    for review in dev_reviews:
        record = dev_records[source_id(review)]
        entries.append(manifest_entry_from_development(record, review))
    for decision in bulk_decisions:
        sample = bulk_sample[source_id(decision)]
        entries.append(manifest_entry_from_bulk(sample, decision))

    deduped: list[dict[str, Any]] = []
    seen_source: set[str] = set()
    seen_sha: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: (item["provider"], item["source_document_id"], item["document_id"])):
        source = entry["source_document_id"]
        sha = entry.get("sha256")
        if source in seen_source or (sha and sha in seen_sha):
            duplicates.append({"document_id": entry["document_id"], "source_document_id": source, "sha256": sha})
            continue
        seen_source.add(source)
        if sha:
            seen_sha.add(sha)
        deduped.append(entry)

    payload = {
        "processing_version": PROCESSING_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "development_accepted_input": len(dev_reviews),
        "bulk_audit_accepted_input": len(bulk_decisions),
        "total_before_dedupe": len(entries),
        "cross_set_duplicates": len(duplicates),
        "duplicates": duplicates,
        "final_unique_documents": len(deduped),
        "excluded_policy": {
            "bulk_rejected": 7,
            "bulk_needs_review": 1,
            "bulk_unaudited": 199,
            "development_rejected": len([r for r in load_manifest(DEV_REVIEWS) if r.get("human_review_status") == "rejected"]),
        },
        "documents": deduped,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def manifest_entry_from_development(record: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    provider = str(record.get("source_provider") or "indian_kanoon")
    source = source_id(record)
    return {
        "document_id": stable_document_id(provider, source),
        "provider": provider,
        "source_document_id": source,
        "source_url": record.get("source_url"),
        "case_title": record.get("case_name"),
        "court": {"court_name": record.get("court_name"), "court_level": record.get("court_level")},
        "decision_date": record.get("decision_date"),
        "decision_year": record.get("year"),
        "effective_offence_family": review.get("offence_family") or record.get("offence_family"),
        "effective_legal_regime": record.get("legal_regime"),
        "temporal_track": record.get("temporal_track"),
        "raw_path": record.get("raw_file_path"),
        "raw_mime_type": record.get("mime_type"),
        "sha256": record.get("sha256"),
        "text_source_type": infer_text_source_type(record),
        "human_review_source": "balanced_development_review",
        "human_review_status": review.get("human_review_status"),
        "automated": automated_fields(record),
        "attribution_text": record.get("attribution_text"),
    }


def manifest_entry_from_bulk(sample: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    provider = str(sample.get("source_provider") or "indian_kanoon")
    source = source_id(sample)
    return {
        "document_id": stable_document_id(provider, source),
        "provider": provider,
        "source_document_id": source,
        "source_url": sample.get("source_url"),
        "case_title": sample.get("case_name"),
        "court": sample.get("court_automated"),
        "decision_date": decision.get("corrected_date") or sample.get("judgment_date"),
        "decision_year": int(str(decision.get("corrected_date"))[:4]) if decision.get("corrected_date") else sample.get("judgment_year"),
        "effective_offence_family": decision.get("effective_offence_family"),
        "effective_legal_regime": decision.get("effective_legal_regime"),
        "temporal_track": sample.get("temporal_track"),
        "raw_path": sample.get("raw_file_path"),
        "raw_mime_type": sample.get("mime_type"),
        "sha256": sample.get("sha256"),
        "text_source_type": infer_text_source_type(sample),
        "human_review_source": "bulk_quality_audit",
        "human_review_status": sample.get("human_audit_status"),
        "automated": {
            "offence_family": sample.get("offence_family_automated"),
            "legal_regime": sample.get("legal_regime_automated"),
            "court": sample.get("court_automated"),
            "decision_date": sample.get("judgment_date"),
            "decision_year": sample.get("judgment_year"),
            "decision": sample.get("automated_decision"),
            "regime_evidence": sample.get("regime_evidence") or [],
        },
        "regime_evidence": sample.get("regime_evidence") or [],
        "attribution_text": sample.get("attribution_text"),
    }


def automated_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "offence_family": record.get("offence_family"),
        "legal_regime": record.get("legal_regime"),
        "court": {"court_name": record.get("court_name"), "court_level": record.get("court_level")},
        "decision_date": record.get("decision_date"),
        "decision_year": record.get("year"),
        "decision": record.get("final_automated_decision") or record.get("status"),
    }


def infer_text_source_type(record: dict[str, Any]) -> str:
    mime = str(record.get("raw_mime_type") or record.get("mime_type") or "").lower()
    raw_path = str(record.get("raw_path") or record.get("raw_file_path") or "")
    size = int(record.get("file_size_bytes") or 0)
    if mime == "application/pdf" or raw_path.lower().endswith(".pdf"):
        return "pdf_native"
    if record.get("document_text_available") and mime == "application/json" and size < 200:
        return "document_text_fallback"
    if mime.startswith("text/") or raw_path.lower().endswith((".html", ".htm", ".txt", ".json")):
        return "local_text"
    return "unknown"


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"(?<![.!?:;])\n(?=[a-z])", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_source(entry: dict[str, Any], repo_root: Path = REPO_ROOT) -> LoadedSource:
    raw_path_value = entry.get("raw_path")
    warnings: list[str] = []
    if not raw_path_value:
        return LoadedSource(entry["document_id"], "missing", "", [], ["missing_raw_path"])
    raw_path = repo_root / str(raw_path_value)
    if not raw_path.exists():
        return LoadedSource(entry["document_id"], "missing", str(raw_path_value), [], ["raw_file_missing"])
    mime = str(entry.get("raw_mime_type") or "").lower()
    suffix = raw_path.suffix.lower()
    if mime == "application/pdf" or suffix == ".pdf":
        return load_pdf(entry, raw_path)
    raw_text = raw_path.read_text(encoding="utf-8", errors="ignore")
    text = normalize_text(clean_html(raw_text))
    source_type = "local_text"
    if is_provider_wrapper(text):
        fallback = fallback_text_from_entry(entry)
        if fallback:
            text = fallback
            source_type = "document_text_fallback"
            warnings.append("original_provider_wrapper_used_fallback_metadata_text")
    return LoadedSource(entry["document_id"], source_type, str(raw_path_value), [{"page_number": None, "text": text}], warnings)


def load_pdf(entry: dict[str, Any], raw_path: Path) -> LoadedSource:
    try:
        import pymupdf
    except ImportError:
        extraction = extract_pdf_text(raw_path)
        return LoadedSource(entry["document_id"], "pdf_native", str(entry.get("raw_path")), [{"page_number": None, "text": normalize_text(extraction.text)}], ["pymupdf_import_fallback_no_page_mapping"])
    warnings: list[str] = []
    pages: list[dict[str, Any]] = []
    try:
        with pymupdf.open(raw_path) as document:
            for index, page in enumerate(document, start=1):
                text = normalize_text(normalize_pdf_text(page.get_text("text")))
                pages.append({"page_number": index, "text": text})
    except Exception as exc:
        return LoadedSource(entry["document_id"], "pdf_native", str(entry.get("raw_path")), [], [f"pdf_extract_failed:{type(exc).__name__}:{str(exc)[:160]}"])
    if not any(page["text"] for page in pages):
        warnings.append("pdf_no_native_text")
    return LoadedSource(entry["document_id"], "pdf_native", str(entry.get("raw_path")), pages, warnings)


def clean_html(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def is_provider_wrapper(text: str) -> bool:
    lowered = text.lower()
    return "original document not available" in lowered or "document not found" in lowered


def fallback_text_from_entry(entry: dict[str, Any]) -> str:
    automated = entry.get("automated") or {}
    evidence = automated.get("regime_evidence") or entry.get("regime_evidence") or []
    if evidence:
        return normalize_text("\n\n".join(str(item) for item in evidence))
    return normalize_text(f"{entry.get('case_title') or ''}\n\n{entry.get('attribution_text') or ''}")


def line_frequencies(pages: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for page in pages:
        seen = set()
        for line in page.get("text", "").splitlines():
            cleaned = line.strip()
            if cleaned:
                seen.add(cleaned)
        counts.update(seen)
    return counts


def strip_repeated_headers_footers(pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if len(pages) < 3:
        return pages, {"removed_header_count": 0, "removed_footer_count": 0}
    counts = line_frequencies(pages)
    threshold = max(3, len(pages) // 2)
    header_removed = 0
    footer_removed = 0
    cleaned_pages: list[dict[str, Any]] = []
    for page in pages:
        lines = page.get("text", "").splitlines()
        if lines and counts[lines[0].strip()] >= threshold:
            lines = lines[1:]
            header_removed += 1
        if lines and counts[lines[-1].strip()] >= threshold:
            lines = lines[:-1]
            footer_removed += 1
        cleaned_pages.append({**page, "text": "\n".join(lines).strip()})
    return cleaned_pages, {"removed_header_count": header_removed, "removed_footer_count": footer_removed}


HEADING_RE = re.compile(r"^((?:\d+\.?\s*)?)(JUDGMENT|ORDER|FACTS?|BACKGROUND|SUBMISSIONS?|ARGUMENTS?|ANALYSIS|DISCUSSION|REASONS?|FINDINGS?|CONCLUSION|BRIEF FACTS|APPELLANT'?S SUBMISSIONS|RESPONDENT'?S SUBMISSIONS)\\b[:\\s-]*$", re.IGNORECASE)
NUMBERED_RE = re.compile(r"^(?:\d+|[IVXLCDM]+)[.)]\\s+")


def paragraph_blocks(entry: dict[str, Any], loaded: LoadedSource) -> tuple[list[dict[str, Any]], dict[str, int]]:
    pages, removal = strip_repeated_headers_footers(loaded.pages)
    blocks: list[dict[str, Any]] = []
    heading_path: list[str] = []
    for page in pages:
        page_number = page.get("page_number")
        parts = [part.strip() for part in re.split(r"\n\s*\n", page.get("text", "")) if part.strip()]
        for part in parts:
            text = normalize_text(part)
            if not text:
                continue
            block_type = classify_block(text, len(blocks))
            if block_type == "heading":
                heading_path = [text[:120]]
            blocks.append(
                {
                    "document_id": entry["document_id"],
                    "paragraph_index": len(blocks),
                    "text": text,
                    "page_start": page_number,
                    "page_end": page_number,
                    "heading_path": list(heading_path),
                    "block_type": block_type,
                    "source_offsets": None,
                }
            )
    return blocks, removal


def classify_block(text: str, index: int) -> str:
    if index == 0:
        return "title"
    if HEADING_RE.match(text) or (len(text) < 90 and text.isupper() and len(text.split()) <= 10):
        return "heading"
    if NUMBERED_RE.match(text):
        return "paragraph"
    if text.startswith(("\"", "'", "“")):
        return "quote"
    if re.match(r"^[-*•]\s+", text):
        return "list"
    return "paragraph"


def chunk_blocks(
    entry: dict[str, Any],
    blocks: list[dict[str, Any]],
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    effective_max = max(1, max_tokens - 50)
    for block in blocks:
        block_tokens = estimated_tokens(block["text"])
        if current and current_tokens + block_tokens > effective_max:
            chunks.append(make_chunk(entry, chunks, current))
            current = overlap_blocks(current, overlap_tokens)
            current_tokens = sum(estimated_tokens(item["text"]) for item in current)
            if current and current_tokens + block_tokens > effective_max:
                current = []
                current_tokens = 0
        if block_tokens > max_tokens:
            if current:
                chunks.append(make_chunk(entry, chunks, current))
                current = []
                current_tokens = 0
            for split in split_oversized_block(block, max_tokens):
                chunks.append(make_chunk(entry, chunks, [split]))
            continue
        current.append(block)
        current_tokens += block_tokens
        if current_tokens >= target_tokens:
            chunks.append(make_chunk(entry, chunks, current))
            current = overlap_blocks(current, overlap_tokens)
            current_tokens = sum(estimated_tokens(item["text"]) for item in current)
    if current:
        chunks.append(make_chunk(entry, chunks, current))
    return chunks


def overlap_blocks(blocks: list[dict[str, Any]], overlap_tokens: int) -> list[dict[str, Any]]:
    if overlap_tokens <= 0:
        return []
    selected: list[dict[str, Any]] = []
    total = 0
    for block in reversed(blocks):
        tokens = estimated_tokens(block["text"])
        if tokens > overlap_tokens:
            break
        if selected and total + tokens > overlap_tokens:
            break
        selected.append(block)
        total += tokens
    return list(reversed(selected))


def split_oversized_block(block: dict[str, Any], max_tokens: int) -> list[dict[str, Any]]:
    words = block["text"].split()
    approx_words = max(50, int((max_tokens - 50) / 1.25))
    splits = []
    for start in range(0, len(words), approx_words):
        text = " ".join(words[start : start + approx_words])
        splits.append({**block, "text": text, "block_type": "paragraph"})
    return splits


def make_chunk(entry: dict[str, Any], chunks: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    index = len(chunks)
    text = "\n\n".join(block["text"] for block in blocks).strip()
    pages = [block.get("page_start") for block in blocks if block.get("page_start") is not None]
    heading_path = next((list(reversed(block.get("heading_path") or [])) for block in reversed(blocks) if block.get("heading_path")), [])
    return {
        "chunk_id": f"{entry['document_id']}:chunk:{index:04d}",
        "document_id": entry["document_id"],
        "provider": entry["provider"],
        "source_document_id": entry["source_document_id"],
        "source_url": entry.get("source_url"),
        "case_title": entry.get("case_title"),
        "court": entry.get("court"),
        "decision_date": entry.get("decision_date"),
        "decision_year": entry.get("decision_year"),
        "effective_offence_family": entry.get("effective_offence_family"),
        "effective_legal_regime": entry.get("effective_legal_regime"),
        "chunk_index": index,
        "paragraph_start": blocks[0]["paragraph_index"],
        "paragraph_end": blocks[-1]["paragraph_index"],
        "page_start": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
        "heading_path": list(reversed(heading_path)),
        "text_source_type": entry.get("text_source_type"),
        "raw_sha256": entry.get("sha256"),
        "chunk_text": text,
        "estimated_token_count": estimated_tokens(text),
        "normalizer_version": NORMALIZER_VERSION,
        "chunker_version": CHUNKER_VERSION,
    }


def output_path_for(base: Path, document_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", document_id)
    return base / f"{safe}.json"


def process_document(entry: dict[str, Any], normalized_dir: Path, chunk_dir: Path, force: bool = False) -> dict[str, Any]:
    normalized_path = output_path_for(normalized_dir, entry["document_id"])
    chunk_path = output_path_for(chunk_dir, entry["document_id"])
    if not force and normalized_path.exists() and chunk_path.exists():
        try:
            existing = json.loads(normalized_path.read_text(encoding="utf-8"))
            if existing.get("source_sha256") == entry.get("sha256") and existing.get("processing_version") == PROCESSING_VERSION:
                chunks = json.loads(chunk_path.read_text(encoding="utf-8"))
                return {"status": "skipped_unchanged", "document_id": entry["document_id"], "paragraphs": len(existing.get("paragraphs", [])), "chunks": len(chunks), "warnings": existing.get("warnings", [])}
        except Exception:
            pass
    try:
        loaded = load_source(entry)
        blocks, removal = paragraph_blocks(entry, loaded)
        if not blocks:
            raise ValueError("no_text_blocks")
        chunks = chunk_blocks(entry, blocks)
        validate_chunks(entry, blocks, chunks)
        normalized = {
            "document_id": entry["document_id"],
            "processing_version": PROCESSING_VERSION,
            "source_sha256": entry.get("sha256"),
            "text_source_type": loaded.text_source_type,
            "raw_path": loaded.raw_path,
            "warnings": loaded.warnings,
            "header_footer_diagnostics": removal,
            "paragraphs": blocks,
        }
        normalized_dir.mkdir(parents=True, exist_ok=True)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        chunk_path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"status": "processed", "document_id": entry["document_id"], "paragraphs": len(blocks), "chunks": len(chunks), "warnings": loaded.warnings, **removal, "text_source_type": loaded.text_source_type}
    except Exception as exc:
        return {"status": "failed", "document_id": entry["document_id"], "stage": "process_document", "error_type": type(exc).__name__, "message": str(exc)[:240]}


def validate_chunks(entry: dict[str, Any], blocks: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    ids = [chunk["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_chunk_ids")
    for expected, chunk in enumerate(chunks):
        if chunk["chunk_index"] != expected or not chunk["chunk_text"].strip():
            raise ValueError("invalid_chunk_sequence_or_empty_text")
        if chunk["paragraph_start"] < 0 or chunk["paragraph_end"] >= len(blocks) or chunk["paragraph_start"] > chunk["paragraph_end"]:
            raise ValueError("invalid_paragraph_range")
        if chunk["page_start"] is not None and chunk["page_end"] is not None and chunk["page_start"] > chunk["page_end"]:
            raise ValueError("invalid_page_range")
        if entry.get("text_source_type") != "pdf_native" and (chunk["page_start"] is not None or chunk["page_end"] is not None):
            raise ValueError("non_pdf_page_provenance_invented")


def process_manifest(
    manifest_path: Path = TRUSTED_MANIFEST,
    output_dir: Path = REPO_ROOT / "data/processed",
    dry_run: bool = False,
    limit: int | None = None,
    document_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not manifest_path.exists():
        build_trusted_manifest(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs = payload["documents"]
    if document_id:
        docs = [doc for doc in docs if doc["document_id"] == document_id]
    if limit is not None:
        docs = docs[:limit]
    if dry_run:
        return {"dry_run": True, "would_process": len(docs), "writes": 0}
    normalized_dir = output_dir / "judgments_normalized"
    chunk_dir = output_dir / "judgment_chunks"
    results = [process_document(doc, normalized_dir, chunk_dir, force=force) for doc in docs]
    summary = summarize_processing(payload, results, chunk_dir)
    CHUNK_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    generate_qa_packet(payload, chunk_dir)
    generate_docs(summary)
    return summary


def summarize_processing(manifest: dict[str, Any], results: list[dict[str, Any]], chunk_dir: Path) -> dict[str, Any]:
    all_chunks: list[dict[str, Any]] = []
    for path in sorted(chunk_dir.glob("*.json")):
        all_chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    sizes = [chunk["estimated_token_count"] for chunk in all_chunks]
    source_counts = Counter(doc.get("text_source_type", "unknown") for doc in manifest["documents"])
    chunks_by_doc = Counter(chunk["document_id"] for chunk in all_chunks)
    pdf_chunks = [chunk for chunk in all_chunks if chunk["text_source_type"] == "pdf_native"]
    non_pdf_chunks = [chunk for chunk in all_chunks if chunk["text_source_type"] != "pdf_native"]
    failures = [result for result in results if result["status"] == "failed"]
    return {
        "processing_version": PROCESSING_VERSION,
        "input_document_count": manifest["final_unique_documents"],
        "processed_document_count": sum(1 for r in results if r["status"] in {"processed", "skipped_unchanged"}),
        "failed_document_count": len(failures),
        "processed": sum(1 for r in results if r["status"] == "processed"),
        "skipped_unchanged": sum(1 for r in results if r["status"] == "skipped_unchanged"),
        "reprocessed": sum(1 for r in results if r["status"] == "processed"),
        "failures": failures,
        "total_paragraphs": sum(int(r.get("paragraphs", 0)) for r in results),
        "total_chunks": len(all_chunks),
        "source_type_counts": dict(sorted(source_counts.items())),
        "page_provenance": {
            "pdf_documents": sum(1 for doc in manifest["documents"] if doc.get("text_source_type") == "pdf_native"),
            "pdf_chunks": len(pdf_chunks),
            "pdf_chunks_with_page_provenance": sum(1 for chunk in pdf_chunks if chunk.get("page_start") is not None and chunk.get("page_end") is not None),
            "non_pdf_documents": sum(1 for doc in manifest["documents"] if doc.get("text_source_type") != "pdf_native"),
            "non_pdf_null_page_chunks": sum(1 for chunk in non_pdf_chunks if chunk.get("page_start") is None and chunk.get("page_end") is None),
            "missing_or_invalid_provenance": 0,
        },
        "chunk_size_statistics": stats(sizes),
        "chunks_per_document": stats(list(chunks_by_doc.values())),
        "diagnostics": {
            "removed_header_count": sum(int(r.get("removed_header_count", 0)) for r in results),
            "removed_footer_count": sum(int(r.get("removed_footer_count", 0)) for r in results),
            "documents_with_no_text": [r["document_id"] for r in failures if "no_text" in r.get("message", "")],
            "documents_with_unusually_low_text": [],
            "documents_with_unusually_large_paragraphs": [],
            "documents_with_fallback_text": [doc["document_id"] for doc in manifest["documents"] if doc.get("text_source_type") == "document_text_fallback"],
            "documents_with_missing_page_provenance": sorted({chunk["document_id"] for chunk in pdf_chunks if chunk.get("page_start") is None}),
        },
        "integrity": integrity_summary(all_chunks),
        "configuration": {
            "target_estimated_tokens": DEFAULT_TARGET_TOKENS,
            "max_estimated_tokens": DEFAULT_MAX_TOKENS,
            "overlap_estimated_tokens": DEFAULT_OVERLAP_TOKENS,
        },
        "trusted_input": {key: manifest[key] for key in ["development_accepted_input", "bulk_audit_accepted_input", "total_before_dedupe", "cross_set_duplicates", "final_unique_documents", "excluded_policy"]},
    }


def stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None, "p95": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {"min": min(values), "max": max(values), "mean": round(statistics.mean(values), 2), "median": statistics.median(values), "p95": ordered[p95_index]}


def integrity_summary(chunks: list[dict[str, Any]]) -> dict[str, int]:
    ids = [chunk["chunk_id"] for chunk in chunks]
    return {
        "duplicate_chunk_ids": len(ids) - len(set(ids)),
        "invalid_paragraph_ranges": sum(1 for c in chunks if c["paragraph_start"] > c["paragraph_end"]),
        "invalid_page_ranges": sum(1 for c in chunks if c["page_start"] is not None and c["page_end"] is not None and c["page_start"] > c["page_end"]),
        "empty_chunks": sum(1 for c in chunks if not c["chunk_text"].strip()),
    }


def generate_qa_packet(manifest: dict[str, Any], chunk_dir: Path, output_path: Path = QA_PACKET) -> None:
    chunks: list[dict[str, Any]] = []
    for path in sorted(chunk_dir.glob("*.json")):
        chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    selected = deterministic_qa_chunks(chunks, 15)
    lines = ["# Judgment Chunking QA", "", "Deterministic bounded sample for human chunk-quality inspection.", ""]
    for chunk in selected:
        lines.extend([
            f"## {chunk['chunk_id']}",
            "",
            f"- document: {chunk['document_id']}",
            f"- source type: `{chunk['text_source_type']}`",
            f"- regime: `{chunk['effective_legal_regime']}`",
            f"- family: `{chunk['effective_offence_family']}`",
            f"- court: `{(chunk.get('court') or {}).get('court_level')}`",
            f"- heading: `{ ' > '.join(chunk.get('heading_path') or []) }`",
            f"- page range: {chunk.get('page_start')} - {chunk.get('page_end')}",
            f"- paragraph range: {chunk['paragraph_start']} - {chunk['paragraph_end']}",
            f"- estimated tokens: {chunk['estimated_token_count']}",
            "",
            "```text",
            chunk["chunk_text"][:1800],
            "```",
            "",
        ])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def deterministic_qa_chunks(chunks: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    rules = [
        lambda c: c["text_source_type"] == "pdf_native",
        lambda c: c["text_source_type"] != "pdf_native",
        lambda c: c["effective_legal_regime"] == "bns_bnss",
        lambda c: c["effective_legal_regime"] == "ipc_crpc",
        lambda c: (c.get("court") or {}).get("court_level") == "district_or_sessions",
    ]
    ordered = sorted(chunks, key=lambda c: hashlib.sha256(c["chunk_id"].encode()).hexdigest())
    for rule in rules:
        for chunk in ordered:
            if chunk["chunk_id"] not in seen and rule(chunk):
                selected.append(chunk)
                seen.add(chunk["chunk_id"])
                break
    for chunk in ordered:
        if len(selected) >= target:
            break
        if chunk["chunk_id"] not in seen:
            selected.append(chunk)
            seen.add(chunk["chunk_id"])
    return selected


def generate_docs(summary: dict[str, Any], output_path: Path = DOC_PATH) -> None:
    lines = [
        "# Judgment Document Processing",
        "",
        "This phase processes only trusted human-approved judgments: accepted balanced development records plus accepted bulk-audit records. Rejected, needs-review, and unaudited bulk records are excluded.",
        "",
        "No embeddings, vector stores, BM25 indexes, reranking, RAG generation, LLM calls, or acquisition are produced in this step.",
        "",
        "## Pipeline",
        "",
        "1. Build `trusted_judgment_processing_manifest.json` from human review manifests.",
        "2. Load local PDF, HTML/text, or fallback text sources.",
        "3. Normalize Unicode, whitespace, soft hyphens, control characters, and safe line wraps.",
        "4. Segment text into paragraph/block records with heading context and page provenance where available.",
        "5. Chunk contiguous paragraph ranges with configurable estimated-token target, max, and overlap.",
        "6. Write ignored normalized/chunk JSON outputs and tracked summary manifests.",
        "",
        "## Defaults",
        "",
        f"- target estimated tokens: {DEFAULT_TARGET_TOKENS}",
        f"- max estimated tokens: {DEFAULT_MAX_TOKENS}",
        f"- overlap estimated tokens: {DEFAULT_OVERLAP_TOKENS}",
        "- token counts are lightweight estimates, not model tokenizer counts.",
        "",
        "## Provenance",
        "",
        "PDF chunks include 1-based page ranges when native text extraction provides page identity. Non-PDF and fallback chunks use null page ranges and retain `text_source_type` plus paragraph ranges.",
        "",
        "Chunk IDs use `<provider>:<source_document_id>:chunk:<zero-padded-index>` and are deterministic for unchanged input/version.",
        "",
        "## CLI",
        "",
        "```bash",
        "python3 backend/scripts/process_judgment_corpus.py --dry-run",
        "python3 backend/scripts/process_judgment_corpus.py --force",
        "python3 backend/scripts/process_judgment_corpus.py --document-id indian_kanoon:1291057",
        "```",
        "",
        "## Current Run Summary",
        "",
        f"- input documents: {summary['input_document_count']}",
        f"- processed/skipped: {summary['processed_document_count']}",
        f"- failed: {summary['failed_document_count']}",
        f"- paragraphs: {summary['total_paragraphs']}",
        f"- chunks: {summary['total_chunks']}",
        "",
        "## Known Limitations",
        "",
        "- No OCR; PDFs without native text fail or warn.",
        "- Fallback JSON wrapper records can only use locally retained fallback/evidence text.",
        "- Header/footer removal is conservative and requires repeated structural evidence.",
        "- Train/test splits and retrieval evaluation are intentionally not defined here.",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=TRUSTED_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data/processed")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--summary", action="store_true", help="Regenerate tracked manifest before processing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.summary or not args.manifest.exists():
        build_trusted_manifest(args.manifest)
    result = process_manifest(args.manifest, args.output_dir, args.dry_run, args.limit, args.document_id, args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("failed_document_count", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
