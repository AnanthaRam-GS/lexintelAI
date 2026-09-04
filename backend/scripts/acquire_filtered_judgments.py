"""Controlled V2 filtered acquisition for recent criminal judgments."""

from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime
from html.parser import HTMLParser
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
from backend.scripts.bulk_acquisition_state import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_RUN_ROOT,
    append_batch,
    build_partitions,
    create_run_state,
    generate_run_id,
    load_run_state,
    rebuild_dedupe_index,
    run_dir,
    run_statistics,
    save_run_state,
    start_new_run,
    validate_run_id,
    write_json_atomic,
)
from backend.scripts.bulk_acquisition_state import empty_request_stats, merge_request_stats  # noqa: E402
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
    DEFAULT_MAX_RETRIES,
    DEFAULT_MIN_REQUEST_INTERVAL_MS,
    IndianKanoonClient,
    IndianKanoonClientError,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
STRATEGY_MANIFEST = MANIFEST_DIR / "development_judgment_strategy_v2.json"
QUOTA_MANIFEST = MANIFEST_DIR / "development_judgment_quotas_v2.json"
QUERY_MANIFEST = MANIFEST_DIR / "development_judgment_queries_v2.json"
BALANCED_QUERY_MANIFEST = MANIFEST_DIR / "balanced_development_queries.json"
GAP_QUERY_MANIFEST = MANIFEST_DIR / "development_judgment_gap_queries.json"
TRANSITION_QUERY_MANIFEST = MANIFEST_DIR / "transition_validation_queries.json"
V1_JUDGMENTS = MANIFEST_DIR / "development_judgments.json"
V2_JUDGMENTS = MANIFEST_DIR / "development_judgments_v2.json"
V2_REVIEW = MANIFEST_DIR / "development_judgment_review_v2.json"
V2_AUDIT = MANIFEST_DIR / "development_candidate_audit_v2.json"
PRESCREEN_JUDGMENTS = MANIFEST_DIR / "development_judgments_prescreen_v2.json"
PRESCREEN_REVIEW = MANIFEST_DIR / "development_judgment_review_prescreen_v2.json"
PRESCREEN_AUDIT = MANIFEST_DIR / "development_candidate_audit_prescreen_v2.json"
BALANCED_JUDGMENTS = MANIFEST_DIR / "balanced_development_judgments.json"
BALANCED_REVIEW = MANIFEST_DIR / "balanced_development_review.json"
BALANCED_AUDIT = MANIFEST_DIR / "balanced_candidate_audit.json"
TRANSITION_CANDIDATES = MANIFEST_DIR / "transition_validation_candidates.json"
TRANSITION_REVIEW = MANIFEST_DIR / "transition_validation_review.json"
TRANSITION_AUDIT = MANIFEST_DIR / "transition_validation_audit.json"
RAW_DIR = REPO_ROOT / "data/raw/judgments/indiankanoon/v2"
BALANCED_RAW_DIR = REPO_ROOT / "data/raw/judgments/indiankanoon/balanced"
TRANSITION_RAW_DIR = REPO_ROOT / "data/raw/judgments/indiankanoon/transition_validation"
DEFAULT_LIMIT = 5
MAX_LIMIT = 50
TRANSITION_MAX_LIMIT = 10
DEFAULT_MAX_API_REQUESTS = 100
DEFAULT_MAX_SEARCH_PAGES = 1
BULK_PLAN_MANIFEST = MANIFEST_DIR / "bulk_acquisition_plan.json"
GLOBAL_DEDUPE_INDEX = MANIFEST_DIR / "global_corpus_dedupe_index.json"
GLOBAL_DEDUPE_SOURCES = [
    V1_JUDGMENTS,
    V2_JUDGMENTS,
    PRESCREEN_JUDGMENTS,
    BALANCED_JUDGMENTS,
    TRANSITION_CANDIDATES,
]
GLOBAL_DEDUPE_REVIEW_SOURCES = [
    MANIFEST_DIR / "development_judgment_review.json",
    V2_REVIEW,
    PRESCREEN_REVIEW,
    BALANCED_REVIEW,
    TRANSITION_REVIEW,
]


class BudgetExceeded(RuntimeError):
    pass


class DocumentTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def normalize_text(text: str) -> str:
    text = html.unescape(text)
    text = " ".join(text.split())
    return text.strip()


def extract_document_text(document_payload: dict[str, Any] | None) -> str:
    if not isinstance(document_payload, dict):
        return ""
    value = document_payload.get("doc")
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = DocumentTextExtractor()
    parser.feed(value)
    parser.close()
    return normalize_text(" ".join(parser.parts))


def document_text_quality(text: str) -> str:
    if not text:
        return "unavailable"
    if len(text) < 500:
        return "sparse"
    return "usable"


def pre_download_decision(candidate_decision: str) -> str:
    if candidate_decision == "reject":
        return "reject_before_download"
    if candidate_decision == "accept_candidate":
        return "download"
    return "needs_more_evidence"


def stats_total(client: IndianKanoonClient) -> int:
    return int(client.get_request_stats()["total_requests"])


def enforce_budget(client: IndianKanoonClient, max_api_requests: int) -> None:
    if stats_total(client) >= max_api_requests:
        raise BudgetExceeded("api_request_budget_reached")


def load_quotas(path: Path | None = None) -> dict[str, int]:
    return {str(record["offence_family"]): int(record["target_quota"]) for record in load_manifest(path or QUOTA_MANIFEST)}


def active_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        if record.get("status") in {"validated", "needs_review"}:
            counts[str(record.get("offence_family"))] += 1
    return dict(counts)


def reviewable_count(records: list[dict[str, Any]]) -> int:
    return sum(1 for record in records if record.get("status") in {"validated", "needs_review"})


def gap_targets(records: list[dict[str, Any]], quotas: dict[str, int]) -> dict[str, int]:
    counts = active_counts(records)
    return {family: max(target - counts.get(family, 0), 0) for family, target in quotas.items()}


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_document_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value)
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    numeric = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if numeric:
        return date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
    month_name = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
        + "|".join(MONTHS)
        + r"),?\s+(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_name:
        return date(int(month_name.group(3)), MONTHS[month_name.group(2).lower()], int(month_name.group(1)))
    return None


def date_within_bounds(value: Any, from_date: str | None, to_date: str | None, fallback_year: int | None = None) -> bool:
    parsed = parse_document_date(value)
    lower = parse_iso_date(from_date)
    upper = parse_iso_date(to_date)
    if parsed:
        if lower and parsed < lower:
            return False
        if upper and parsed > upper:
            return False
        return True
    if fallback_year is None:
        return True
    if lower and fallback_year < lower.year:
        return False
    if upper and fallback_year > upper.year:
        return False
    return True


def document_year(value: Any) -> int | None:
    parsed = parse_document_date(value)
    if parsed:
        return parsed.year
    return parse_year(value)


def year_within_bounds(year: int | None, from_date: str | None, to_date: str | None) -> bool:
    return date_within_bounds(None, from_date, to_date, fallback_year=year)


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


def regime_evidence_snippets(text: str, limit: int = 8) -> list[str]:
    snippets: list[str] = []
    patterns = (
        r"Bharatiya\s+Nyaya\s+Sanhita,?\s*2023",
        r"Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita,?\s*2023",
        r"\bBNS\b",
        r"\bBNSS\b",
        r"Indian\s+Penal\s+Code",
        r"Code\s+of\s+Criminal\s+Procedure",
        r"\bIPC\b",
        r"\bCrPC\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(match.start() - 60, 0)
            end = min(match.end() + 60, len(text))
            snippet = " ".join(text[start:end].split())
            if snippet and snippet not in snippets:
                snippets.append(snippet[:180])
            if len(snippets) >= limit:
                return snippets
    return snippets


def review_record_for(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "local_id": record["local_id"],
        "source_document_id": record["source_document_id"],
        "case_name": record["case_name"],
        "offence_family": record["offence_family"],
        "source_url": record["source_url"],
        "automated_status": record.get("final_automated_decision") or record["status"],
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
        "year": document_year((metadata or result).get("date") or result.get("title")),
        "search_filter_result": "considered",
        "pre_download_decision": decision.get("pre_download_decision"),
        "pre_download_reasons": decision.get("pre_download_reasons", []),
        "document_text_available": decision.get("document_text_available"),
        "document_text_length": decision.get("document_text_length"),
        "document_text_quality": decision.get("document_text_quality"),
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


def dry_run(
    limit: int,
    max_api_requests: int,
    strategy_manifest: Path = STRATEGY_MANIFEST,
    query_manifest: Path = QUERY_MANIFEST,
) -> int:
    strategy = json.loads(strategy_manifest.read_text(encoding="utf-8"))
    queries = load_manifest(query_manifest)
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


def normalize_repo_path(path_value: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"path must be inside repository: {path_value}") from exc
    if must_exist and not resolved.exists():
        raise ValueError(f"path does not exist: {path_value}")
    return resolved


def repo_display_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "seen": len(records),
        "processed": len(records),
        "downloaded": sum(1 for record in records if record.get("raw_file_path")),
        "duplicates": sum(1 for record in records if "duplicate" in str(record.get("notes") or "")),
        "rejected": sum(1 for record in records if record.get("status") in {"reject", "rejected_pre_download", "failed"}),
    }


def refresh_bulk_state_counts(state: dict[str, Any], candidates: list[dict[str, Any]], client_stats: dict[str, Any] | None = None) -> None:
    state["candidate_counts"] = summarize_records(candidates)
    state["reviewable_counts"] = {
        "total": reviewable_count(candidates),
        "accept_candidate": sum(1 for record in candidates if record.get("final_automated_decision") == "accept_candidate"),
        "needs_review": sum(1 for record in candidates if record.get("final_automated_decision") == "needs_review"),
    }
    if client_stats is not None:
        state["request_stats"] = client_stats
    state["seen_source_ids"] = sorted({str(record.get("source_document_id")) for record in candidates if record.get("source_document_id")})
    state["processed_source_ids"] = list(state["seen_source_ids"])
    state["downloaded_source_ids"] = sorted({str(record.get("source_document_id")) for record in candidates if record.get("raw_file_path")})
    state["duplicate_source_ids"] = sorted({str(record.get("source_document_id")) for record in candidates if "duplicate" in str(record.get("notes") or "")})
    state["rejected_source_ids"] = sorted(
        {
            str(record.get("source_document_id"))
            for record in candidates
            if record.get("status") in {"reject", "rejected_pre_download", "failed"}
        }
    )


def bulk_manifest_paths(state_root: Path, run_id: str) -> tuple[Path, Path, Path, Path]:
    root = run_dir(state_root, run_id)
    return (
        root / "candidates.json",
        root / "review.json",
        root / "audit.json",
        root / "raw",
    )


def run_bulk_acquisition(
    *,
    run_id: str | None,
    resume_run_id: str | None,
    retry_failures_run_id: str | None,
    target_count: int,
    max_api_requests: int,
    query_manifest: Path,
    max_search_pages: int,
    delay: float,
    state_root: Path = DEFAULT_RUN_ROOT,
    batch_size: int = DEFAULT_BATCH_SIZE,
    client: IndianKanoonClient | None = None,
    bulk_stage: str = "stage_a_500",
) -> int:
    selected_run_id = retry_failures_run_id or resume_run_id or run_id or generate_run_id()
    selected_run_id = validate_run_id(selected_run_id)
    queries = load_bulk_queries(query_manifest, bulk_stage)
    if not queries:
        raise ValueError("no bulk query groups selected")
    expanded_query_manifest = run_dir(state_root, selected_run_id) / "expanded_queries.json"

    if resume_run_id or retry_failures_run_id:
        state = load_run_state(state_root, selected_run_id)
        current_reviewable = int(state.get("reviewable_counts", {}).get("total") or 0)
        if state.get("status") == "completed" and current_reviewable >= target_count:
            print(f"bulk run already completed: {selected_run_id}")
            return 0
        if expanded_query_manifest.exists():
            queries = load_manifest(expanded_query_manifest)
    else:
        state = create_run_state(
            selected_run_id,
            strategy_version="v2_recent_criminal_filter",
            query_manifest=repo_display_path(query_manifest),
            target_count=target_count,
            api_budget=max_api_requests,
            partitions=build_partitions(queries, target_count, max_search_pages),
            batch_size=batch_size,
        )
        start_new_run(state_root, state)
        write_manifest_atomic(expanded_query_manifest, queries)
    starting_request_stats = state.get("request_stats") or empty_request_stats()
    client = client or IndianKanoonClient()

    def cumulative_client_stats() -> dict[str, Any]:
        return merge_request_stats(starting_request_stats, client.get_request_stats())

    candidates_path, review_path, audit_path, raw_dir = bulk_manifest_paths(state_root, selected_run_id)
    state["status"] = "running"
    save_run_state(state_root, state)

    pending_partitions = [
        partition
        for partition in state.get("partitions", [])
        if partition.get("status") != "completed"
    ]
    if retry_failures_run_id:
        pending_partitions = [
            partition
            for partition in pending_partitions
            if any(item.get("partition_id") == partition.get("partition_id") and item.get("retryable") for item in state.get("failed_queue", []))
        ]

    for partition in pending_partitions:
        if reviewable_count(load_manifest(candidates_path)) >= target_count:
            break
        prior_requests = int(state.get("request_stats", {}).get("total_requests", 0))
        if prior_requests >= max_api_requests:
            state["status"] = "stopped_budget"
            save_run_state(state_root, state)
            print(f"bulk run stopped at API budget: {selected_run_id}")
            return 0
        remaining_api_requests = max_api_requests - prior_requests
        partition["status"] = "running"
        save_run_state(state_root, state)
        before = len(load_manifest(candidates_path))
        result = acquire(
            limit=target_count,
            max_api_requests=remaining_api_requests,
            query_id=str(partition["partition_id"]),
            query_manifest=expanded_query_manifest,
            judgment_manifest=candidates_path,
            review_manifest=review_path,
            audit_manifest=audit_path,
            raw_dir=raw_dir,
            delay=delay,
            max_search_pages=int(partition.get("max_pages") or max_search_pages),
            enforce_family_quotas=False,
            extra_duplicate_manifests=GLOBAL_DEDUPE_SOURCES,
            client=client,
        )
        candidates = load_manifest(candidates_path)
        after = len(candidates)
        partition["status"] = "completed" if result == 0 else "failed"
        partition["current_reviewable"] = reviewable_count([record for record in candidates if record.get("query_id") == partition["partition_id"]])
        partition["candidates_seen"] = after - before
        partition["pages_completed"] = list(range(int(partition.get("max_pages") or max_search_pages)))
        partition["last_page"] = (int(partition.get("max_pages") or max_search_pages) - 1) if partition["pages_completed"] else None
        refresh_bulk_state_counts(state, candidates, cumulative_client_stats())
        if after > before:
            new_records = candidates[before:after]
            append_batch(state_root, state, new_records[: int(state.get("batch_size") or batch_size)])
        save_run_state(state_root, state)
        if result != 0:
            state["status"] = "failed"
            save_run_state(state_root, state)
            return result

    refresh_bulk_state_counts(state, load_manifest(candidates_path), cumulative_client_stats())
    state["status"] = "completed" if reviewable_count(load_manifest(candidates_path)) >= target_count or all(p.get("status") == "completed" for p in state.get("partitions", [])) else "paused"
    save_run_state(state_root, state)
    stats_path = run_dir(state_root, selected_run_id) / "statistics.json"
    write_json_atomic(stats_path, run_statistics(state))
    print(json.dumps(run_statistics(state), sort_keys=True))
    return 0


def rebuild_global_dedupe_index(output_path: Path = GLOBAL_DEDUPE_INDEX) -> int:
    manifest_paths = [path for path in GLOBAL_DEDUPE_SOURCES if path.exists()]
    review_paths = [path for path in GLOBAL_DEDUPE_REVIEW_SOURCES if path.exists()]
    index = rebuild_dedupe_index(manifest_paths, output_path, review_paths)
    print(f"dedupe source records: {len(index['source_key_index'])}")
    return 0


def load_bulk_queries(path: Path, stage_id: str | None = None) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError(f"bulk plan must be a JSON object or query list: {path}")
    stages = payload.get("stages")
    if not isinstance(stages, list):
        raise ValueError(f"bulk plan missing stages: {path}")
    stage = next((item for item in stages if item.get("stage_id") == (stage_id or stages[0].get("stage_id"))), None)
    if not isinstance(stage, dict):
        raise ValueError(f"bulk plan stage not found: {stage_id}")
    queries: list[dict[str, Any]] = []
    for partition in stage.get("partitions", []):
        for query in partition.get("queries", []):
            query_record = dict(query)
            query_record.setdefault("query_id", partition["partition_id"])
            query_record.setdefault("offence_family", partition.get("family"))
            query_record.setdefault("temporal_track", partition.get("track"))
            query_record.setdefault("from_date", partition.get("from_date"))
            query_record.setdefault("to_date", partition.get("to_date"))
            query_record.setdefault("doctypes", "judgments")
            query_record.setdefault("target_quota", partition.get("target"))
            query_record.setdefault("court_preference", partition.get("court_preference"))
            queries.append(query_record)
    return queries


def load_bulk_plan(path: Path, stage_id: str | None = None) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"bulk plan must be a JSON object: {path}")
    stages = payload.get("stages")
    if not isinstance(stages, list):
        raise ValueError(f"bulk plan missing stages: {path}")
    stage = next((item for item in stages if item.get("stage_id") == (stage_id or "stage_a_500")), None)
    if not isinstance(stage, dict):
        raise ValueError(f"bulk plan stage not found: {stage_id or 'stage_a_500'}")
    return {"plan": payload, "stage": stage}


def validate_bulk_stage(stage: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    target = int(stage.get("target_count") or 0)
    family_targets = stage.get("family_targets") or {}
    temporal_targets = stage.get("temporal_targets") or {}
    partitions = stage.get("partitions") or []
    if family_targets and sum(int(value) for value in family_targets.values()) != target:
        errors.append("sum of family_targets must equal target_count")
    if temporal_targets and sum(int(value) for value in temporal_targets.values()) != target:
        errors.append("sum of temporal_targets must equal target_count")
    covered_families = {partition.get("family") for partition in partitions if partition.get("target", 0)}
    for family, count in family_targets.items():
        if int(count) > 0 and family not in covered_families:
            errors.append(f"positive family target lacks partition: {family}")
    partition_total = sum(int(partition.get("target") or 0) for partition in partitions)
    if partition_total < target:
        errors.append("partition target envelope is below target_count")
    return errors


def bulk_dry_run(
    *,
    plan_path: Path,
    stage_id: str,
    target_count: int,
    max_api_requests: int,
    max_search_pages: int,
    batch_size: int,
) -> int:
    loaded = load_bulk_plan(plan_path, stage_id)
    plan = loaded["plan"]
    stage = loaded["stage"]
    errors = validate_bulk_stage(stage)
    print("Bulk acquisition dry run")
    print("run mode: dry-run")
    print(f"plan ID: {plan.get('plan_id')}")
    print(f"selected stage: {stage.get('stage_id')}")
    print(f"target count: {stage.get('target_count', target_count)}")
    print(f"partition count: {len(stage.get('partitions') or [])}")
    print(f"family targets: {json.dumps(stage.get('family_targets') or {}, sort_keys=True)}")
    print(f"temporal targets: {json.dumps(stage.get('temporal_targets') or {}, sort_keys=True)}")
    print(f"global request budget: {stage.get('request_budget', max_api_requests)}")
    print(f"max pages: {stage.get('max_pages_per_query', max_search_pages)}")
    print(f"batch size: {stage.get('batch_size', batch_size)}")
    min_interval = os.getenv("INDIAN_KANOON_MIN_REQUEST_INTERVAL_MS", str(DEFAULT_MIN_REQUEST_INTERVAL_MS))
    max_retries = os.getenv("INDIAN_KANOON_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
    print(f"rate-limit settings: min_interval_ms={min_interval}, max_retries={max_retries}")
    print(f"quality guards: {repo_display_path(STRATEGY_MANIFEST)}")
    if errors:
        print(f"plan executable: no ({'; '.join(errors)})")
        return 2
    print("plan executable: yes")
    print("No Indian Kanoon API requests were made.")
    return 0


def acquire(
    limit: int = DEFAULT_LIMIT,
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
    query_id: str | None = None,
    offence_family: str | None = None,
    temporal_track: str | None = None,
    query_manifest: Path = QUERY_MANIFEST,
    judgment_manifest: Path = PRESCREEN_JUDGMENTS,
    review_manifest: Path = PRESCREEN_REVIEW,
    audit_manifest: Path = PRESCREEN_AUDIT,
    raw_dir: Path = RAW_DIR,
    delay: float = 1.0,
    max_search_pages: int = DEFAULT_MAX_SEARCH_PAGES,
    enforce_family_quotas: bool = True,
    extra_duplicate_manifests: list[Path] | None = None,
    client: IndianKanoonClient | None = None,
) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    client = client or IndianKanoonClient()
    queries = filtered_queries(load_manifest(query_manifest), query_id, offence_family, temporal_track)
    if not queries:
        raise ValueError("no v2 query groups selected")
    quotas = load_quotas()
    v1_records = load_manifest(V1_JUDGMENTS)
    prior_v2_records = load_manifest(V2_JUDGMENTS)
    prior_prescreen_records = load_manifest(PRESCREEN_JUDGMENTS)
    extra_duplicate_records = [
        record
        for manifest in (extra_duplicate_manifests or [])
        for record in load_manifest(manifest)
    ]
    records = load_manifest(judgment_manifest)
    reviews = load_manifest(review_manifest)
    audit = load_manifest(audit_manifest)
    accepted_counts = active_counts(records)
    seen_source_ids = {
        str(record.get("source_document_id"))
        for record_set in (v1_records, prior_v2_records, prior_prescreen_records, extra_duplicate_records, records, audit)
        for record in record_set
        if record.get("source_document_id")
    }
    query_download_counts: Counter[str] = Counter(
        str(record.get("query_id"))
        for record in records
        if record.get("status") in {"validated", "needs_review", "accept_candidate"}
        and record.get("query_id")
    )
    downloaded = 0
    target_reviewable = limit

    for query in queries:
        if reviewable_count(records) >= target_reviewable:
            break
        query_limit = int(query.get("target_quota") or limit)
        if query_download_counts[str(query["query_id"])] >= query_limit:
            continue
        family = str(query["offence_family"])
        if enforce_family_quotas and not quota_allows(family, accepted_counts, quotas):
            continue
        for page in range(max(1, max_search_pages)):
            if reviewable_count(records) >= target_reviewable:
                break
            if query_download_counts[str(query["query_id"])] >= query_limit:
                break
            if enforce_family_quotas and not quota_allows(family, accepted_counts, quotas):
                break
            enforce_budget(client, max_api_requests)
            try:
                search_response = client.search(
                    str(query["query"]),
                    page=page,
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
            results = extract_results(search_response)
            if not results:
                break

            for rank, result in enumerate(results, start=1 + (page * len(results))):
                if reviewable_count(records) >= target_reviewable:
                    break
                if query_download_counts[str(query["query_id"])] >= query_limit:
                    break
                if enforce_family_quotas and not quota_allows(family, accepted_counts, quotas):
                    break
                source_id = extract_source_document_id(result)
                if not source_id or source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)
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
                date_source = metadata.get("date") or result.get("date") or case_name
                year = document_year(date_source)
                if not date_within_bounds(date_source, query.get("from_date"), query.get("to_date"), fallback_year=year):
                    decision = {
                        "decision": "reject",
                        "reasons": ["outside_temporal_track"],
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
                    continue
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
                document_text = extract_document_text(document)
                document_quality = document_text_quality(document_text)
                pre_text = "\n".join(
                    part for part in (document_text, metadata_text(result, metadata, document)) if part
                )
                pre_decision = decide_candidate_quality(pre_text, base_record)
                pre_kind = pre_download_decision(pre_decision.decision)
                pre_decision_dict = pre_decision.to_dict()
                pre_decision_dict.update(
                    {
                        "pre_download_decision": pre_kind,
                        "pre_download_reasons": pre_decision.reasons,
                        "document_text_available": bool(document_text),
                        "document_text_length": len(document_text),
                        "document_text_quality": document_quality,
                    }
                )
                if pre_decision.decision == "reject":
                    rejected = dict(base_record)
                    rejected["status"] = "rejected_pre_download"
                    rejected["notes"] = "; ".join(pre_decision.reasons)
                    upsert_by_local_id(records, rejected)
                    upsert_by_local_id(audit, {"local_id": f"v2-audit-{source_id}", **audit_entry(query, rank, source_id, result, metadata, pre_decision_dict, candidate_api_before, stats_total(client))})
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
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"{safe_filename(source_id)}_{safe_filename(case_name or source_id)}{extension}"
                if raw_path.exists():
                    incoming_digest = hashlib.sha256(content).hexdigest()
                    if sha256_file(raw_path) != incoming_digest:
                        raw_path.write_bytes(content)
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
                    quotas=quotas if enforce_family_quotas else None,
                    duplicate=duplicate is not None,
                    corrupt=file_size(raw_path) == 0,
                )
                decision_dict = decision.to_dict()
                decision_dict.update(
                    {
                        "pre_download_decision": pre_kind,
                        "pre_download_reasons": pre_decision.reasons,
                        "document_text_available": bool(document_text),
                        "document_text_length": len(document_text),
                        "document_text_quality": document_quality,
                    }
                )
                full_record["legal_regime"] = decision.legal_regime
                full_record["quality_scores"] = {
                    "document_type": decision.document_type_score,
                    "criminal_relevance": decision.criminal_relevance_score,
                    "metadata_quality": decision.metadata_quality_score,
                }
                full_record["detected_statutes"] = decision.detected_statutes
                full_record["regime_evidence"] = regime_evidence_snippets(full_text)
                full_record["status"] = "validated" if decision.decision == "accept_candidate" else decision.decision
                full_record["final_automated_decision"] = decision.decision
                full_record["notes"] = "; ".join(decision.reasons) if decision.reasons else None
                upsert_by_local_id(records, full_record)
                full_record["document_text_available"] = bool(document_text)
                full_record["document_text_length"] = len(document_text)
                full_record["document_text_quality"] = document_quality
                upsert_by_local_id(audit, {"local_id": f"v2-audit-{source_id}", **audit_entry(query, rank, source_id, result, metadata, decision_dict, candidate_api_before, stats_total(client))})
                downloaded += 1
                query_download_counts[str(query["query_id"])] += 1
                if decision.decision in {"accept_candidate", "needs_review"}:
                    accepted_counts[family] = accepted_counts.get(family, 0) + 1
                    upsert_by_local_id(reviews, review_record_for(full_record))

    write_manifest_atomic(judgment_manifest, records)
    write_manifest_atomic(review_manifest, reviews)
    write_manifest_atomic(audit_manifest, audit)
    print(f"V2 documents downloaded: {downloaded}")
    print(f"Reviewable candidates: {reviewable_count(records)}")
    print(json.dumps(client.get_request_stats(), sort_keys=True))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--strategy", default=str(STRATEGY_MANIFEST))
    parser.add_argument("--query-id")
    parser.add_argument("--offence-family")
    parser.add_argument("--temporal-track")
    parser.add_argument("--max-api-requests", type=int, default=DEFAULT_MAX_API_REQUESTS)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--balanced", action="store_true", help="Use Step 0.4E balanced corpus manifests")
    parser.add_argument("--targeted-gap-fill", action="store_true", help="Use Step 0.4F targeted gap query manifest")
    parser.add_argument("--transition-validation", action="store_true", help="Use Step 0.4I transition validation manifests")
    parser.add_argument("--max-search-pages", type=int, default=DEFAULT_MAX_SEARCH_PAGES)
    parser.add_argument("--bulk", action="store_true", help="Run explicit bulk acquisition mode with durable run state")
    parser.add_argument("--run-id", help="Stable bulk run ID matching bulk_YYYYMMDD_HHMMSS_<suffix>")
    parser.add_argument("--resume", help="Resume an existing bulk run ID")
    parser.add_argument("--retry-failures", help="Retry retryable failures for an existing bulk run ID")
    parser.add_argument("--bulk-plan", default=str(BULK_PLAN_MANIFEST))
    parser.add_argument("--bulk-stage", default="stage_a_500")
    parser.add_argument("--bulk-stats", help="Print deterministic statistics for an existing bulk run ID")
    parser.add_argument("--rebuild-dedupe-index", action="store_true", help="Rebuild the generated global corpus dedupe index")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    args = parse_args(argv)
    strategy_manifest = Path(args.strategy)
    if args.rebuild_dedupe_index:
        return rebuild_global_dedupe_index()
    if args.bulk_stats:
        state = load_run_state(DEFAULT_RUN_ROOT, validate_run_id(args.bulk_stats))
        print(json.dumps(run_statistics(state), indent=2, sort_keys=True))
        return 0
    query_manifest = TRANSITION_QUERY_MANIFEST if args.transition_validation else GAP_QUERY_MANIFEST if args.targeted_gap_fill else BALANCED_QUERY_MANIFEST if args.balanced else QUERY_MANIFEST
    use_balanced_outputs = args.balanced or args.targeted_gap_fill
    if args.bulk or args.resume or args.retry_failures:
        try:
            bulk_plan = normalize_repo_path(args.bulk_plan)
            if args.dry_run:
                return bulk_dry_run(
                    plan_path=bulk_plan,
                    stage_id=args.bulk_stage,
                    target_count=args.limit,
                    max_api_requests=args.max_api_requests,
                    max_search_pages=args.max_search_pages,
                    batch_size=args.batch_size,
                )
            return run_bulk_acquisition(
                run_id=args.run_id,
                resume_run_id=args.resume,
                retry_failures_run_id=args.retry_failures,
                target_count=args.limit,
                max_api_requests=args.max_api_requests,
                query_manifest=bulk_plan,
                max_search_pages=args.max_search_pages,
                delay=args.delay,
                batch_size=args.batch_size,
                bulk_stage=args.bulk_stage,
            )
        except (BudgetExceeded, ValueError, FileExistsError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.transition_validation and args.limit > TRANSITION_MAX_LIMIT:
        print(f"transition validation limit capped at {TRANSITION_MAX_LIMIT}", file=sys.stderr)
        args.limit = TRANSITION_MAX_LIMIT
    if args.dry_run:
        return dry_run(
            args.limit,
            args.max_api_requests,
            strategy_manifest=strategy_manifest,
            query_manifest=query_manifest,
        )
    try:
        return acquire(
            limit=args.limit,
            max_api_requests=args.max_api_requests,
            query_id=args.query_id,
            offence_family=args.offence_family,
            temporal_track=args.temporal_track,
            query_manifest=query_manifest,
            judgment_manifest=TRANSITION_CANDIDATES if args.transition_validation else BALANCED_JUDGMENTS if use_balanced_outputs else PRESCREEN_JUDGMENTS,
            review_manifest=TRANSITION_REVIEW if args.transition_validation else BALANCED_REVIEW if use_balanced_outputs else PRESCREEN_REVIEW,
            audit_manifest=TRANSITION_AUDIT if args.transition_validation else BALANCED_AUDIT if use_balanced_outputs else PRESCREEN_AUDIT,
            raw_dir=TRANSITION_RAW_DIR if args.transition_validation else BALANCED_RAW_DIR if use_balanced_outputs else RAW_DIR,
            delay=args.delay,
            max_search_pages=args.max_search_pages,
            enforce_family_quotas=not args.transition_validation,
            extra_duplicate_manifests=[BALANCED_JUDGMENTS] if args.transition_validation else None,
        )
    except (BudgetExceeded, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
