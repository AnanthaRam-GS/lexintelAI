"""N1: ingestion and the query path must open the same Chroma collection."""

from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.app.api import query as query_api
from backend.app.core.config import DEFAULT_CHROMA_COLLECTION, REPO_ROOT, Settings, resolve_chroma_location
from backend.app.services import ingestion
from backend.scripts import build_vector_index


class RecordingVectorStore:
    instances: list["RecordingVectorStore"] = []

    def __init__(self, persist_dir: Path, collection_name: str, collection_metadata: dict) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        RecordingVectorStore.instances.append(self)


def settings_without_env_file(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


class ChromaCollectionConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        RecordingVectorStore.instances = []

    def ingestion_location(self, settings: Settings) -> tuple[Path, str]:
        with patch("backend.app.services.vector_store.ChromaVectorStore", RecordingVectorStore):
            store = ingestion.trusted_vector_store(settings)
        return store.persist_dir, store.collection_name

    def query_location(self, settings: Settings) -> tuple[Path, str]:
        args = query_api.retrieval_service_args(settings)
        return args.chroma_persist_dir, args.collection

    def test_default_collection_is_the_trusted_corpus_collection(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHROMA_COLLECTION_NAME", None)
            settings = settings_without_env_file()
        self.assertEqual(DEFAULT_CHROMA_COLLECTION, "legalai_trusted_judgments_v1")
        self.assertEqual(settings.chroma_collection_name, DEFAULT_CHROMA_COLLECTION)
        self.assertEqual(self.ingestion_location(settings)[1], DEFAULT_CHROMA_COLLECTION)
        self.assertEqual(self.query_location(settings)[1], DEFAULT_CHROMA_COLLECTION)

    def test_ingestion_and_query_resolve_the_same_configured_collection(self) -> None:
        settings = settings_without_env_file(chroma_collection_name="custom_collection", chroma_persist_dir="./some_store")
        self.assertEqual(self.ingestion_location(settings), self.query_location(settings))
        self.assertEqual(self.query_location(settings), (REPO_ROOT / "some_store", "custom_collection"))

    def test_collection_name_from_environment_reaches_both_paths(self) -> None:
        with patch.dict(os.environ, {"CHROMA_COLLECTION_NAME": "env_collection", "CHROMA_PERSIST_DIR": "/tmp/legalai_env_store"}):
            settings = settings_without_env_file()
        self.assertEqual(self.ingestion_location(settings), (Path("/tmp/legalai_env_store"), "env_collection"))
        self.assertEqual(self.query_location(settings), (Path("/tmp/legalai_env_store"), "env_collection"))

    def test_cached_query_service_uses_the_shared_resolution(self) -> None:
        captured = []
        with patch.dict(os.environ, {"CHROMA_COLLECTION_NAME": "env_collection", "CHROMA_PERSIST_DIR": "/tmp/legalai_env_store"}):
            with patch.object(query_api, "make_service", side_effect=lambda args: captured.append(args) or object()):
                query_api._cached_retrieval_service.__wrapped__()
        self.assertEqual((captured[0].chroma_persist_dir, captured[0].collection), (Path("/tmp/legalai_env_store"), "env_collection"))

    def test_relative_persist_dir_is_resolved_against_repo_root(self) -> None:
        settings = settings_without_env_file(chroma_persist_dir="./chroma_store")
        self.assertEqual(resolve_chroma_location(settings)[0], REPO_ROOT / "chroma_store")

    def test_vector_index_builder_defaults_follow_the_shared_setting(self) -> None:
        with patch.dict(os.environ, {"CHROMA_COLLECTION_NAME": "env_collection", "CHROMA_PERSIST_DIR": "/tmp/legalai_env_store"}):
            args = build_vector_index.build_parser().parse_args([])
        self.assertEqual((args.persist_dir, args.collection), (Path("/tmp/legalai_env_store"), "env_collection"))
        self.assertEqual(build_vector_index.DEFAULT_COLLECTION, DEFAULT_CHROMA_COLLECTION)


if __name__ == "__main__":
    unittest.main()
