"""Import a filled step 24 review sheet and compute the human-verified grounding rate (RAG-003).

Input: ``review_sheet.csv`` filled by reviewers and its ``review_key.json`` (both from ``build_review_sheet.py``).
Validation: every answer row has a ``legal_correctness`` value and every authority row (``citation`` or
``text_reference``) a ``citation_support`` value from the allowed sets, a ``reviewer``, and no duplicate
``review_id``. A sheet with errors is refused, with the row IDs.

Output per configuration (unblinded with the key):
- human-verified grounding rate, strict: supported / judged authorities; lenient: (supported + partly) / judged;
- incorrect-law share among judged authorities;
- legal correctness counts and the share of answers judged correct (cannot_judge excluded).

``--output`` writes the result JSON (aggregates only, no answer text), e.g. into the run folder
``data/evaluation/runs/2026-10_v3_groq/human_review/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.build_review_sheet import CITATION_SUPPORT, LEGAL_CORRECTNESS  # noqa: E402


def validate(rows: list[dict[str, str]]) -> list[str]:
    errors, seen = [], set()
    for row in rows:
        review_id = row.get("review_id", "")
        if review_id in seen:
            errors.append(f"{review_id}: duplicate review_id")
        seen.add(review_id)
        kind = row.get("row_type")
        if kind == "answer":
            if row.get("legal_correctness", "").strip() not in LEGAL_CORRECTNESS:
                errors.append(f"{review_id}: legal_correctness must be one of {sorted(LEGAL_CORRECTNESS)}")
        elif kind in {"citation", "text_reference"}:
            if row.get("citation_support", "").strip() not in CITATION_SUPPORT:
                errors.append(f"{review_id}: citation_support must be one of {sorted(CITATION_SUPPORT)}")
        else:
            errors.append(f"{review_id}: unknown row_type {kind!r}")
        if not row.get("reviewer", "").strip():
            errors.append(f"{review_id}: reviewer is empty")
    return errors


def compute(rows: list[dict[str, str]], key: dict[str, Any]) -> dict[str, Any]:
    support: dict[str, Counter] = defaultdict(Counter)
    correctness: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        config = key["key"][row["example_id"]][row["answer_label"]]
        if row["row_type"] == "answer":
            correctness[config][row["legal_correctness"].strip()] += 1
        else:
            support[config][row["citation_support"].strip()] += 1
    result = {}
    for config in sorted(set(support) | set(correctness)):
        judged = sum(support[config].values())
        judged_answers = sum(n for value, n in correctness[config].items() if value != "cannot_judge")
        result[config] = {
            "authorities_judged": judged,
            "citation_support": dict(support[config]),
            "human_grounding_rate_strict": round(support[config]["supported"] / judged, 4) if judged else None,
            "human_grounding_rate_lenient": round((support[config]["supported"] + support[config]["partly"]) / judged, 4) if judged else None,
            "incorrect_law_share": round(support[config]["incorrect_law"] / judged, 4) if judged else None,
            "answers_judged": sum(correctness[config].values()),
            "legal_correctness": dict(correctness[config]),
            "answers_correct_share": round(correctness[config]["correct"] / judged_answers, 4) if judged_answers else None,
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.sheet.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    errors = validate(rows)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        raise SystemExit(f"refused: {len(errors)} problem(s) in the review sheet")
    key = json.loads(args.key.read_text(encoding="utf-8"))
    result = {"reviewed_rows": len(rows), "reviewers": sorted({row["reviewer"].strip() for row in rows}), "configurations": compute(rows, key)}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
