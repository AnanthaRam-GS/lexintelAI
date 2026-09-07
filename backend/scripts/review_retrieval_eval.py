"""Apply a human relevance judgment to the retrieval evaluation manifest."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.retrieval.evaluation import apply_review
from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH


def parse_relevance(value: str) -> int | str:
    if value == "uncertain":
        return value
    parsed = int(value)
    if parsed not in {0, 1, 2}:
        raise argparse.ArgumentTypeError("relevance must be 0, 1, 2, or uncertain")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judgments-path", type=Path, default=JUDGMENTS_PATH)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--chunk-id", required=True)
    parser.add_argument("--relevance", required=True, type=parse_relevance)
    parser.add_argument("--document-relevant", required=True, choices=["yes", "no", "uncertain"])
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--reviewed-at", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reviewed_at = args.reviewed_at or datetime.now(UTC).isoformat()
    updated = apply_review(args.judgments_path, args.query_id, args.chunk_id, args.relevance, args.document_relevant, args.reviewer, reviewed_at, args.notes)
    print(f"updated {updated['query_id']} {updated['chunk_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
