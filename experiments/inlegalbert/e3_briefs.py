"""Step E3 brief check: the brief fixtures through the local document map, NER backend off and on. No LLM.

Fixtures: the five professional-brief fixtures (judgment, FIR, charge sheet, petition, unknown), rendered to PDFs and
parsed exactly as an upload (``brief_fixtures``), and the scanned FIR (``fixtures/ocr/fir_scanned.pdf``) through the
OCR parser, compared with ``fir.expected.json``. The dense provider is the product's BGE-M3 query embedder, the same
for both runs.

Per fixture and backend it records:
- the expected-output comparison, field by field, as the fixture tests check it (document type; parties with roles;
  dated events; procedural stages; evidence categories present and absent): items found and items lost;
- the brief's document fields (``professional_brief``: parties and roles, chronology, procedural considerations,
  evidence identified), compared off vs on;
- the map's NER-derived fields (``parties``, ``important_dates``, ``explicit_sections``, ``explicit_statutes``), the
  trusted retrieval query built from the map, and the rendered map text sent to the model: gains and losses.

Rule (step E3 brief): no fixture may lose an expected item.

    .venv/bin/python experiments/inlegalbert/e3_briefs.py --out experiments/inlegalbert/results
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

FIXTURES = ("judgment", "fir", "chargesheet", "petition", "unknown", "fir_scanned")
EVIDENCE_LABELS = {"witnesses": "Witnesses", "documents": "Documents", "medical_forensic": "Medical/forensic",
                   "electronic": "Electronic", "recoveries": "Recoveries/seizures"}


def private_chunks(name: str) -> tuple[str, list[Any]]:
    from backend.app.services.chunker import chunk_document
    from backend.app.services.document_parser import parse_document
    from backend.app.services.private_pdf_rag import build_private_chunks
    from backend.scripts.tests.brief_fixtures import fixture_private_chunks

    if name != "fir_scanned":
        return fixture_private_chunks(name)
    path = REPO / "backend/scripts/tests/fixtures/ocr/fir_scanned.pdf"
    document = parse_document(path, ocr_profile="query")
    document["source_file_name"] = path.name
    return path.name, build_private_chunks(chunk_document(document))


def expectation_check(document_map: Any, expected: dict) -> dict[str, Any]:
    from backend.app.services import professional_brief as brief

    parties = brief.parties_and_roles(document_map)
    dates = {item.split(" - ", 1)[0] for item in brief.chronology(document_map)}
    stages = {label.strip().lower() for stage in document_map.procedural_stages for label in stage.stages}
    categories = {label.strip() for item in brief.evidence_identified(document_map) for label in item.split(": ", 1)[0].split(",")}

    def party_found(party: dict) -> bool:
        return any(item.lower().startswith(f"{party['role']}:") and party["name"].lower() in item.lower() for item in parties)

    fields = {
        "document_type": {"expected": [expected["document_type"]],
                          "found": [expected["document_type"]] if document_map.document_type == expected["document_type"] else []},
        "parties": {"expected": [f"{p['role']}: {p['name']}" for p in expected["parties"]],
                    "found": [f"{p['role']}: {p['name']}" for p in expected["parties"] if party_found(p)]},
        "dated_events": {"expected": expected["dated_events"], "found": [d for d in expected["dated_events"] if d in dates]},
        "procedural_stages": {"expected": expected["procedural_stages"],
                              "found": [s for s in expected["procedural_stages"] if s.lower() in stages]},
        "evidence_categories": {"expected": expected["evidence_categories"],
                                "found": [c for c in expected["evidence_categories"] if EVIDENCE_LABELS[c] in categories]},
        "absent_evidence_categories": {"expected": expected.get("absent_evidence_categories", []),
                                       "found": [c for c in expected.get("absent_evidence_categories", []) if EVIDENCE_LABELS[c] not in categories]},
    }
    for value in fields.values():
        value["missing"] = [item for item in value["expected"] if item not in value["found"]]
    return fields


def snapshot(name: str, backend: str, dense_provider: Any, budget: int) -> dict[str, Any]:
    from backend.app.core.config import Settings
    from backend.app.services import ner_backend
    from backend.app.services import professional_brief as brief
    from backend.app.services.local_document_map import build_enriched_trusted_query, build_local_document_map, render_local_document_map
    from backend.scripts.tests.brief_fixtures import expected

    os.environ["LEGALAI_NER_BACKEND"] = backend
    filename, chunks = private_chunks(name)
    if backend == "combined":
        ner_backend.load_engine(Settings())  # load outside the timed map build
    started = perf_counter()
    document_map = build_local_document_map(chunks, filename=filename, dense_provider=dense_provider, token_budget_tokens=budget)
    map_ms = round((perf_counter() - started) * 1000, 1)
    return {
        "chunks": len(chunks),
        "map_ms": map_ms,
        "expectations": expectation_check(document_map, expected("fir" if name == "fir_scanned" else name)),
        "brief_fields": {"parties_and_roles": brief.parties_and_roles(document_map), "chronology": brief.chronology(document_map),
                         "procedural_considerations": brief.procedural_considerations(document_map),
                         "evidence_identified": brief.evidence_identified(document_map)},
        "ner_fields": {"parties": document_map.parties, "important_dates": document_map.important_dates,
                       "explicit_sections": document_map.explicit_sections, "explicit_statutes": document_map.explicit_statutes},
        "trusted_query": build_enriched_trusted_query(document_map, fallback_query="Prepare a case brief for this document."),
        "rendered_map": render_local_document_map(document_map),
        "ner_status": ner_backend.ner_status(Settings()),
    }


def diff(off: list[str], on: list[str]) -> dict[str, list[str]]:
    return {"gained": [x for x in on if x not in off], "lost": [x for x in off if x not in on]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from backend.app.core.config import Settings
    from backend.scripts.rerun_retrieval_eval import make_service

    service, _device = make_service("product")
    budget = Settings().private_pdf_input_budget_tokens
    report: dict[str, Any] = {"fixtures": {}}
    lost_expected_total = 0
    for name in FIXTURES:
        off = snapshot(name, "deterministic", service.dense_provider, budget)
        on = snapshot(name, "combined", service.dense_provider, budget)
        if on["ner_status"]["active"] != "combined":
            raise SystemExit(f"combined backend not active: {on['ner_status']}")
        expectations = {}
        for field, value in off["expectations"].items():
            found_on = on["expectations"][field]["found"]
            lost = [x for x in value["found"] if x not in found_on]
            lost_expected_total += len(lost)
            expectations[field] = {"expected": len(value["expected"]), "found_off": len(value["found"]), "found_on": len(found_on),
                                   "gained": [x for x in found_on if x not in value["found"]], "lost": lost,
                                   "missing_on": on["expectations"][field]["missing"]}
        report["fixtures"][name] = {
            "chunks": off["chunks"],
            "map_ms": {"deterministic": off["map_ms"], "combined": on["map_ms"]},
            "expected_items": expectations,
            "brief_fields_identical": off["brief_fields"] == on["brief_fields"],
            "brief_fields_diff": {field: diff(off["brief_fields"][field], on["brief_fields"][field]) for field in off["brief_fields"]},
            "ner_fields": {field: {"deterministic": off["ner_fields"][field], "combined": on["ner_fields"][field],
                                   **diff(off["ner_fields"][field], on["ner_fields"][field])} for field in off["ner_fields"]},
            "trusted_query_identical": off["trusted_query"] == on["trusted_query"],
            "trusted_query": {"deterministic": off["trusted_query"], "combined": on["trusted_query"]},
            "rendered_map_identical": off["rendered_map"] == on["rendered_map"],
            "rendered_map_diff": diff(off["rendered_map"].splitlines(), on["rendered_map"].splitlines()),
        }
    report["lost_expected_items"] = lost_expected_total
    report["verdict"] = "PASS" if lost_expected_total == 0 else "FAIL"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "e3_briefs.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, row in report["fixtures"].items():
        print(name, "chunks", row["chunks"], "map_ms", row["map_ms"], "brief identical", row["brief_fields_identical"],
              "trusted query identical", row["trusted_query_identical"], "rendered identical", row["rendered_map_identical"])
        for field, value in row["expected_items"].items():
            print(f"   {field:28s} expected {value['expected']} off {value['found_off']} on {value['found_on']} lost {value['lost']} gained {value['gained']}")
        for field, value in row["ner_fields"].items():
            if value["gained"] or value["lost"]:
                print(f"   NER {field}: +{value['gained']} -{value['lost']}")
    print("lost expected items:", lost_expected_total, "verdict:", report["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
