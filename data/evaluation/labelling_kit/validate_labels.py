"""Check a completed labelling sheet and merge it into a NEW retrieval-benchmark version (step 24 labelling kit).

Checks (any failure refuses the merge and lists the rows):
- every ``human_relevance`` is 2, 1, 0 or uncertain; every ``document_relevant`` is yes, no or uncertain;
- no empty label and no empty ``reviewer``;
- no duplicate (query_id, chunk_id);
- every sheet row is a candidate in ``pool_traces.json`` and every pooled candidate is labelled;
- every query in the queries CSV has labels, and no query reuses a frozen ID (eval-q001..030).

Merge: writes ``--out-dir`` (e.g. ``data/evaluation/benchmarks/retrieval_v2``) with ``queries.json``,
``judgments.json`` and ``pool_traces.json`` = the frozen 30-query benchmark (read, verified by its hashes, never
modified) plus the new queries, and ``MANIFEST.json`` (version, counts, frozen input hashes). The frozen files in
``data/structured/manifests`` are never written; the script refuses that directory as output.

Usage:
    .venv/bin/python data/evaluation/labelling_kit/validate_labels.py --queries my_queries.csv \\
        --sheet completed_sheet.csv --traces /tmp/pools/pool_traces.json --out-dir data/evaluation/benchmarks/retrieval_v2
    (add --check-only to validate without merging)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FROZEN_DIR = REPO_ROOT / "data/structured/manifests"
FROZEN = {"queries": FROZEN_DIR / "retrieval_eval_queries.json", "judgments": FROZEN_DIR / "retrieval_eval_judgments.json",
          "traces": FROZEN_DIR / "retrieval_eval_pool_traces.json"}
RELEVANCE = {"2": 2, "1": 1, "0": 0, "uncertain": "uncertain"}
DOCUMENT = {"yes", "no", "uncertain"}
NEW_VERSION = "legalai-retrieval-eval-v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def check(queries: list[dict[str, str]], sheet: list[dict[str, str]], traces: list[dict[str, Any]], frozen_ids: set[str]) -> list[str]:
    errors = []
    query_ids = {q["query_id"] for q in queries}
    for query_id in sorted(query_ids & frozen_ids):
        errors.append(f"{query_id}: reuses a frozen query ID")
    pooled = {(t["query_id"], t["chunk_id"]) for t in traces}
    seen = set()
    for number, row in enumerate(sheet, start=2):
        key = (row.get("query_id", ""), row.get("chunk_id", ""))
        where = f"sheet line {number} ({key[0]} {key[1]})"
        if key in seen:
            errors.append(f"{where}: duplicate candidate")
        seen.add(key)
        if key not in pooled:
            errors.append(f"{where}: not a pooled candidate in pool_traces.json")
        if key[0] not in query_ids:
            errors.append(f"{where}: query not in the queries CSV")
        if row.get("human_relevance", "") == "":
            errors.append(f"{where}: human_relevance is missing")
        elif row["human_relevance"] not in RELEVANCE:
            errors.append(f"{where}: human_relevance must be 2, 1, 0 or uncertain (got {row['human_relevance']!r})")
        if row.get("document_relevant", "") == "":
            errors.append(f"{where}: document_relevant is missing")
        elif row["document_relevant"] not in DOCUMENT:
            errors.append(f"{where}: document_relevant must be yes, no or uncertain (got {row['document_relevant']!r})")
        if not row.get("reviewer"):
            errors.append(f"{where}: reviewer is missing")
    for query_id, chunk_id in sorted(pooled - seen):
        errors.append(f"{query_id} {chunk_id}: pooled candidate has no label row")
    for query_id in sorted(query_ids - {key[0] for key in seen}):
        errors.append(f"{query_id}: no labels")
    return errors


def merge(queries: list[dict[str, str]], sheet: list[dict[str, str]], traces: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    if out_dir.resolve() == FROZEN_DIR.resolve():
        raise SystemExit("refused: the frozen manifests directory is never written")
    before = {name: sha256(path) for name, path in FROZEN.items()}
    frozen_queries = json.loads(FROZEN["queries"].read_text(encoding="utf-8"))
    frozen_judgments = json.loads(FROZEN["judgments"].read_text(encoding="utf-8"))
    frozen_traces = json.loads(FROZEN["traces"].read_text(encoding="utf-8"))
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_queries = [{"evaluation_version": NEW_VERSION, "query_id": q["query_id"], "query_text": q["query_text"], "mode": q["mode"],
                    "intended_statutes_or_topic": q["intended_statutes_or_topic"], "query_type": q.get("query_type") or None,
                    "target_family": q.get("target_family") or None, "target_regime": q.get("target_regime") or None,
                    "author": q["author"], "notes": q.get("notes", "")} for q in queries]
    new_judgments = [{"evaluation_version": NEW_VERSION, "query_id": row["query_id"], "chunk_id": row["chunk_id"],
                      "document_id": row.get("document_id"), "case_title": row.get("case_title"), "blinded_order": int(row["blinded_order"]),
                      "human_status": "reviewed", "human_relevance": RELEVANCE[row["human_relevance"]],
                      "document_relevant": row["document_relevant"], "reviewer": row["reviewer"], "reviewed_at": reviewed_at,
                      "notes": row.get("notes", "")} for row in sheet]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "queries.json").write_text(json.dumps(frozen_queries + new_queries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "judgments.json").write_text(json.dumps(frozen_judgments + new_judgments, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "pool_traces.json").write_text(json.dumps(frozen_traces + traces, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    after = {name: sha256(path) for name, path in FROZEN.items()}
    if before != after:
        raise SystemExit("frozen benchmark files changed during the merge")
    manifest = {"version": NEW_VERSION, "created_at": reviewed_at, "base": "legalai-retrieval-eval-v1 (frozen, unchanged)",
                "frozen_input_sha256": before, "queries": {"frozen": len(frozen_queries), "new": len(new_queries)},
                "judgments": {"frozen": len(frozen_judgments), "new": len(new_judgments)}}
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    queries, sheet = read_csv(args.queries), read_csv(args.sheet)
    traces = json.loads(args.traces.read_text(encoding="utf-8"))
    frozen_ids = {q["query_id"] for q in json.loads(FROZEN["queries"].read_text(encoding="utf-8"))}
    errors = check(queries, sheet, traces, frozen_ids)
    if errors:
        print("\n".join(errors[:100]), file=sys.stderr)
        raise SystemExit(f"refused: {len(errors)} problem(s); nothing was merged")
    print(json.dumps({"queries": len(queries), "labels": len(sheet), "status": "valid"}))
    if args.check_only:
        return 0
    if args.out_dir is None:
        raise SystemExit("--out-dir is required to merge (or use --check-only)")
    print(json.dumps(merge(queries, sheet, traces, args.out_dir), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
