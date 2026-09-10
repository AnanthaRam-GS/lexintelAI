"""Dry-run interface for the future grounded answer evaluation generation step."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_eval.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Validate future generation plan without model calls")
    parser.add_argument("--eval-path", type=Path, default=EVAL_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = json.loads(args.eval_path.read_text(encoding="utf-8"))
    examples = manifest["examples"]
    plan = {
        "status": "DRY_RUN_ONLY",
        "live_generation_executed": False,
        "llm_calls": 0,
        "conditions": ["LLM_ONLY", "GROUNDED_RAG"],
        "example_count": len(examples),
        "planned_outputs": len(examples) * 2,
        "llm_only_contract": manifest["conditions"]["CONDITION_A"]["description"],
        "grounded_rag_contract": manifest["conditions"]["CONDITION_B"]["description"],
        "model_source": manifest["model_control"]["model_source"],
    }
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
