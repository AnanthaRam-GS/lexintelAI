"""Step E3: the LEGALAI_NER_BACKEND switch (services/ner_backend.py), with a mocked model. No model files needed."""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.services import ner_backend
from backend.app.services.hybrid_legal_ner import HybridMergeConfig, merge_hybrid_entities
from backend.app.services.inference_lock import InferenceBusy
from backend.app.services.legal_ner import extract_deterministic_entities

TEXT = "Ramesh Kumar filed an appeal under Section 302 IPC before the High Court of Kerala against the State of Kerala."


def span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


def raw(needle: str, native: str, confidence: float, text: str = TEXT) -> dict:
    start, end = span(text, needle)
    return {"start": start, "end": end, "type": native, "confidence": confidence}


# What a model might predict on TEXT: a person, a provision overlapping the rule-owned SECTION, a court,
# a respondent that names the State (party rule -> ORGANIZATION), a low-confidence place and a case number.
RAW = [
    raw("Ramesh Kumar", "PETITIONER", 0.97),
    raw("Section 302", "PROVISION", 0.99),
    raw("High Court of Kerala", "COURT", 0.95),
    raw("State of Kerala", "RESPONDENT", 0.93),
    raw("Kerala", "GPE", 0.40, text=TEXT[: TEXT.index("against")]),
    raw("IPC", "CASE_NUMBER", 0.9),
]


class FakeEngine:
    device = "cpu"

    def __init__(self, predictions=None, error: Exception | None = None) -> None:
        self.predictions = predictions if predictions is not None else RAW
        self.error = error
        self.calls: list[str] = []

    def predict(self, text: str) -> list[dict]:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return list(self.predictions)


def settings(backend: str, directory: Path | str = "models/does-not-exist") -> SimpleNamespace:
    return SimpleNamespace(legalai_ner_backend=backend, legalai_ner_checkpoint_dir=str(directory), legalai_model_device="cpu")


@contextlib.contextmanager
def checkpoint(content: bytes = b"weights", expected: str | None = None):
    """A checkpoint directory whose weights hash to ``expected`` (the pinned hash is patched to match)."""
    with tempfile.TemporaryDirectory() as directory:
        weights = Path(directory) / ner_backend.CHECKPOINT_WEIGHTS
        weights.write_bytes(content)
        digest = ner_backend.checkpoint_sha256(weights)
        with patch.object(ner_backend, "CHECKPOINT_SHA256", expected or digest):
            yield Path(directory)


class NerBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def entity_keys(self, entities) -> set[tuple[str, str]]:
        return {(e.text, str(e.entity_type)) for e in entities}

    # -- flag off ------------------------------------------------------------------------------------------------

    def test_default_backend_is_deterministic(self) -> None:
        from backend.app.core.config import Settings

        self.assertEqual(Settings().legalai_ner_backend, "deterministic")
        self.assertEqual(ner_backend.configured_backend(settings("")), "deterministic")
        self.assertEqual(ner_backend.configured_backend(settings("bogus")), "deterministic")

    def test_flag_off_returns_the_deterministic_result_and_loads_no_model(self) -> None:
        factory = patch.object(ner_backend, "engine_factory", side_effect=AssertionError("model loaded"))
        with factory as mocked:
            result = ner_backend.extract_entities(TEXT, settings("deterministic"))
        mocked.assert_not_called()
        expected = extract_deterministic_entities(TEXT)
        self.assertEqual(result.extractor, "deterministic_legal_ner")
        self.assertEqual([e.model_dump() for e in result.entities], [e.model_dump() for e in expected.entities])
        self.assertEqual(ner_backend.ner_status(settings("deterministic")),
                         {"backend": "deterministic", "active": "deterministic", "model": "not_used"})

    def test_flag_off_leaves_query_understanding_untouched(self) -> None:
        from backend.app.services.legal_query_understanding import understand_legal_query

        understanding = understand_legal_query(TEXT, section_ranking_mode="deterministic")
        self.assertIs(ner_backend.with_backend_entities(understanding, settings("deterministic")), understanding)

    # -- flag on -------------------------------------------------------------------------------------------------

    def test_flag_on_applies_the_frozen_combination_policy(self) -> None:
        engine = FakeEngine()
        with checkpoint() as directory, patch.object(ner_backend, "engine_factory", return_value=engine):
            result = ner_backend.extract_entities(TEXT, settings("combined", directory))
        deterministic = extract_deterministic_entities(TEXT)
        expected = merge_hybrid_entities(
            deterministic.entities, ner_backend.to_canonical(TEXT, RAW), HybridMergeConfig(mode="hybrid", min_confidence=0.70)
        ).entities
        self.assertEqual(engine.calls, [TEXT])
        self.assertEqual(result.extractor, ner_backend.COMBINED_EXTRACTOR)
        self.assertEqual(result.model_name, ner_backend.MODEL_NAME)
        self.assertEqual([e.model_dump() for e in result.entities], [e.model_dump() for e in expected])
        keys = self.entity_keys(result.entities)
        self.assertIn(("Ramesh Kumar", "PERSON"), keys)  # petitioner, a person by the party rule
        self.assertIn(("State of Kerala", "ORGANIZATION"), keys)  # respondent naming the State
        self.assertNotIn(("Kerala", "LOCATION"), keys)  # below the 0.70 threshold
        self.assertFalse(any(e.metadata.get("native_type") == "CASE_NUMBER" for e in result.entities))  # not mapped
        # The rule-owned SECTION and STATUTE are kept exactly as the deterministic NER found them.
        rule_owned = {(e.start_char, e.end_char, str(e.entity_type)) for e in deterministic.entities
                      if str(e.entity_type) in {"SECTION", "STATUTE"}}
        self.assertTrue(rule_owned)
        self.assertTrue(rule_owned <= {(e.start_char, e.end_char, str(e.entity_type)) for e in result.entities})
        self.assertFalse(any(e.source == "model" and str(e.entity_type) in {"SECTION", "STATUTE"} for e in result.entities))
        status = ner_backend.ner_status(settings("combined", directory))
        self.assertEqual((status["active"], status["model"]["status"], status["fallback"]), ("combined", "ready", False))
        self.assertEqual(status["calls"], {"combined_calls": 1, "fallback_calls": 0})

    def test_flag_on_replaces_query_understanding_entities(self) -> None:
        from backend.app.services.legal_query_understanding import understand_legal_query

        understanding = understand_legal_query(TEXT, section_ranking_mode="deterministic")
        with checkpoint() as directory, patch.object(ner_backend, "engine_factory", return_value=FakeEngine()):
            updated = ner_backend.with_backend_entities(understanding, settings("combined", directory))
        self.assertIsNot(updated, understanding)
        self.assertIn(("Ramesh Kumar", "PERSON"), self.entity_keys(updated.entities))
        # Everything retrieval and the prompts read is unchanged.
        self.assertEqual(updated.model_dump(exclude={"entities"}), understanding.model_dump(exclude={"entities"}))

    def test_model_loads_once(self) -> None:
        with checkpoint() as directory, patch.object(ner_backend, "engine_factory", return_value=FakeEngine()) as factory:
            for _ in range(3):
                ner_backend.extract_entities(TEXT, settings("combined", directory))
        factory.assert_called_once()

    # -- fallbacks -----------------------------------------------------------------------------------------------

    def assert_deterministic(self, result) -> None:
        expected = extract_deterministic_entities(TEXT)
        self.assertEqual(result.extractor, "deterministic_legal_ner")
        self.assertEqual([e.model_dump() for e in result.entities], [e.model_dump() for e in expected.entities])

    def test_missing_checkpoint_falls_back_with_warning_and_health_indicator(self) -> None:
        with tempfile.TemporaryDirectory() as empty, self.assertLogs("legalai.ner", level="WARNING") as logs, \
                patch.object(ner_backend, "engine_factory", side_effect=AssertionError("must not load")):
            result = ner_backend.extract_entities(TEXT, settings("combined", Path(empty) / "seed-22"))
            again = ner_backend.extract_entities(TEXT, settings("combined", Path(empty) / "seed-22"))
        self.assert_deterministic(result)
        self.assert_deterministic(again)
        self.assertTrue(any("reason=checkpoint_missing" in line for line in logs.output))
        status = ner_backend.ner_status(settings("combined", Path(empty) / "seed-22"))
        self.assertEqual((status["backend"], status["active"], status["fallback"]), ("combined", "deterministic", True))
        self.assertEqual(status["model"]["reason"], "checkpoint_missing")
        self.assertEqual(status["calls"]["fallback_calls"], 2)

    def test_checkpoint_with_another_hash_is_not_loaded(self) -> None:
        with checkpoint(expected="0" * 64) as directory, self.assertLogs("legalai.ner", level="WARNING"), \
                patch.object(ner_backend, "engine_factory", side_effect=AssertionError("must not load")):
            result = ner_backend.extract_entities(TEXT, settings("combined", directory))
        self.assert_deterministic(result)
        self.assertEqual(ner_backend.ner_status(settings("combined", directory))["model"]["reason"], "checkpoint_hash_mismatch")

    def test_load_failure_falls_back(self) -> None:
        with checkpoint() as directory, self.assertLogs("legalai.ner", level="WARNING"), \
                patch.object(ner_backend, "engine_factory", side_effect=OSError("corrupt")):
            result = ner_backend.extract_entities(TEXT, settings("combined", directory))
        self.assert_deterministic(result)
        self.assertEqual(ner_backend.ner_status(settings("combined", directory))["model"]["reason"], "load_failed")

    def test_inference_error_falls_back_without_failing(self) -> None:
        engine = FakeEngine(error=RuntimeError("mps exploded"))
        with checkpoint() as directory, self.assertLogs("legalai.ner", level="WARNING") as logs, \
                patch.object(ner_backend, "engine_factory", return_value=engine):
            result = ner_backend.extract_entities(TEXT, settings("combined", directory))
        self.assert_deterministic(result)
        self.assertTrue(any("reason=inference_error" in line for line in logs.output))

    def test_lock_timeout_falls_back_for_this_call_only(self) -> None:
        busy = InferenceBusy("MODEL_BUSY", "busy", 15, 30.0)
        engine = FakeEngine()
        with checkpoint() as directory, patch.object(ner_backend, "engine_factory", return_value=engine):
            with patch.object(engine, "predict", side_effect=busy), self.assertLogs("legalai.ner", level="WARNING") as logs:
                result = ner_backend.extract_entities(TEXT, settings("combined", directory))
            self.assert_deterministic(result)
            self.assertTrue(any("reason=lock_timeout" in line for line in logs.output))
            later = ner_backend.extract_entities(TEXT, settings("combined", directory))  # the model is still used
        self.assertEqual(later.extractor, ner_backend.COMBINED_EXTRACTOR)

    def test_lock_timeout_while_loading_is_retried_later(self) -> None:
        busy = InferenceBusy("MODELS_LOADING", "loading", 10, 30.0)
        with checkpoint() as directory, patch.object(ner_backend, "engine_factory", side_effect=[busy, FakeEngine()]):
            with self.assertLogs("legalai.ner", level="WARNING"):
                first = ner_backend.extract_entities(TEXT, settings("combined", directory))
            second = ner_backend.extract_entities(TEXT, settings("combined", directory))
        self.assert_deterministic(first)
        self.assertEqual(second.extractor, ner_backend.COMBINED_EXTRACTOR)

    # -- warm-up -------------------------------------------------------------------------------------------------

    def test_warm_up_loads_and_runs_one_inference_only_when_combined(self) -> None:
        engine = FakeEngine()
        with checkpoint() as directory, patch.object(ner_backend, "engine_factory", return_value=engine):
            self.assertIsNone(ner_backend.start_ner_warm_up(settings("deterministic", directory)))
            status = ner_backend.warm_up_ner(settings("combined", directory))
        self.assertEqual(engine.calls, [ner_backend.WARMUP_TEXT])
        self.assertEqual(status["model"]["status"], "ready")
        self.assertIn("warmup_ms", status["model"])


class LockUsageTests(unittest.TestCase):
    """The real engine class with a tiny torch model: every load and inference holds the process-wide model lock."""

    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def test_load_and_every_window_batch_hold_the_inference_lock(self) -> None:
        import torch

        labels = len(ner_backend.LABELS)
        held: list[str] = []
        depth = {"value": 0}

        @contextlib.contextmanager
        def recording_slot(name: str):
            held.append(name)
            depth["value"] += 1
            try:
                yield
            finally:
                depth["value"] -= 1

        class TinyModel(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.config = SimpleNamespace(id2label={i: label for i, label in enumerate(ner_backend.LABELS)})
                self.weight = torch.nn.Parameter(torch.zeros(1))

            def forward(self, input_ids, attention_mask):
                assert depth["value"] == 1, "inference outside the model lock"
                logits = torch.zeros(*input_ids.shape, labels)
                logits[..., ner_backend.LABELS.index("B-COURT")] = 5.0  # every token says B-COURT
                return SimpleNamespace(logits=logits)

        class TinyTokenizer:
            def __call__(self, text, **kwargs):
                # Two windows of two word tokens each (special tokens have empty offsets).
                return {"input_ids": [[101, 5, 6, 102], [101, 7, 102]],
                        "attention_mask": [[1, 1, 1, 1], [1, 1, 1]],
                        "offset_mapping": [[(0, 0), (0, 4), (5, 9), (0, 0)], [(0, 0), (10, 14), (0, 0)]]}

        fake_transformers = SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=lambda path: TinyTokenizer()),
            AutoModelForTokenClassification=SimpleNamespace(from_pretrained=lambda path: TinyModel()),
        )
        with patch.dict("sys.modules", {"transformers": fake_transformers}), \
                patch("backend.app.services.model_device.inference_slot", recording_slot), \
                patch.object(ner_backend, "WINDOW_BATCH", 1):
            engine = ner_backend.CombinedNerEngine(Path("unused"), "cpu")
            self.assertEqual(held, ["inlegalbert_ner"])  # the load
            predictions = engine.predict("Aaaa Bbbb Cccc")
        self.assertEqual(held, ["inlegalbert_ner"] * 3)  # load + one per window batch
        self.assertEqual([(p["start"], p["end"], p["type"]) for p in predictions],
                         [(0, 4, "COURT"), (5, 9, "COURT"), (10, 14, "COURT")])

    def test_decode_takes_each_token_from_its_most_central_window(self) -> None:
        o, b, i = ner_backend.LABELS.index("O"), ner_backend.LABELS.index("B-GPE"), ner_backend.LABELS.index("I-GPE")

        def row(label: int, p: float = 0.9) -> list[float]:
            values = [0.0] * len(ner_backend.LABELS)
            values[label] = p
            return values

        # Both tokens sit off-centre in window 1 (B-GPE, then O) and nearer the centre of window 2 (B-GPE, I-GPE),
        # so window 2 labels both: one entity over both tokens, confidence the mean of 0.8 and 0.6.
        offsets = [[(0, 4), (5, 9), (0, 0), (0, 0), (0, 0), (0, 0)], [(0, 0), (0, 4), (5, 9), (0, 0)]]
        probs = [[row(b), row(o), row(o), row(o), row(o), row(o)], [row(o), row(b, 0.8), row(i, 0.6), row(o)]]
        decoded = ner_backend.decode_windows(offsets, probs)
        self.assertEqual(decoded, [{"start": 0, "end": 9, "type": "GPE", "confidence": 0.7}])


class DocumentMapIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def test_document_map_entities_follow_the_backend(self) -> None:
        from backend.app.services.local_document_map import extract_sections_and_entities

        chunk = SimpleNamespace(text=TEXT, private_chunk_id="P1", page_start=1, page_end=1)
        with patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "deterministic"}):
            off = extract_sections_and_entities([chunk])
        with checkpoint() as directory, patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "combined",
                                                                "LEGALAI_NER_CHECKPOINT_DIR": str(directory)}), \
                patch.object(ner_backend, "engine_factory", return_value=FakeEngine()):
            on = extract_sections_and_entities([chunk])
        self.assertEqual(off[0], on[0])  # explicit sections: rule-owned, unchanged
        self.assertNotIn("Ramesh Kumar", off[1])
        self.assertIn("Ramesh Kumar", on[1])
        self.assertIn("State of Kerala", on[1])


if __name__ == "__main__":
    unittest.main()
