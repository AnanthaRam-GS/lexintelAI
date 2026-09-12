"""Diagnostic CLI for legal query-understanding orchestration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_query_understanding import understand_legal_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a legal query without running retrieval or answer generation.")
    parser.add_argument("query", help="Raw legal query text")
    parser.add_argument(
        "--section-ranking-mode",
        choices=["deterministic", "cross_encoder_protected_hybrid"],
        default="deterministic",
        help="Section ranking mode. Cross-encoder mode falls back unless a ranker is injected by application code.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = understand_legal_query(args.query, section_ranking_mode=args.section_ranking_mode)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
