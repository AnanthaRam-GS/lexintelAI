"""Controlled V2 filtered acquisition for recent criminal judgments."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.acquire_development_judgments import (  # noqa: E402
    ATTRIBUTION_TEXT,
    extension_for_content,
    extract_case_name,
    extract_court_name,
    extract_results,
    extract_source_document_id,
    normalize_court_level,
    normalize_original_document_payload,
    parse_year,
    should_stop_for_api_error,
)
from backend.scripts.corpus_analysis.scoring import (  # noqa: E402
    decide_candidate_quality,
    quota_allows,
)
from backend.scripts.corpus_utils import (  # noqa: E402
    file_size,
    find_duplicate_by_sha256,
    load_manifest,
    safe_filename,
    sha256_file,
    write_manifest_atomic,
)
from backend.scripts.env_utils import load_project_env  # noqa: E402
from backend.scripts.generate_judgment_review_report import clean_text_preview  # noqa: E402
from backend.scripts.indiankanoon_client import (  # noqa: E402
    IndianKanoonClient,
    IndianKanoonClientError,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
STRATEGY_MANIFEST = MANIFEST_DIR / "development_judgment_strategy_v2.json"
QUOTA_MANIFEST = MANIFEST_DIR / "development_judgment_quotas_v2.json"
QUERY_MANIFEST = MANIFEST_DIR / "development_judgment_queries_v2.json"
V1_JUDGMENTS = MANIFEST_DIR / "development_judgments.json"
V2_JUDGMENTS = MANIFEST_DIR / "development_judgments_v2.json"
V2_REVIEW = MANIFEST_DIR / "development_judgment_review_v2.json"
V2_AUDIT = MANIFEST_DIR / "development_candidate_audit_v2.json"
RAW_DIR = REPO_ROOT / "data/raw/judgments/indiankanoon/v2"
DEFAULT_LIMIT = 5
MAX_LIMIT = 50
DEFAULT_MAX_API_REQUESTS = 100


class BudgetExceeded(RuntimeError):
    pass


def stats_total(client: IndianKanoonClient) -> int:
    return int(client.get_request_stats()["total_requests"])


def enforce_budget(client: IndianKanoonClient, max_api_requests: int) -> None:
    if stats_total(client) >= max_api_requests:
        raise BudgetExceeded("api_request_budget_reached")


def load_quotas(path: Path = QUOTA_MANIFEST) -> dict[str, int]:
    return {str(record["offence_family"]): int(record["target_quota"]) for record in load_manifest(path)}


def active_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        if record.get("status") == "validated":
            counts[str(record.get("offence_family"))] += 1
    return dict(counts)


def text_from_payload(content: bytes, mime_type: str, metadata_text: str) -> str:
    if mime_type.startswith("text/") or mime_type == "application/json":
        return f"{metadata_text}\n{clean_text_preview(content.decode('utf-8', errors='ignore'), 4000)}"
    return metadata_text


def metadata_text(result: dict[str, Any], metadata: dict[str, Any], document: dict[str, Any] | None = None) -> str:
    parts: list[str] = []
    for source in (result, metadata, document or {}):
        for value in source.values():
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def review_record_for(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_id": record["local_id"],
        "source_document_id": record["source_document_id"],
        "case_name": record["case_name"],
        "offence_family": record["offence_family"],
        "source_url": record["source_url"],
        "automated_status": record["status"],
        "human_review_status": "pending",
        "review_notes": None,
    }


def upsert_by_local_id(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    for index, existing in enumerate(records):
        if existing.get("local_id") == record["local_id"]:
            records[index] = record
            return
    records.append(record)


def source_id_seen(source_id: str, *record_sets: list[dict[str, Any]]) -> bool:
    return any(str(record.get("source_document_id")) == source_id for records in record_sets for record in records)


def audit_entry(
    query: dict[str, Any],
    rank: int,
    source_id: str | None,
    result: dict[str, Any],
    metadata: dict[str, Any] | None,
    decision: dict[str, Any],
    api_before: int,
    api_after: int,
) -> dict[str, Any]:
    return {
        "source_document_id": source_id,
        "query_id": query.get("query_id"),
        "offence_family": query.get("offence_family"),
        "temporal_track": query.get("temporal_track"),
        "retrieval_rank": rank,
        "search_title": result.get("title") or result.get("doc_title"),
        "court": (metadata or result).get("court") or (metadata or result).get("docsource"),
        "year": parse_year((metadata or result).get("date") or result.get("title")),
        "search_filter_result": "considered",
        "document_type_score": decision.get("document_type_score"),
        "criminal_relevance_score": decision.get("criminal_relevance_score"),
        "metadata_quality_score": decision.get("metadata_quality_score"),
        "detected_statutes": decision.get("detected_statutes", []),
        "detected_regime": decision.get("legal_regime"),
        "final_automated_decision": decision.get("decision"),
        "rejection_reasons": decision.get("reasons", []),
        "api_requests_consumed": api_after - api_before,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def filtered_queries(
    queries: list[dict[str, Any]],
    query_id: str | None,
    offence_family: str | None,
    temporal_track: str | None,
) -> list[dict[str, Any]]:
    selected = queries
    if query_id:
        selected = [query for query in selected if query.get("query_id") == query_id]
    if offence_family:
        selected = [query for query in selected if query.get("offence_family") == offence_family]
    if temporal_track:
        selected = [query for query in selected if query.get("temporal_track") == temporal_track]
    return selected


def dry_run(limit: int, max_api_requests: int, strategy_manifest: Path = STRATEGY_MANIFEST) -> int:
    strategy = json.loads(strategy_manifest.read_text(encoding="utf-8"))
    queries = load_manifest(QUERY_MANIFEST)
    quotas = load_quotas()
    print("V2 filtered acquisition dry run")
    print(f"Temporal tracks: {', '.join(track['name'] for track in strategy['temporal_tracks'])}")
    print(f"Query groups: {len(queries)}")
    print(f"Offence-family quotas: {quotas}")
    print(f"Document limit: {limit}")
    print(f"API request budget: {max_api_requests}")
    print(f"Criminal thresholds: {strategy['quality_thresholds']}")
    print("No Indian Kanoon API requests were made.")
    return 0


def acquire(
    limit: int = DEFAULT_LIMIT,
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
    query_id: str | None = None,
    offence_family: str | None = None,
    temporal_track: str | None = None,
    delay: float = 1.0,
) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    client = IndianKanoonClient()
    queries = filtered_queries(load_manifest(QUERY_MANIFEST), query_id, offence_family, temporal_track)
    if not queries:
        raise ValueError("no v2 query groups selected")
    quotas = load_quotas()
    v1_records = load_manifest(V1_JUDGMENTS)
    records = load_manifest(V2_JUDGMENTS)
    reviews = load_manifest(V2_REVIEW)
    audit = load_manifest(V2_AUDIT)
    accepted_counts = active_counts(records)
    downloaded = 0

    for query in queries:
        if downloaded >= limit:
            break
        family = str(query["offence_family"])
        if not quota_allows(family, accepted_counts, quotas):
            continue
        enforce_budget(client, max_api_requests)
        before = stats_total(client)
        try:
            search_response = client.search(
                str(query["query"]),
                page=0,
                doctypes=query.get("doctypes"),
                from_date=query.get("from_date"),
                to_date=query.get("to_date"),
            )
        except IndianKanoonClientError as exc:
            print(f"{query['query_id']}: search failed: {exc}", file=sys.stderr)
            if should_stop_for_api_error(exc):
                break
            continue
        time.sleep(delay)

        for rank, result in enumerate(extract_results(search_response), start=1):
            if downloaded >= limit:
                break
            if not quota_allows(family, accepted_counts, quotas):
                break
            source_id = extract_source_document_id(result)
            if not source_id or source_id_seen(source_id, v1_records, records):
                continue
            enforce_budget(client, max_api_requests)
            candidate_api_before = stats_total(client)
            metadata: dict[str, Any] = {}
            document: dict[str, Any] | None = None
            try:
                metadata = client.get_document_metadata(source_id)
                time.sleep(delay)
                enforce_budget(client, max_api_requests)
                document = client.get_document(source_id)
                time.sleep(delay)
            except IndianKanoonClientError as exc:
                print(f"{source_id}: metadata/document failed: {exc}", file=sys.stderr)
                decision = {
                    "decision": "reject",
                    "reasons": ["metadata_or_document_fetch_failed"],
                    "document_type_score": None,
                    "criminal_relevance_score": None,
                    "metadata_quality_score": None,
                    "detected_statutes": [],
                    "legal_regime": "unknown",
                }
                upsert_by_local_id(
                    audit,
                    {"local_id": f"v2-audit-{source_id}", **audit_entry(query, rank, source_id, result, metadata, decision, candidate_api_before, stats_total(client))},
                )
                if should_stop_for_api_error(exc):
                    break
                continue

            case_name = extract_case_name(result, metadata)
            court_name = extract_court_name(result, metadata)
            year = parse_year(metadata.get("date") or result.get("date") or case_name)
            base_record = {
                "local_id": f"v2-{source_id}",
                "source_provider": "indian_kanoon",
                "source_document_id": source_id,
                "source_url": f"https://indiankanoon.org/doc/{source_id}/",
                "case_name": case_name,
                "case_number": None,
                "court_name": court_name,
                "court_level": normalize_court_level(court_name),
                "decision_date": metadata.get("date"),
                "year": year,
                "legal_regime": "unknown",
                "offence_family": family,
                "known_sections": [],
                "acquisition_query": query["query"],
                "query_id": query["query_id"],
                "temporal_track": query["temporal_track"],
                "retrieval_rank": rank,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "raw_file_path": None,
                "sha256": None,
                "file_size_bytes": None,
                "mime_type": None,
                "attribution_required": True,
                "attribution_text": ATTRIBUTION_TEXT,
                "status": "screened",
                "acquisition_strategy_version": "v2_recent_criminal_filter",
                "notes": None,
            }
            pre_text = metadata_text(result, metadata, document)
            pre_decision = decide_candidate_quality(pre_text, base_record)
            if pre_decision.decision == "reject":
                rejected = dict(base_record)
                rejected["status"] = "rejected_pre_download"
                rejected["notes"] = "; ".join(pre_decision.reasons)
                upsert_by_local_id(records, rejected)
                upsert_by_local_id(audit, {"local_id": f"v2-audit-{source_id}", **audit_entry(query, rank, source_id, result, metadata, pre_decision.to_dict(), candidate_api_before, stats_total(client))})
                continue

            enforce_budget(client, max_api_requests)
            try:
                payload = client.get_original_document(source_id)
                time.sleep(delay)
            except IndianKanoonClientError as exc:
                failed = dict(base_record)
                failed["status"] = "failed"
                failed["notes"] = f"original_document_failed: {exc}"
                upsert_by_local_id(records, failed)
                decision = pre_decision.to_dict()
                decision["decision"] = "reject"
                decision["reasons"] = list(decision["reasons"]) + ["raw_retrieval_failure"]
                upsert_by_local_id(audit, {"local_id": f"v2-audit-{source_id}", **audit_entry(query, rank, source_id, result, metadata, decision, candidate_api_before, stats_total(client))})
                if should_stop_for_api_error(exc):
                    break
                continue

            content, mime_type = normalize_original_document_payload(payload)
            extension = extension_for_content(content, mime_type)
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            raw_path = RAW_DIR / f"{safe_filename(source_id)}_{safe_filename(case_name or source_id)}{extension}"
            if raw_path.exists():
                incoming_digest = hashlib.sha256(content).hexdigest()
                if sha256_file(raw_path) != incoming_digest:
                    continue
            else:
                raw_path.write_bytes(content)
            digest = sha256_file(raw_path)
            duplicate = find_duplicate_by_sha256(digest, v1_records + records)
            full_record = dict(base_record)
            full_record.update(
                {
                    "raw_file_path": str(raw_path.relative_to(REPO_ROOT)),
                    "sha256": digest,
                    "file_size_bytes": file_size(raw_path),
                    "mime_type": mime_type,
                }
            )
            full_text = text_from_payload(content, mime_type, pre_text)
            decision = decide_candidate_quality(
                full_text,
                full_record,
                accepted_counts=accepted_counts,
                quotas=quotas,
                duplicate=duplicate is not None,
                corrupt=file_size(raw_path) == 0,
            )
            full_record["legal_regime"] = decision.legal_regime
            full_record["quality_scores"] = {
                "document_type": decision.document_type_score,
                "criminal_relevance": decision.criminal_relevance_score,
                "metadata_quality": decision.metadata_quality_score,
            }
            full_record["detected_statutes"] = decision.detected_statutes
            full_record["status"] = "validated" if decision.decision == "accept_candidate" else decision.decision
            full_record["notes"] = "; ".join(decision.reasons) if decision.reasons else None
            upsert_by_local_id(records, full_record)
            upsert_by_local_id(audit, {"local_id": f"v2-audit-{source_id}", **audit_entry(query, rank, source_id, result, metadata, decision.to_dict(), candidate_api_before, stats_total(client))})
            downloaded += 1
            if decision.decision == "accept_candidate":
                accepted_counts[family] = accepted_counts.get(family, 0) + 1
                upsert_by_local_id(reviews, review_record_for(full_record))

    write_manifest_atomic(V2_JUDGMENTS, records)
    write_manifest_atomic(V2_REVIEW, reviews)
    write_manifest_atomic(V2_AUDIT, audit)
    print(f"V2 documents downloaded: {downloaded}")
    print(json.dumps(client.get_request_stats(), sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--strategy", default=str(STRATEGY_MANIFEST))
    parser.add_argument("--query-id")
    parser.add_argument("--offence-family")
    parser.add_argument("--temporal-track")
    parser.add_argument("--max-api-requests", type=int, default=DEFAULT_MAX_API_REQUESTS)
    parser.add_argument("--delay", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    load_project_env()
    args = parse_args()
    strategy_manifest = Path(args.strategy)
    if args.dry_run:
        return dry_run(args.limit, args.max_api_requests, strategy_manifest=strategy_manifest)
    try:
        return acquire(
            limit=args.limit,
            max_api_requests=args.max_api_requests,
            query_id=args.query_id,
            offence_family=args.offence_family,
            temporal_track=args.temporal_track,
            delay=args.delay,
        )
    except (BudgetExceeded, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
