"""The end-to-end fake providers (step 17): refused outside APP_ENV=test, never imported without the flag, and
deterministic, schema-valid and citation-grounded when enabled. No database, no network, no model files."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI  # noqa: E402

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.startup_checks import (  # noqa: E402
    InsecureConfigurationError,
    run_startup_security_checks,
    validate_e2e_fake_providers,
)
from backend.app.services.legal_answer_generation import (  # noqa: E402
    AnswerMode,
    GroundingStatus,
    build_grounded_evidence_packet,
    generate_legal_answer,
)
from backend.app.services.legal_answer_prompt_v2 import NO_COVERAGE_STATEMENT, build_legal_answer_prompt_v2  # noqa: E402
from backend.app.services.legal_query_understanding import understand_legal_query  # noqa: E402
from backend.app.testing.e2e import e2e_paths, install_e2e_providers  # noqa: E402
from backend.app.testing.fake_providers import FakeAnswerAdapter, HashingEmbedder, OverlapReranker  # noqa: E402
from backend.scripts.tests.test_legal_answer_foundation import evidence, retrieval  # noqa: E402

NOT_TEST_ENVS = ("development", "production", "staging", "")


def settings_for(app_env: str, **values) -> Settings:
    return Settings(_env_file=None, app_env=app_env, legalai_e2e_fake_providers=True, **values)


# DATABASE_URL is required outside APP_ENV=test (step 20); importing the app never connects, so any URL will do.
UNCONNECTABLE_DATABASE_URL = "postgresql://unconfigured.invalid:5432/legalai_unconfigured"


def run_python(code: str, **env: str) -> subprocess.CompletedProcess:
    # A fresh interpreter, so backend.main is imported with exactly these settings (env beats .env).
    clean = {key: value for key, value in os.environ.items() if not key.startswith(("LEGALAI_E2E", "APP_ENV"))}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], cwd=REPO_ROOT, env={**clean, **env}, capture_output=True, text=True, timeout=120
    )


class RefusedOutsideTestTests(unittest.TestCase):
    def test_startup_check_refuses_the_flag_outside_test(self) -> None:
        for env in NOT_TEST_ENVS:
            with self.subTest(app_env=env), self.assertRaisesRegex(InsecureConfigurationError, "LEGALAI_E2E_FAKE_PROVIDERS"):
                validate_e2e_fake_providers(settings_for(env))
        validate_e2e_fake_providers(settings_for("test"))  # allowed
        validate_e2e_fake_providers(Settings(_env_file=None, app_env="production"))  # flag off: nothing to refuse

    def test_full_startup_checks_refuse_before_touching_the_database(self) -> None:
        def no_database():
            raise AssertionError("the database must not be opened")

        with self.assertRaisesRegex(InsecureConfigurationError, "LEGALAI_E2E_FAKE_PROVIDERS"):
            run_startup_security_checks(settings_for("production", jwt_secret_key="x" * 48), no_database)

    def test_installer_refuses_outside_test_even_when_called_directly(self) -> None:
        for env in NOT_TEST_ENVS:
            with self.subTest(app_env=env), self.assertRaises(InsecureConfigurationError):
                install_e2e_providers(FastAPI(), settings_for(env))

    def test_the_app_does_not_start_with_the_flag_outside_test(self) -> None:
        for env in ("development", "production"):
            with self.subTest(app_env=env):
                completed = run_python(
                    "import backend.main", APP_ENV=env, LEGALAI_E2E_FAKE_PROVIDERS="1", JWT_SECRET_KEY="k" * 48, DATABASE_URL=UNCONNECTABLE_DATABASE_URL
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("InsecureConfigurationError", completed.stderr)
                self.assertIn("LEGALAI_E2E_FAKE_PROVIDERS is set outside APP_ENV=test", completed.stderr)

    def test_no_fake_code_is_imported_without_the_flag(self) -> None:
        completed = run_python(
            """
            import sys
            import backend.main
            print(sorted(name for name in sys.modules if name.startswith("backend.app.testing")))
            print(backend.main.app.dependency_overrides)
            """,
            APP_ENV="development",
            JWT_SECRET_KEY="k" * 48,
            DATABASE_URL=UNCONNECTABLE_DATABASE_URL,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.split(), ["[]", "{}"])

    def test_the_app_starts_in_e2e_mode_only_with_app_env_test(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            completed = run_python(
                """
                import backend.main
                from backend.app.api import query
                overrides = backend.main.app.dependency_overrides
                print(query.get_retrieval_service in overrides, query.get_answer_adapter in overrides)
                print(query.BM25_PERSIST_DIR)
                """,
                APP_ENV="test",
                LEGALAI_E2E_FAKE_PROVIDERS="1",
                LEGALAI_E2E_STATE_DIR=state,
                CHROMA_PERSIST_DIR=str(Path(state) / "chroma_store"),
                LEGALAI_MODEL_WARMUP="false",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.splitlines(), ["True True", str(Path(state).resolve() / "bm25_store")])


class StorePathTests(unittest.TestCase):
    def test_state_dir_is_required_and_the_real_stores_are_refused(self) -> None:
        with patch.dict(os.environ, {"LEGALAI_E2E_STATE_DIR": ""}), self.assertRaisesRegex(InsecureConfigurationError, "STATE_DIR"):
            e2e_paths(settings_for("test"))
        with tempfile.TemporaryDirectory() as state, patch.dict(os.environ, {"LEGALAI_E2E_STATE_DIR": state}):
            with self.assertRaisesRegex(InsecureConfigurationError, "inside LEGALAI_E2E_STATE_DIR"):
                e2e_paths(settings_for("test", chroma_persist_dir=str(REPO_ROOT / "chroma_store")))
            paths = e2e_paths(settings_for("test", chroma_persist_dir=str(Path(state) / "chroma_store")))
            self.assertEqual(paths["bm25"], Path(state).resolve() / "bm25_store")
        with patch.dict(os.environ, {"LEGALAI_E2E_STATE_DIR": str(REPO_ROOT)}), self.assertRaises(InsecureConfigurationError):
            e2e_paths(settings_for("test", chroma_persist_dir=str(REPO_ROOT / "chroma_store")))

    def test_fake_retrieval_refuses_the_model_warm_up(self) -> None:
        with tempfile.TemporaryDirectory() as state, patch.dict(os.environ, {"LEGALAI_E2E_STATE_DIR": state}):
            settings = settings_for("test", chroma_persist_dir=str(Path(state) / "chroma_store"), legalai_model_warmup=True)
            with self.assertRaisesRegex(InsecureConfigurationError, "LEGALAI_MODEL_WARMUP=false"):
                install_e2e_providers(FastAPI(), settings)


class FakeProviderTests(unittest.TestCase):
    QUESTION = "Section 302 IPC murder bail before Sessions Court"

    def answer(self, question: str, mode: AnswerMode, items=None):
        understanding = understand_legal_query(question)
        evidence_set = retrieval(items)
        prompt = build_legal_answer_prompt_v2(build_grounded_evidence_packet(understanding, evidence_set), mode=mode).prompt
        return generate_legal_answer(understanding, evidence_set, mode=mode, adapter=FakeAnswerAdapter(), prompt=prompt)

    def test_answers_are_schema_valid_and_cite_only_retrieved_evidence(self) -> None:
        for mode in (AnswerMode.PUBLIC, AnswerMode.PROFESSIONAL):
            with self.subTest(mode=mode):
                result = self.answer(self.QUESTION, mode, [evidence("E1"), evidence("E2", "An unrelated property partition dispute.")])
                self.assertEqual(result.grounding_status, GroundingStatus.STRUCTURALLY_GROUNDED)
                self.assertEqual(result.evidence_used, ["E1"])  # the evidence that shares words with the question
                self.assertTrue(result.claims and all(c.citations for c in result.claims))
                metadata = evidence("E1").citation_metadata
                self.assertEqual(result.citations[0].source_metadata["case_name"], metadata.case_name)  # copied exactly
                self.assertFalse(result.summary.startswith(NO_COVERAGE_STATEMENT))

    def test_an_unrelated_question_gets_the_no_coverage_answer(self) -> None:
        result = self.answer("How do I register a trademark for my bakery?", AnswerMode.PUBLIC)
        self.assertTrue(result.summary.startswith(NO_COVERAGE_STATEMENT))
        self.assertEqual(result.claims, [])

    def test_the_same_prompt_gives_the_same_answer(self) -> None:
        first, second = (self.answer(self.QUESTION, AnswerMode.PROFESSIONAL) for _ in range(2))
        self.assertEqual(first.model_dump(exclude={"timings"}), second.model_dump(exclude={"timings"}))

    def test_embedder_and_reranker_are_deterministic_and_prefer_shared_words(self) -> None:
        embedder = HashingEmbedder()
        bail, murder, trademark = embedder.embed_documents(["bail after long custody", "murder trial witnesses", "trademark bakery logo"])
        query = embedder.embed_query("bail custody")
        dot = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731
        self.assertEqual(len(query), 1024)
        self.assertEqual(query, embedder.embed_query("bail custody"))
        self.assertGreater(dot(query, bail), max(dot(query, murder), dot(query, trademark)))
        candidates = retrieval([evidence("E1", "bail after long custody"), evidence("E2", "trademark bakery")]).evidence
        results = [type("R", (), {"text": item.text, "chunk_id": item.chunk_id})() for item in candidates]
        scores = OverlapReranker().score_pairs("bail custody", results)
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(scores, OverlapReranker().score_pairs("bail custody", results))


if __name__ == "__main__":
    unittest.main()
