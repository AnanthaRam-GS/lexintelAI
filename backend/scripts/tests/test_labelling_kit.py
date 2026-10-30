"""Step 24 labelling kit: pooling (with a fake retriever), the labelling sheet, validation and the v2 merge."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

KIT = REPO_ROOT / "data/evaluation/labelling_kit"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"labelling_kit_{name}", KIT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pools = load("generate_pools")
labels = load("validate_labels")


@dataclass
class FakeResult:
    chunk_id: str
    rank: int
    score: float = 1.0
    rerank_score: float | None = None
    document_id: str = "doc"
    case_title: str = "A vs B"
    court: str = "High Court"
    decision_date: str | None = None
    page_start: int = 1
    page_end: int = 1
    paragraph_start: int = 1
    paragraph_end: int = 1
    effective_offence_family: str = "other"
    effective_legal_regime: str = "ipc_crpc"
    text: str = "excerpt text"


def fake_retrieve(query: str, mode: str, top_k: int, candidate_k: int, rerank: bool):
    offset = {"lexical": 0, "dense": 10, "hybrid": 5}[mode] + (2 if rerank else 0)
    return [FakeResult(chunk_id=f"c{offset + i}", rank=i) for i in range(1, top_k + 1)]


QUERIES = [
    {"query_id": "new-q001", "query_text": "anticipatory bail under BNSS 482", "mode": "professional",
     "intended_statutes_or_topic": "BNSS 482 anticipatory bail", "query_type": "procedural_relief", "target_family": "other",
     "target_regime": "bns_bnss", "author": "example", "notes": ""},
    {"query_id": "new-q002", "query_text": "my landlord took my deposit and refuses to return it, is that cheating",
     "mode": "public", "intended_statutes_or_topic": "IPC 420 / BNS 318 cheating", "query_type": "plain_language",
     "target_family": "cheating_and_fraud", "target_regime": "mixed_or_transition", "author": "example", "notes": ""},
]


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class PoolTests(unittest.TestCase):
    def test_pool_v1_rules_and_a_blinded_sheet(self) -> None:
        judgments, traces = pools.pool_queries(QUERIES, fake_retrieve, list(pools.SYSTEM_MODES))
        per_query = [j for j in judgments if j["query_id"] == "new-q001"]
        self.assertLessEqual(len(per_query), 25)
        chunks = {j["chunk_id"] for j in per_query}
        for offset in (0, 10, 5, 7):  # every system's top 5 is kept
            self.assertTrue({f"c{offset + i}" for i in range(1, 6)} <= chunks)
        self.assertTrue(all(t["best_rank"] <= 15 for t in traces))
        with tempfile.TemporaryDirectory() as tmp:
            summary = pools.write_outputs(Path(tmp), QUERIES, judgments, traces, list(pools.SYSTEM_MODES))
            with (Path(tmp) / "labelling_sheet.csv").open(newline="", encoding="utf-8") as handle:
                sheet = list(csv.DictReader(handle))
        self.assertEqual(summary["candidates"], len(sheet))
        self.assertTrue(all(row["human_relevance"] == "" and row["reviewer"] == "" for row in sheet))
        for hidden in ("dense_rank", "lexical_rank", "rerank_score", "hybrid_score"):
            self.assertNotIn(hidden, sheet[0])

    def test_queries_csv_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.csv"
            write_csv(path, pools.QUERY_COLUMNS, [{**QUERIES[0], "query_id": "eval-q001"}, {**QUERIES[1], "mode": "lawyer", "author": ""}])
            with self.assertRaises(SystemExit) as caught:
                pools.read_queries(path)
            for expected in ("new-q001", "mode must be", "author is empty"):
                self.assertIn(expected, str(caught.exception))
        self.assertEqual((KIT / "queries_template.csv").read_text().strip().split(","), pools.QUERY_COLUMNS)


class ValidateAndMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.judgments, self.traces = pools.pool_queries(QUERIES, fake_retrieve, list(pools.SYSTEM_MODES))
        self.sheet = [{**{c: str(j.get(c, "")) for c in pools.SHEET_COLUMNS}, "human_relevance": "1", "document_relevant": "yes",
                       "reviewer": "example", "notes": ""} for j in self.judgments]
        self.queries = [{k: v for k, v in q.items()} for q in QUERIES]
        self.frozen_ids = {q["query_id"] for q in json.loads(labels.FROZEN["queries"].read_text())}

    def test_a_clean_sheet_merges_into_a_new_version_and_the_frozen_files_stay_unchanged(self) -> None:
        self.assertEqual(labels.check(self.queries, self.sheet, self.traces, self.frozen_ids), [])
        before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in labels.FROZEN.items()}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = labels.merge(self.queries, self.sheet, self.traces, Path(tmp) / "retrieval_v2")
            merged_queries = json.loads((Path(tmp) / "retrieval_v2/queries.json").read_text())
            merged_judgments = json.loads((Path(tmp) / "retrieval_v2/judgments.json").read_text())
        after = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in labels.FROZEN.items()}
        self.assertEqual(before, after)
        self.assertEqual(manifest["queries"], {"frozen": 30, "new": 2})
        self.assertEqual(manifest["judgments"], {"frozen": 695, "new": len(self.sheet)})
        self.assertEqual(len(merged_queries), 32)
        self.assertEqual(merged_judgments[-1]["human_relevance"], 1)

    def test_problems_are_listed(self) -> None:
        bad = [dict(row) for row in self.sheet]
        bad[0]["human_relevance"] = "3"
        bad[1]["document_relevant"] = ""
        bad[2]["reviewer"] = ""
        bad.append(dict(bad[3]))
        bad.append({**bad[4], "chunk_id": "not-pooled"})
        del bad[5]
        errors = labels.check(self.queries + [{**QUERIES[0], "query_id": "eval-q001"}], bad, self.traces, self.frozen_ids)
        text = "\n".join(errors)
        for expected in ("must be 2, 1, 0 or uncertain", "document_relevant is missing", "reviewer is missing", "duplicate candidate",
                         "not a pooled candidate", "has no label row", "reuses a frozen query ID", "eval-q001: no labels"):
            self.assertIn(expected, text)

    def test_the_frozen_directory_is_never_an_output(self) -> None:
        with self.assertRaisesRegex(SystemExit, "never written"):
            labels.merge(self.queries, self.sheet, self.traces, labels.FROZEN_DIR)


if __name__ == "__main__":
    unittest.main()
