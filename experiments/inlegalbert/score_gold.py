"""Step E1: score each seed's best-validation checkpoint ONCE on the 36 gold NER examples.

Implements section 5 of docs/experiments/INLEGALBERT_E1_PROTOCOL.md: (a) the model alone (mapped entities at
confidence >= 0.70), (b) the deterministic baseline, (c) the combined system (the product's hybrid merge, unchanged),
with the existing exact scorer, per-type metrics, bootstrap CIs, the paired bootstrap of (c) - (b), the median seed by
the combined system's F1, and the verdict against the frozen thresholds of docs/experiments/INLEGALBERT_PLAN.md.

A seed is scored only once: its predictions are written to results/predictions-seed-<n>.json and the script refuses to
predict that seed again. Nothing here changes the model, the mapping or the policy.

    ../../.venv/bin/python score_gold.py --seeds 11 22 33
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from backend.app.schemas.legal_ner import CanonicalEntity, EntityProvenance  # noqa: E402
from backend.app.services.hybrid_legal_ner import HybridMergeConfig, merge_hybrid_entities  # noqa: E402
from backend.app.services.legal_ner import CANONICAL_ENTITY_TYPES, exact_entity_metrics, extract_deterministic_entities  # noqa: E402
from backend.scripts.evaluate_deterministic_legal_ner import load_gold_entities  # noqa: E402
from backend.scripts.run_inlegalbert_ner_trial import load_gold_payload  # noqa: E402

THRESHOLD = 0.70
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261111
EXTRACTOR = "inlegalbert_e1_ner"
RESULTS = HERE / "results"

# Section 2 of the protocol, frozen before training.
DIRECT_MAP = {"COURT": "COURT", "DATE": "DATE", "STATUTE": "STATUTE", "PROVISION": "SECTION", "ORG": "ORGANIZATION",
              "GPE": "LOCATION", "PRECEDENT": "CASE_NAME", "JUDGE": "PERSON", "LAWYER": "PERSON", "WITNESS": "PERSON",
              "OTHER_PERSON": "PERSON"}
PARTY_TYPES = {"PETITIONER", "RESPONDENT"}
ORG_PARTY_START = re.compile(r"^\s*(?:the\s+)?(?:State|Union of India|Government|Commissioner|Director|Municipal|Central Bureau)\b", re.I)
ORG_PARTY_WORD = re.compile(r"\b(?:Ltd|Limited|Pvt|Bank|Corporation|Company|Department|Board|Authority|Council|Commission|"
                            r"Society|Trust|University|Police)\b", re.I)

# Plan section 6 (frozen thresholds).
D0_F1_FROZEN = 0.787879
F1_MIN = 0.838
PRECISION_MIN = 0.805
BRIEF_TYPES = ["STATUTE", "SECTION", "COURT", "DATE", "LEGAL_ROLE", "LEGAL_PROCEDURE", "POLICE_STATION", "FIR_NUMBER"]


def canonical_type(native: str, text: str) -> str | None:
    if native in PARTY_TYPES:
        return "ORGANIZATION" if ORG_PARTY_START.search(text) or ORG_PARTY_WORD.search(text) else "PERSON"
    return DIRECT_MAP.get(native)  # CASE_NUMBER -> None (dropped)


def to_canonical(text: str, raw: list[dict], model_name: str) -> list[CanonicalEntity]:
    entities, seen = [], set()
    for item in raw:
        span = text[item["start"]:item["end"]]
        mapped = canonical_type(item["type"], span)
        if mapped is None or (item["start"], item["end"], mapped) in seen:
            continue
        seen.add((item["start"], item["end"], mapped))
        entities.append(CanonicalEntity(
            text=span, normalized_text=span.casefold(), entity_type=mapped, start_char=item["start"], end_char=item["end"],
            confidence=item["confidence"], source="model", extractor=EXTRACTOR, model_name=model_name,
            metadata={"native_type": item["type"]},
            provenance=[EntityProvenance(source="model", extractor=EXTRACTOR, model_name=model_name, confidence=item["confidence"])]))
    return entities


def counts(predicted: list[CanonicalEntity], gold: list[CanonicalEntity]) -> tuple[int, int, int]:
    overall = exact_entity_metrics(predicted, gold)["overall"]
    return overall["true_positive"], overall["false_positive"], overall["false_negative"]


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 6), "recall": round(r, 6), "f1": round(2 * p * r / (p + r) if p + r else 0.0, 6),
            "tp": tp, "fp": fp, "fn": fn}


def summarize(per_example: list[dict], system: str) -> dict:
    gold = [g for ex in per_example for g in ex["gold"]]
    predicted = [p for ex in per_example for p in ex[system]]
    per_type = {}
    for entity_type in CANONICAL_ENTITY_TYPES:
        g = [e for e in gold if e.entity_type == entity_type]
        p = [e for e in predicted if e.entity_type == entity_type]
        per_type[entity_type] = {"gold_support": len(g), "predicted": len(p), **prf(*counts(p, g))}
    return {"overall": prf(*counts(predicted, gold)), "per_type": per_type}


def bootstrap(per_example: list[dict], systems: list[str]) -> dict:
    """95% CIs of F1 per system and of the paired difference combined - deterministic (same resamples)."""
    rng = random.Random(BOOTSTRAP_SEED)
    cells = {s: [counts(ex[s], ex["gold"]) for ex in per_example] for s in systems}
    n = len(per_example)
    draws = {s: [] for s in systems}
    diffs = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        f1 = {}
        for s in systems:
            tp = sum(cells[s][i][0] for i in idx)
            fp = sum(cells[s][i][1] for i in idx)
            fn = sum(cells[s][i][2] for i in idx)
            f1[s] = prf(tp, fp, fn)["f1"]
            draws[s].append(f1[s])
        diffs.append(f1["combined"] - f1["deterministic"])
    ci = lambda v: [round(sorted(v)[int(0.025 * len(v))], 4), round(sorted(v)[int(0.975 * len(v)) - 1], 4)]  # noqa: E731
    return {"f1_ci95": {s: ci(draws[s]) for s in systems},
            "paired_combined_minus_deterministic": {"mean": round(statistics.mean(diffs), 4), "ci95": ci(diffs)}}


def score_seed(seed: int, gold_payload: dict) -> dict:
    marker = RESULTS / f"predictions-seed-{seed}.json"
    if marker.exists():
        raw_by_id = json.loads(marker.read_text(encoding="utf-8"))["raw_predictions"]
    else:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer
        from train_ner import predict_entities

        checkpoint = REPO / "models" / "inlegalbert_ner" / f"seed-{seed}"
        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        model = AutoModelForTokenClassification.from_pretrained(checkpoint).to(device)
        texts = [ex["text"] for ex in gold_payload["examples"]]
        raw = predict_entities(model, tokenizer, texts, device)  # the single scoring pass for this seed
        raw_by_id = {ex["example_id"]: r for ex, r in zip(gold_payload["examples"], raw)}
        RESULTS.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"seed": seed, "checkpoint": str(checkpoint.relative_to(REPO)),
                                      "raw_predictions": raw_by_id}, indent=1), encoding="utf-8")
    model_name = f"law-ai/InLegalBERT+InLegalNER seed {seed}"
    per_example = []
    for ex in gold_payload["examples"]:
        text = ex["text"]
        gold = load_gold_entities(ex)
        deterministic = extract_deterministic_entities(text).entities
        model_all = to_canonical(text, raw_by_id[ex["example_id"]], model_name)
        model_alone = [e for e in model_all if e.confidence >= THRESHOLD]
        combined = merge_hybrid_entities(deterministic, model_all, HybridMergeConfig(mode="hybrid", min_confidence=THRESHOLD)).entities
        per_example.append({"example_id": ex["example_id"], "gold": gold, "deterministic": deterministic,
                            "model_alone": model_alone, "combined": combined})
    systems = ["model_alone", "deterministic", "combined"]
    zero = [ex for ex in per_example if not ex["gold"]]
    result = {"seed": seed, "systems": {s: summarize(per_example, s) for s in systems},
              "bootstrap": bootstrap(per_example, systems),
              "no_entity_examples": {"ids": [ex["example_id"] for ex in zero],
                                     "false_positives": {s: sum(len(ex[s]) for ex in zero) for s in systems}},
              "per_example": [{"example_id": ex["example_id"],
                               **{s: [[e.start_char, e.end_char, str(e.entity_type)] for e in ex[s]] for s in ["gold"] + systems}}
                              for ex in per_example]}
    return result


def verdict(result: dict) -> dict:
    c = result["systems"]["combined"]
    d = result["systems"]["deterministic"]
    losses = {t: {"deterministic_f1": d["per_type"][t]["f1"], "combined_f1": c["per_type"][t]["f1"],
                  "gold_support": d["per_type"][t]["gold_support"]}
              for t in BRIEF_TYPES if c["per_type"][t]["f1"] < d["per_type"][t]["f1"]}
    paired_low = result["bootstrap"]["paired_combined_minus_deterministic"]["ci95"][0]
    criteria = {
        "f1_at_least_0.838": {"value": c["overall"]["f1"], "pass": c["overall"]["f1"] >= F1_MIN},
        "paired_improvement_ci_above_zero": {"value": result["bootstrap"]["paired_combined_minus_deterministic"], "pass": paired_low > 0},
        "precision_at_least_0.805": {"value": c["overall"]["precision"], "pass": c["overall"]["precision"] >= PRECISION_MIN},
        "no_loss_on_brief_types": {"value": losses, "pass": not losses},
        "no_false_positives_on_no_entity_examples": {"value": result["no_entity_examples"]["false_positives"]["combined"],
                                                      "pass": result["no_entity_examples"]["false_positives"]["combined"] == 0},
    }
    return {"criteria": criteria, "overall": "PASS" if all(v["pass"] for v in criteria.values()) else "FAIL"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 22, 33])
    args = parser.parse_args()
    gold_payload = load_gold_payload()  # validates the frozen 36-example / 89-entity contract
    results = [score_seed(seed, gold_payload) for seed in args.seeds]
    d0 = results[0]["systems"]["deterministic"]["overall"]["f1"]
    ranked = sorted(results, key=lambda r: r["systems"]["combined"]["overall"]["f1"])
    median = ranked[len(ranked) // 2]
    mean = {s: {k: round(statistics.mean(r["systems"][s]["overall"][k] for r in results), 6) for k in ("precision", "recall", "f1")}
            for s in ("model_alone", "deterministic", "combined")}
    summary = {"deterministic_f1_recomputed": d0, "deterministic_f1_frozen": D0_F1_FROZEN,
               "median_seed": median["seed"], "seed_order_by_combined_f1": [r["seed"] for r in ranked],
               "mean_over_seeds": mean, "verdict_median_seed": verdict(median),
               "verdict_per_seed": {r["seed"]: verdict(r)["overall"] for r in results}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e1_results.json").write_text(json.dumps({"summary": summary, "seeds": results}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
