"""Marker for tests that check committed manifests against the local trusted-judgment corpus.

The chunked corpus (``data/processed/judgment_chunks``, Indian Kanoon judgments) is gitignored, so these tests run
on a developer machine that has it and are skipped in CI and other clean checkouts (docs/TESTING.md).
"""

from __future__ import annotations

import unittest

from backend.scripts.build_vector_index import CHUNK_DIR

LOCAL_CORPUS_PRESENT = any(CHUNK_DIR.glob("*.json"))

requires_local_corpus = unittest.skipUnless(
    LOCAL_CORPUS_PRESENT,
    "local-only: checks committed manifests against the gitignored trusted-judgment chunks in "
    "data/processed/judgment_chunks (real corpus, not available in CI)",
)
