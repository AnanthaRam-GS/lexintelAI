"""Step E4: parties from the model in the local document map (flag on only), with a mocked model.

Rule: docs/experiments/NER_PARTY_ROLES_PLAN.md section 3. The flag-off identity test compares today's output on the
20 party gold documents with the snapshot written before the change (party_gold_docs.py).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.services import ner_backend
from backend.app.services import professional_brief as brief
from backend.app.services.local_document_map import (
    PartyRole,
    accused_list_lines,
    build_local_document_map,
    extract_model_parties,
    merge_model_parties,
    snap_to_words,
)
from backend.scripts.tests.party_gold_docs import SNAPSHOT_PATH, document_chunks, flag_off_outputs
from backend.scripts.tests.test_ner_backend import checkpoint


class SpanEngine:
    """A fake model: predicts ``(needle, native type, confidence)`` wherever a needle occurs in the text."""

    device = "cpu"

    def __init__(self, spans: list[tuple[str, str, float]]) -> None:
        self.spans = spans
        self.calls = 0

    def predict(self, text: str) -> list[dict]:
        self.calls += 1
        out = []
        for needle, native, confidence in self.spans:
            for match in re.finditer(re.escape(needle), text):
                out.append({"start": match.start(), "end": match.end(), "type": native, "confidence": confidence})
        return sorted(out, key=lambda item: item["start"])


def chunk(text: str, chunk_id: str = "P1", page: int = 1) -> SimpleNamespace:
    return SimpleNamespace(text=text, private_chunk_id=chunk_id, page_start=page, page_end=page, pages=str(page),
                           source_file_name="doc.pdf", token_estimate=len(text.split()))


@contextlib.contextmanager
def combined(spans: list[tuple[str, str, float]]):
    engine = SpanEngine(spans)
    ner_backend.reset_ner_backend()  # the backend caches the loaded engine
    with checkpoint() as directory, patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "combined",
                                                            "LEGALAI_NER_CHECKPOINT_DIR": str(directory)}), \
            patch.object(ner_backend, "engine_factory", return_value=engine):
        yield engine


def model_parties(text: str, spans: list[tuple[str, str, float]], left_role: str = "petitioner/appellant",
                  document_type: str | None = None) -> list[tuple[str, str]]:
    with combined(spans):
        _result, entities = ner_backend.extract_entities_detailed(text)
    return [(p.role, p.name) for p in extract_model_parties([chunk(text)], [entities], left_role, document_type)]


class ModelPartyRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def test_party_types_are_parties_with_default_roles(self) -> None:
        text = "Ramesh Kumar filed this petition. The State of Kerala opposed it."
        found = model_parties(text, [("Ramesh Kumar", "PETITIONER", 0.95), ("State of Kerala", "RESPONDENT", 0.93)],
                              left_role="petitioner")
        self.assertEqual(found, [("petitioner", "Ramesh Kumar"), ("respondent", "State of Kerala")])

    def test_party_type_takes_a_cue_on_its_side_only(self) -> None:
        text = "The complainant Meera Rao reported it.\nThe accused Ravi Das fled.\nThe accused Anil Roy appealed."
        found = model_parties(text, [("Meera Rao", "PETITIONER", 0.9), ("Ravi Das", "RESPONDENT", 0.9),
                                     ("Anil Roy", "PETITIONER", 0.9)], left_role="appellant")
        # complainant is on the petitioner side; accused is on the respondent side; a PETITIONER with an
        # "accused" cue keeps the document's left-party role.
        self.assertEqual(found, [("complainant", "Meera Rao"), ("accused", "Ravi Das"), ("appellant", "Anil Roy")])

    def test_entities_without_role_are_dropped(self) -> None:
        text = "Kiran Rao saw the incident. Judge Mehta heard the case. The witness Sunil Jain was examined."
        found = model_parties(text, [("Kiran Rao", "OTHER_PERSON", 0.9), ("Mehta", "JUDGE", 0.9),
                                     ("Sunil Jain", "WITNESS", 0.9), ("Fictionpur Bank", "ORG", 0.9)])
        self.assertEqual(found, [])

    def test_witness_judge_and_lawyer_are_never_parties_even_with_a_cue(self) -> None:
        text = "Accused: Sunil Jain. Respondent: Mehta. Petitioner: Rao Advocate."
        found = model_parties(text, [("Sunil Jain", "WITNESS", 0.9), ("Mehta", "JUDGE", 0.9), ("Rao Advocate", "LAWYER", 0.9)])
        self.assertEqual(found, [])

    def test_person_and_organisation_with_cues_before_after_and_lists(self) -> None:
        text = ("Respondent No. 2: Priya Rao, resident of Samplepur.\n"
                "The accused, namely, Ajay Pal, Vijay Pal and Mohan Lal were arrested.\n"
                "Sunrise Traders Ltd.\n.... Petitioners\n"
                "Dev Kumar (complainant) and Lata Devi, the informant, were present.")
        found = model_parties(text, [("Priya Rao", "OTHER_PERSON", 0.9), ("Ajay Pal", "OTHER_PERSON", 0.9),
                                     ("Vijay Pal", "OTHER_PERSON", 0.9), ("Mohan Lal", "OTHER_PERSON", 0.9),
                                     ("Sunrise Traders Ltd.", "ORG", 0.9), ("Dev Kumar", "OTHER_PERSON", 0.9),
                                     ("Lata Devi", "OTHER_PERSON", 0.9)])
        self.assertEqual(found, [("respondent", "Priya Rao"), ("accused", "Ajay Pal"), ("accused", "Vijay Pal"),
                                 ("accused", "Mohan Lal"), ("petitioner", "Sunrise Traders Ltd"), ("complainant", "Dev Kumar"),
                                 ("informant", "Lata Devi")])

    def test_a_list_does_not_continue_across_other_words(self) -> None:
        text = "The accused Ajay Pal came with his friend Vijay Pal."
        found = model_parties(text, [("Ajay Pal", "OTHER_PERSON", 0.9), ("Vijay Pal", "OTHER_PERSON", 0.9)])
        self.assertEqual(found, [("accused", "Ajay Pal")])

    def test_cue_must_be_on_the_same_line_before_the_entity(self) -> None:
        text = "The accused was arrested.\nKiran Rao gave a statement."
        self.assertEqual(model_parties(text, [("Kiran Rao", "OTHER_PERSON", 0.9)]), [])

    def test_entities_below_the_frozen_threshold_are_ignored(self) -> None:
        text = "The accused Ravi Das fled."
        self.assertEqual(model_parties(text, [("Ravi Das", "RESPONDENT", 0.69)]), [])
        self.assertEqual(model_parties(text, [("Ravi Das", "RESPONDENT", 0.70)]), [("accused", "Ravi Das")])

    def test_generic_and_short_names_are_dropped(self) -> None:
        text = "The State filed it. Respondent: AB."
        self.assertEqual(model_parties(text, [("State", "RESPONDENT", 0.9), ("AB", "RESPONDENT", 0.9)]), [])

    def test_each_party_cites_the_chunk_it_was_found_in(self) -> None:
        chunks = [chunk("Nothing here.", "P1", 1), chunk("The accused Ravi Das fled.", "P2", 3)]
        with combined([("Ravi Das", "RESPONDENT", 0.9)]):
            entities = [ner_backend.extract_entities_detailed(c.text)[1] for c in chunks]
        parties = extract_model_parties(chunks, entities, "petitioner")
        self.assertEqual(parties, [PartyRole(role="accused", name="Ravi Das", private_evidence_id="P2", page_start=3, page_end=3)])


class WholeWordSpanTests(unittest.TestCase):
    """E4b fix 1: model spans snapped to whole words before they become party names."""

    def snap(self, text: str, piece: str) -> str:
        start = text.index(piece)
        a, b = snap_to_words(text, start, start + len(piece))
        return text[a:b]

    def test_a_span_cut_inside_a_word_is_completed(self) -> None:
        self.assertEqual(self.snap("Accused No. 1: Dev Fakename, s/o Mohan.", "Dev Fake"), "Dev Fakename")
        self.assertEqual(self.snap("appellant No. 3 Bharat Ninave @ Bhau is the son", "Bharat Ninave @ Bha"), "Bharat Ninave @ Bhau")
        self.assertEqual(self.snap("the accused Ravi Sampleton fled", "avi Sample"), "Ravi Sampleton")

    def test_edges_are_trimmed_and_spaces_are_not_crossed(self) -> None:
        self.assertEqual(self.snap("(Meera Rao), the complainant", "(Meera Rao),"), "Meera Rao")
        self.assertEqual(self.snap("Ravi Das and Anil Roy", "Ravi Das"), "Ravi Das")
        self.assertEqual(self.snap("M/s Orchid Traders Pvt. Ltd. is accused", "Orchid Traders Pvt. Ltd."), "Orchid Traders Pvt. Ltd")

    def test_hyphens_and_apostrophes_inside_words_are_kept(self) -> None:
        self.assertEqual(self.snap("Samplepur Urban Co-operative Bank Ltd.", "Samplepur Urban Co"), "Samplepur Urban Co-operative")
        self.assertEqual(self.snap("the accused Leo D\'Souza fled", "Leo D\'Sou"), "Leo D\'Souza")
        self.assertEqual(self.snap("Ravi Das - the accused", "Ravi Das"), "Ravi Das")  # a spaced dash is not a joiner

    def test_snapped_names_reach_the_parties(self) -> None:
        text = "Accused No. 1: Dev Fakename, s/o Mohan."
        found = model_parties(text, [("Dev Fake", "RESPONDENT", 0.9)], document_type="chargesheet")
        self.assertEqual(found, [("accused", "Dev Fakename")])

    def test_a_truncated_name_now_merges_with_the_regex_party(self) -> None:
        text = "Accused No. 1: Dev Fakename, s/o Mohan."
        with combined([("Dev Fake", "RESPONDENT", 0.9)]):
            entities = ner_backend.extract_entities_detailed(text)[1]
        model = extract_model_parties([chunk(text)], [entities], "petitioner", "chargesheet")
        regex = [PartyRole(role="accused", name="Dev Fakename", private_evidence_id="P1", page_start=1, page_end=1)]
        self.assertEqual(merge_model_parties(regex, model), regex)


class AccusedCueTests(unittest.TestCase):
    """E4b fix 2: accused numbers and accused lists in FIRs and charge sheets."""

    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def test_accused_numbers_override_the_respondent_tag_in_a_charge_sheet(self) -> None:
        text = ("A-1 Manoj Gaikar @ Bunty, in custody;\nA2 Farhan Shaikh, in custody;\nA 3 Kavita Dongre, on bail;\n"
                "Accused No. 4: Raju Tambol, absconding.\nAccused 5 Mohan Lal is dead.")
        spans = [("Manoj Gaikar @ Bunty", "RESPONDENT", 0.9), ("Farhan Shaikh", "RESPONDENT", 0.9),
                 ("Kavita Dongre", "OTHER_PERSON", 0.9), ("Raju Tam", "RESPONDENT", 0.9), ("Mohan Lal", "PETITIONER", 0.9)]
        found = model_parties(text, spans, document_type="chargesheet")
        self.assertEqual(found, [("accused", "Manoj Gaikar @ Bunty"), ("accused", "Farhan Shaikh"), ("accused", "Kavita Dongre"),
                                 ("accused", "Raju Tambol"), ("accused", "Mohan Lal")])

    def test_first_candidate_on_each_line_of_an_accused_list_in_an_fir(self) -> None:
        text = ("5. Details of known accused:\n   (i) Suresh Kotwal @ Sonu, aged about 30;\n"
                "   (ii) Imran Bhaldar and his brother Salim Bhaldar;\n   (iii) Deepak Zambre.\n"
                "6. Contents of the complaint:\nI, Lakshmi Varad, state that Mohan Pethkar saw it.")
        spans = [("Suresh Kotwal @ Sonu", "OTHER_PERSON", 0.9), ("Imran Bhaldar", "OTHER_PERSON", 0.9),
                 ("Salim Bhaldar", "OTHER_PERSON", 0.9), ("Deepak Zambre", "RESPONDENT", 0.9),
                 ("Lakshmi Varad", "OTHER_PERSON", 0.9), ("Mohan Pethkar", "OTHER_PERSON", 0.9)]
        found = model_parties(text, spans, document_type="FIR")
        self.assertEqual(found, [("accused", "Suresh Kotwal @ Sonu"), ("accused", "Imran Bhaldar"), ("accused", "Deepak Zambre")])

    def test_the_list_ends_at_the_first_line_without_a_marker(self) -> None:
        text = "Accused persons:\n1. Ravi Das\nThe police also met Anil Roy.\n2. Mohan Lal"
        spans = [("Ravi Das", "OTHER_PERSON", 0.9), ("Anil Roy", "OTHER_PERSON", 0.9), ("Mohan Lal", "OTHER_PERSON", 0.9)]
        self.assertEqual(model_parties(text, spans, document_type="FIR"), [("accused", "Ravi Das")])

    def test_other_document_types_keep_the_e4_rule(self) -> None:
        text = "A-1 Manoj Gaikar, in custody.\nDetails of known accused:\n(i) Imran Bhaldar"
        spans = [("Manoj Gaikar", "RESPONDENT", 0.9), ("Imran Bhaldar", "OTHER_PERSON", 0.9)]
        for document_type in ("judgment", "petition", "order", "unknown", None):
            with self.subTest(document_type=document_type):
                self.assertEqual(model_parties(text, spans, document_type=document_type), [("respondent", "Manoj Gaikar")])

    def test_without_an_accused_cue_the_e4_rule_applies_in_a_charge_sheet(self) -> None:
        text = "Complainant: Asha Rao, proprietor.\nThe witness Geeta Demo was examined."
        spans = [("Asha Rao", "PETITIONER", 0.9), ("Geeta Demo", "WITNESS", 0.9)]
        self.assertEqual(model_parties(text, spans, document_type="chargesheet"), [("complainant", "Asha Rao")])

    def test_accused_list_lines_helper(self) -> None:
        text = "Heading accused:\n(i) A\nii) B\n(3) C\n- D\nA-5 E\nend\n(vi) F"
        lines = [text[a:b].strip() for a, b in accused_list_lines(text)]
        self.assertEqual(lines, ["(i) A", "ii) B", "(3) C", "- D", "A-5 E"])

    def test_charge_sheet_end_to_end_with_a_mocked_model(self) -> None:
        filename, chunks = document_chunks("s03_chargesheet_four_accused")
        spans = [("Manoj Gaikar @ Bunty", "RESPONDENT", 0.9), ("Farhan Shaikhwadi", "RESPONDENT", 0.9),
                 ("Kavita Dongrekar", "RESPONDENT", 0.9), ("Raju Tam", "RESPONDENT", 0.9)]
        with combined(spans):
            on = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(on.document_type, "chargesheet")
        roles = {p.name: p.role for p in on.parties_and_roles}
        for name in ("Manoj Gaikar @ Bunty", "Farhan Shaikhwadi", "Kavita Dongrekar", "Raju Tambolkar"):  # the alias is a separate word
            self.assertEqual(roles.get(name), "accused", name)


class MergeTests(unittest.TestCase):
    def regex(self, *items: tuple[str, str]) -> list[PartyRole]:
        return [PartyRole(role=role, name=name, private_evidence_id="P1", page_start=1, page_end=1) for role, name in items]

    def model(self, *items: tuple[str, str]) -> list[PartyRole]:
        return [PartyRole(role=role, name=name, private_evidence_id="P2", page_start=2, page_end=2) for role, name in items]

    def test_regex_parties_stay_first_and_unchanged(self) -> None:
        regex = self.regex(("complainant", "Meera Rao"), ("accused", "Ravi Das"))
        merged = merge_model_parties(regex, self.model(("accused", "Anil Roy")))
        self.assertEqual(merged[:2], regex)
        self.assertEqual([(p.role, p.name) for p in merged[2:]], [("accused", "Anil Roy")])

    def test_the_same_person_is_not_added_again_whatever_the_role(self) -> None:
        regex = self.regex(("accused", "RAVI DAS"), ("respondent", "The State Of Kerala"))
        model = self.model(("accused", "Ravi Das"), ("respondent", "Ravi"), ("complainant", "Shri Ravi Das"),
                           ("respondent", "State of Kerala"))
        self.assertEqual(merge_model_parties(regex, model), regex)

    def test_aliases_are_the_same_person(self) -> None:
        regex = self.regex(("applicant", "NEELAM @ NEERAJ"))
        model = self.model(("applicant", "Neeraj"), ("accused", "Suresh Kotwal @ Sonu"), ("accused", "Sonu"),
                           ("accused", "Suresh Kotwal alias Sonu"))
        merged = merge_model_parties(regex, model)
        self.assertEqual([(p.role, p.name) for p in merged], [("applicant", "NEELAM @ NEERAJ"), ("accused", "Suresh Kotwal @ Sonu")])

    def test_different_people_with_a_shared_surname_are_kept(self) -> None:
        merged = merge_model_parties([], self.model(("appellant", "Gopal Ninave"), ("appellant", "Sitaram Ninave")))
        self.assertEqual(len(merged), 2)

    def test_the_existing_cap_of_ten_applies(self) -> None:
        regex = self.regex(*[("accused", f"Person {chr(65 + i)}one") for i in range(8)])
        merged = merge_model_parties(regex, self.model(*[("accused", f"Other {chr(65 + i)}two") for i in range(5)]))
        self.assertEqual(len(merged), 10)
        self.assertEqual(merged[:8], regex)


class DocumentMapTests(unittest.TestCase):
    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def test_flag_off_output_is_byte_identical_to_the_snapshot(self) -> None:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        current = json.loads(json.dumps(flag_off_outputs(), ensure_ascii=False))
        self.assertEqual(sorted(current), sorted(snapshot))
        for doc_id in snapshot:
            with self.subTest(doc_id=doc_id):
                self.assertEqual(current[doc_id], snapshot[doc_id])

    def test_no_test_helper_opens_the_public_label_files(self) -> None:
        from pathlib import Path

        original = Path.read_text

        def guarded(path, *args, **kwargs):
            if str(path).endswith(".labels.json"):
                raise AssertionError(f"opened {path}")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded):
            from backend.scripts.tests.party_gold_docs import documents

            docs = documents()
            document_chunks("p01_gujarat_hc_2021")
        self.assertEqual({d for d, v in docs.items() if v["source"] == "public"},
                         {"p01_gujarat_hc_2021", "p02_andhra_hc_2023", "p03_punjab_hc_2023", "p04_supreme_court_2022",
                          "p05_allahabad_hc_2019"})

    def test_flag_off_never_calls_the_model(self) -> None:
        filename, chunks = document_chunks("s01_fir_multi_accused")
        engine = SpanEngine([("Imran Bhaldar", "RESPONDENT", 0.99)])
        with patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "deterministic"}), \
                patch.object(ner_backend, "engine_factory", return_value=engine):
            document_map = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(engine.calls, 0)
        self.assertNotIn("Imran Bhaldar", [p.name for p in document_map.parties_and_roles])

    def test_flag_on_adds_model_parties_in_the_existing_format(self) -> None:
        filename, chunks = document_chunks("f_fir")
        with patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "deterministic"}):
            off = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        with combined([("Ravi Sampleton", "RESPONDENT", 0.95), ("Kiran Exampleton", "WITNESS", 0.95),
                       ("Arjun Notreal", "OTHER_PERSON", 0.95)]) as engine:
            on = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(engine.calls, len(chunks))  # one inference per chunk, shared with the entity fields
        # The regex already has both parties; the model adds no duplicate, no witness and no officer.
        self.assertEqual(brief.parties_and_roles(on), brief.parties_and_roles(off))
        for item in brief.parties_and_roles(on):
            self.assertRegex(item, r"^[A-Z][a-z/]+: .+ \[P\d+(, pp?\. [\d-]+)?\]$")

    def test_flag_on_model_party_reaches_the_brief_with_a_reference(self) -> None:
        filename, chunks = document_chunks("s01_fir_multi_accused")
        with combined([("Imran Bhaldar", "OTHER_PERSON", 0.95), ("Deepak Zambre", "OTHER_PERSON", 0.95)]):
            on = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        items = brief.parties_and_roles(on)
        # "(ii) Imran Bhaldar" in the numbered list has no cue; the narrative "associates" has none either:
        # only cue-backed mentions count, so the outcome depends on the text, not on the mock.
        texts = {c.private_chunk_id: c.text for c in chunks}
        for party in on.parties_and_roles:
            self.assertIn(party.name.lower(), re.sub(r"\s+", " ", texts[party.private_evidence_id]).lower())
        self.assertTrue(all(re.search(r"\[P\d+", item) for item in items))

    def test_flag_on_with_the_model_unavailable_gives_the_regex_parties(self) -> None:
        filename, chunks = document_chunks("f_petition")
        with patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "deterministic"}):
            off = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        with patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "combined", "LEGALAI_NER_CHECKPOINT_DIR": "models/does-not-exist"}):
            on = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        self.assertEqual(on.parties_and_roles, off.parties_and_roles)


class DetailedEntitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        ner_backend.reset_ner_backend()
        self.addCleanup(ner_backend.reset_ner_backend)

    def test_deterministic_has_no_model_entities(self) -> None:
        with patch.dict(os.environ, {"LEGALAI_NER_BACKEND": "deterministic"}):
            result, model = ner_backend.extract_entities_detailed("The accused Ravi Das fled.")
        self.assertEqual(model, [])
        plain = ner_backend.extract_entities("The accused Ravi Das fled.")
        self.assertEqual([e.model_dump() for e in result.entities], [e.model_dump() for e in plain.entities])

    def test_combined_returns_the_same_entities_and_the_model_types(self) -> None:
        text = "The accused Ravi Das fled. Sunil Jain saw it."
        spans = [("Ravi Das", "RESPONDENT", 0.9), ("Sunil Jain", "WITNESS", 0.8), ("fled", "OTHER_PERSON", 0.5)]
        with combined(spans):
            result, model = ner_backend.extract_entities_detailed(text)
            plain = ner_backend.extract_entities(text)
        self.assertEqual([e.model_dump() for e in result.entities], [e.model_dump() for e in plain.entities])
        self.assertEqual([(e.text, e.metadata["native_type"]) for e in model], [("Ravi Das", "RESPONDENT"), ("Sunil Jain", "WITNESS")])


if __name__ == "__main__":
    unittest.main()
