"""Tests for corpus integrity helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.scripts.corpus_utils import (
    file_size,
    find_duplicate_by_sha256,
    load_manifest,
    safe_filename,
    sha256_file,
    write_manifest_atomic,
)


class CorpusUtilsTest(unittest.TestCase):
    def test_sha256_file_streams_expected_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.txt"
            path.write_bytes(b"legalai")

            self.assertEqual(
                sha256_file(path),
                "c419470639ed007d5d0ab64e6bbd1631f0875a552f5225ddc03e3b5e45a166ef",
            )
            self.assertEqual(file_size(path), 7)

    def test_safe_filename(self) -> None:
        self.assertEqual(safe_filename("A/B: C?"), "A_B_C")
        self.assertEqual(safe_filename(" ... "), "untitled")

    def test_manifest_roundtrip_is_json_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "manifest.json"
            records = [{"document_id": "doc-1", "sha256": "abc"}]

            write_manifest_atomic(path, records)

            self.assertEqual(load_manifest(path), records)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), records)

    def test_find_duplicate_by_sha256(self) -> None:
        records = [{"document_id": "doc-1", "sha256": "abc"}]

        self.assertEqual(find_duplicate_by_sha256("abc", records), records[0])
        self.assertIsNone(find_duplicate_by_sha256("def", records))


if __name__ == "__main__":
    unittest.main()
