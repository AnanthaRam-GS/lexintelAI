"""Step E3 retrieval check: the frozen 30-query benchmark through the product query path, NER backend off and on.

No LLM. For each backend (``deterministic``, then ``combined``) every frozen query goes through the product's query
understanding (``understand_legal_query`` + ``ner_backend.with_backend_entities``, as in ``api/query.py``) and the
query the product sends to retrieval (``understanding.query``) is retrieved by the frozen stack with the frozen pooling
(``rerun_retrieval_eval``: depth 20, all four systems). Rankings are scored with the frozen metric code against the
frozen human labels.

Outputs (``--out``): ``e3_retrieval.json`` with, for hybrid + rerank (the production system): P@5, pooled R@5, pooled
R@20, MRR@5 and nDCG@5 per backend with bootstrap 95% CIs (10,000 resamples of the 30 queries, seed 20261111), the
paired differences (combined - deterministic) on the same resamples, per-query rank changes, the flag-off comparison
with the frozen numbers and rankings, and the frozen E3 verdict (plan section 6).

    .venv/bin/python experiments/inlegalbert/e3_retrieval.py --out experiments/inlegalbert/results
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.scripts.analyze_retrieval_eval import SYSTEMS, compute_metrics, rankings_for_query  # noqa: E402
from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH, QUERIES_PATH, TRACES_PATH  # noqa: E402
from backend.scripts.rerun_retrieval_eval import FROZEN_RESULTS_PATH, make_service, metrics_with_unjudged  # noqa: E402

SYSTEM = "hybrid_rerank"
METRICS = {"P@5": "broad_precision_at_5", "R@5": "broad_pooled_recall_at_5", "R@20": "broad_pooled_recall_at_20",
           "MRR@5": "broad_mrr_at_5", "nDCG@5": "graded_ndcg_at_5"}
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261111
# Frozen E3 rule (INLEGALBERT_PLAN.md section 6): no regression = P@5 >= 0.873 and nDCG@5 >= 0.814 (frozen - 0.005);
# an improvement needs delta nDCG@5 >= +0.02 with a paired-bootstrap lower bound > 0.
P5_FLOOR, NDCG5_FLOOR, GAIN_DELTA = 0.873, 0.814, 0.02


class ProductPathRetriever:
    """The pooling retriever, with the product's query-understanding step in front (records what it sends)."""

    def __init__(self, service: Any, settings: Any) -> None:
        self.service, self.settings = service, settings
        self.sent: dict[str, str] = {}
        self.entities: dict[str, list[list[Any]]] = {}

    def retrieve(self, query: str, mode: str, top_k: int, candidate_k: int, rerank: bool = False) -> list[Any]:
        from backend.app.services.legal_query_understanding import understand_legal_query
        from backend.app.services.ner_backend import with_backend_entities

        understanding = with_backend_entities(understand_legal_query(query, section_ranking_mode="deterministic"), self.settings)
        self.sent[query] = understanding.query
        self.entities[query] = [[e.start_char, e.end_char, str(e.entity_type), e.text, e.source] for e in understanding.entities]
        return self.service.retrieve(understanding.query, mode, top_k=top_k, candidate_k=candidate_k, rerank=rerank).results


def run_backend(backend: str, queries: list[dict], service: Any) -> tuple[list[dict], ProductPathRetriever, dict]:
    from backend.app.core.config import Settings
    from backend.app.services import ner_backend
    from backend.app.services.retrieval.evaluation import PoolingConfig, generate_pool

    os.environ["LEGALAI_NER_BACKEND"] = backend
    ner_backend.reset_ner_backend()
    settings = Settings()
    retriever = ProductPathRetriever(service, settings)
    _judgments, traces = generate_pool(queries, retriever, PoolingConfig(20, 15, 5, 25))
    return traces, retriever, ner_backend.ner_status(settings)


def per_query_values(per_query: list[dict]) -> dict[str, list[float]]:
    return {name: [row["systems"][SYSTEM][field] for row in per_query] for name, field in METRICS.items()}


def bootstrap(off: dict[str, list[float]], on: dict[str, list[float]]) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(off["P@5"])
    draws = {name: {"off": [], "on": [], "diff": []} for name in METRICS}
    for _ in range(BOOTSTRAP_RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        for name in METRICS:
            a = statistics.fmean(off[name][i] for i in idx)
            b = statistics.fmean(on[name][i] for i in idx)
            draws[name]["off"].append(a)
            draws[name]["on"].append(b)
            draws[name]["diff"].append(b - a)

    def ci(values: list[float]) -> list[float]:
        ordered = sorted(values)
        return [round(ordered[int(0.025 * len(ordered))], 4), round(ordered[int(0.975 * len(ordered)) - 1], 4)]

    return {name: {"deterministic": {"mean": round(statistics.fmean(off[name]), 6), "ci95": ci(d["off"])},
                   "combined": {"mean": round(statistics.fmean(on[name]), 6), "ci95": ci(d["on"])},
                   "paired_difference": {"mean": round(statistics.fmean(on[name]) - statistics.fmean(off[name]), 6),
                                         "ci95": ci(d["diff"])}}
            for name, d in draws.items()}


def rank_changes(queries: list[dict], off: list[dict], on: list[dict]) -> list[dict]:
    rows = []
    for query in queries:
        a = rankings_for_query(off, query["query_id"], SYSTEM)
        b = rankings_for_query(on, query["query_id"], SYSTEM)
        moved = {chunk: {"off": a.index(chunk) + 1 if chunk in a else None, "on": b.index(chunk) + 1 if chunk in b else None}
                 for chunk in dict.fromkeys(a[:20] + b[:20]) if (a.index(chunk) if chunk in a else None) != (b.index(chunk) if chunk in b else None)}
        rows.append({"query_id": query["query_id"], "identical_top20": a[:20] == b[:20], "moved_chunks": moved})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    frozen_traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
    frozen_overall = json.loads(FROZEN_RESULTS_PATH.read_text(encoding="utf-8"))["overall"][SYSTEM]

    service, device = make_service("product")
    off_traces, off_retriever, off_status = run_backend("deterministic", queries, service)
    on_traces, on_retriever, on_status = run_backend("combined", queries, service)
    if on_status["active"] != "combined" or on_status["model"].get("status") != "ready":
        raise SystemExit(f"combined backend not active: {on_status}")

    off_pq, off_agg, off_unjudged = metrics_with_unjudged(queries, judgments, off_traces)
    on_pq, on_agg, on_unjudged = metrics_with_unjudged(queries, judgments, on_traces)
    off_vals, on_vals = per_query_values(off_pq), per_query_values(on_pq)
    boot = bootstrap(off_vals, on_vals)

    frozen_rank_match = sum(rankings_for_query(frozen_traces, q["query_id"], SYSTEM) == rankings_for_query(off_traces, q["query_id"], SYSTEM)
                            for q in queries)
    off_overall = {name: off_agg["overall"][SYSTEM][field] for name, field in METRICS.items()}
    on_overall = {name: on_agg["overall"][SYSTEM][field] for name, field in METRICS.items()}
    frozen = {name: frozen_overall[field] for name, field in METRICS.items()}
    sent_unchanged = all(on_retriever.sent[q] == q == off_retriever.sent[q] for q in off_retriever.sent)

    no_drop = on_overall["P@5"] >= P5_FLOOR and on_overall["nDCG@5"] >= NDCG5_FLOOR
    gain = boot["nDCG@5"]["paired_difference"]["mean"] >= GAIN_DELTA and boot["nDCG@5"]["paired_difference"]["ci95"][0] > 0
    entities_changed = sum(off_retriever.entities[q["query_text"]] != on_retriever.entities[q["query_text"]] for q in queries)
    result = {
        "device": device, "system": SYSTEM,
        "flag_off_vs_frozen": {"metrics_rerun": off_overall, "metrics_frozen": frozen,
                               "metrics_identical": off_overall == frozen,
                               "identical_rankings": f"{frozen_rank_match}/{len(queries)}"},
        "query_sent_to_retrieval_is_original_query": sent_unchanged,
        "queries_whose_entities_changed": entities_changed,
        "overall": {"deterministic": off_overall, "combined": on_overall},
        "bootstrap": boot,
        "unjudged": {"deterministic": off_unjudged.get(SYSTEM), "combined": on_unjudged.get(SYSTEM)},
        "rank_changes": rank_changes(queries, off_traces, on_traces),
        "ner_status_combined": on_status,
        "entities": {q["query_id"]: {"deterministic": off_retriever.entities[q["query_text"]],
                                      "combined": on_retriever.entities[q["query_text"]]} for q in queries},
        "verdict": {"no_drop": {"P@5": [on_overall["P@5"], P5_FLOOR], "nDCG@5": [on_overall["nDCG@5"], NDCG5_FLOOR], "pass": no_drop},
                    "gain": {"delta_ndcg5": boot["nDCG@5"]["paired_difference"], "threshold": GAIN_DELTA, "claimed": gain},
                    "overall": "PASS" if no_drop else "FAIL"},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "e3_retrieval.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("flag_off_vs_frozen", "query_sent_to_retrieval_is_original_query", "queries_whose_entities_changed", "overall", "verdict")}
    summary["identical_top20_on_vs_off"] = sum(r["identical_top20"] for r in result["rank_changes"])
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
