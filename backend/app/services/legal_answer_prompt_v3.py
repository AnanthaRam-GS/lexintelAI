"""Prompt v3 for citation-grounded LegalAI answers (product runtime, step 22): v2 plus concision.

v1 (``legal_answer_prompt.py``) is the frozen evaluation baseline and v2 (``legal_answer_prompt_v2.py``) the step 11c
prompt; both stay pinned and unchanged. v3 keeps every v2 rule (structured claims tied to evidence IDs, case names
copied exactly, the no-coverage answer) and the same output schemas, so the API contract and the frontend are
unchanged. It adds length rules, because on Groq's 8,000-token per-request limit the v2 professional answer and the
brief did not fit in the output left after the evidence (``docs/live_runs/LIVE_RUN_SUMMARY.md``, steps 11d and 21):

1. A per-mode output target: about ``PUBLIC_TARGET_OUTPUT_TOKENS`` for public answers and
   ``PROFESSIONAL_TARGET_OUTPUT_TOKENS`` for professional answers, for the whole JSON object.
2. No repetition: each point appears once, in the field it belongs to.
3. Short list items: list fields hold at most 3 short bullet-style entries, summaries two sentences, at most 4 claims.
4. Nothing the product does not read: citations go in the claims only (``generate_legal_answer`` takes the answer's
   citations from the claims, so the answer object's own ``citations`` list stays empty); a citation's
   ``source_metadata`` carries only ``case_name`` and ``source_url`` (what the public sources list shows; the
   validator checks only the fields present), and ``retrieved_authorities`` only ``evidence_id`` and ``case_name``. With rules 1-3 alone (the first v3 live runs,
   step 22) answers still ran 1,500-2,000 tokens and R1, R3 and every brief stopped at the 2,048-token limit.
5. Only E# evidence IDs are citable; uploaded-document excerpts (P#) are facts, never citations (a P# citation always
   fails validation with UNKNOWN_EVIDENCE_ID).
6. When the uploaded document's map (``<PRIVATE_DOCUMENT_MAP>``) is present, LegalAI shows its parties, chronology,
   procedural stages and evidence to the lawyer itself (``professional_brief.py``); the model must not restate
   them, only use them. The rule names the block without its opening ``<``: the tag itself in every prompt would
   read as a document map that is not there (the question-mode check, and the fake E2E provider's detector).
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
from backend.app.services.legal_answer_prompt_v2 import NO_COVERAGE_STATEMENT, V2_RULES

PROMPT_V3 = "legal_answer_prompt_v3"

PUBLIC_TARGET_OUTPUT_TOKENS = 900
PROFESSIONAL_TARGET_OUTPUT_TOKENS = 1200
# About 0.75 English words per token: the target is also given in words, which models follow more reliably.
WORDS_PER_TOKEN = 0.75


def target_output_tokens(mode: AnswerMode) -> int:
    return PUBLIC_TARGET_OUTPUT_TOKENS if mode == AnswerMode.PUBLIC else PROFESSIONAL_TARGET_OUTPUT_TOKENS


def concision_rules(mode: AnswerMode) -> str:
    tokens = target_output_tokens(mode)
    words = int(round(tokens * WORDS_PER_TOKEN, -1))
    return f"""Be concise. The whole JSON answer, including claims and citations, must stay under about {tokens} tokens (about {words} words). Stop once the question is answered; never pad.
State each point once, in the field it belongs to. Do not repeat the summary, an issue, a principle or a claim in another field.
Summaries are at most two sentences. Lists of text hold short bullet-style strings: one sentence each, at most about 20 words. Give at most 3 entries per list, and only the most important; an empty list is better than an entry not grounded in the evidence. Keep every field's type exactly as the schema defines it: uncertainties are objects with code and message, retrieved_authorities and citations are objects, never plain strings.
Give at most 4 claims. A claim's text is one sentence. A citation's supported_text is a short paraphrase of at most about 15 words. Do not cite the same evidence for near-identical claims.
Citations belong in claims: leave the answer object's own citations list empty, because LegalAI reads citations from the claims only. In each citation's source_metadata give only case_name and source_url, copied exactly; leave out court, date and every other field (LegalAI adds them from the evidence). In retrieved_authorities give only evidence_id and case_name, once per cited evidence item.
Only E# evidence IDs from the evidence set can be cited. Uploaded-document excerpts (P#) are the user's facts: use them in the text, but never put a P# ID in a citation.
If the uploaded document's map (the PRIVATE_DOCUMENT_MAP block) is present, LegalAI shows its parties, chronology, procedural stages and evidence list to the lawyer separately. Use them, but do not restate them: do not list the parties, dates or evidence items again in material_facts_from_query, procedural_posture or analysis."""


def build_legal_answer_prompt_v3(packet: GroundedEvidencePacket, *, mode: AnswerMode = AnswerMode.PUBLIC) -> LegalAnswerPrompt:
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
            "<LENGTH_RULES>",
            concision_rules(mode),
            "</LENGTH_RULES>",
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


__all__ = [
    "NO_COVERAGE_STATEMENT",
    "PROMPT_V3",
    "PROFESSIONAL_TARGET_OUTPUT_TOKENS",
    "PUBLIC_TARGET_OUTPUT_TOKENS",
    "build_legal_answer_prompt_v3",
    "concision_rules",
    "target_output_tokens",
]
