"""Step E4 measurement: brief Parties & Roles, regex only (flag off) vs regex + model (flag on). No LLM.

Plan and frozen rules: docs/experiments/NER_PARTY_ROLES_PLAN.md. For every document of the party gold set that has
gold labels (the fixtures and the synthetic documents now; each public excerpt once a teammate has labelled it), the
document is rendered to a PDF and parsed, chunked and mapped as an upload (``party_gold_docs.document_chunks`` ->
``build_local_document_map``), once with ``LEGALAI_NER_BACKEND=deterministic`` (S0) and once with ``combined`` (S1,
the real seed 22 checkpoint, hash-checked by the backend). ``document_map.parties_and_roles`` is scored with
``party_gold/score_parties.py``. Public excerpts without labels are not run at all (no flag-on output is produced for
them before they are labelled) and are reported as pending. (The flag-off test snapshot does contain today's regex
output for them; LABELLING_GUIDE.md asks the labeller not to open it.)

Each S1 party's reference is checked independently: the cited chunk must belong to the document and its text must
contain the party's name (case- and whitespace-insensitive).

    .venv/bin/python experiments/inlegalbert/e4_party_roles.py --out experiments/inlegalbert/results
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments/inlegalbert/party_gold"))

import score_parties as scorer  # noqa: E402

SETS = {"fixture": "fixtures", "synthetic": "synthetic", "public": "public"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def run_system(backend: str, doc_ids: list[str]) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    from backend.app.core.config import Settings
    from backend.app.services import ner_backend
    from backend.app.services import professional_brief as brief
    from backend.app.services.local_document_map import build_local_document_map
    from backend.scripts.tests.party_gold_docs import TOKEN_BUDGET, document_chunks

    os.environ["LEGALAI_NER_BACKEND"] = backend
    ner_backend.reset_ner_backend()
    if backend == "combined":
        ner_backend.load_engine(Settings())  # load outside the timed map builds
    out: dict[str, list[dict]] = {}
    timings: dict[str, float] = {}
    rendered: dict[str, list[str]] = {}
    for doc_id in doc_ids:
        filename, chunks = document_chunks(doc_id)
        texts = {chunk.private_chunk_id: _norm(chunk.text) for chunk in chunks}
        started = perf_counter()
        document_map = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=TOKEN_BUDGET)
        timings[doc_id] = round((perf_counter() - started) * 1000, 1)
        out[doc_id] = [{"role": p.role, "name": p.name, "private_evidence_id": p.private_evidence_id,
                        "page_start": p.page_start, "page_end": p.page_end,
                        "valid_reference": bool(p.name and p.private_evidence_id in texts and _norm(p.name) in texts[p.private_evidence_id])}
                       for p in document_map.parties_and_roles]
        rendered[doc_id] = brief.parties_and_roles(document_map)
    status = ner_backend.ner_status(Settings())
    return out, {"status": status, "map_ms": timings, "brief_items": rendered}


def subset_report(gold: dict[str, dict], doc_ids: list[str], base: dict, new: dict, preds_new: dict) -> dict[str, Any]:
    g = {d: gold[d] for d in doc_ids}
    b = {d: base[d] for d in doc_ids}
    n = {d: new[d] for d in doc_ids}
    boot = scorer.paired_bootstrap([b[d] for d in doc_ids], [n[d] for d in doc_ids])
    return {
        "documents": len(doc_ids), "gold_parties": sum(len(gold[d]["parties"]) for d in doc_ids),
        "micro": {"regex": scorer.micro(b.values()), "combined": scorer.micro(n.values())},
        "per_role": {"regex": scorer.per_role(b.values()), "combined": scorer.per_role(n.values())},
        "bootstrap": boot,
        "rules": scorer.evaluate_rules(g, b, n, {d: preds_new[d] for d in doc_ids}, boot),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    gold, pending = scorer.load_gold()
    doc_ids = list(gold)

    preds_off, meta_off = run_system("deterministic", doc_ids)
    preds_on, meta_on = run_system("combined", doc_ids)
    status = meta_on["status"]
    if status["active"] != "combined" or status["model"].get("status") != "ready" or status["calls"]["fallback_calls"]:
        raise SystemExit(f"combined backend not active for every call: {status}")

    base = {d: scorer.score_document(gold[d]["parties"], preds_off[d]) for d in doc_ids}
    new = {d: scorer.score_document(gold[d]["parties"], preds_on[d]) for d in doc_ids}
    regex_kept_first = {d: preds_on[d][:len(preds_off[d])] == preds_off[d] for d in doc_ids}

    labelled_now = [d for d in doc_ids if gold[d]["source"] in {"fixture", "synthetic"}]
    report: dict[str, Any] = {
        "status": "UNREVIEWED",
        "plan": "docs/experiments/NER_PARTY_ROLES_PLAN.md",
        "ner_status_combined": status,
        "public_pending": pending,
        "evaluation_sets": {},
        "per_document": {},
        "regex_output_kept_first_and_unchanged": regex_kept_first,
        "map_ms": {"deterministic": meta_off["map_ms"], "combined": meta_on["map_ms"]},
    }
    report["evaluation_sets"]["fixtures+synthetic"] = subset_report(gold, labelled_now, base, new, preds_on)
    for source in ("fixture", "synthetic", "public"):
        ids = [d for d in doc_ids if gold[d]["source"] == source]
        if ids:
            report["evaluation_sets"][SETS[source]] = subset_report(gold, ids, base, new, preds_on)
    if any(gold[d]["source"] == "public" for d in doc_ids):
        report["evaluation_sets"]["all"] = subset_report(gold, doc_ids, base, new, preds_on)
    for d in doc_ids:
        report["per_document"][d] = {
            "source": gold[d]["source"], "document_type": gold[d].get("document_type"), "gold": len(gold[d]["parties"]),
            "regex": {k: base[d][k] for k in ("predicted", "tp", "fp", "fn", "duplicates", "partial_tp", "found_gold",
                                               "missed_gold", "false_positives", "partial_matches")},
            "combined": {k: new[d][k] for k in ("predicted", "tp", "fp", "fn", "duplicates", "partial_tp", "found_gold",
                                                 "missed_gold", "false_positives", "partial_matches")},
            "regex_items": meta_off["brief_items"][d], "combined_items": meta_on["brief_items"][d],
            "combined_added": [f"{p['role']}: {p['name']} [{p['private_evidence_id']}]" for p in preds_on[d][len(preds_off[d]):]],
            "combined_invalid_references": [f"{p['role']}: {p['name']}" for p in preds_on[d] if not p["valid_reference"]],
        }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "e4_party_roles.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    for name, subset in report["evaluation_sets"].items():
        m = subset["micro"]
        print(f"== {name}: {subset['documents']} docs, {subset['gold_parties']} gold parties")
        for system in ("regex", "combined"):
            s = m[system]
            fmt = lambda v: "-" if v is None else f"{v:.3f}"  # noqa: E731
            print(f"   {system:8s} P {fmt(s['precision'])} R {fmt(s['recall'])} F1 {fmt(s['f1'])}  "
                  f"(TP {s['tp']} FP {s['fp']} FN {s['fn']} dup {s['duplicates']})  partial P {fmt(s['partial']['precision'])} R {fmt(s['partial']['recall'])}")
        for rule, value in subset["rules"].items():
            print(f"   {rule}: {value if isinstance(value, str) else ('PASS' if value['pass'] else 'FAIL')}")
    print("public pending:", pending)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
