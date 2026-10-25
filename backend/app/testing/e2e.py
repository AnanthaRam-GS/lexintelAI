"""Wire the app for a browser end-to-end run (test only; docs/TESTING.md, "End-to-end tests").

``backend/main.py`` calls ``install_e2e_providers`` only when ``LEGALAI_E2E_FAKE_PROVIDERS=1`` and ``APP_ENV=test``;
this function checks both again and refuses otherwise.

Environment (read here, not in Settings, because nothing else may use them):

- ``LEGALAI_E2E_STATE_DIR`` (required): the run's own directory. BM25 is read and written in
  ``<state>/bm25_store`` and uploads go to ``<state>/uploads``; ``CHROMA_PERSIST_DIR`` must point inside it too.
  The repository's own ``chroma_store``/``bm25_store`` are refused.
- ``LEGALAI_E2E_RETRIEVAL``: ``fake`` (default; hashing embedder, overlap reranker, no model files) or ``real``
  (BGE-M3 and the BGE reranker over the stores in the state directory, e.g. copies of the dev stores).
- ``LEGALAI_E2E_LLM``: ``fake`` (default; the deterministic answer adapter) or ``real`` (the configured provider).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from backend.app.core.config import REPO_ROOT, Settings, resolve_chroma_location
from backend.app.core.startup_checks import InsecureConfigurationError, app_env

logger = logging.getLogger("legalai.e2e")

MODES = ("fake", "real")


def e2e_mode(name: str) -> str:
    value = (os.environ.get(name) or "fake").strip().lower()
    if value not in MODES:
        raise InsecureConfigurationError(f"{name} must be one of {MODES}")
    return value


def e2e_paths(settings: Settings) -> dict[str, Path]:
    raw = (os.environ.get("LEGALAI_E2E_STATE_DIR") or "").strip()
    if not raw:
        raise InsecureConfigurationError("LEGALAI_E2E_STATE_DIR must be set for an end-to-end run")
    state = Path(raw).resolve()
    chroma_dir, _collection = resolve_chroma_location(settings)
    paths = {"state": state, "chroma": chroma_dir.resolve(), "bm25": state / "bm25_store", "uploads": state / "uploads"}
    for name in ("chroma", "bm25", "uploads"):
        if state not in paths[name].parents:
            raise InsecureConfigurationError(f"the end-to-end {name} directory must be inside LEGALAI_E2E_STATE_DIR")
    for real in (REPO_ROOT / "chroma_store", REPO_ROOT / "bm25_store"):
        if real.resolve() in (paths["chroma"], paths["bm25"], state):
            raise InsecureConfigurationError("an end-to-end run must not use the repository's own stores")
    return paths


def build_fake_retrieval_service(paths: dict[str, Path], settings: Settings) -> Any:
    from backend.app.services.retrieval.bm25 import DEFAULT_INDEX_NAME, Bm25Config, Bm25LexicalIndex
    from backend.app.services.retrieval.service import HybridConfig, RetrievalService
    from backend.app.services.vector_store import EXPECTED_EMBEDDING_DIMENSION, INDEX_VERSION, ChromaVectorStore
    from backend.app.testing.fake_providers import HashingEmbedder, OverlapReranker

    _chroma, collection = resolve_chroma_location(settings)
    return RetrievalService(
        dense_provider=HashingEmbedder(),
        vector_store=ChromaVectorStore(
            paths["chroma"], collection, {"index_version": INDEX_VERSION}, create_if_missing=False, expected_dimension=EXPECTED_EMBEDDING_DIMENSION
        ),
        lexical_index=Bm25LexicalIndex(paths["bm25"], DEFAULT_INDEX_NAME, Bm25Config(k1=1.5, b=0.75)),
        hybrid_config=HybridConfig(rrf_k=60, candidate_k=20),
        reranker=OverlapReranker(),
    )


def install_e2e_providers(app: FastAPI, settings: Settings) -> dict[str, str]:
    """Point the stores at the run's directory and swap in the deterministic providers. Returns the modes."""
    if not settings.legalai_e2e_fake_providers or app_env(settings) != "test":
        raise InsecureConfigurationError("LEGALAI_E2E_FAKE_PROVIDERS is honoured only with APP_ENV=test")
    from backend.app.api import ingest as ingest_api
    from backend.app.api import query as query_api
    from backend.app.services import ingestion
    from backend.scripts import build_lexical_index

    paths = e2e_paths(settings)
    retrieval, llm = e2e_mode("LEGALAI_E2E_RETRIEVAL"), e2e_mode("LEGALAI_E2E_LLM")
    paths["uploads"].mkdir(parents=True, exist_ok=True)
    ingest_api.UPLOAD_DIR = paths["uploads"]
    query_api.BM25_PERSIST_DIR = paths["bm25"]
    build_lexical_index.DEFAULT_PERSIST_DIR = paths["bm25"]
    query_api.clear_retrieval_service_cache()

    if retrieval == "fake":
        from backend.app.testing.fake_providers import HashingEmbedder

        if settings.legalai_model_warmup:
            # The warm-up builds the real retrieval service directly (it does not go through the override).
            raise InsecureConfigurationError("fake retrieval needs LEGALAI_MODEL_WARMUP=false (no model files are loaded)")

        # Built per request: an admin ingestion adds chunks, and a new service sees them (the index files are small).
        app.dependency_overrides[query_api.get_retrieval_service] = lambda: build_fake_retrieval_service(paths, settings)
        ingestion._default_embedder = HashingEmbedder  # same vectors as the fake query embedder
    if llm == "fake":
        from backend.app.testing.fake_providers import FakeAnswerAdapter

        app.dependency_overrides[query_api.get_answer_adapter] = FakeAnswerAdapter
    logger.warning("END-TO-END TEST MODE: retrieval=%s llm=%s state=%s", retrieval, llm, paths["state"])
    return {"retrieval": retrieval, "llm": llm}
