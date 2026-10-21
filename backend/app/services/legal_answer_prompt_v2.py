"""Prompt v2 for citation-grounded LegalAI answers (product runtime).

v1 (``legal_answer_prompt.py``) is the frozen baseline used by the Phase-0
evaluation and is not changed. v2 keeps v1's rules, query context and
evidence blocks, and adds three rules found necessary in the step 11 live runs
(``docs/live_runs/LIVE_RUN_SUMMARY.md``):

1. Structured claims are mandatory: every substantive statement is a claim
   whose citations reference evidence IDs from the evidence set. (Live run R1
   returned an empty ``claims`` array and cited only in prose.)
2. Case names are copied exactly as given in the evidence metadata. (Live run
   P1 shortened case names, so every citation failed validation.)
3. When no retrieved evidence is relevant to the question, the answer must say
   so, starting with ``NO_COVERAGE_STATEMENT``, and must not give a substantive
   legal answer from general knowledge. (Live run P3 answered an off-corpus
   question from general knowledge.)
"""

from __future__ import annotations

from backend.app.services.legal_answer_generation import AnswerMode, GroundedEvidencePacket
from backend.app.services.legal_answer_prompt import (
    PROFESSIONAL_REQUIREMENTS,
    PUBLIC_REQUIREMENTS,
    SYSTEM_RULES,
    LegalAnswerPrompt,
    evidence_blocks,
    query_context,
)

PROMPT_V1 = "legal_answer_prompt_v1"
PROMPT_V2 = "legal_answer_prompt_v2"
PROMPT_VERSION = PROMPT_V2

NO_COVERAGE_STATEMENT = "The available sources do not cover this question."

V2_RULES = f"""Every substantive statement in the answer must be backed by at least one entry in "claims", and each claim must list citations whose evidence_id is an ID from the evidence set. Prose markers such as "(E2)" do not replace structured claims; an answer with an empty claims array is invalid unless it is a no-coverage answer as described below.
When a citation includes source_metadata, copy case_name, court, date and source_url exactly as they appear in that evidence item's METADATA. Do not shorten, reformat or complete them.
First decide whether any evidence item is relevant to the question. If none is, the answer is a no-coverage answer: begin the summary (and, for public answers, the summary field) with exactly "{NO_COVERAGE_STATEMENT}", say what kind of source or professional could help, return an empty claims array, and give no substantive legal answer, provisions, procedures, fees or steps from general knowledge."""


def build_legal_answer_prompt_v2(packet: GroundedEvidencePacket, *, mode: AnswerMode = AnswerMode.PUBLIC) -> LegalAnswerPrompt:
    requirements = PUBLIC_REQUIREMENTS if mode == AnswerMode.PUBLIC else PROFESSIONAL_REQUIREMENTS
    prompt = "\n\n".join(
        [
            "<SYSTEM_RULES>",
            SYSTEM_RULES,
            "</SYSTEM_RULES>",
            "<ANSWER_MODE>",
            mode.value,
            "</ANSWER_MODE>",
            "<MODE_REQUIREMENTS>",
            requirements,
            "</MODE_REQUIREMENTS>",
            "<GROUNDING_RULES>",
            V2_RULES,
            "</GROUNDING_RULES>",
            "<QUERY_CONTEXT>",
            query_context(packet),
            "</QUERY_CONTEXT>",
            "<EVIDENCE_SET>",
            evidence_blocks(packet),
            "</EVIDENCE_SET>",
            "<CITATION_POLICY>",
            "Citations may only reference evidence IDs present in this evidence set. Structured citation objects are authoritative; prose markers alone are insufficient.",
            "</CITATION_POLICY>",
        ]
    )
    return LegalAnswerPrompt(
        schema_version=packet.schema_version,
        mode=mode,
        prompt=prompt,
        answer_schema="PublicLegalAnswer" if mode == AnswerMode.PUBLIC else "ProfessionalLegalBrief",
        citation_policy=packet.citation_policy,
        character_count=len(prompt),
    )


def is_no_coverage_answer(summary: str | None) -> bool:
    return bool(summary) and summary.strip().startswith(NO_COVERAGE_STATEMENT)
