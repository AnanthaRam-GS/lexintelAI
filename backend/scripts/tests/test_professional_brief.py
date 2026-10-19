"""Field-by-field tests for the professional brief sources (BRIEF-001, BRIEF-002). No database, no LLM."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services import professional_brief as brief
from backend.app.services.legal_rag_retrieval import (
    CitationMetadata,
    LegalEvidenceChunk,
    LegalRetrievalResult,
    RetrievalStageCounts,
    RetrievalTimings,
)
from backend.app.services.local_document_map import (
    ChronologyEntry,
    EvidenceItem,
    LocalDocumentMap,
    PartyRole,
    ProceduralStage,
    build_local_document_map,
    parse_date_iso,
)
from backend.app.services.private_pdf_rag import build_private_chunks


def chunks(*texts: str):
    return build_private_chunks([{"text": text, "page_start": index + 1, "page_end": index + 1} for index, text in enumerate(texts)])


def sample_map() -> LocalDocumentMap:
    return LocalDocumentMap(
        document_type="FIR",
        parties_and_roles=[
            PartyRole(role="complainant", name="Meera Placeholder", private_evidence_id="P1", page_start=1, page_end=1),
            PartyRole(role="accused", name=None, private_evidence_id="P1"),  # role only: not a party entry
        ],
        chronology=[
            ChronologyEntry(date="04-03-2024", event=None, context="Date of registration: 04-03-2024", private_evidence_id="P1", page_start=1, page_end=1),
            ChronologyEntry(date="04-03-2024", event="FIR registered", context="The FIR was registered on 04-03-2024", private_evidence_id="P2", page_start=2, page_end=2),
            ChronologyEntry(date="03-03-2024", event="incident occurred", context="occurrence: 03-03-2024", private_evidence_id="P1", page_start=1, page_end=1),
            ChronologyEntry(date="sometime in 2024", event=None, context="undated", private_evidence_id="P1"),
        ],
        procedural_stages=[ProceduralStage(("FIR registration",), "The FIR was registered on 04-03-2024.", "P2", 2, 2)],
        evidence_items=[EvidenceItem(("witnesses", "electronic"), "The eye-witness saw it on CCTV.", "P1", 1, 2)],
        missing_or_unclear_information=["No accused or defence position excerpt was identified in the uploaded material."],
    )


class DocumentFieldTests(unittest.TestCase):
    def test_parties_and_roles_carry_role_name_and_p_reference(self) -> None:
        self.assertEqual(brief.parties_and_roles(sample_map()), ["Complainant: Meera Placeholder [P1, p. 1]"])

    def test_chronology_is_dated_sorted_deduplicated_and_referenced(self) -> None:
        self.assertEqual(
            brief.chronology(sample_map()),
            [
                "2024-03-03 - Incident occurred: occurrence: 03-03-2024 [P1, p. 1]",
                "2024-03-04 - FIR registered: The FIR was registered on 04-03-2024 [P2, p. 2]",
            ],
        )

    def test_procedural_considerations_use_stage_detection_then_model_posture(self) -> None:
        self.assertEqual(
            brief.procedural_considerations(sample_map(), ["Bail application pending (model posture)."]),
            ["FIR registration: The FIR was registered on 04-03-2024. [P2, p. 2]", "Bail application pending (model posture)."],
        )

    def test_evidence_identified_uses_evidence_detection_with_categories(self) -> None:
        self.assertEqual(brief.evidence_identified(sample_map()), ["Witnesses, Electronic: The eye-witness saw it on CCTV. [P1, pp. 1-2]"])

    def test_without_a_document_every_document_field_is_empty(self) -> None:
        self.assertEqual(brief.parties_and_roles(None), [])
        self.assertEqual(brief.chronology(None), [])
        self.assertEqual(brief.evidence_identified(None), [])
        self.assertEqual(brief.document_limitations(None), [])
        self.assertEqual(brief.procedural_considerations(None, ["Model posture."]), ["Model posture."])

    def test_document_fields_are_never_copies_of_each_other(self) -> None:
        document_map = sample_map()
        fields = {
            "parties_and_roles": brief.parties_and_roles(document_map),
            "chronology": brief.chronology(document_map),
            "procedural_considerations": brief.procedural_considerations(document_map),
            "evidence_identified": brief.evidence_identified(document_map),
        }
        names = list(fields)
        for index, left in enumerate(names):
            for right in names[index + 1:]:
                self.assertFalse(set(fields[left]) & set(fields[right]), f"{left} shares items with {right}")


class LlmPartyValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = chunks("Complainant: Meera Placeholder. Accused: Ravi Sampleton.", "Statement recorded.")

    def test_accepts_a_party_backed_by_a_matching_p_reference(self) -> None:
        accepted = brief.validated_llm_parties([{"name": "Ravi  Sampleton", "role": "accused", "evidence_id": "P1"}], self.chunks)
        self.assertEqual(accepted, ["Accused: Ravi  Sampleton [P1, p. 1]"])

    def test_rejects_unknown_reference_text_mismatch_and_missing_fields(self) -> None:
        candidates = [
            {"name": "Ravi Sampleton", "role": "accused", "evidence_id": "P9"},  # no such chunk
            {"name": "Ravi Sampleton", "role": "accused", "evidence_id": "P2"},  # name not in P2
            {"name": "Invented Person", "role": "witness", "evidence_id": "P1"},  # not in the document
            {"name": "Meera Placeholder", "role": "", "evidence_id": "P1"},  # no role
            "Complainant: Meera Placeholder",  # free text, no reference
        ]
        self.assertEqual(brief.validated_llm_parties(candidates, self.chunks), [])


class ExtractorTests(unittest.TestCase):
    def test_dates_parse_day_first_and_month_names(self) -> None:
        self.assertEqual(parse_date_iso("04-03-2024"), "2024-03-04")
        self.assertEqual(parse_date_iso("14.8.2015"), "2015-08-14")
        self.assertEqual(parse_date_iso("12 March 2024"), "2024-03-12")
        self.assertEqual(parse_date_iso("March 12, 2024"), "2024-03-12")
        self.assertEqual(parse_date_iso("31.02.2024"), None)

    def test_text_without_labelled_parties_yields_no_parties(self) -> None:
        document_map = build_local_document_map(
            chunks("Notes of a meeting. The secretary reported that the tank needs cleaning. Members discussed parking."),
            filename="notes.pdf", dense_provider=None, token_budget_tokens=4000,
        )
        self.assertEqual(document_map.parties_and_roles, [])
        self.assertEqual(brief.parties_and_roles(document_map), [])
        self.assertIn(
            "No party with a stated role (complainant, accused, petitioner, respondent ...) was identified in the uploaded document.",
            document_map.missing_or_unclear_information,
        )

    def test_fir_word_does_not_match_first(self) -> None:
        document_map = build_local_document_map(
            chunks("Judgment dated 30.10.2013 passed by the Judicial Magistrate First Class."),
            filename="j.pdf", dense_provider=None, token_budget_tokens=4000,
        )
        self.assertNotEqual(document_map.chronology[0].event, "FIR registered")


def evidence(rank: int, *, score: float | None, document_id: str = "doc", text: str = "") -> LegalEvidenceChunk:
    chunk_id = f"{document_id}:chunk:{rank:04d}"
    citation = CitationMetadata(citation_id=f"E{rank}", chunk_id=chunk_id, document_id=document_id, judgment_id=document_id)
    return LegalEvidenceChunk(
        rank=rank, citation_id=f"E{rank}", chunk_id=chunk_id, document_id=document_id, judgment_id=document_id,
        text=text or f"Chunk {rank}: the court considered regular bail.", case_name=f"Case {document_id}",
        court={"court_name": "High Court", "court_level": "high_court"}, judgment_date="2023-05-06",
        source_url="https://example.test/doc", page_start=2, page_end=3, paragraph_start=4, paragraph_end=6,
        reranker_score=score, reranker_rank=rank if score is not None else None, citation_metadata=citation,
    )


def retrieval(items: list[LegalEvidenceChunk], query: str = "regular bail custody") -> LegalRetrievalResult:
    return LegalRetrievalResult(
        query=query, query_understanding_version="test", understanding_summary={}, evidence=items,
        stage_counts=RetrievalStageCounts(bm25_returned=0, dense_returned=0, rrf_unique_candidates=0, reranker_candidates=0, final_evidence_count=len(items)),
        timings=RetrievalTimings(),
    )


class PrecedentTests(unittest.TestCase):
    def test_relevance_is_the_sigmoid_of_the_reranker_score(self) -> None:
        for score in (-7.5, -1.0, 0.0, 0.3, 4.2, 40.0, -40.0):
            self.assertAlmostEqual(brief.normalize_reranker_score(score), 1 / (1 + math.exp(-score)), places=6)
        self.assertLess(brief.normalize_reranker_score(-1.0), brief.normalize_reranker_score(0.3))  # monotonic
        self.assertIsNone(brief.normalize_reranker_score(None))
        self.assertIsNone(brief.normalize_reranker_score(float("nan")))

    def test_precedents_come_from_retrieved_metadata_one_per_document(self) -> None:
        items = [evidence(1, score=3.1, document_id="a"), evidence(2, score=-0.4, document_id="b"), evidence(3, score=1.0, document_id="a")]
        precedents = brief.precedents_from_retrieval(retrieval(items), max_chars=400)
        self.assertEqual([p.document_id for p in precedents], ["a", "b"])
        first = precedents[0]
        self.assertEqual(
            (first.chunk_id, first.case_name, first.court, first.year, first.source_url, first.page_start, first.page_end, first.paragraph_start, first.paragraph_end),
            ("a:chunk:0001", "Case a", "High Court", 2023, "https://example.test/doc", 2, 3, 4, 6),
        )
        self.assertEqual([p.reranker_score for p in precedents], [3.1, -0.4])
        self.assertEqual([p.relevance_score for p in precedents], [brief.normalize_reranker_score(3.1), brief.normalize_reranker_score(-0.4)])
        self.assertEqual(len({p.relevance_score for p in precedents}), 2)

    def test_missing_reranker_score_gives_null_relevance(self) -> None:
        precedents = brief.precedents_from_retrieval(retrieval([evidence(1, score=None)]), max_chars=400)
        self.assertIsNone(precedents[0].relevance_score)
        self.assertIsNone(precedents[0].reranker_score)
        self.assertEqual(brief.precedents_from_retrieval(None, max_chars=400), [])

    def test_excerpt_is_bounded_verbatim_and_centred_on_the_query_passage(self) -> None:
        filler = " ".join(f"Paragraph {n} discusses unrelated procedural history of the trial." for n in range(40))
        text = f"{filler} The court held that regular bail may be granted after long custody. {filler}"
        excerpt = brief.precedent_excerpt(text, "regular bail custody", 200)
        self.assertLessEqual(len(excerpt), 200)
        self.assertIn("regular bail may be granted after long custody", excerpt)
        self.assertTrue(excerpt.startswith("...") and excerpt.endswith("..."))
        self.assertIn(excerpt.strip(".").strip(), " ".join(text.split()))
        short = "Bail was granted."
        self.assertEqual(brief.precedent_excerpt(short, "bail", 200), short)


class FixturePrivacyTests(unittest.TestCase):
    """The brief fixtures hold no real personal data (fixtures/briefs/README.md)."""

    LABEL = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD"
    PATTERNS = {
        "phone": r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)",
        "aadhaar": r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)",
        "pan": r"\b[A-Z]{5}\d{4}[A-Z]\b",
        "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    }

    def test_synthetic_fixtures_are_labelled_and_contain_no_identifiers(self) -> None:
        import re

        from backend.scripts.tests.brief_fixtures import FIXTURE_NAMES, expected, fixture_text

        for name in FIXTURE_NAMES:
            with self.subTest(fixture=name):
                text = fixture_text(name)
                for kind, pattern in self.PATTERNS.items():
                    self.assertEqual(re.findall(pattern, text), [], f"{name}: {kind}")
                if expected(name)["synthetic"]:
                    self.assertTrue(text.startswith(self.LABEL))
                    self.assertTrue(text.rstrip().endswith(self.LABEL + "."))
                else:
                    self.assertIn("public judgment", text)
                    self.assertIn("Indian Kanoon", text)


if __name__ == "__main__":
    unittest.main()
