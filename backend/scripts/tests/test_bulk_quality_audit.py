"""Tests for offline bulk corpus quality audit tooling."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.scripts import review_bulk_quality_audit as audit


def candidate(
    source_id: str,
    family: str,
    regime: str = "ipc_crpc",
    track: str = "recent_ipc",
    court: str = "high_court",
    status: str = "validated",
    decision: str = "accept_candidate",
    query_id: str | None = None,
    mime_type: str = "application/pdf",
    size: int = 1000,
) -> dict[str, object]:
    return {
        "local_id": f"v2-{source_id}",
        "source_provider": "indian_kanoon",
        "source_document_id": source_id,
        "source_url": f"https://indiankanoon.org/doc/{source_id}/",
        "case_name": f"Case {source_id}",
        "court_name": court,
        "court_level": court,
        "decision_date": None,
        "year": 2024,
        "legal_regime": regime,
        "offence_family": family,
        "known_sections": [],
        "detected_statutes": ["IPC"],
        "regime_evidence": ["Section 302 IPC"],
        "acquisition_query": "query",
        "query_id": query_id or f"q-{family}",
        "temporal_track": track,
        "raw_file_path": f"raw/{source_id}.pdf",
        "sha256": f"sha-{source_id}",
        "file_size_bytes": size,
        "mime_type": mime_type,
        "attribution_required": True,
        "attribution_text": "Judgment data sourced from Indian Kanoon API.",
        "status": status,
        "final_automated_decision": decision,
        "quality_scores": {"document_type": 0.9, "criminal_relevance": 0.9, "metadata_quality": 1.0},
        "document_text_available": True,
        "document_text_length": 1200,
        "document_text_quality": "usable",
    }


class BulkQualityAuditTest(unittest.TestCase):
    def test_deterministic_sample_selection_and_no_duplicates(self) -> None:
        records = [candidate(str(index), family) for index, family in enumerate(sorted(audit.OFFENCE_FAMILIES) * 6, start=1)]

        first, _first_reasons = audit.allocate_sample(records, 25)
        second, _second_reasons = audit.allocate_sample(records, 25)

        self.assertEqual([r["source_document_id"] for r in first], [r["source_document_id"] for r in second])
        self.assertEqual(len(first), 25)
        self.assertEqual(len({r["source_document_id"] for r in first}), 25)

    def test_represents_populated_families_regimes_tracks_and_courts(self) -> None:
        records = [
            candidate("1", "homicide", "ipc_crpc", "recent_ipc", "high_court"),
            candidate("2", "other", "bns_bnss", "current_transition", "supreme_court"),
            candidate("3", "sexual_offences", "mixed_or_transition", "landmark_historical", "district_or_sessions"),
            candidate("4", "theft_and_robbery", "unknown", "recent_ipc", "unknown"),
        ]

        selected, _reasons = audit.allocate_sample(records, 4)

        self.assertEqual({r["offence_family"] for r in selected}, {r["offence_family"] for r in records})
        self.assertEqual({r["legal_regime"] for r in selected}, {r["legal_regime"] for r in records})
        self.assertEqual({r["temporal_track"] for r in selected}, {r["temporal_track"] for r in records})
        self.assertEqual({r["court_level"] for r in selected}, {r["court_level"] for r in records})

    def test_sample_manifest_schema_defaults_pending(self) -> None:
        record = candidate("10", "homicide")
        sample = audit.sample_record(record, 1, ["minimum_offence_family:homicide"])

        self.assertEqual(sample["human_audit_status"], "pending")
        self.assertEqual(sample["source_document_id"], "10")
        self.assertEqual(sample["offence_family_automated"], "homicide")
        self.assertIn("criminal_relevance", sample)
        self.assertIsNone(sample["rag_suitability"])

    def test_apply_review_does_not_overwrite_automated_or_provenance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.json"
            sample = audit.sample_record(candidate("11", "homicide"), 1, ["reason"])
            path.write_text(json.dumps([sample]), encoding="utf-8")

            audit.apply_review(
                "11",
                "Ananthu",
                sample_path=path,
                criminal_relevance="correct",
                document_type="judgment",
                offence_family_review="corrected",
                corrected_offence_family="other",
                legal_regime_review="confirmed",
                court_metadata_review="correct",
                date_metadata_review="uncertain",
                text_quality="usable",
                duplicate_or_noise="no",
                rag_suitability="accept",
                notes="bounded note",
            )

            updated = json.loads(path.read_text(encoding="utf-8"))[0]
            self.assertEqual(updated["offence_family_automated"], "homicide")
            self.assertEqual(updated["corrected_offence_family"], "other")
            self.assertEqual(updated["source_url"], sample["source_url"])
            self.assertEqual(updated["raw_file_path"], sample["raw_file_path"])
            self.assertEqual(updated["sha256"], sample["sha256"])
            self.assertEqual(updated["human_audit_status"], "reviewed")

    def test_partial_metrics_exclude_uncertain_from_accuracy_denominators(self) -> None:
        reviewed = audit.sample_record(candidate("12", "homicide"), 1, ["reason"])
        reviewed.update(
            {
                "human_audit_status": "reviewed",
                "criminal_relevance": "correct",
                "document_type": "uncertain",
                "offence_family_review": "confirmed",
                "legal_regime_review": "uncertain",
                "court_metadata_review": "correct",
                "date_metadata_review": "uncertain",
                "text_quality": "usable",
                "duplicate_or_noise": "no",
                "rag_suitability": "accept",
            }
        )

        metrics = audit.compute_metrics([reviewed])

        self.assertEqual(metrics["criminal_relevance_precision"]["reviewed"], 1)
        self.assertEqual(metrics["document_type_precision"]["reviewed"], 0)
        self.assertIsNone(metrics["document_type_precision"]["percent"])
        self.assertEqual(metrics["rag_suitability_rate"]["percent"], 100.0)

    def test_correction_matrix_generation(self) -> None:
        reviewed = audit.sample_record(candidate("13", "homicide"), 1, ["reason"])
        reviewed.update(
            {
                "human_audit_status": "reviewed",
                "offence_family_review": "corrected",
                "corrected_offence_family": "other",
                "legal_regime_review": "confirmed",
            }
        )

        matrices = audit.correction_matrices([reviewed])

        self.assertEqual(matrices["offence_family"]["homicide"]["other"], 1)
        self.assertEqual(matrices["legal_regime"]["ipc_crpc"]["ipc_crpc"], 1)

    def test_preview_fallback_for_provider_original_unavailable_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            raw = root / "raw/20.json"
            raw.parent.mkdir()
            raw.write_text('{"errmsg":"Original document not available"}', encoding="utf-8")
            sample = audit.sample_record(
                candidate("20", "other", mime_type="application/json", size=44),
                1,
                ["provider_original_unavailable_or_fallback"],
            )
            sample["raw_file_path"] = "raw/20.json"
            sample["regime_evidence"] = ["Stored document endpoint text evidence under Section 379 CrPC."]

            preview = audit.preview_for(sample, repo_root=root)

            self.assertTrue(preview["available"])
            self.assertEqual(preview["source"], "document_text_fallback_evidence")
            self.assertIn("Section 379", preview["text"])

    def test_no_network_or_llm_dependency_for_generation_helpers(self) -> None:
        records = [candidate(str(index), "homicide") for index in range(249)]
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            candidates = root / "candidates.json"
            sample_path = root / "sample.json"
            candidates.write_text(json.dumps(records), encoding="utf-8")
            with patch("backend.scripts.review_bulk_quality_audit.REPO_ROOT", root):
                sample = audit.generate_sample(candidates, sample_path, 5)

        self.assertEqual(len(sample), 5)
        self.assertNotIn("indiankanoon_client", sys.modules)


if __name__ == "__main__":
    unittest.main()
