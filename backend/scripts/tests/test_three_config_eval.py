"""Step 24: scoring of the three-configuration evaluation, the LLM-only v3 prompt, and the retrieval re-run guards."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.legal_answer_generation import AnswerMode  # noqa: E402
from backend.scripts import run_three_config_eval as evaluation  # noqa: E402


def record(config: str, *, claims=None, issues=None, evidence=None, summary="s", answer=None, status="SUCCESS", no_coverage=False):
    return {"config": config, "status": status, "claims": claims or [], "citation_issues": issues or [], "evidence": evidence or [],
            "summary": summary, "answer": answer or {}, "no_coverage": no_coverage}


def claim(claim_id: str, *evidence_ids: str, text: str = "t") -> dict:
    return {"claim_id": claim_id, "text": text, "citations": [{"evidence_id": e, "claim_id": claim_id} for e in evidence_ids]}


class CaseReferenceTests(unittest.TestCase):
    def test_finds_case_names_and_reporter_citations(self) -> None:
        text = "As held in Arnesh Kumar v. State of Bihar and in Sushila Aggarwal vs State (NCT of Delhi), see AIR 1980 SC 898 and (2014) 8 SCC 273."
        refs = evaluation.case_references(text)
        self.assertIn("Arnesh Kumar v. State of Bihar", refs)
        self.assertTrue(any(ref.startswith("Sushila Aggarwal v. State") for ref in refs))
        self.assertIn("AIR 1980 SC 898", refs)
        self.assertIn("(2014) 8 SCC 273", refs)
        self.assertEqual(evaluation.case_references("Bail depends on the facts. Section 437 CrPC applies."), [])

    def test_a_reference_is_supported_by_a_distinctive_party_name_in_the_evidence(self) -> None:
        evidence = ["Sri Tanay Das vs The State Of Tripura", "Arnesh Kumar vs State Of Bihar & Anr"]
        self.assertTrue(evaluation.reference_supported("Arnesh Kumar v. State of Bihar", evidence))
        self.assertFalse(evaluation.reference_supported("Gurbaksh Singh Sibbia v. State of Punjab", evidence))
        self.assertFalse(evaluation.reference_supported("State v. Union of India", evidence))  # only generic words
        self.assertFalse(evaluation.reference_supported("AIR 1980 SC 898", evidence))  # the evidence has no reporters


class ScoreRecordTests(unittest.TestCase):
    def test_llm_only_citations_and_case_names_are_all_unsupported(self) -> None:
        scores = evaluation.score_record(record(
            "A_llm_only", claims=[claim("c1", "E1")], issues=[{"code": "UNKNOWN_EVIDENCE_ID", "evidence_id": "E1", "claim_id": "c1"}],
            answer={"analysis": ["Following Arnesh Kumar v. State of Bihar, arrest is not automatic."]},
        ))
        self.assertEqual((scores["citations_total"], scores["citations_valid"], scores["has_valid_claim"]), (1, 0, False))
        self.assertEqual((scores["unsupported_structured_citations"], scores["text_case_references"], scores["unsupported_text_case_references"]), (1, 1, 1))

    def test_rag_scores_follow_the_validator(self) -> None:
        evidence = [{"evidence_id": "E1", "case_name": "Arnesh Kumar vs State Of Bihar"}, {"evidence_id": "E2", "case_name": "X vs Y"}]
        issues = [{"code": "METADATA_MISMATCH", "evidence_id": "E2", "claim_id": "c2"},
                  {"code": "UNKNOWN_EVIDENCE_ID", "evidence_id": "E9", "claim_id": "c3"}]
        scores = evaluation.score_record(record(
            "C_full_legalai", claims=[claim("c1", "E1"), claim("c2", "E2"), claim("c3", "E9")], issues=issues, evidence=evidence,
            answer={"analysis": ["Arnesh Kumar v. State of Bihar limits arrest; Lalita Kumari v. Government of U.P. requires an FIR."]},
        ))
        self.assertEqual((scores["citations_total"], scores["citations_valid"], scores["has_valid_claim"]), (3, 1, True))
        self.assertEqual(scores["unsupported_structured_citations"], 1)  # E9 only; a metadata typo is invalid, not unsupported
        self.assertEqual((scores["text_case_references"], scores["unsupported_text_case_references"]), (2, 1))
        self.assertEqual(scores["issue_codes"], ["METADATA_MISMATCH", "UNKNOWN_EVIDENCE_ID"])

    def test_statuses(self) -> None:
        self.assertTrue(evaluation.score_record(record("B_dense_rag", status="TRUNCATED"))["truncated"])
        self.assertFalse(evaluation.score_record(record("B_dense_rag", status="TRUNCATED"))["schema_valid"])
        self.assertTrue(evaluation.score_record(record("C_full_legalai", no_coverage=True))["no_coverage"])


class AggregateTests(unittest.TestCase):
    def test_rates(self) -> None:
        examples = {"q1": {"category": ["procedural"]}, "q2": {"category": ["negative_out_of_scope"]}}
        rows = []
        for example_id, valid, total, no_cov in (("q1", 3, 4, False), ("q2", 0, 0, True)):
            scores = {"status": "SUCCESS", "schema_valid": True, "truncated": False, "no_coverage": no_cov, "claims": 2,
                      "citations_total": total, "citations_valid": valid, "has_valid_claim": valid > 0,
                      "unsupported_structured_citations": total - valid, "text_case_references": 1, "unsupported_text_case_references": 0,
                      "issue_codes": []}
            rows.append({"config": "C_full_legalai", "example_id": example_id, "scores": scores, "latency_s": 5.0})
        result = evaluation.aggregate(rows, examples)["C_full_legalai"]
        self.assertEqual((result["structural_grounding_rate"], result["answers_with_valid_claim_rate"]), (0.75, 0.5))
        self.assertEqual(result["unsupported_citation_rate"], round(1 / 6, 4))
        self.assertEqual((result["out_of_scope_queries"], result["out_of_scope_no_coverage_rate"]), (1, 1.0))


class DenseOnlyServiceTests(unittest.TestCase):
    def test_forces_dense_without_rerank(self) -> None:
        calls = []

        class Inner:
            name = "inner"

            def retrieve(self, query, mode, *, top_k, candidate_k, filters, rerank):
                calls.append((mode, top_k, candidate_k, rerank))
                return "results"

        service = evaluation.DenseOnlyService(Inner())
        self.assertEqual(service.retrieve("q", mode="hybrid", top_k=5, candidate_k=20, filters=None, rerank=True), "results")
        self.assertEqual(calls, [("dense", 5, 20, False)])
        self.assertEqual(service.name, "inner")


class LlmOnlyPromptTests(unittest.TestCase):
    def test_same_sections_no_evidence_and_empty_citations(self) -> None:
        from backend.app.services.legal_answer_prompt_v3_llm_only import NO_EVIDENCE, build_legal_answer_prompt_v3_llm_only

        prompt = build_legal_answer_prompt_v3_llm_only("Is cheating bailable?", mode=AnswerMode.PROFESSIONAL)
        for block in ("<SYSTEM_RULES>", "<MODE_REQUIREMENTS>", "<LENGTH_RULES>", "<QUERY_CONTEXT>", "<EVIDENCE_SET>", "<CITATION_POLICY>"):
            self.assertIn(block, prompt)
        self.assertIn(NO_EVIDENCE, prompt)
        self.assertIn("must be empty", prompt)
        self.assertIn("about 1200 tokens", prompt)
        self.assertNotIn("<EVIDENCE id=", prompt)


class ReviewSheetTests(unittest.TestCase):
    """The review sheet and the import, on synthetic raw outputs and a synthetic filled sheet."""

    def write_raw(self, raw: Path, sample: list[str]) -> None:
        import json

        for example_id in sample:
            for config in evaluation.CONFIGS:
                rag = config != "A_llm_only"
                record_ = {
                    "config": config, "example_id": example_id, "mode": "public", "query": f"query {example_id}", "status": "SUCCESS",
                    "summary": "summary", "answer": {"what_this_may_mean": ["See Arnesh Kumar v. State of Bihar."]},
                    "claims": [claim("c1", "E1")] if rag else [claim("c1")],
                    "evidence": [{"evidence_id": "E1", "case_name": "Arnesh Kumar vs State Of Bihar", "text_excerpt": "excerpt"}] if rag else [],
                }
                path = raw / config / f"{example_id}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record_), encoding="utf-8")

    def test_sample_build_fill_and_import(self) -> None:
        import csv
        import json

        from backend.scripts import build_review_sheet, import_human_review

        examples = json.loads(evaluation.EVAL_PATH.read_text(encoding="utf-8"))["examples"]
        sample = build_review_sheet.stratified_sample(examples)
        self.assertEqual(len(sample), 15)
        self.assertEqual(sample, build_review_sheet.stratified_sample(examples))  # deterministic
        chosen = [e for e in examples if e["example_id"] in sample]
        self.assertEqual({e["mode"] for e in chosen}, {"public", "professional"})
        self.assertEqual({e["difficulty"] for e in chosen}, {"basic", "moderate", "hard"})
        self.assertEqual(sum("negative_out_of_scope" in e["category"] for e in chosen), 2)

        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp) / "raw", Path(tmp) / "review"
            self.write_raw(raw, sample)
            build_review_sheet.main(["--raw-dir", str(raw), "--out-dir", str(out)])
            with (out / "review_sheet.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            key = json.loads((out / "review_key.json").read_text())
            self.assertEqual({row["answer_label"] for row in rows}, {"X", "Y", "Z"})
            self.assertNotIn("config", rows[0])  # blinded
            self.assertEqual(sum(row["row_type"] == "answer" for row in rows), 45)
            # Fill it: every RAG citation supported, every text reference partly, the LLM-only answers incorrect.
            for row in rows:
                config = key["key"][row["example_id"]][row["answer_label"]]
                row["reviewer"] = "synthetic"
                if row["row_type"] == "answer":
                    row["legal_correctness"] = "incorrect" if config == "A_llm_only" else "correct"
                elif row["row_type"] == "citation":
                    row["citation_support"] = "supported"
                else:
                    row["citation_support"] = "not_supported" if config == "A_llm_only" else "partly"
            filled = out / "filled.csv"
            with filled.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=build_review_sheet.COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            result_path = Path(tmp) / "result.json"
            import_human_review.main(["--sheet", str(filled), "--key", str(out / "review_key.json"), "--output", str(result_path)])
            result = json.loads(result_path.read_text())["configurations"]
            self.assertEqual(result["A_llm_only"]["human_grounding_rate_strict"], 0.0)
            self.assertEqual(result["C_full_legalai"]["human_grounding_rate_strict"], 0.5)  # 15 supported, 15 partly
            self.assertEqual(result["C_full_legalai"]["human_grounding_rate_lenient"], 1.0)
            self.assertEqual((result["A_llm_only"]["answers_correct_share"], result["B_dense_rag"]["answers_correct_share"]), (0.0, 1.0))

            rows[0]["legal_correctness"], rows[1]["citation_support"], rows[2]["reviewer"] = "", "maybe", ""
            with filled.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=build_review_sheet.COLUMNS)
                writer.writeheader()
                writer.writerows(rows + [rows[3]])
            errors = import_human_review.validate(rows + [rows[3]])
            self.assertTrue(any("legal_correctness" in e for e in errors))
            self.assertTrue(any("citation_support" in e for e in errors))
            self.assertTrue(any("reviewer is empty" in e for e in errors))
            self.assertTrue(any("duplicate" in e for e in errors))
            with self.assertRaisesRegex(SystemExit, "problem"):
                import_human_review.main(["--sheet", str(filled), "--key", str(out / "review_key.json")])

    def test_extra_review_values_are_own_categories_outside_the_denominators(self) -> None:
        from backend.scripts import import_human_review

        key = {"key": {"q1": {"X": "C_full_legalai", "Y": "B_dense_rag"}}}

        def row(review_id, label, row_type, correctness="", support=""):
            return {"review_id": review_id, "example_id": "q1", "answer_label": label, "row_type": row_type,
                    "legal_correctness": correctness, "citation_support": support, "reviewer": "r"}

        rows = [
            row("a1", "X", "answer", correctness="correct"),
            row("a2", "X", "answer", correctness="abstained"),
            row("a3", "X", "answer", correctness="no_answer"),
            row("a4", "X", "answer", correctness="incorrect"),
            row("c1", "X", "citation", support="supported"),
            row("c2", "X", "citation", support="partly"),
            row("t1", "X", "text_reference", support="not_applicable"),
            row("t2", "X", "text_reference", support="not_supported"),
            row("a5", "Y", "answer", correctness="abstained"),
        ]
        self.assertEqual(import_human_review.validate(rows), [])
        result = import_human_review.compute(rows, key)
        c = result["C_full_legalai"]
        # One-to-one: every value is counted under its own name; nothing is merged into cannot_judge.
        self.assertEqual(c["legal_correctness"], {"correct": 1, "abstained": 1, "no_answer": 1, "incorrect": 1})
        self.assertEqual(c["citation_support"], {"supported": 1, "partly": 1, "not_applicable": 1, "not_supported": 1})
        # not_applicable is not a judged authority; abstained and no_answer are not judged for correctness.
        self.assertEqual(c["authorities_judged"], 3)
        self.assertEqual((c["human_grounding_rate_strict"], c["human_grounding_rate_lenient"]), (0.3333, 0.6667))
        self.assertEqual((c["answers_judged"], c["answers_judged_for_correctness"], c["answers_correct_share"]), (4, 2, 0.5))
        self.assertEqual(c["by_row_type"]["citation"]["human_grounding_rate_strict"], 0.5)
        self.assertEqual(c["by_row_type"]["text_reference"]["authorities_judged"], 1)
        # Only abstentions: nothing judged for correctness, so no share rather than 0.
        self.assertIsNone(result["B_dense_rag"]["answers_correct_share"])
        # Values outside both scales are still refused.
        self.assertTrue(import_human_review.validate([row("z", "X", "answer", correctness="mostly")]))

    # Step 28: round 2 (full cited passages) is recorded alongside round 1.
    ROUND2_KEY = {"key": {"q1": {"X": "C_full_legalai", "Y": "B_dense_rag", "Z": "A_llm_only"}}}

    @staticmethod
    def _r1(review_id, label, row_type, support="", correctness="", notes=""):
        return {"review_id": review_id, "example_id": "q1", "answer_label": label, "row_type": row_type,
                "legal_correctness": correctness, "citation_support": support, "reviewer": "r1", "notes": notes,
                "evidence_excerpt": ""}

    def _round1(self):
        r = self._r1
        return [r("a1", "X", "answer", correctness="correct"), r("a2", "Y", "answer", correctness="correct"),
                r("a3", "Z", "answer", correctness="incorrect"),
                r("c1", "X", "citation", "supported"), r("c2", "X", "citation", "partly"),
                r("c3", "X", "citation", "not_supported"), r("c4", "X", "citation", "incorrect_law"),
                r("t1", "X", "text_reference", "not_applicable"),
                r("c5", "Y", "citation", "partly"), r("c6", "Y", "citation", "supported")]

    @staticmethod
    def _r2(review_id, label, row_type, r1_support, support):
        return {"review_id": review_id, "example_id": "q1", "answer_label": label, "row_type": row_type,
                "r1_support": r1_support, "citation_support": support, "reviewer": "r2"}

    def _round2(self):
        r = self._r2
        return [r("c2", "X", "citation", "partly", "supported"), r("c3", "X", "citation", "not_supported", "partly"),
                r("c4", "X", "citation", "incorrect_law", "incorrect_law"), r("t1", "X", "text_reference", "not_applicable", "not_applicable"),
                r("c5", "Y", "citation", "partly", "partly")]

    def test_round2_replaces_only_the_re_reviewed_rows_and_reports_the_change(self) -> None:
        from backend.scripts import import_human_review as imp

        round1, round2 = self._round1(), self._round2()
        self.assertEqual(imp.validate_round2(round2, round1), [])
        before = imp.compute(round1, self.ROUND2_KEY)
        result = imp.compute_round2(round1, round2, self.ROUND2_KEY)
        c = result["C_full_legalai"]
        # Round 1 as it was: 1 supported, 1 partly of 4 judged (not_applicable excluded).
        self.assertEqual((c["round1"]["human_grounding_rate_strict"], c["round1"]["human_grounding_rate_lenient"]), (0.25, 0.5))
        self.assertEqual(c["round1"]["human_grounding_rate_strict"], before["C_full_legalai"]["human_grounding_rate_strict"])
        # Round 2: c2 partly -> supported, c3 not_supported -> partly; c1 (supported in round 1) kept.
        self.assertEqual((c["round2"]["human_grounding_rate_strict"], c["round2"]["human_grounding_rate_lenient"]), (0.5, 0.75))
        self.assertEqual(c["change"], {"human_grounding_rate_strict": 0.25, "human_grounding_rate_lenient": 0.25, "incorrect_law_share": 0.0})
        self.assertEqual(c["re_reviewed"], 4)
        self.assertEqual(c["transitions"]["partly -> supported"], 1)
        b = result["B_dense_rag"]
        self.assertEqual((b["round1"]["human_grounding_rate_strict"], b["round2"]["human_grounding_rate_strict"], b["change"]["human_grounding_rate_strict"]), (0.5, 0.5, 0.0))
        self.assertIsNone(result["A_llm_only"]["round1"])  # no authorities
        # Round 1 rows are not modified by the merge.
        self.assertEqual([row["citation_support"] for row in round1], [row["citation_support"] for row in self._round1()])

    def test_round2_sheet_must_match_round1(self) -> None:
        from backend.scripts import import_human_review as imp

        round1, r = self._round1(), self._r2
        errors = imp.validate_round2(self._round2()[:-1] + [
            r("c6", "Y", "citation", "supported", "supported"),       # supported in round 1: not re-reviewed
            r("c2", "X", "citation", "partly", "supported"),          # duplicate
            {**r("c5", "Y", "citation", "not_supported", ""), "reviewer": ""},  # r1 changed, empty judgment and reviewer
        ], round1)
        joined = "\n".join(errors)
        for expected in ("c6: not a round 1 authority row", "c2: duplicate", "c5: r1_support differs",
                         "c5: citation_support must be", "c5: reviewer is empty"):
            self.assertIn(expected, joined)
        self.assertIn("c5: missing from round 2", "\n".join(imp.validate_round2(self._round2()[:-1], round1)))

    def test_round2_import_never_overwrites_round1(self) -> None:
        import csv
        import json

        from backend.scripts import import_human_review as imp

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            def write(path, rows):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            write(tmp / "r1.csv", self._round1())
            write(tmp / "r2.csv", self._round2())
            (tmp / "key.json").write_text(json.dumps(self.ROUND2_KEY))
            imp.main(["--sheet", str(tmp / "r1.csv"), "--key", str(tmp / "key.json"), "--output", str(tmp / "result.json")])
            round1_result = (tmp / "result.json").read_text()
            args = ["--round", "2", "--sheet", str(tmp / "r2.csv"), "--round1-sheet", str(tmp / "r1.csv"), "--key", str(tmp / "key.json")]
            with self.assertRaisesRegex(SystemExit, "never overwrites round 1"):
                imp.main(args + ["--output", str(tmp / "result.json")])
            self.assertEqual((tmp / "result.json").read_text(), round1_result)
            with self.assertRaisesRegex(SystemExit, "needs --round1-sheet"):
                imp.main(["--round", "2", "--sheet", str(tmp / "r2.csv"), "--key", str(tmp / "key.json")])
            imp.main(args + ["--output", str(tmp / "result_round2.json")])
            imp.main(args + ["--output", str(tmp / "result_round2.json")])  # a round 2 result may be rewritten
            result = json.loads((tmp / "result_round2.json").read_text())
            self.assertEqual((result["round"], result["re_reviewed_rows"]), (2, 5))
            self.assertEqual(result["configurations"]["C_full_legalai"]["round2"]["human_grounding_rate_strict"], 0.5)
            self.assertEqual((tmp / "result.json").read_text(), round1_result)

    def test_round2_sheet_rows_use_the_full_chunk_without_the_key(self) -> None:
        from backend.scripts import build_review_round2 as b2

        chunk_a, chunk_b = "A" * 600 + " rest of passage A", "B" * 600 + " rest of passage B"
        round1 = [self._r1("c1", "X", "citation", "supported"), self._r1("c2", "X", "citation", "partly", notes="cut off"),
                  self._r1("t1", "Y", "text_reference", "not_applicable"), self._r1("a1", "X", "answer", correctness="correct")]
        round1[0]["evidence_excerpt"], round1[1]["evidence_excerpt"] = chunk_a[:600], chunk_b[:600]
        round1[2]["evidence_excerpt"] = "(named in the answer text)"
        pooled = b2.evidence_ids_by_example({"rows": [{"example_id": "q1", "config": "B", "evidence_chunk_ids": ["k:a"]},
                                                      {"example_id": "q1", "config": "C", "evidence_chunk_ids": ["k:b"]}]})
        self.assertEqual(pooled, {"q1": {"k:a", "k:b"}})
        rows = b2.round2_rows(round1, pooled, {"k:a": chunk_a, "k:b": chunk_b})
        self.assertEqual([row["review_id"] for row in rows], ["c2", "t1"])  # supported and answer rows left out
        self.assertEqual((rows[0]["evidence_excerpt"], rows[0]["chunk_id"], rows[0]["chunk_chars"]), (chunk_b, "k:b", len(chunk_b)))
        self.assertEqual((rows[0]["r1_support"], rows[0]["r1_notes"], rows[0]["citation_support"], rows[0]["reviewer"], rows[0]["notes"]),
                         ("partly", "cut off", "", "", ""))
        self.assertEqual((rows[1]["chunk_id"], rows[1]["evidence_excerpt"]), ("", "(named in the answer text)"))
        self.assertNotIn("legal_correctness", b2.ROUND2_COLUMNS)
        # Two different chunks starting with the same excerpt, or none: refused, nothing guessed.
        with self.assertRaisesRegex(SystemExit, "c2: 2 matching chunks"):
            b2.round2_rows(round1, {"q1": {"k:b", "k:b2"}}, {"k:b": chunk_b, "k:b2": chunk_b[:600] + " other"})
        with self.assertRaisesRegex(SystemExit, "c2: 0 matching chunks"):
            b2.round2_rows(round1, {"q1": {"k:a"}}, {"k:a": chunk_a})

    def test_round2_builder_never_takes_the_key(self) -> None:
        from backend.scripts import build_review_round2 as b2

        with self.assertRaisesRegex(SystemExit, "blinding key"):
            b2.main(["--round1-sheet", "/tmp/review_key.json", "--out", "/tmp/x/round2.csv"])
        with self.assertRaisesRegex(SystemExit, "outside the repository"):
            b2.main(["--round1-sheet", "/tmp/r1.csv", "--out", str(REPO_ROOT / "round2.csv")])

    def test_the_sheet_goes_outside_the_repository(self) -> None:
        from backend.scripts import build_review_sheet

        with self.assertRaisesRegex(SystemExit, "outside the repository"):
            build_review_sheet.main(["--raw-dir", "x", "--out-dir", str(REPO_ROOT / "review")])


class DailyCapacityStopTests(unittest.TestCase):
    """Step 24b: the run stops cleanly at the first DAILY_CAPACITY_REACHED; that query stays missing."""

    def test_stops_and_saves_nothing_for_the_refused_query(self) -> None:
        from unittest.mock import patch

        attempts = []

        def fake_llm_only(example, adapter):
            attempts.append(example["example_id"])
            status = evaluation.DAILY_CAPACITY if len(attempts) == 3 else "SUCCESS"
            return {"config": "A_llm_only", "example_id": example["example_id"], "mode": example["mode"], "status": status,
                    "backend": {"model": "m", "fallback_used": False}, "latency_s": 1.0, "claims": [], "evidence": []}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(evaluation, "run_llm_only", side_effect=fake_llm_only), \
                patch("backend.scripts.retrieve_legal_evidence.make_service", return_value=object()), \
                patch("backend.app.services.llm_provider_chain.build_answer_adapter", return_value=object()):
            evaluation.main(["--raw-dir", tmp, "--output-dir", str(Path(tmp) / "out"), "--configs", "A_llm_only", "--mode", "professional"])
            saved = sorted(p.stem for p in (Path(tmp) / "A_llm_only").glob("*.json"))
        self.assertEqual(len(attempts), 3)  # nothing is attempted after the refusal
        self.assertEqual(saved, attempts[:2])  # the refused query is not saved, so a later run retries it
        self.assertTrue(all(int(a.split("q")[-1]) >= 16 for a in attempts))  # professional queries only


class GuardTests(unittest.TestCase):
    def test_raw_outputs_must_be_outside_the_repository(self) -> None:
        with self.assertRaisesRegex(SystemExit, "outside the repository"):
            evaluation.main(["--raw-dir", str(REPO_ROOT / "tmp_raw"), "--score-only"])

    def test_frozen_manifests_are_read_only(self) -> None:
        from backend.scripts import rerun_retrieval_eval

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "read-only"):
                evaluation.main(["--raw-dir", tmp, "--output-dir", str(REPO_ROOT / "data/structured/manifests"), "--score-only"])
        with self.assertRaisesRegex(SystemExit, "read-only"):
            rerun_retrieval_eval.main(["--variant", "cpu_fp32", "--output-dir", str(REPO_ROOT / "data/structured/manifests")])


if __name__ == "__main__":
    unittest.main()
