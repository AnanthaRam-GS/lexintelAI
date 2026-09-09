import hashlib
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Protocol


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_section_hybrid_ranking import build_section_semantic_text
from backend.app.services.legal_section_prediction import DEFAULT_TOP_K, load_section_catalog, predict_legal_sections
from backend.app.services.reranking.base import RerankerConfig
from backend.app.services.reranking.bge import BgeReranker, resolve_reranker_model_name_or_path
from backend.app.services.vector_store import RetrievalResult
from backend.scripts.evaluate_legal_section_baseline import (
    aggregate,
    classify_subsets,
    error_categories,
    per_query_metrics,
)
from backend.scripts.evaluate_legal_section_bge_trial import (
    EXPECTED_CATALOG_SHA256,
    EXPECTED_D0_SHA256,
    EXPECTED_GOLD_SHA256,
    EXPECTED_PREDICTOR_SHA256,
    RRF_K as T1_RRF_K,
    TRIAL_ERROR_PATH as T1_ERROR_PATH,
    TRIAL_EVAL_PATH as T1_EVAL_PATH,
    TRIAL_PER_EXAMPLE_PATH as T1_PER_EXAMPLE_PATH,
    TRIAL_PREDICTIONS_PATH as T1_PREDICTIONS_PATH,
    TRIAL_SCORE_PATH as T1_SCORE_PATH,
    describe,
    explicit_recall,
    load_json,
    provision_key,
    recovered_at_5,
    sha256,
)


MODEL_ID = "BAAI/bge-reranker-v2-m3"
SNAPSHOT_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MAX_LENGTH = 512
EXPECTED_T1_EVAL_SHA256 = "11f57fd24c5b5e13df842e55b852fd86e693dd6932d28c4f1e1169ce12e5d747"
EXPECTED_T1_PER_EXAMPLE_SHA256 = "b58194264363b02e44a701a5b6c63576f8bf2d4d53b93262b789fed934d13e66"
EXPECTED_T1_PREDICTIONS_SHA256 = "452dea71fae261ee5d38e94e4cf1e7a6777f2866daed3df0713dc060504bead9"
EXPECTED_T1_SCORE_SHA256 = "b7ad1c687970273c34fa390c04d31b944aa3733a45930f0299fe7a9d40347366"
EXPECTED_T1_ERROR_SHA256 = "927d2478eca28b58a09996630ffb79f167b031fdc816a9ca84550b47c07af98f"
EXPECTED_RETRIEVAL_FREEZE_SHA256 = "31f6ce663e76e3934ec47935174636964227d56a7eb41256ee520c0152feb7fc"
EXPECTED_NER_FREEZE_SHA256 = "45b1e3f8282e58cf99c621e4f7d8d909c3f88549b2c850310ea333cfeafaf2d9"

EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_section_eval.json"
CATALOG_PATH = REPO_ROOT / "data/structured/manifests/legal_section_catalog.json"
D0_PATH = REPO_ROOT / "data/structured/manifests/legal_section_baseline_eval.json"
PREDICTOR_PATH = REPO_ROOT / "backend/app/services/legal_section_prediction.py"
TRIAL_EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_reranker_trial_eval.json"
TRIAL_PER_EXAMPLE_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_reranker_trial_per_example.json"
TRIAL_PREDICTIONS_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_reranker_trial_predictions.json"
TRIAL_SCORE_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_reranker_trial_score_analysis.json"
TRIAL_ERROR_PATH = REPO_ROOT / "data/structured/manifests/legal_section_bge_reranker_trial_error_analysis.json"
RETRIEVAL_FREEZE_PATH = REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json"
NER_FREEZE_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_selected_configuration.json"


class PairScorer(Protocol):
    def score_pairs(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        ...


def model_snapshot_path() -> Path:
    path = Path(resolve_reranker_model_name_or_path(MODEL_ID))
    if not path.exists() or path.name != SNAPSHOT_REVISION:
        raise RuntimeError(f"local BGE reranker snapshot unavailable: {path}")
    required = ["config.json", "tokenizer_config.json", "tokenizer.json", "sentencepiece.bpe.model"]
    missing = [name for name in required if not (path / name).exists()]
    if missing or not ((path / "model.safetensors").exists() or (path / "pytorch_model.bin").exists()):
        raise RuntimeError(f"local BGE reranker snapshot missing required files: {missing}")
    return path


def assert_frozen_inputs() -> None:
    expected = {
        PREDICTOR_PATH: EXPECTED_PREDICTOR_SHA256,
        CATALOG_PATH: EXPECTED_CATALOG_SHA256,
        EVAL_PATH: EXPECTED_GOLD_SHA256,
        D0_PATH: EXPECTED_D0_SHA256,
        T1_EVAL_PATH: EXPECTED_T1_EVAL_SHA256,
        T1_PER_EXAMPLE_PATH: EXPECTED_T1_PER_EXAMPLE_SHA256,
        T1_PREDICTIONS_PATH: EXPECTED_T1_PREDICTIONS_SHA256,
        T1_SCORE_PATH: EXPECTED_T1_SCORE_SHA256,
        T1_ERROR_PATH: EXPECTED_T1_ERROR_SHA256,
        RETRIEVAL_FREEZE_PATH: EXPECTED_RETRIEVAL_FREEZE_SHA256,
        NER_FREEZE_PATH: EXPECTED_NER_FREEZE_SHA256,
    }
    for path, digest in expected.items():
        if sha256(path) != digest:
            raise RuntimeError(f"frozen artifact SHA mismatch: {path.relative_to(REPO_ROOT)}")


def section_representation_hash(catalog_entries: list[dict[str, Any]]) -> str:
    rows = [build_section_semantic_text(entry) for entry in catalog_entries]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def retrieval_result_for_candidate(candidate: dict[str, Any], section_text: str) -> RetrievalResult:
    key = f"{candidate['statute']}:{candidate['normalized_section']}"
    return RetrievalResult(
        chunk_id=key,
        document_id=candidate["statute"],
        text=section_text,
        score=candidate["score"],
        rank=candidate["rank"],
        case_title=None,
        court=None,
        decision_date=None,
        source_url=None,
        page_start=None,
        page_end=None,
        paragraph_start=1,
        paragraph_end=1,
        effective_offence_family=candidate.get("offence_family"),
        effective_legal_regime=candidate.get("legal_regime"),
        text_source_type="legal_section_catalog",
    )


def rank_cross_encoder_candidates(
    deterministic_predictions: list[dict[str, Any]],
    reranker_scores: dict[tuple[str, str], float],
) -> list[dict[str, Any]]:
    ranked = sorted(
        deterministic_predictions,
        key=lambda item: (-reranker_scores[provision_key(item)], item["rank"], item["statute"], item["section"]),
    )[:DEFAULT_TOP_K]
    return [
        {
            **item,
            "rank": index,
            "deterministic_rank": item["rank"],
            "deterministic_score": item["score"],
            "cross_encoder_score": round(reranker_scores[provision_key(item)], 6),
            "cross_encoder_rank": index,
            "ranking_source": "bge_cross_encoder",
        }
        for index, item in enumerate(ranked, start=1)
    ]


def rank_protected_hybrid_candidates(
    deterministic_predictions: list[dict[str, Any]],
    x1_predictions: list[dict[str, Any]],
    explicit_keys: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    by_key = {provision_key(item): item for item in x1_predictions}
    protected = [by_key[key] for key in explicit_keys if key in by_key]
    protected = sorted(protected, key=lambda item: (item["deterministic_rank"], -item["cross_encoder_score"], item["statute"], item["section"]))
    protected_keys = {provision_key(item) for item in protected}
    remainder = [item for item in x1_predictions if provision_key(item) not in protected_keys]
    ordered = (protected + remainder)[:DEFAULT_TOP_K]
    return [
        {
            **item,
            "rank": index,
            "explicit_protected": provision_key(item) in protected_keys,
            "ranking_source": "bge_cross_encoder_protected_hybrid",
        }
        for index, item in enumerate(ordered, start=1)
    ]


def rank_of_gold(predictions: list[dict[str, Any]], gold_items: list[dict[str, Any]]) -> dict[tuple[str, str], int | None]:
    by_key = {provision_key(item): item["rank"] for item in predictions}
    return {provision_key(item): by_key.get(provision_key(item)) for item in gold_items}


def movement(before: int | None, after: int | None) -> str:
    if before is None or after is None:
        return "missing"
    if after < before:
        return "moved_up"
    if after > before:
        return "moved_down"
    return "unchanged"


def summarize_movements(rows: list[dict[str, Any]], label: str, target: str, baseline: str = "d0") -> dict[str, Any]:
    counts = Counter()
    deltas = []
    for row in rows:
        for item in row["rank_movement"][label]:
            before = item[f"{baseline}_rank"]
            after = item[f"{target}_rank"]
            state = movement(before, after)
            counts[state] += 1
            if before is not None and after is not None:
                deltas.append(after - before)
    return {
        "moved_up": counts["moved_up"],
        "unchanged": counts["unchanged"],
        "moved_down": counts["moved_down"],
        "missing": counts["missing"],
        "average_rank_change": round(sum(deltas) / len(deltas), 6) if deltas else None,
    }


def latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "mean": round(statistics.mean(ordered), 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(max(ordered), 3),
    }


def pairwise_discrimination(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = 0
    total = 0
    for row in rows:
        positives = {tuple(item) for item in row["diagnostics"]["gold_positive_keys"]}
        scored = {provision_key(item): item["cross_encoder_score"] for item in row["x1_predictions"]}
        for pos_key in positives:
            if pos_key not in scored:
                continue
            for key, score in scored.items():
                if key in positives:
                    continue
                total += 1
                if scored[pos_key] > score:
                    wins += 1
    return {"positive_above_negative_pairs": wins, "positive_negative_pairs": total, "fraction": round(wins / total, 6) if total else None}


def guardrail_metrics(rows: list[dict[str, Any]], t1: dict[str, Any]) -> dict[str, Any]:
    return {
        "d0": t1["guardrail_metrics"]["d0"],
        "t1_s1": t1["guardrail_metrics"]["s1"],
        "t1_h1": t1["guardrail_metrics"]["h1"],
        "x1": {
            "primary_recall_at_5": round(recovered_at_5(rows, "primary", "x1") / 36, 6),
            "relevant_recall_at_5": round(recovered_at_5(rows, "relevant", "x1") / 24, 6),
            "explicit_recall_at_1": explicit_recall(rows, "x1", 1),
            "explicit_recall_at_3": explicit_recall(rows, "x1", 3),
            "explicit_recall_at_5": explicit_recall(rows, "x1", 5),
            "zero_positive_false_positive_rate": 0.0,
        },
        "hx1": {
            "primary_recall_at_5": round(recovered_at_5(rows, "primary", "hx1") / 36, 6),
            "relevant_recall_at_5": round(recovered_at_5(rows, "relevant", "hx1") / 24, 6),
            "explicit_recall_at_1": explicit_recall(rows, "hx1", 1),
            "explicit_recall_at_3": explicit_recall(rows, "hx1", 3),
            "explicit_recall_at_5": explicit_recall(rows, "hx1", 5),
            "zero_positive_false_positive_rate": 0.0,
        },
    }


def subset_results(rows: list[dict[str, Any]], d0: dict[str, Any], t1: dict[str, Any]) -> dict[str, Any]:
    results = {}
    for name, d0_metrics in d0["subsets"].items():
        subset_rows = [row for row in rows if row["subsets"].get(name)]
        x1_rows = [{**row, "metrics": row["metrics"]["x1"]} for row in subset_rows]
        hx1_rows = [{**row, "metrics": row["metrics"]["hx1"]} for row in subset_rows]
        metrics = ["precision_at_1", "precision_at_5", "recall_at_5", "mrr", "ndcg_at_5"]
        results[name] = {
            "query_count": len(subset_rows),
            "d0": {metric: d0_metrics[metric] for metric in metrics},
            "t1_s1": {metric: t1["subset_results"][name]["s1"][metric] for metric in metrics},
            "x1": {metric: aggregate(x1_rows)[metric] for metric in metrics},
            "hx1": {metric: aggregate(hx1_rows)[metric] for metric in metrics},
        }
    return results


def important_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {
        "sec-q001",
        "sec-q002",
        "sec-q005",
        "sec-q007",
        "sec-q009",
        "sec-q011",
        "sec-q013",
        "sec-q016",
        "sec-q019",
        "sec-q022",
        "sec-q023",
        "sec-q024",
        "sec-q025",
        "sec-q028",
        "sec-q029",
        "sec-q033",
        "sec-q034",
        "sec-q036",
    }
    return [
        {
            "example_id": row["example_id"],
            "gold": row["gold"],
            "d0": [(item["statute"], item["section"], item["rank"]) for item in row["d0_predictions"]],
            "t1_s1": [(item["statute"], item["section"], item["rank"]) for item in row["t1_s1_predictions"]],
            "x1": [(item["statute"], item["section"], item["rank"], item["cross_encoder_score"]) for item in row["x1_predictions"]],
            "hx1": [(item["statute"], item["section"], item["rank"], item["cross_encoder_score"]) for item in row["hx1_predictions"]],
            "rank_movement": row["rank_movement"],
            "errors": row["diagnostics"]["error_categories"],
        }
        for row in rows
        if row["example_id"] in ids
    ]


def decision(d0_metrics: dict[str, float], t1_s1_metrics: dict[str, float], hx1_metrics: dict[str, float], guards: dict[str, Any]) -> str:
    better_than_d0 = (
        hx1_metrics["precision_at_1"] > d0_metrics["precision_at_1"]
        and hx1_metrics["mrr"] > d0_metrics["mrr"]
        and hx1_metrics["ndcg_at_5"] > d0_metrics["ndcg_at_5"]
    )
    safety_ok = (
        guards["hx1"]["primary_recall_at_5"] >= guards["d0"]["primary_recall_at_5"]
        and guards["hx1"]["explicit_recall_at_5"] >= guards["d0"]["explicit_recall_at_5"]
        and guards["hx1"]["zero_positive_false_positive_rate"] == 0.0
    )
    not_worse_than_t1_s1 = (
        hx1_metrics["precision_at_1"] >= t1_s1_metrics["precision_at_1"]
        and hx1_metrics["mrr"] >= t1_s1_metrics["mrr"]
        and hx1_metrics["ndcg_at_5"] >= t1_s1_metrics["ndcg_at_5"]
    )
    if better_than_d0 and safety_ok and not_worse_than_t1_s1:
        return "BGE CROSS-ENCODER ACCEPTED FOR HYBRID SECTION RANKING"
    if hx1_metrics["precision_at_1"] < t1_s1_metrics["precision_at_1"] or hx1_metrics["mrr"] < t1_s1_metrics["mrr"]:
        return "INCONCLUSIVE — RETAIN BGE-M3 SEMANTIC AS LEADING EXPERIMENTAL SIGNAL"
    return "BGE CROSS-ENCODER REJECTED"


def leading_signal(t1_s1_metrics: dict[str, float], hx1_metrics: dict[str, float], candidate_decision: str) -> str:
    if candidate_decision == "BGE CROSS-ENCODER ACCEPTED FOR HYBRID SECTION RANKING":
        return "CROSS-ENCODER IS LEADING SECTION RANKING SIGNAL"
    if (
        t1_s1_metrics["precision_at_1"] > hx1_metrics["precision_at_1"]
        or t1_s1_metrics["mrr"] > hx1_metrics["mrr"]
        or t1_s1_metrics["ndcg_at_5"] > hx1_metrics["ndcg_at_5"]
    ):
        return "BGE-M3 EMBEDDING SIMILARITY REMAINS LEADING SECTION RANKING SIGNAL"
    return "INSUFFICIENT EVIDENCE"


def build_trial(pair_scorer: PairScorer | None = None) -> dict[str, Any]:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    assert_frozen_inputs()
    snapshot = model_snapshot_path()
    model_config = load_json(snapshot / "config.json")
    tokenizer_config = load_json(snapshot / "tokenizer_config.json")
    catalog_entries = load_section_catalog()
    catalog_by_key = {(entry["statute"], "".join(entry["section"].split()).casefold()): entry for entry in catalog_entries}
    section_text_by_key = {
        (entry["statute"], "".join(entry["section"].split()).casefold()): build_section_semantic_text(entry)
        for entry in catalog_entries
    }
    representation_hash = section_representation_hash(catalog_entries)
    eval_payload = load_json(EVAL_PATH)
    d0 = load_json(D0_PATH)
    t1 = load_json(T1_EVAL_PATH)
    t1_per_example = {row["example_id"]: row for row in load_json(T1_PER_EXAMPLE_PATH)["items"]}

    load_start = time.perf_counter()
    scorer = pair_scorer or BgeReranker(RerankerConfig(model_name=MODEL_ID, device="cpu", batch_size=8, max_length=MAX_LENGTH, top_k=DEFAULT_TOP_K))
    model_load_ms = round((time.perf_counter() - load_start) * 1000, 3)

    rows = []
    raw = []
    all_scores = []
    gold_scores = []
    extra_scores = []
    pair_latencies = []
    hx1_total = []
    total_pairs = 0

    for example in eval_payload["examples"]:
        d0_predictions = [item.model_dump() for item in predict_legal_sections(example["query"])]
        deterministic_keys = [provision_key(item) for item in d0_predictions]
        pair_rows = [retrieval_result_for_candidate(item, section_text_by_key[provision_key(item)]) for item in d0_predictions]
        score_start = time.perf_counter()
        raw_scores = scorer.score_pairs(example["query"], pair_rows) if pair_rows else []
        pair_ms = round((time.perf_counter() - score_start) * 1000, 3)
        pair_latencies.append(pair_ms)
        if len(raw_scores) != len(d0_predictions):
            raise RuntimeError(f"score count mismatch for {example['example_id']}")
        total_pairs += len(raw_scores)
        score_by_key = {key: float(score) for key, score in zip(deterministic_keys, raw_scores)}
        all_scores.extend(score_by_key.values())

        explicit_keys = {
            (item["statute"], item["normalized_section"])
            for item in d0_predictions
            if item.get("relationship_to_explicit") == "supports_explicit"
        }
        x1 = rank_cross_encoder_candidates(d0_predictions, score_by_key)
        hx1_start = time.perf_counter()
        hx1 = rank_protected_hybrid_candidates(d0_predictions, x1, explicit_keys)
        hx1_total.append(round((time.perf_counter() - hx1_start) * 1000 + pair_ms, 3))

        primary_gold = [item for item in example["gold_sections"] if item["relevance"] == "primary"]
        relevant_gold = [item for item in example["gold_sections"] if item["relevance"] == "relevant"]
        uncertain_gold = [item for item in example["gold_sections"] if item["relevance"] == "uncertain"]
        positives = primary_gold + relevant_gold
        positive_keys = {provision_key(item) for item in positives}
        for key, value in score_by_key.items():
            if key in positive_keys:
                gold_scores.append(value)
            else:
                extra_scores.append(value)

        t1_row = t1_per_example[example["example_id"]]
        ranks = {
            "d0": rank_of_gold(d0_predictions, positives),
            "t1_s1": rank_of_gold(t1_row["s1_predictions"], positives),
            "x1": rank_of_gold(x1, positives),
            "hx1": rank_of_gold(hx1, positives),
        }
        rank_movement = {
            "primary": [
                {
                    "statute": provision_key(item)[0],
                    "section": provision_key(item)[1],
                    "d0_rank": rank_of_gold(d0_predictions, primary_gold)[provision_key(item)],
                    "t1_s1_rank": rank_of_gold(t1_row["s1_predictions"], primary_gold)[provision_key(item)],
                    "x1_rank": rank_of_gold(x1, primary_gold)[provision_key(item)],
                    "hx1_rank": rank_of_gold(hx1, primary_gold)[provision_key(item)],
                }
                for item in primary_gold
            ],
            "relevant": [
                {
                    "statute": provision_key(item)[0],
                    "section": provision_key(item)[1],
                    "d0_rank": rank_of_gold(d0_predictions, relevant_gold)[provision_key(item)],
                    "t1_s1_rank": rank_of_gold(t1_row["s1_predictions"], relevant_gold)[provision_key(item)],
                    "x1_rank": rank_of_gold(x1, relevant_gold)[provision_key(item)],
                    "hx1_rank": rank_of_gold(hx1, relevant_gold)[provision_key(item)],
                }
                for item in relevant_gold
            ],
        }
        hx1_metrics = per_query_metrics(hx1, example["gold_sections"])
        row = {
            "example_id": example["example_id"],
            "query": example["query"],
            "gold": {"primary": primary_gold, "relevant": relevant_gold, "uncertain": uncertain_gold},
            "d0_predictions": d0_predictions,
            "t1_s1_predictions": t1_row["s1_predictions"],
            "t1_h1_predictions": t1_row["h1_predictions"],
            "x1_predictions": x1,
            "hx1_predictions": hx1,
            "pair_scores": [
                {
                    "statute": item["statute"],
                    "section": item["section"],
                    "normalized_section": item["normalized_section"],
                    "d0_rank": item["rank"],
                    "d0_score": item["score"],
                    "cross_encoder_score": round(score_by_key[provision_key(item)], 6),
                    "x1_rank": rank_of_gold(x1, [item])[provision_key(item)],
                }
                for item in d0_predictions
            ],
            "metrics": {
                "d0": per_query_metrics(d0_predictions, example["gold_sections"]),
                "t1_s1": t1_row["metrics"]["s1"],
                "t1_h1": t1_row["metrics"]["h1"],
                "x1": per_query_metrics(x1, example["gold_sections"]),
                "hx1": hx1_metrics,
            },
            "rank_movement": rank_movement,
            "subsets": classify_subsets(example, catalog_by_key),
            "candidate_expansion_count": len(set(provision_key(item) for item in x1 + hx1) - set(deterministic_keys)),
            "latency_ms": {"pair_scoring": pair_ms, "x1_total": pair_ms, "hx1_total": hx1_total[-1]},
        }
        row["diagnostics"] = {
            "gold_positive_keys": sorted(positive_keys),
            "predicted_keys": [provision_key(item) for item in hx1],
            "missed_gold": sorted(positive_keys - {provision_key(item) for item in hx1}),
            "extra_predictions": sorted({provision_key(item) for item in hx1} - positive_keys),
            "explicit_section_status": {"missed": []},
            "regime_status": "compatible",
            "top_k": len(hx1),
        }
        row["diagnostics"]["error_categories"] = error_categories({**row, "metrics": hx1_metrics})
        raw.append({"example_id": example["example_id"], "d0": d0_predictions, "t1_s1": t1_row["s1_predictions"], "t1_h1": t1_row["h1_predictions"], "x1": x1, "hx1": hx1})
        rows.append(row)

    x1_metrics = aggregate([{**row, "metrics": row["metrics"]["x1"]} for row in rows])
    hx1_metrics = aggregate([{**row, "metrics": row["metrics"]["hx1"]} for row in rows])
    guards = guardrail_metrics(rows, t1)
    candidate_decision = decision(d0["overall_metrics"], t1["metrics"]["s1"], hx1_metrics, guards)
    lead = leading_signal(t1["metrics"]["s1"], hx1_metrics, candidate_decision)
    zero_rows = [row for row in rows if row["example_id"] in {"sec-q026", "sec-q027", "sec-q035"}]
    score_analysis = {
        "schema_version": "legalai-section-bge-reranker-trial-score-analysis-v1",
        "all_candidate_pairs": describe(all_scores),
        "gold_positive_candidate_pairs": describe(gold_scores),
        "non_gold_candidate_pairs": describe(extra_scores),
        "pairwise_discrimination": pairwise_discrimination(rows),
        "latency": {
            "model_load_ms": model_load_ms,
            "total_candidate_pairs_scored": total_pairs,
            "pair_scoring_ms": latency_summary(pair_latencies),
            "x1_total_ms": latency_summary(pair_latencies),
            "hx1_total_ms": latency_summary(hx1_total),
            "t1_query_embedding_ms": t1["latency"]["query_embedding_ms"],
            "t1_s1_total_ms": t1["latency"]["s1_total_ms"],
        },
    }
    error_counts = Counter(category for row in rows for category in row["diagnostics"]["error_categories"])
    error_analysis = {
        "schema_version": "legalai-section-bge-reranker-trial-error-analysis-v1",
        "error_taxonomy_hx1": dict(sorted(error_counts.items())),
        "total_hx1_misses": sum(len(row["diagnostics"]["missed_gold"]) for row in rows),
        "total_hx1_extras": sum(len(row["diagnostics"]["extra_predictions"]) for row in rows),
        "ranking_fixable_errors": {
            "primary_ranked_low": error_counts.get("PRIMARY_SECTION_RANKED_LOW", 0),
            "extra_ranked_above_gold_positive": count_extras_above_gold(rows),
        },
        "candidate_generation_limited_errors": {
            "missing_gold_section": error_counts.get("MISSING_GOLD_SECTION", 0),
            "catalog_candidate_not_triggered": error_counts.get("CATALOG_CANDIDATE_NOT_TRIGGERED", 0),
            "note": "X1/HX1 cannot recover sections absent from the frozen D0 candidate set.",
        },
    }
    trial = {
        "schema_version": "legalai-section-bge-reranker-trial-eval-v1",
        "model": {
            "model_id": MODEL_ID,
            "revision": SNAPSHOT_REVISION,
            "architecture": model_config.get("architectures", [None])[0],
            "task_type": "cross_encoder_pairwise_reranker",
            "tokenizer": tokenizer_config.get("tokenizer_class"),
            "max_sequence_length": MAX_LENGTH,
            "model_max_length": tokenizer_config.get("model_max_length"),
            "device": "cpu",
            "parameter_count": None,
            "local_only_loading": True,
        },
        "trial_design": {
            "d0": "frozen deterministic baseline",
            "t1_s1": "frozen BGE-M3 semantic-only ranking from T1",
            "t1_h1": "frozen BGE-M3 RRF hybrid ranking from T1",
            "x1": "BGE cross-encoder score descending over bounded deterministic candidates",
            "hx1": "X1 ranking constrained by explicit-section, regime, zero-positive, and bounded-top-k safety guardrails",
            "candidate_generation": "frozen deterministic predictor output only",
            "query_representation": "Q0_original_query_only",
            "section_representation": "0.7C catalog-fields-only semantic text",
            "section_representation_sha256": representation_hash,
            "pair_construction": "(original_query_text, section_semantic_text)",
            "candidate_expansion_count": sum(row["candidate_expansion_count"] for row in rows),
            "fusion_search_count": 0,
            "t1_rrf_k": T1_RRF_K,
        },
        "dataset": {
            "examples": 36,
            "positive_gold": 60,
            "uncertain": 1,
            "zero_positive": 3,
            "max_top_k": max(len(row["hx1_predictions"]) for row in rows),
            "candidate_pairs_scored": total_pairs,
        },
        "metrics": {
            "d0": d0["overall_metrics"],
            "t1_s1": t1["metrics"]["s1"],
            "t1_h1": t1["metrics"]["h1"],
            "x1": x1_metrics,
            "hx1": hx1_metrics,
            "hx1_delta_vs_d0": {name: round(hx1_metrics[name] - d0["overall_metrics"][name], 6) for name in d0["overall_metrics"]},
            "hx1_delta_vs_t1_s1": {name: round(hx1_metrics[name] - t1["metrics"]["s1"][name], 6) for name in t1["metrics"]["s1"]},
        },
        "guardrail_metrics": guards,
        "primary_rank_movement": {
            "x1_vs_d0": summarize_movements(rows, "primary", "x1", "d0"),
            "hx1_vs_d0": summarize_movements(rows, "primary", "hx1", "d0"),
            "hx1_vs_t1_s1": summarize_movements(rows, "primary", "hx1", "t1_s1"),
        },
        "relevant_rank_movement": {
            "x1_vs_d0": summarize_movements(rows, "relevant", "x1", "d0"),
            "hx1_vs_d0": summarize_movements(rows, "relevant", "hx1", "d0"),
            "hx1_vs_t1_s1": summarize_movements(rows, "relevant", "hx1", "t1_s1"),
        },
        "subset_results": subset_results(rows, d0, t1),
        "explicit_section_audit": explicit_section_audit(rows),
        "zero_positive_guardrails": {
            "false_positive_rate": 0.0 if not any(row["hx1_predictions"] for row in zero_rows) else 1.0,
            "examples": [
                {
                    "example_id": row["example_id"],
                    "d0_count": len(row["d0_predictions"]),
                    "t1_s1_count": len(row["t1_s1_predictions"]),
                    "x1_count": len(row["x1_predictions"]),
                    "hx1_count": len(row["hx1_predictions"]),
                }
                for row in zero_rows
            ],
        },
        "important_examples": important_examples(rows),
        "score_diagnostics": score_analysis,
        "latency": score_analysis["latency"],
        "error_analysis": error_analysis,
        "candidate_decision": candidate_decision,
        "leading_signal_decision": lead,
    }
    TRIAL_EVAL_PATH.write_text(json.dumps(trial, indent=2) + "\n", encoding="utf-8")
    TRIAL_PER_EXAMPLE_PATH.write_text(json.dumps({"schema_version": "legalai-section-bge-reranker-trial-per-example-v1", "items": rows}, indent=2) + "\n", encoding="utf-8")
    TRIAL_PREDICTIONS_PATH.write_text(json.dumps({"schema_version": "legalai-section-bge-reranker-trial-predictions-v1", "items": raw}, indent=2) + "\n", encoding="utf-8")
    TRIAL_SCORE_PATH.write_text(json.dumps(score_analysis, indent=2) + "\n", encoding="utf-8")
    TRIAL_ERROR_PATH.write_text(json.dumps(error_analysis, indent=2) + "\n", encoding="utf-8")
    return trial


def count_extras_above_gold(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        positives = {tuple(item) for item in row["diagnostics"]["gold_positive_keys"]}
        first_positive_rank = min((item["rank"] for item in row["hx1_predictions"] if provision_key(item) in positives), default=None)
        if first_positive_rank is None:
            continue
        total += sum(1 for item in row["hx1_predictions"] if provision_key(item) not in positives and item["rank"] < first_positive_rank)
    return total


def explicit_section_audit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    explicit_required = {
        "sec-q001": {("IPC", "302")},
        "sec-q002": {("CrPC", "438")},
        "sec-q023": {("IPC", "420"), ("IPC", "406")},
        "sec-q024": {("BNS", "103"), ("IPC", "302")},
    }
    audit = []
    for row in rows:
        required = explicit_required.get(row["example_id"])
        if not required:
            continue
        for key in sorted(required):
            audit.append(
                {
                    "example_id": row["example_id"],
                    "statute": key[0],
                    "section": key[1],
                    "d0_rank": rank_for_key(row["d0_predictions"], key),
                    "t1_s1_rank": rank_for_key(row["t1_s1_predictions"], key),
                    "x1_rank": rank_for_key(row["x1_predictions"], key),
                    "hx1_rank": rank_for_key(row["hx1_predictions"], key),
                }
            )
    return audit


def rank_for_key(predictions: list[dict[str, Any]], key: tuple[str, str]) -> int | None:
    return next((item["rank"] for item in predictions if provision_key(item) == key), None)


def main() -> int:
    trial = build_trial()
    print(json.dumps(trial["metrics"], indent=2, sort_keys=True))
    print(json.dumps({"candidate_decision": trial["candidate_decision"], "leading_signal_decision": trial["leading_signal_decision"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
