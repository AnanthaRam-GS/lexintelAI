"""Durable state helpers for staged bulk corpus acquisition."""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.scripts.corpus_utils import load_manifest


RUN_ID_PATTERN = re.compile(r"^bulk_\d{8}_\d{6}_[a-z0-9]{4,12}$")
CHECKPOINT_VERSION = 1
RUN_STATUSES = {
    "created",
    "running",
    "paused",
    "completed",
    "failed",
    "stopped_budget",
    "stopped_provider",
    "stopped_quality",
}
DEFAULT_BATCH_SIZE = 100
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_ROOT = REPO_ROOT / "data/processed/acquisition_runs"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def generate_run_id(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    suffix = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
    return f"bulk_{current.strftime('%Y%m%d_%H%M%S')}_{suffix}"


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.match(run_id):
        raise ValueError("run_id must match bulk_YYYYMMDD_HHMMSS_<4-12 lowercase letters/digits>")
    return run_id


def run_dir(root: Path, run_id: str) -> Path:
    return root / validate_run_id(run_id)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2, sort_keys=True)
            file_obj.write("\n")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON checkpoint must be an object: {path}")
    return payload


def empty_request_stats() -> dict[str, Any]:
    return {
        "total_requests": 0,
        "requests_by_endpoint": {
            "search": 0,
            "document": 0,
            "metadata": 0,
            "original_document": 0,
            "other": 0,
        },
        "responses_by_category": {
            "2xx": 0,
            "4xx": 0,
            "429": 0,
            "5xx": 0,
            "other": 0,
        },
    }


def partition_from_query(query: dict[str, Any], target: int, max_pages: int, budget: int | None = None) -> dict[str, Any]:
    return {
        "partition_id": str(query["query_id"]),
        "family": query.get("offence_family"),
        "track": query.get("temporal_track"),
        "court": query.get("court_preference"),
        "from_date": query.get("from_date"),
        "to_date": query.get("to_date"),
        "query_ids": [query.get("query_id")],
        "target": target,
        "current_reviewable": 0,
        "status": "pending",
        "pages_completed": [],
        "last_page": None,
        "last_candidate_rank": 0,
        "candidates_seen": 0,
        "request_budget": budget,
        "request_count": 0,
        "max_pages": max_pages,
    }


def build_partitions(queries: list[dict[str, Any]], default_target: int, max_pages: int) -> list[dict[str, Any]]:
    partitions: list[dict[str, Any]] = []
    seen_partition_ids: set[str] = set()
    for query in queries:
        partition_id = str(query["query_id"])
        if partition_id in seen_partition_ids:
            continue
        seen_partition_ids.add(partition_id)
        target = int(query.get("target_quota") or default_target)
        partitions.append(partition_from_query(query, target=target, max_pages=max_pages))
    return partitions


def create_run_state(
    run_id: str,
    *,
    strategy_version: str,
    query_manifest: str,
    target_count: int,
    api_budget: int,
    partitions: list[dict[str, Any]],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "run_id": validate_run_id(run_id),
        "strategy_version": strategy_version,
        "started_at": now,
        "last_updated_at": now,
        "status": "created",
        "query_manifest": query_manifest,
        "configured_target": target_count,
        "api_budget": api_budget,
        "request_stats": empty_request_stats(),
        "partitions": partitions,
        "candidate_counts": {"seen": 0, "processed": 0, "downloaded": 0, "duplicates": 0, "rejected": 0},
        "reviewable_counts": {"total": 0, "accept_candidate": 0, "needs_review": 0},
        "failure_counts": {},
        "checkpoint_version": CHECKPOINT_VERSION,
        "seen_source_ids": [],
        "processed_source_ids": [],
        "downloaded_source_ids": [],
        "duplicate_source_ids": [],
        "rejected_source_ids": [],
        "failed_queue": [],
        "batches": [],
        "batch_size": batch_size,
    }


def save_run_state(root: Path, state: dict[str, Any]) -> None:
    if state.get("status") not in RUN_STATUSES:
        raise ValueError(f"invalid run status: {state.get('status')}")
    state = dict(state)
    state["last_updated_at"] = utc_now()
    write_json_atomic(run_dir(root, str(state["run_id"])) / "state.json", state)


def start_new_run(root: Path, state: dict[str, Any]) -> None:
    path = run_dir(root, str(state["run_id"]))
    if path.exists():
        raise FileExistsError(f"bulk run already exists: {state['run_id']}")
    path.mkdir(parents=True)
    (path / "batches").mkdir()
    save_run_state(root, state)


def load_run_state(root: Path, run_id: str) -> dict[str, Any]:
    state = read_json_object(run_dir(root, run_id) / "state.json")
    if state.get("run_id") != run_id:
        raise ValueError("checkpoint run_id does not match requested run")
    if state.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("unsupported checkpoint version")
    if state.get("status") not in RUN_STATUSES:
        raise ValueError(f"invalid run status: {state.get('status')}")
    return state


def merge_request_stats(existing: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    merged = empty_request_stats()
    merged["total_requests"] = int(existing.get("total_requests", 0)) + int(latest.get("total_requests", 0))
    for group in ("requests_by_endpoint", "responses_by_category"):
        for key in merged[group]:
            merged[group][key] = int(existing.get(group, {}).get(key, 0)) + int(latest.get(group, {}).get(key, 0))
    return merged


def append_unique(state: dict[str, Any], key: str, value: str) -> None:
    values = list(state.setdefault(key, []))
    if value not in values:
        values.append(value)
        state[key] = values


def queue_failure(
    state: dict[str, Any],
    *,
    source_document_id: str | None,
    partition_id: str,
    stage: str,
    failure_type: str,
    retryable: bool,
    error_code: str | int | None = None,
) -> None:
    item = {
        "source_document_id": source_document_id,
        "partition_id": partition_id,
        "stage": stage,
        "failure_type": failure_type,
        "attempts": 1,
        "last_error_code": None if error_code is None else str(error_code),
        "last_attempt_at": utc_now(),
        "retryable": retryable,
    }
    state.setdefault("failed_queue", []).append(item)
    counts = dict(state.setdefault("failure_counts", {}))
    counts[failure_type] = int(counts.get(failure_type, 0)) + 1
    state["failure_counts"] = counts


def next_batch_path(root: Path, state: dict[str, Any]) -> Path:
    return run_dir(root, str(state["run_id"])) / "batches" / f"batch_{len(state.get('batches', [])) + 1:04d}.json"


def append_batch(root: Path, state: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path = next_batch_path(root, state)
    write_json_atomic(path, records)
    rel_path = str(path.relative_to(run_dir(root, str(state["run_id"]))))
    state.setdefault("batches", []).append({"path": rel_path, "record_count": len(records)})


def iter_manifest_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(load_manifest(path))
    return records


STATUS_RANK = {
    "human_accepted": 5,
    "human_rejected": 4,
    "automated_reviewable": 3,
    "automated_rejected": 2,
    "failed": 1,
    "unknown": 0,
}


def canonical_status(record: dict[str, Any], review_by_source_id: dict[str, str] | None = None) -> str:
    source_id = str(record.get("source_document_id") or "")
    human_status = (review_by_source_id or {}).get(source_id)
    if human_status == "accepted":
        return "human_accepted"
    if human_status == "rejected":
        return "human_rejected"
    decision = record.get("final_automated_decision")
    status = record.get("status")
    if decision in {"accept_candidate", "needs_review"} or status in {"validated", "needs_review", "accept_candidate"}:
        return "automated_reviewable"
    if decision == "reject" or status in {"reject", "rejected_pre_download", "excluded_duplicate", "excluded_irrelevant"}:
        return "automated_rejected"
    if status == "failed":
        return "failed"
    return "unknown"


def _source_manifest(path: Path, record: dict[str, Any]) -> str:
    if record.get("source_manifest"):
        return str(record["source_manifest"])
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def rebuild_dedupe_index(
    manifest_paths: list[Path],
    output_path: Path,
    review_manifest_paths: list[Path] | None = None,
) -> dict[str, Any]:
    review_by_source_id: dict[str, str] = {}
    for review_path in review_manifest_paths or []:
        for review in load_manifest(review_path):
            source_id = review.get("source_document_id")
            status = review.get("human_review_status")
            if source_id and status in {"accepted", "rejected"}:
                review_by_source_id[str(source_id)] = str(status)

    source_index: dict[str, dict[str, Any]] = {}
    sha_aliases: dict[str, list[dict[str, str]]] = {}
    for path in manifest_paths:
        for record in load_manifest(path):
            provider = str(record.get("source_provider") or "")
            source_id = str(record.get("source_document_id") or "")
            if not provider or not source_id:
                continue
            source_key = f"{provider}:{source_id}"
            status = canonical_status(record, review_by_source_id)
            source_manifest = _source_manifest(path, record)
            existing = source_index.get(source_key)
            if existing is None:
                source_index[source_key] = {
                    "provider": provider,
                    "source_document_id": source_id,
                    "sha256": record.get("sha256"),
                    "canonical_record": record.get("local_id") or record.get("document_id"),
                    "canonical_status": status,
                    "status_precedence": STATUS_RANK[status],
                    "first_seen_run_id": record.get("run_id"),
                    "seen_in_manifests": [source_manifest],
                    "all_statuses": [status],
                }
            else:
                if source_manifest not in existing["seen_in_manifests"]:
                    existing["seen_in_manifests"].append(source_manifest)
                if status not in existing["all_statuses"]:
                    existing["all_statuses"].append(status)
                if STATUS_RANK[status] > int(existing.get("status_precedence", 0)):
                    existing["canonical_status"] = status
                    existing["status_precedence"] = STATUS_RANK[status]
                    existing["canonical_record"] = record.get("local_id") or record.get("document_id")
                if not existing.get("sha256") and record.get("sha256"):
                    existing["sha256"] = record.get("sha256")
            provider = str(record.get("source_provider") or "")
            sha = record.get("sha256")
            if sha:
                alias = {"provider": provider, "source_document_id": source_id}
                aliases = sha_aliases.setdefault(str(sha), [])
                if alias not in aliases:
                    aliases.append(alias)

    payload = {
        "version": 2,
        "status_precedence": ["human_accepted", "human_rejected", "automated_reviewable", "automated_rejected", "failed", "unknown"],
        "source_key_index": {
            key: source_index[key]
            for key in sorted(source_index)
        },
        "sha_index": {
            sha: {
                "sha256": sha,
                "alias_count": len(aliases),
                "aliases": sorted(aliases, key=lambda item: (item["provider"], item["source_document_id"])),
            }
            for sha, aliases in sorted(sha_aliases.items())
        },
    }
    write_json_atomic(output_path, payload)
    return payload


def run_statistics(state: dict[str, Any]) -> dict[str, Any]:
    partition_statuses = Counter(partition.get("status") for partition in state.get("partitions", []))
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "partitions": {
            "total": len(state.get("partitions", [])),
            "completed": partition_statuses.get("completed", 0),
            "pending": partition_statuses.get("pending", 0),
            "running": partition_statuses.get("running", 0),
            "failed": partition_statuses.get("failed", 0),
        },
        "search_candidates": state.get("candidate_counts", {}).get("seen", 0),
        "processed_candidates": state.get("candidate_counts", {}).get("processed", 0),
        "downloaded_documents": state.get("candidate_counts", {}).get("downloaded", 0),
        "reviewable_candidates": state.get("reviewable_counts", {}).get("total", 0),
        "duplicates": state.get("candidate_counts", {}).get("duplicates", 0),
        "rejections": state.get("candidate_counts", {}).get("rejected", 0),
        "failures": state.get("failure_counts", {}),
        "request_stats": state.get("request_stats", empty_request_stats()),
        "batches": state.get("batches", []),
    }
