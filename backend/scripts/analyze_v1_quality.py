"""Run deterministic quality analysis over the V1 diagnostic judgment corpus."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_analysis.scoring import decide_candidate_quality  # noqa: E402
from backend.scripts.corpus_utils import load_manifest, write_manifest_atomic  # noqa: E402
from backend.scripts.generate_judgment_review_report import clean_text_preview  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
V1_JUDGMENTS = MANIFEST_DIR / "development_judgments.json"
OUTPUT_MANIFEST = MANIFEST_DIR / "v1_quality_analysis.json"


def text_for_record(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("case_name") or ""),
        str(record.get("court_name") or ""),
        str(record.get("acquisition_query") or ""),
        str(record.get("notes") or ""),
    ]
    raw_file_path = record.get("raw_file_path")
    if raw_file_path:
        raw_path = REPO_ROOT / str(raw_file_path)
        if raw_path.exists() and raw_path.suffix.lower() in {".html", ".htm", ".txt", ".json"}:
            parts.append(clean_text_preview(raw_path.read_text(encoding="utf-8", errors="ignore"), 4000))
    return "\n".join(parts)


def analyze() -> list[dict[str, Any]]:
    records = load_manifest(V1_JUDGMENTS)
    results: list[dict[str, Any]] = []
    for record in records:
        decision = decide_candidate_quality(
            text_for_record(record),
            record,
            duplicate=record.get("status") == "excluded_duplicate",
            corrupt=record.get("status") == "failed",
        )
        result = {
            "source_document_id": record.get("source_document_id"),
            "local_id": record.get("local_id"),
            "case_name": record.get("case_name"),
            "acquisition_status": record.get("status"),
            "offence_family": record.get("offence_family"),
            "document_type_score": decision.document_type_score,
            "criminal_relevance_score": decision.criminal_relevance_score,
            "metadata_quality_score": decision.metadata_quality_score,
            "detected_statutes": decision.detected_statutes,
            "detected_regime": decision.legal_regime,
            "automated_candidate_decision": decision.decision,
            "reason_codes": decision.reasons,
            "analysis_version": "v2_recent_criminal_filter",
            "analyzed_at": datetime.now(UTC).isoformat(),
        }
        results.append(result)
    write_manifest_atomic(OUTPUT_MANIFEST, results)
    return results


def main() -> int:
    results = analyze()
    counts: dict[str, int] = {}
    for result in results:
        decision = str(result["automated_candidate_decision"])
        counts[decision] = counts.get(decision, 0) + 1
    print(f"V1 records analyzed: {len(results)}")
    print(json.dumps(counts, sort_keys=True))
    print(f"Wrote {OUTPUT_MANIFEST.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
