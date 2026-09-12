"""Validate and aggregate the grounded legal answer evaluation set."""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
EVAL_PATH = MANIFEST_DIR / "legal_answer_eval.json"
REVIEWS_PATH = MANIFEST_DIR / "legal_answer_eval_reviews.json"
PAIR_MAP_PATH = MANIFEST_DIR / "legal_answer_eval_pair_map.json"

POSITIVE_DIMENSIONS = [
    "LEGAL_RELEVANCE",
    "LEGAL_CORRECTNESS",
    "GROUNDING_SUPPORT",
    "CITATION_QUALITY",
    "COMPLETENESS",
    "UNCERTAINTY_HANDLING",
    "REGIME_HANDLING",
    "ACTIONABILITY",
]
HALLUCINATION_DIMENSION = "HALLUCINATION_SEVERITY"
PREFERENCES = {"A", "B", "Tie"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-path", type=Path, default=EVAL_PATH)
    parser.add_argument("--reviews-path", type=Path, default=REVIEWS_PATH)
    parser.add_argument("--pair-map-path", type=Path, default=PAIR_MAP_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    eval_manifest = load_json(args.eval_path)
    reviews_manifest = load_json(args.reviews_path)
    pair_map = load_json(args.pair_map_path)
    errors = validate_eval_manifest(eval_manifest)
    errors.extend(validate_pair_map(eval_manifest, pair_map))
    errors.extend(validate_reviews(eval_manifest, reviews_manifest))
    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors}, indent=2))
        return 1
    completed = [review for review in reviews_manifest.get("reviews", []) if review.get("review_status") == "completed"]
    if not completed:
        print(json.dumps({"status": "READY_FOR_GENERATION_OR_REVIEW", "completed_reviews": 0, "metrics": {}}, indent=2))
        return 0
    print(json.dumps({"status": "REVIEWS_AGGREGATED", "completed_reviews": len(completed), "metrics": aggregate_reviews(completed)}, indent=2))
    return 0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_eval_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    examples = manifest.get("examples", [])
    ids = [example.get("example_id") for example in examples]
    if manifest.get("schema_version") != "legalai-grounded-answer-eval-v1":
        errors.append("unexpected eval schema_version")
    if len(examples) != 30:
        errors.append("eval manifest must contain exactly 30 examples")
    if len(ids) != len(set(ids)):
        errors.append("example_id values must be unique")
    if Counter(example.get("mode") for example in examples) != {"public": 15, "professional": 15}:
        errors.append("mode distribution must be 15 public and 15 professional")
    if Counter(example.get("difficulty") for example in examples) != {"basic": 10, "moderate": 10, "hard": 10}:
        errors.append("difficulty distribution must be 10 basic, 10 moderate, 10 hard")
    if any(example.get("review_status") != "pending" for example in examples):
        errors.append("all examples must remain pending before review")
    if any(example.get("human_scores") not in (None, {}, []) for example in examples):
        errors.append("human_scores must be empty before review")
    if any(has_answer_leakage(example) for example in examples):
        errors.append("examples must not contain benchmark answers or citation suggestions")
    category_counts = Counter(category for example in examples for category in example.get("category", []))
    required = {
        "mixed_transition": 4,
        "special_statute": 4,
        "explicit_section": 6,
        "plain_language_public": 8,
        "negative_out_of_scope": 3,
    }
    for category, minimum in required.items():
        if category_counts[category] < minimum:
            errors.append(f"{category} coverage below required minimum {minimum}")
    expected_dimensions = set(POSITIVE_DIMENSIONS + [HALLUCINATION_DIMENSION, "OVERALL_PREFERENCE"])
    if set(manifest.get("rubric", {}).get("dimensions", [])) != expected_dimensions:
        errors.append("rubric dimensions are not frozen as expected")
    if set(manifest.get("rubric", {}).get("positive_scale", {}).keys()) != {"0", "1", "2", "3", "4"}:
        errors.append("positive score scale must be 0-4")
    if set(manifest.get("rubric", {}).get("hallucination_scale", {}).keys()) != {"0", "1", "2", "3"}:
        errors.append("hallucination score scale must be 0-3")
    if not manifest.get("component_hashes", {}).get("backend/app/services/legal_answer_prompt.py"):
        errors.append("prompt hash is required")
    return errors


def has_answer_leakage(example: dict[str, Any]) -> bool:
    forbidden = {"ideal_answer", "reference_answer", "model_answer", "citation_suggestions", "retrieved_case_names"}
    return bool(forbidden.intersection(example))


def validate_pair_map(eval_manifest: dict[str, Any], pair_map: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    examples = eval_manifest.get("examples", [])
    pairs = pair_map.get("pairs", [])
    ids = [example["example_id"] for example in examples]
    if pair_map.get("pairing_version") != "legalai-answer-pairing-v1":
        errors.append("unexpected pairing version")
    if [pair.get("example_id") for pair in pairs] != ids:
        errors.append("pair map must match frozen example order")
    a_conditions = Counter(pair.get("display_A_condition") for pair in pairs)
    b_conditions = Counter(pair.get("display_B_condition") for pair in pairs)
    if a_conditions != {"LLM_ONLY": 15, "GROUNDED_RAG": 15}:
        errors.append("display A balance must be 15/15")
    if b_conditions != {"LLM_ONLY": 15, "GROUNDED_RAG": 15}:
        errors.append("display B balance must be 15/15")
    if any(pair.get("display_A_condition") == pair.get("display_B_condition") for pair in pairs):
        errors.append("paired display conditions must differ")
    if not pair_map.get("concealed_from_reviewer_packet"):
        errors.append("pair mapping must be concealed from reviewer packet")
    return errors


def validate_reviews(eval_manifest: dict[str, Any], reviews_manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ids = {example["example_id"] for example in eval_manifest.get("examples", [])}
    if reviews_manifest.get("rubric_version") != "legalai-answer-rubric-v1":
        errors.append("review rubric version mismatch")
    for index, review in enumerate(reviews_manifest.get("reviews", []), start=1):
        if review.get("example_id") not in ids:
            errors.append(f"review {index} references unknown example_id")
        if not review.get("reviewer_id"):
            errors.append(f"review {index} missing reviewer_id")
        if review.get("preference") not in PREFERENCES:
            errors.append(f"review {index} preference must be A, B, or Tie")
        for answer_key in ["A", "B"]:
            scores = review.get("scores", {}).get(answer_key, {})
            for dimension in POSITIVE_DIMENSIONS:
                if scores.get(dimension) not in {0, 1, 2, 3, 4}:
                    errors.append(f"review {index} {answer_key} {dimension} must be 0-4")
            if scores.get(HALLUCINATION_DIMENSION) not in {0, 1, 2, 3}:
                errors.append(f"review {index} {answer_key} hallucination severity must be 0-3")
    return errors


def aggregate_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    preference_counts = Counter(review["preference"] for review in reviews)
    for review in reviews:
        for answer_key in ["A", "B"]:
            scores = review["scores"][answer_key]
            for dimension in POSITIVE_DIMENSIONS + [HALLUCINATION_DIMENSION]:
                by_condition[answer_key][dimension].append(scores[dimension])
            by_condition[answer_key]["quality_composite"].append(mean(scores[dimension] for dimension in POSITIVE_DIMENSIONS))
    return {
        "display_dimension_means": {
            answer_key: {dimension: round(mean(values), 4) for dimension, values in dimensions.items()}
            for answer_key, dimensions in by_condition.items()
        },
        "pairwise_preference_counts": dict(preference_counts),
    }


if __name__ == "__main__":
    raise SystemExit(main())
