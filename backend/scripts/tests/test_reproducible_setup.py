"""Step 20: the corpus loader's chunk-file check, build_indexes.py's refusals and the E2E database opt-in.

No database, model or corpus file is needed: the chunk files and the expected fingerprint are synthetic.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.retrieval.bm25 import chunk_universe_fingerprint  # noqa: E402
from backend.scripts import build_indexes, load_corpus  # noqa: E402
from backend.scripts import reconcile_common, reconcile_inventory  # noqa: E402
from backend.scripts.e2e import setup_e2e  # noqa: E402
from backend.scripts.reconcile_common import TargetRefused  # noqa: E402

CHUNKS = [
    {"chunk_id": f"synthetic:1:chunk:{i}", "document_id": "synthetic:1", "chunk_text": f"text {i}",
     "normalizer_version": "n1", "chunker_version": "c1"}
    for i in range(3)
]


class ChunkFileCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.chunk_dir = self.root / "judgment_chunks"
        self.chunk_dir.mkdir()
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"documents": [{"document_id": "synthetic:1"}]}), encoding="utf-8")
        summary = self.root / "summary.json"
        summary.write_text(json.dumps({"chunk_count": 3, "chunk_universe_fingerprint": chunk_universe_fingerprint(CHUNKS)}), encoding="utf-8")
        patches = [
            mock.patch.object(reconcile_inventory, "CHUNK_DIR", self.chunk_dir),
            mock.patch.object(reconcile_inventory, "TRUSTED_MANIFEST", manifest),
            mock.patch.object(load_corpus, "LEXICAL_SUMMARY", summary),
            mock.patch.object(load_corpus, "REPO_ROOT", self.root),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write_chunks(self, chunks: list[dict]) -> None:
        (self.chunk_dir / "synthetic_1.json").write_text(json.dumps(chunks), encoding="utf-8")

    def test_the_curated_chunks_pass(self) -> None:
        self.write_chunks(CHUNKS)
        self.assertEqual(load_corpus.check_chunk_files(), {"documents": 1, "chunks": 3, "fingerprint": chunk_universe_fingerprint(CHUNKS)})

    def test_missing_chunk_files_are_refused_with_the_readme_pointer(self) -> None:
        with self.assertRaisesRegex(SystemExit, "no chunk files.*README"):
            load_corpus.check_chunk_files()

    def test_a_changed_text_is_refused(self) -> None:
        self.write_chunks([*CHUNKS[:2], {**CHUNKS[2], "chunk_text": "edited"}])
        with self.assertRaisesRegex(SystemExit, "not the curated corpus"):
            load_corpus.check_chunk_files()

    def test_a_missing_chunk_is_refused(self) -> None:
        self.write_chunks(CHUNKS[:2])
        with self.assertRaisesRegex(SystemExit, "not the curated corpus"):
            load_corpus.check_chunk_files()


class BuildIndexesRefusalTests(unittest.TestCase):
    def test_the_repository_stores_are_refused_without_confirm_dev(self) -> None:
        with mock.patch.dict(os.environ, {"X_URL": "postgresql://h/legalai_x"}):
            with self.assertRaisesRegex(SystemExit, "pass --confirm-dev"):
                build_indexes.main(["--database-url-env", "X_URL", "--chroma-dir", str(REPO_ROOT / "chroma_store"),
                                    "--bm25-dir", str(REPO_ROOT / "bm25_store")])


class E2eDatabaseOptInTests(unittest.TestCase):
    def check(self, database: str, mode: str = "real", allow: str | None = None) -> str:
        env = {"APP_ENV": "test", "DATABASE_URL": f"postgresql://h/{database}", "E2E_ALLOW_DATABASE": allow or ""}
        with tempfile.TemporaryDirectory() as state, mock.patch.dict(os.environ, env), \
                mock.patch.object(reconcile_common, "dev_database_name", return_value="legalai_fresh"):
            return setup_e2e.check_target(Path(state), mode)

    def test_without_the_opt_in_the_env_database_is_refused(self) -> None:
        with self.assertRaisesRegex(TargetRefused, "development database"):
            self.check("legalai_fresh")

    def test_the_opt_in_allows_exactly_that_database_in_real_mode(self) -> None:
        self.assertEqual(self.check("legalai_fresh", allow="legalai_fresh"), "legalai_fresh")

    def test_the_opt_in_does_not_widen_other_names(self) -> None:
        with self.assertRaisesRegex(TargetRefused, "not an end-to-end database"):
            self.check("legalai_other", allow="legalai_fresh")

    def test_the_opt_in_is_refused_in_fake_mode(self) -> None:
        with self.assertRaisesRegex(TargetRefused, "only accepted with --mode real"):
            self.check("legalai_fresh", mode="fake", allow="legalai_fresh")

    def test_the_usual_targets_still_work(self) -> None:
        self.assertEqual(self.check("legalai_e2e", mode="fake"), "legalai_e2e")
        self.assertEqual(self.check("legalai_rehearsal"), "legalai_rehearsal")


if __name__ == "__main__":
    unittest.main()
