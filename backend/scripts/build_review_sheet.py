"""Human review sheet for the step 24 three-configuration evaluation (RAG-003): 15 queries x 3 configurations.

Reads the raw outputs of ``run_three_config_eval.py`` (outside the repository) and writes, also outside the
repository:

- ``review_sheet.csv``: one row per cited authority (structured citation, or a case named in the answer text) and
  one answer-level row per answer. Configurations are blinded per query as X/Y/Z in a seeded random order;
- ``review_key.json``: the blinding key (which letter is which configuration), kept away from reviewers.

Reviewers fill, per answer row, ``legal_correctness`` (correct | partly_correct | incorrect | cannot_judge) and, per
authority row, ``citation_support`` (supported | partly | not_supported | incorrect_law), plus ``reviewer``.
``import_human_review.py`` validates a filled sheet and computes the human-verified grounding rate.

The 15 queries are a deterministic stratified sample of the 30: both modes, every difficulty, and the out-of-scope
queries (where an honest "not covered" answer is the correct one).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.run_three_config_eval import CONFIGS, EVAL_PATH, answer_text, case_references  # noqa: E402

SAMPLE_SIZE = 15
SEED = 20261030
COLUMNS = ["review_id", "example_id", "answer_label", "mode", "query", "row_type", "claim_id", "claim_text", "authority",
           "evidence_excerpt", "answer_summary", "legal_correctness", "citation_support", "reviewer", "notes"]
LEGAL_CORRECTNESS = {"correct", "partly_correct", "incorrect", "cannot_judge"}
CITATION_SUPPORT = {"supported", "partly", "not_supported", "incorrect_law"}


def stratified_sample(examples: list[dict[str, Any]], size: int = SAMPLE_SIZE, seed: int = SEED) -> list[str]:
    """Exactly 2 out-of-scope queries (seeded), then round-robin over (mode, difficulty) strata of the in-scope ones."""
    rng = random.Random(seed)
    out_of_scope = [e["example_id"] for e in examples if "negative_out_of_scope" in e["category"]]
    chosen = sorted(rng.sample(out_of_scope, min(2, len(out_of_scope))))
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for example in examples:
        if example["example_id"] not in out_of_scope:
            strata[(example["mode"], example["difficulty"])].append(example["example_id"])
    for ids in strata.values():
        rng.shuffle(ids)
    keys = sorted(strata)
    while len(chosen) < size and any(strata.values()):
        for key in keys:
            if strata[key] and len(chosen) < size:
                chosen.append(strata[key].pop())
    return sorted(chosen)


def rows_for_answer(record: dict[str, Any], label: str, review_prefix: str) -> list[dict[str, Any]]:
    evidence = {item["evidence_id"]: item for item in record.get("evidence") or []}
    base = {"example_id": record["example_id"], "answer_label": label, "mode": record["mode"], "query": record["query"]}
    summary = record.get("summary") or f"(no answer: {record['status']})"
    rows = [{**base, "row_type": "answer", "answer_summary": summary}]
    for claim in record.get("claims") or []:
        for citation in claim.get("citations") or []:
            item = evidence.get(citation.get("evidence_id"))
            authority = (citation.get("source_metadata") or {}).get("case_name") or (item or {}).get("case_name") or citation.get("evidence_id")
            rows.append({**base, "row_type": "citation", "claim_id": claim.get("claim_id"), "claim_text": claim.get("text"),
                         "authority": authority, "evidence_excerpt": (item or {}).get("text_excerpt", "(not in the retrieved evidence)")})
    for reference in case_references(answer_text(record.get("answer"), record.get("summary"), record.get("claims") or [])):
        rows.append({**base, "row_type": "text_reference", "authority": reference, "evidence_excerpt": "(named in the answer text)"})
    for index, row in enumerate(rows, start=1):
        row["review_id"] = f"{review_prefix}-{index:02d}"
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True, help="outside the repository")
    args = parser.parse_args(argv)
    out_dir = args.out_dir.resolve()
    if out_dir == REPO_ROOT or REPO_ROOT in out_dir.parents:
        raise SystemExit("refused: the review sheet holds answer text and goes outside the repository")

    examples = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["examples"]
    sample = stratified_sample(examples)
    rng = random.Random(SEED)
    rows, key = [], {}
    for example_id in sample:
        letters = ["X", "Y", "Z"]
        configs = list(CONFIGS)
        rng.shuffle(configs)
        key[example_id] = dict(zip(letters, configs))
        for letter, config in zip(letters, configs):
            path = args.raw_dir / config / f"{example_id}.json"
            if not path.exists():
                raise SystemExit(f"missing raw output {path}")
            rows += rows_for_answer(json.loads(path.read_text(encoding="utf-8")), letter, f"{example_id}-{letter}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "review_sheet.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})
    (out_dir / "review_key.json").write_text(json.dumps({"seed": SEED, "sample": sample, "key": key}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(sample), "answers": len(sample) * 3, "rows": len(rows), "sheet": str(out_dir / "review_sheet.csv")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
