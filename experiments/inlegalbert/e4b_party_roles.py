"""Step E4b: Parties & Roles with the two fixes. Regression check now; the held-out judge later. No LLM.

Plan and frozen rules: docs/experiments/NER_PARTY_ROLES_E4B_PLAN.md.

``regression``: the 5 fixtures and 10 synthetic documents of E4, regex only (S0) vs regex + model with the E4b fixes
(S1). **Not the judge.** It compares S1 with E4's combined output (``results/e4_party_roles.json``): every gold party E4
matched strictly must still be matched, and E4's six errors are listed with what happened to each. It never opens
the public label files.

``judge``: the 5 public excerpts, scored once (rules J1-J6). It refuses to run while any excerpt is unlabelled, and
refuses to overwrite ``results/e4b_judge.json``.

    .venv/bin/python experiments/inlegalbert/e4b_party_roles.py regression --out experiments/inlegalbert/results
    .venv/bin/python experiments/inlegalbert/e4b_party_roles.py judge --out experiments/inlegalbert/results
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "party_gold"))

import e4_party_roles as e4  # noqa: E402  (run_system: the upload path, S0 or S1)
import score_parties as scorer  # noqa: E402

PUBLIC_IDS = ("p01_gujarat_hc_2021", "p02_andhra_hc_2023", "p03_punjab_hc_2023", "p04_supreme_court_2022", "p05_allahabad_hc_2019")
E4_ERRORS = {  # E4's six false positives (NER_PARTY_ROLES_RESULTS.md section 3)
    "f_chargesheet": ["accused: Dev Fake"],
    "s03_chargesheet_four_accused": ["respondent: Manoj Gaikar @ Bunty", "respondent: Farhan Shaikhwadi",
                                     "respondent: Kavita Dongrekar", "respondent: Raju Tam"],
    "s07_judgment_criminal_appeal": ["appellant: Bharat Ninave @ Bha"],
}


def run_both(doc_ids: list[str]) -> tuple[dict, dict, dict]:
    preds_off, _meta_off = e4.run_system("deterministic", doc_ids)
    preds_on, meta_on = e4.run_system("combined", doc_ids)
    status = meta_on["status"]
    if status["active"] != "combined" or status["model"].get("status") != "ready" or status["calls"]["fallback_calls"]:
        raise SystemExit(f"combined backend not active for every call: {status}")
    return preds_off, preds_on, meta_on


def wrong_accused_roles(gold: dict[str, dict], predictions: dict[str, list[dict]]) -> dict[str, list[str]]:
    """J3: S1 parties naming a gold accused (role or alternative role) with a role that party cannot have."""
    out: dict[str, list[str]] = {}
    for doc_id, preds in predictions.items():
        accused = [g for g in gold[doc_id]["parties"] if "accused" in {g["role"], *g.get("alternative_roles", [])}]
        bad = [f"{p['role']}: {p['name']}" for p in preds for g in accused
               if scorer.name_credit(p["name"], g["name"]) == 1.0 and scorer.role_credit(p["role"], g) != 1.0]
        if bad:
            out[doc_id] = bad
    return out


def report(gold: dict, doc_ids: list[str], preds_off: dict, preds_on: dict) -> dict[str, Any]:
    base = {d: scorer.score_document(gold[d]["parties"], preds_off[d]) for d in doc_ids}
    new = {d: scorer.score_document(gold[d]["parties"], preds_on[d]) for d in doc_ids}
    boot = scorer.paired_bootstrap([base[d] for d in doc_ids], [new[d] for d in doc_ids])
    e4_rules = scorer.evaluate_rules({d: gold[d] for d in doc_ids}, base, new, {d: preds_on[d] for d in doc_ids}, boot)
    micro_on, micro_off = scorer.micro(new.values()), scorer.micro(base.values())
    wrong = wrong_accused_roles(gold, {d: preds_on[d] for d in doc_ids})
    rules = {
        "J1_precision_at_least_0.90": {"pass": micro_on["precision"] is not None and micro_on["precision"] >= 0.90,
                                       "combined_precision": micro_on["precision"]},
        "J2_recall_gain_at_least_0.10": {"pass": micro_on["recall"] - micro_off["recall"] >= 0.10,
                                         "delta": micro_on["recall"] - micro_off["recall"]},
        "J3_no_wrong_accused_role": {"pass": not wrong, "wrong": wrong},
        "J4_no_regex_party_lost": e4_rules["R3_no_regex_party_lost"],
        "J5_valid_reference": e4_rules["R5_valid_reference"],
        "J6_none_invented_on_empty_docs": {**e4_rules["R6_none_invented_on_empty_docs"],
                                           "vacuous": not e4_rules["R6_none_invented_on_empty_docs"]["empty_docs"]},
    }
    rules["overall"] = "PASS" if all(v["pass"] for v in rules.values()) else "FAIL"
    return {
        "documents": len(doc_ids), "gold_parties": sum(len(gold[d]["parties"]) for d in doc_ids),
        "micro": {"regex": micro_off, "combined": micro_on},
        "per_role": {"regex": scorer.per_role(base.values()), "combined": scorer.per_role(new.values())},
        "bootstrap": boot, "rules": rules,
        "per_document": {d: {"gold": len(gold[d]["parties"]),
                             "regex": {k: base[d][k] for k in ("tp", "fp", "fn", "found_gold", "false_positives")},
                             "combined": {k: new[d][k] for k in ("tp", "fp", "fn", "found_gold", "missed_gold", "false_positives",
                                                                  "partial_matches")},
                             "combined_items": [f"{p['role']}: {p['name']} [{p['private_evidence_id']}]" for p in preds_on[d]]}
                         for d in doc_ids},
    }


def regression(out_dir: Path) -> int:
    gold, _ = scorer.load_gold(include_public=False)  # never opens the public label files
    doc_ids = list(gold)
    preds_off, preds_on, meta_on = run_both(doc_ids)
    result = report(gold, doc_ids, preds_off, preds_on)
    e4_result = json.loads((HERE / "results/e4_party_roles.json").read_text(encoding="utf-8"))
    lost = {}
    for d in doc_ids:
        before = set(e4_result["per_document"][d]["combined"]["found_gold"])
        missing = sorted(before - set(result["per_document"][d]["combined"]["found_gold"]))
        if missing:
            lost[d] = missing
    errors = {d: {error: error in result["per_document"][d]["combined"]["false_positives"] for error in items}
              for d, items in E4_ERRORS.items()}
    result.update({
        "label": "REGRESSION CHECK ONLY - NOT THE JUDGE (NER_PARTY_ROLES_E4B_PLAN.md section 5)",
        "status": "UNREVIEWED", "ner_status_combined": meta_on["status"],
        "e4_correct_parties_lost": lost,
        "e4_errors_still_present": errors,
        "e4_combined_micro": e4_result["evaluation_sets"]["fixtures+synthetic"]["micro"]["combined"],
    })
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "e4b_regression.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    fmt = lambda v: "-" if v is None else f"{v:.3f}"  # noqa: E731
    print("REGRESSION CHECK ONLY - NOT THE JUDGE")
    for name, m in (("regex", result["micro"]["regex"]), ("E4 combined", result["e4_combined_micro"]), ("E4b combined", result["micro"]["combined"])):
        print(f"  {name:13s} P {fmt(m['precision'])} R {fmt(m['recall'])} F1 {fmt(m['f1'])} (TP {m['tp']} FP {m['fp']} FN {m['fn']})")
    print("  E4 correct parties lost:", lost or "none")
    print("  E4 errors still present:", {d: [e for e, v in x.items() if v] for d, x in errors.items()})
    for d, row in result["per_document"].items():
        if row["combined"]["false_positives"] or row["combined"]["missed_gold"]:
            print(f"  {d}: FP {row['combined']['false_positives']} missed {row['combined']['missed_gold']}")
    return 0


def judge(out_dir: Path) -> int:
    target = out_dir / "e4b_judge.json"
    if target.exists():
        raise SystemExit(f"{target} exists: the judge is scored once (plan section 2)")
    gold, pending = scorer.load_gold(include_public=True)
    if pending or any(d not in gold for d in PUBLIC_IDS):
        raise SystemExit(f"not all excerpts are labelled: pending {pending}")
    doc_ids = list(PUBLIC_IDS)
    preds_off, preds_on, meta_on = run_both(doc_ids)
    result = report(gold, doc_ids, preds_off, preds_on)
    result.update({"label": "E4b JUDGE: the 5 public excerpts, scored once", "status": "UNREVIEWED",
                   "ner_status_combined": meta_on["status"],
                   "labellers": sorted({gold[d]["labeller"] for d in doc_ids})})
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"micro": result["micro"], "rules": {k: (v if isinstance(v, str) else v["pass"]) for k, v in result["rules"].items()}},
                     indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("regression", "judge"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return regression(args.out) if args.mode == "regression" else judge(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
