"""Step E4 party scorer: precision, recall and F1 of (name, role) parties against the party gold set.

Frozen with the gold set and docs/experiments/NER_PARTY_ROLES_PLAN.md, before any flag-on run. Pure Python; it does
not import product code, so the scoring cannot follow the system being scored.

**Name normalization** (``normalize_name``): Unicode NFKC, casefold; "alias", "urf", "a.k.a." -> "@"; "(decd.)" and a
trailing "& Ors." / "and anr." / "and others" / "and another" removed; leading honorifics (Shri, Smt, Sri, Shrimati,
Kumari, Km, Mr, Mrs, Ms, Miss, Dr, M/s, Messrs, Late) and a leading "the" removed; punctuation other than "@" and "&"
turned into spaces; whitespace collapsed.

**Strict match (primary; all pass rules use it):** normalized names equal, and the predicted role is the gold role or
one of its ``alternative_roles``. Matching is one-to-one, in prediction order. A prediction that strictly matches a gold
party already matched (the same person again, with another acceptable role) is a *duplicate*: neither TP nor FP.

**Partial credit (secondary, reported only):** after strict matching, the remaining predictions and gold parties are
paired greedily by credit = name credit x role credit (ties: prediction order, then gold order), credit > 0 only.
- name credit 1 (equal), 0.5 when an alias part of one equals an alias part of the other ("Neelam" for
  "Neelam @ Neeraj"), or when one name's tokens are a contiguous run inside the other's, covering at least half of the
  longer name's tokens, and not made only of generic words ("Kuppaiah" for "A. Kuppaiah"); else 0;
- role credit 1 (acceptable role), 0.5 when the roles are in the same group: moving party {petitioner, appellant,
  applicant, petitioner/appellant} or first informant {complainant, informant}; else 0.

**Metrics:** micro precision = TP / (predictions - duplicates), recall = TP / gold parties, F1. Per role: TP and FN are
counted under the gold party's primary role, FP under the predicted role; F1_role = 2TP / (2TP + FP + FN), and 1.0
for a role with no gold party and no prediction.
**Bootstrap:** 10,000 paired resamples of documents, seed 20261111 (INLEGALBERT_PLAN.md section 6), 95% percentile CI.

    .venv/bin/python experiments/inlegalbert/party_gold/score_parties.py --self-test
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
ROLES = ("appellant", "respondent", "petitioner", "applicant", "accused", "complainant", "informant")
ROLE_GROUPS = ({"petitioner", "appellant", "applicant", "petitioner/appellant"}, {"complainant", "informant"})
GENERIC_TOKENS = {"the", "state", "of", "union", "india", "government", "and", "&", "@", "bank", "ltd", "limited",
                  "pvt", "private", "company", "police", "station", "accused", "complainant", "petitioner", "respondent",
                  "appellant", "applicant", "informant"}
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261111
_HONORIFIC = re.compile(r"^(?:shri|smt|sri|shrimati|kumari|km|mr|mrs|ms|miss|dr|m/s|messrs|late)\b\.?\s*")


# ---------------------------------------------------------------------------
# Normalization and credit
# ---------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    text = re.sub(r"\b(?:alias|urf|a\.\s?k\.\s?a\.?|aka)\b", " @ ", text)
    text = re.sub(r"\(\s*(?:decd|deceased|dead)\.?\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:")
    text = re.sub(r"(?:\s*&\s*|\s+and\s+)(?:ors|others|anr|another)\.?$", "", text).strip(" ,.;:")
    while True:
        stripped = _HONORIFIC.sub("", text)
        stripped = re.sub(r"^the\s+", "", stripped)
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"[^\w@&\s]", " ", text)
    text = re.sub(r"\s*@\s*", " @ ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(normalized: str) -> list[str]:
    return [t for t in normalized.split() if t != "@"]


def _alias_parts(normalized: str) -> set[str]:
    return {part.strip() for part in normalized.split("@") if part.strip()}


def _contiguous(short: list[str], long: list[str]) -> bool:
    return any(long[i:i + len(short)] == short for i in range(len(long) - len(short) + 1))


def name_credit(predicted: str, gold: str) -> float:
    a, b = normalize_name(predicted), normalize_name(gold)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _alias_parts(a) & _alias_parts(b):
        return 0.5
    ta, tb = _tokens(a), _tokens(b)
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if short and _contiguous(short, long) and len(short) >= math.ceil(len(long) / 2) and not set(short) <= GENERIC_TOKENS:
        return 0.5
    return 0.0


def role_credit(predicted_role: str, gold: dict) -> float:
    role = predicted_role.strip().casefold()
    acceptable = {gold["role"], *gold.get("alternative_roles", [])}
    if role in acceptable:
        return 1.0
    if any(role in group and acceptable & group for group in ROLE_GROUPS):
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Per-document scoring
# ---------------------------------------------------------------------------


def score_document(gold_parties: list[dict], predictions: list[dict]) -> dict[str, Any]:
    """``predictions``: [{"role", "name", ...}] in output order. Returns counts, matches and per-role counts."""
    matched_gold: dict[int, int] = {}  # gold index -> prediction index
    status = ["fp"] * len(predictions)
    for pi, pred in enumerate(predictions):
        strict = [gi for gi, g in enumerate(gold_parties)
                  if name_credit(pred["name"], g["name"]) == 1.0 and role_credit(pred["role"], g) == 1.0]
        free = [gi for gi in strict if gi not in matched_gold]
        if free:
            matched_gold[free[0]] = pi
            status[pi] = "tp"
        elif strict:
            status[pi] = "duplicate"
    tp = sum(s == "tp" for s in status)
    duplicates = sum(s == "duplicate" for s in status)
    fp = sum(s == "fp" for s in status)
    fn_indices = [gi for gi in range(len(gold_parties)) if gi not in matched_gold]

    # partial credit over what is left
    pairs = []
    for pi, pred in enumerate(predictions):
        if status[pi] != "fp":
            continue
        for gi in fn_indices:
            credit = name_credit(pred["name"], gold_parties[gi]["name"]) * role_credit(pred["role"], gold_parties[gi])
            if credit > 0:
                pairs.append((-credit, pi, gi))
    used_p, used_g, partial = set(), set(), 0.0
    partial_matches = []
    for neg, pi, gi in sorted(pairs):
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        partial += -neg
        partial_matches.append({"prediction": predictions[pi]["name"], "gold": gold_parties[gi]["name"], "credit": -neg})

    per_role: dict[str, dict[str, int]] = {}

    def bump(role: str, key: str) -> None:
        per_role.setdefault(role, {"tp": 0, "fp": 0, "fn": 0})[key] += 1

    for gi, g in enumerate(gold_parties):
        bump(g["role"], "tp" if gi in matched_gold else "fn")
    for pi, pred in enumerate(predictions):
        if status[pi] == "fp":
            bump(pred["role"].strip().casefold(), "fp")
    return {
        "gold": len(gold_parties), "predicted": len(predictions), "tp": tp, "fp": fp, "fn": len(fn_indices),
        "duplicates": duplicates, "partial_tp": tp + partial,
        "found_gold": sorted(gold_parties[gi]["name"] + " | " + gold_parties[gi]["role"] for gi in matched_gold),
        "missed_gold": [gold_parties[gi]["name"] + " | " + gold_parties[gi]["role"] for gi in fn_indices],
        "false_positives": [f"{p['role']}: {p['name']}" for p, s in zip(predictions, status) if s == "fp"],
        "partial_matches": partial_matches, "per_role": per_role,
    }


# ---------------------------------------------------------------------------
# Aggregates, bootstrap
# ---------------------------------------------------------------------------


def prf(tp: float, predicted: float, gold: float) -> dict[str, float | None]:
    p = tp / predicted if predicted else None
    r = tp / gold if gold else None
    f = 2 * tp / (predicted + gold) if (predicted + gold) else None
    return {"precision": p, "recall": r, "f1": f}


def micro(rows: Iterable[dict]) -> dict[str, Any]:
    rows = list(rows)
    tp = sum(r["tp"] for r in rows)
    scored = sum(r["predicted"] - r["duplicates"] for r in rows)
    gold = sum(r["gold"] for r in rows)
    partial = sum(r["partial_tp"] for r in rows)
    return {"tp": tp, "fp": sum(r["fp"] for r in rows), "fn": sum(r["fn"] for r in rows), "gold": gold,
            "predicted": scored, "duplicates": sum(r["duplicates"] for r in rows),
            **prf(tp, scored, gold), "partial": prf(partial, scored, gold)}


def per_role(rows: Iterable[dict]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, int]] = {}
    for row in rows:
        for role, counts in row["per_role"].items():
            for key, value in counts.items():
                totals.setdefault(role, {"tp": 0, "fp": 0, "fn": 0})[key] += value
    out = {}
    for role, c in sorted(totals.items()):
        denominator = 2 * c["tp"] + c["fp"] + c["fn"]
        out[role] = {**c, "f1": 2 * c["tp"] / denominator if denominator else None,
                     "recall": c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None}
    return out


def _percentile_ci(values: list[float]) -> list[float]:
    ordered = sorted(values)
    return [round(ordered[int(0.025 * len(ordered))], 4), round(ordered[int(0.975 * len(ordered)) - 1], 4)]


def paired_bootstrap(base: list[dict], new: list[dict]) -> dict[str, Any]:
    """Document-level paired bootstrap of micro precision, recall and F1 (base = regex-only, new = combined)."""
    assert len(base) == len(new)
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(base)
    draws: dict[str, dict[str, list[float]]] = {m: {"base": [], "new": [], "diff": []} for m in ("precision", "recall", "f1")}
    for _ in range(BOOTSTRAP_RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        a, b = micro(base[i] for i in idx), micro(new[i] for i in idx)
        for metric in draws:
            if a[metric] is None or b[metric] is None:
                continue
            draws[metric]["base"].append(a[metric])
            draws[metric]["new"].append(b[metric])
            draws[metric]["diff"].append(b[metric] - a[metric])
    a, b = micro(base), micro(new)
    return {metric: {"regex": {"value": a[metric], "ci95": _percentile_ci(d["base"])},
                     "combined": {"value": b[metric], "ci95": _percentile_ci(d["new"])},
                     "difference": {"value": None if a[metric] is None or b[metric] is None else b[metric] - a[metric],
                                    "ci95": _percentile_ci(d["diff"])},
                     "resamples_used": len(d["diff"])}
            for metric, d in draws.items()}


# ---------------------------------------------------------------------------
# Rules (docs/experiments/NER_PARTY_ROLES_PLAN.md section 3)
# ---------------------------------------------------------------------------

RECALL_GAIN = 0.10


def evaluate_rules(gold: dict[str, dict], base: dict[str, dict], new: dict[str, dict], new_predictions: dict[str, list[dict]],
                   boot: dict[str, Any]) -> dict[str, Any]:
    """``base``/``new``: doc_id -> score_document row. ``new_predictions`` items carry ``valid_reference`` (bool)."""
    recall = boot["recall"]
    r1 = recall["difference"]["value"] is not None and recall["difference"]["value"] >= RECALL_GAIN and recall["difference"]["ci95"][0] > 0
    precision = boot["precision"]
    r2 = precision["combined"]["value"] is not None and (precision["regex"]["value"] is None
                                                        or precision["combined"]["value"] >= precision["regex"]["value"])
    lost = {d: sorted(set(base[d]["found_gold"]) - set(new[d]["found_gold"])) for d in base}
    lost = {d: v for d, v in lost.items() if v}
    base_roles, new_roles = per_role(base.values()), per_role(new.values())
    def f1(roles: dict, role: str) -> float:  # a role with nothing to score (no gold, no prediction) counts as 1.0
        value = roles.get(role, {}).get("f1")
        return 1.0 if value is None else value

    worse = {role: {"regex_f1": f1(base_roles, role), "combined_f1": f1(new_roles, role)}
             for role in sorted(set(base_roles) | set(new_roles)) if f1(new_roles, role) < f1(base_roles, role)}
    invalid = {d: [f"{p['role']}: {p['name']}" for p in preds if not p.get("valid_reference")] for d, preds in new_predictions.items()}
    invalid = {d: v for d, v in invalid.items() if v}
    empty_docs = [d for d, g in gold.items() if not g["parties"]]
    invented = {d: new[d]["false_positives"] for d in empty_docs if new[d]["predicted"]}
    rules = {
        "R1_recall_gain": {"pass": r1, "delta": recall["difference"]["value"], "ci95": recall["difference"]["ci95"],
                           "threshold": RECALL_GAIN},
        "R2_precision_not_lower": {"pass": r2, "regex": precision["regex"]["value"], "combined": precision["combined"]["value"],
                                   "delta_ci95": precision["difference"]["ci95"]},
        "R3_no_regex_party_lost": {"pass": not lost, "lost": lost},
        "R4_no_role_worse": {"pass": not worse, "worse": worse, "regex": base_roles, "combined": new_roles},
        "R5_valid_reference": {"pass": not invalid, "invalid": invalid,
                               "checked": sum(len(p) for p in new_predictions.values())},
        "R6_none_invented_on_empty_docs": {"pass": not invented, "empty_docs": empty_docs, "invented": invented},
    }
    rules["overall"] = "PASS" if all(v["pass"] for v in rules.values() if isinstance(v, dict)) else "FAIL"
    return rules


# ---------------------------------------------------------------------------
# Gold loading
# ---------------------------------------------------------------------------


def load_gold(include_public: bool = True) -> tuple[dict[str, dict], list[str]]:
    """(doc_id -> gold record, public doc_ids still pending). Public excerpts count only once labelled."""
    gold = {}
    for path in sorted((HERE / "gold").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        gold[record["doc_id"]] = record
    pending = []
    if include_public:
        for path in sorted((HERE / "public").glob("*.labels.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("label_status") != "labelled":
                pending.append(record["doc_id"])
                continue
            validate_labels(record)
            gold[record["doc_id"]] = record
    return gold, pending


def validate_labels(record: dict) -> None:
    for party in record["parties"]:
        if not party.get("name") or party.get("role") not in ROLES:
            raise ValueError(f"{record['doc_id']}: invalid party {party}")
        for role in party.get("alternative_roles", []):
            if role not in ROLES:
                raise ValueError(f"{record['doc_id']}: invalid alternative role {role}")
    if not record.get("labeller"):
        raise ValueError(f"{record['doc_id']}: labelled files need a labeller")


# ---------------------------------------------------------------------------
# Self-test (no system output): the scorer's own sanity checks
# ---------------------------------------------------------------------------


def self_test() -> None:
    assert normalize_name("The State Of Madhya Pradesh") == normalize_name("State of Madhya Pradesh")
    assert normalize_name("Devender Singh & Ors.") == "devender singh"
    assert normalize_name("Venus Goyal and anr.") == "venus goyal"
    assert normalize_name("NEELAM @ NEERAJ") == normalize_name("Neelam alias Neeraj") == "neelam @ neeraj"
    assert normalize_name("M/s Sunrise Fictional Traders") == "sunrise fictional traders"
    assert normalize_name("Smt. Kunja Devi") == "kunja devi"
    assert normalize_name("KARMANBHAI REVABHAI BHARWAD (decd.)") == "karmanbhai revabhai bharwad"
    assert name_credit("Neelam", "Neelam @ Neeraj") == 0.5
    assert name_credit("Kuppaiah", "A. Kuppaiah") == 0.5
    assert name_credit("State", "State of Gujarat") == 0.0
    assert name_credit("Ravi", "Ravi Sampleton Kumar") == 0.0
    g = {"role": "appellant", "alternative_roles": ["accused"]}
    assert role_credit("Appellant", g) == role_credit("accused", g) == 1.0
    assert role_credit("petitioner/appellant", g) == 0.5 and role_credit("respondent", g) == 0.0
    gold_parties = [{"name": "Ravi Sampleton", "role": "accused", "alternative_roles": []},
                    {"name": "Meera Placeholder", "role": "complainant", "alternative_roles": ["informant"]}]
    row = score_document(gold_parties, [{"name": "Meera Placeholder", "role": "complainant"},
                                        {"name": "Meera Placeholder", "role": "informant"},
                                        {"name": "Ravi", "role": "accused"},
                                        {"name": "Kiran Exampleton", "role": "accused"}])
    assert (row["tp"], row["duplicates"], row["fp"], row["fn"]) == (1, 1, 2, 1), row
    assert row["partial_tp"] == 1.5  # "Ravi" covers 1 of 2 tokens of "Ravi Sampleton": name 0.5 x role 1.0
    gold, pending = load_gold()
    for doc_id, record in gold.items():
        perfect = score_document(record["parties"], [{"name": p["name"], "role": p["role"]} for p in record["parties"]])
        assert perfect["tp"] == len(record["parties"]) and perfect["fp"] == perfect["fn"] == 0, doc_id
    rows = {d: score_document(r["parties"], [{"name": p["name"], "role": p["role"]} for p in r["parties"]]) for d, r in gold.items()}
    boot = paired_bootstrap(list(rows.values()), list(rows.values()))
    assert boot["recall"]["difference"]["ci95"] == [0.0, 0.0]
    print(f"self-test OK: {len(gold)} gold documents, {sum(len(r['parties']) for r in gold.values())} parties, "
          f"public pending: {pending}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
