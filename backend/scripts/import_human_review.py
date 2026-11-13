"""Import a filled step 24 review sheet and compute the human-verified grounding rate (RAG-003).

Input: ``review_sheet.csv`` filled by reviewers and its ``review_key.json`` (both from ``build_review_sheet.py``).
Validation: every answer row has a ``legal_correctness`` value and every authority row (``citation`` or
``text_reference``) a ``citation_support`` value from the allowed sets, a ``reviewer``, and no duplicate
``review_id``. A sheet with errors is refused, with the row IDs.

Accepted values: the sheet's own scale (``build_review_sheet.LEGAL_CORRECTNESS``, ``CITATION_SUPPORT``) plus three
values the 2026-10 reviewer used that the sheet scale has no counterpart for. They are kept as categories of their own
(identity mapping, one-to-one; nothing is merged or renamed), counted, and left out of the rate denominators, like
``cannot_judge``:
- ``legal_correctness``: ``abstained`` (the answer gave a no-coverage answer instead of a legal answer) and
  ``no_answer`` (no answer was produced: a generation or provider failure);
- ``citation_support``: ``not_applicable`` (the row is not an authority, e.g. a scorer artefact).

Output per configuration (unblinded with the key):
- human-verified grounding rate, strict: supported / judged authorities; lenient: (supported + partly) / judged;
  judged authorities exclude ``not_applicable``;
- the same counts split by row type (``citation``: structured citations, comparable with the structural grounding
  rate; ``text_reference``: cases named in the answer text);
- incorrect-law share among judged authorities;
- legal correctness counts and the share of answers judged correct (``cannot_judge``, ``abstained`` and
  ``no_answer`` excluded).

``--output`` writes the result JSON (aggregates only, no answer text), e.g. into the run folder
``data/evaluation/runs/2026-10_v3_groq/human_review/``.

**Round 2** (``--round 2``; sheet from ``build_review_round2.py``): a re-review, with full cited passages, of the round 1
authority rows not judged ``supported``. Round 2 is recorded *alongside* round 1 and never overwrites it:
- ``--round1-sheet`` is the reviewed round 1 sheet, read only; every round 2 row must be one of its authority rows not
  judged ``supported``, with an unchanged ``r1_support``, and every such row must be re-judged;
- the output (e.g. ``result_round2.json``) holds, per configuration, the round 1 rates, the round 2 rates (round 1
  with the re-reviewed rows replaced by their round 2 judgment) and the change, plus the round 1 -> round 2
  transitions. Writing over a round 1 result file is refused.
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

# Values outside the sheet scale, accepted as their own categories and excluded from the denominators (see above).
LEGAL_CORRECTNESS_NOT_JUDGED = {"cannot_judge", "abstained", "no_answer"}
CITATION_SUPPORT_NOT_JUDGED = {"not_applicable"}
ACCEPTED_LEGAL_CORRECTNESS = LEGAL_CORRECTNESS | LEGAL_CORRECTNESS_NOT_JUDGED
ACCEPTED_CITATION_SUPPORT = CITATION_SUPPORT | CITATION_SUPPORT_NOT_JUDGED


def validate(rows: list[dict[str, str]]) -> list[str]:
    errors, seen = [], set()
    for row in rows:
        review_id = row.get("review_id", "")
        if review_id in seen:
            errors.append(f"{review_id}: duplicate review_id")
        seen.add(review_id)
        kind = row.get("row_type")
        if kind == "answer":
            if row.get("legal_correctness", "").strip() not in ACCEPTED_LEGAL_CORRECTNESS:
                errors.append(f"{review_id}: legal_correctness must be one of {sorted(ACCEPTED_LEGAL_CORRECTNESS)}")
        elif kind in {"citation", "text_reference"}:
            if row.get("citation_support", "").strip() not in ACCEPTED_CITATION_SUPPORT:
                errors.append(f"{review_id}: citation_support must be one of {sorted(ACCEPTED_CITATION_SUPPORT)}")
        else:
            errors.append(f"{review_id}: unknown row_type {kind!r}")
        if not row.get("reviewer", "").strip():
            errors.append(f"{review_id}: reviewer is empty")
    return errors


def _rates(counts: Counter) -> dict[str, Any]:
    judged = sum(n for value, n in counts.items() if value not in CITATION_SUPPORT_NOT_JUDGED)
    return {
        "authorities_judged": judged,
        "citation_support": dict(counts),
        "human_grounding_rate_strict": round(counts["supported"] / judged, 4) if judged else None,
        "human_grounding_rate_lenient": round((counts["supported"] + counts["partly"]) / judged, 4) if judged else None,
        "incorrect_law_share": round(counts["incorrect_law"] / judged, 4) if judged else None,
    }


def compute(rows: list[dict[str, str]], key: dict[str, Any]) -> dict[str, Any]:
    support: dict[str, Counter] = defaultdict(Counter)
    support_by_type: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    correctness: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        config = key["key"][row["example_id"]][row["answer_label"]]
        if row["row_type"] == "answer":
            correctness[config][row["legal_correctness"].strip()] += 1
        else:
            value = row["citation_support"].strip()
            support[config][value] += 1
            support_by_type[config][row["row_type"]][value] += 1
    result = {}
    for config in sorted(set(support) | set(correctness)):
        judged_answers = sum(n for value, n in correctness[config].items() if value not in LEGAL_CORRECTNESS_NOT_JUDGED)
        result[config] = {
            **_rates(support[config]),
            "by_row_type": {row_type: _rates(counts) for row_type, counts in sorted(support_by_type[config].items())},
            "answers_judged": sum(correctness[config].values()),
            "answers_judged_for_correctness": judged_answers,
            "legal_correctness": dict(correctness[config]),
            "answers_correct_share": round(correctness[config]["correct"] / judged_answers, 4) if judged_answers else None,
        }
    return result


def validate_round2(round2: list[dict[str, str]], round1: list[dict[str, str]]) -> list[str]:
    """Round 2 rows must re-judge exactly the round 1 authority rows not judged ``supported``."""
    expected = {row["review_id"]: row for row in round1
                if row["row_type"] in {"citation", "text_reference"} and row["citation_support"].strip() != "supported"}
    errors, seen = [], set()
    for row in round2:
        review_id = row.get("review_id", "")
        if review_id in seen:
            errors.append(f"{review_id}: duplicate review_id")
        seen.add(review_id)
        original = expected.get(review_id)
        if original is None:
            errors.append(f"{review_id}: not a round 1 authority row awaiting re-review")
            continue
        for column in ("example_id", "answer_label", "row_type"):
            if row.get(column, "") != original[column]:
                errors.append(f"{review_id}: {column} differs from round 1")
        if row.get("r1_support", "").strip() != original["citation_support"].strip():
            errors.append(f"{review_id}: r1_support differs from the round 1 judgment")
        if row.get("citation_support", "").strip() not in ACCEPTED_CITATION_SUPPORT:
            errors.append(f"{review_id}: citation_support must be one of {sorted(ACCEPTED_CITATION_SUPPORT)}")
        if not row.get("reviewer", "").strip():
            errors.append(f"{review_id}: reviewer is empty")
    errors += [f"{review_id}: missing from round 2" for review_id in sorted(set(expected) - seen)]
    return errors


def _headline(rates: dict[str, Any]) -> dict[str, Any]:
    keys = ("authorities_judged", "citation_support", "human_grounding_rate_strict", "human_grounding_rate_lenient", "incorrect_law_share")
    return {**{key: rates[key] for key in keys}, "by_row_type": rates["by_row_type"]}


def _change(before: float | None, after: float | None) -> float | None:
    return None if before is None or after is None else round(after - before, 4)


def compute_round2(round1: list[dict[str, str]], round2: list[dict[str, str]], key: dict[str, Any]) -> dict[str, Any]:
    """Round 1 rates, round 2 rates (round 1 with the re-reviewed rows replaced) and the change, per configuration."""
    replaced = {row["review_id"]: row["citation_support"].strip() for row in round2}
    merged = [{**row, "citation_support": replaced.get(row["review_id"], row["citation_support"])} for row in round1]
    first, second = compute(round1, key), compute(merged, key)
    transitions: dict[str, Counter] = defaultdict(Counter)
    for row in round2:
        config = key["key"][row["example_id"]][row["answer_label"]]
        transitions[config][f"{row['r1_support'].strip()} -> {row['citation_support'].strip()}"] += 1
    result = {}
    for config in sorted(first):
        if not first[config]["authorities_judged"] and not second[config]["authorities_judged"]:
            result[config] = {"round1": None, "round2": None, "change": None, "re_reviewed": 0, "transitions": {}}
            continue
        r1, r2 = _headline(first[config]), _headline(second[config])
        result[config] = {
            "round1": r1,
            "round2": r2,
            "change": {
                "human_grounding_rate_strict": _change(r1["human_grounding_rate_strict"], r2["human_grounding_rate_strict"]),
                "human_grounding_rate_lenient": _change(r1["human_grounding_rate_lenient"], r2["human_grounding_rate_lenient"]),
                "incorrect_law_share": _change(r1["incorrect_law_share"], r2["incorrect_law_share"]),
            },
            "re_reviewed": sum(transitions[config].values()),
            "transitions": dict(sorted(transitions[config].items())),
        }
    return result


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _refuse(errors: list[str], what: str) -> None:
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        raise SystemExit(f"refused: {len(errors)} problem(s) in the {what}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--round", type=int, choices=(1, 2), default=1)
    parser.add_argument("--round1-sheet", type=Path, help="with --round 2: the reviewed round 1 sheet (read only)")
    args = parser.parse_args(argv)
    if args.round == 2:
        return _main_round2(args)
    rows = _read(args.sheet)
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


def _main_round2(args: argparse.Namespace) -> int:
    if args.round1_sheet is None:
        raise SystemExit("refused: --round 2 needs --round1-sheet")
    if args.output and args.output.exists():
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        if existing.get("round") != 2:
            raise SystemExit(f"refused: {args.output} is a round 1 result; round 2 never overwrites round 1")
    round1, round2 = _read(args.round1_sheet), _read(args.sheet)
    _refuse(validate(round1), "round 1 sheet")
    _refuse(validate_round2(round2, round1), "round 2 sheet")
    key = json.loads(args.key.read_text(encoding="utf-8"))
    result = {
        "round": 2,
        "round1_reviewers": sorted({row["reviewer"].strip() for row in round1}),
        "round2_reviewers": sorted({row["reviewer"].strip() for row in round2}),
        "re_reviewed_rows": len(round2),
        "configurations": compute_round2(round1, round2, key),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
