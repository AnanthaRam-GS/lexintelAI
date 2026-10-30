"""Prompt v3 LLM-only variant: the evaluation baseline "A, LLM-only" of the step 24 three-configuration re-run.

Not used by the product. It keeps prompt v3's structure, length rules and output schemas
(``PublicLegalAnswer`` / ``ProfessionalLegalBrief``), so the only difference from the product prompt is that no
evidence is retrieved or shown:

- the same ``<SYSTEM_RULES>``, ``<ANSWER_MODE>`` and ``<MODE_REQUIREMENTS>`` as v1-v3;
- ``<QUERY_CONTEXT>`` holds only the original query (no query understanding, which belongs to the retrieval
  pipeline);
- ``<EVIDENCE_SET>`` says that no evidence is provided, and the citation rules say every ``citations`` list stays
  empty and no case, court, date, URL or evidence ID may be invented (as in the frozen Phase-0 ``LLM_ONLY``
  condition, ``run_grounded_answer_eval_generation.build_llm_only_prompt``);
- v3's length rules, without the rules that only concern cited evidence.

Prompts v1, v2 and v3 are unchanged; this file is pinned beside them in the evaluation run's provenance.
"""

from __future__ import annotations

import json

from backend.app.services.legal_answer_generation import AnswerMode
from backend.app.services.legal_answer_prompt import PROFESSIONAL_REQUIREMENTS, PUBLIC_REQUIREMENTS, SYSTEM_RULES
from backend.app.services.legal_answer_prompt_v3 import WORDS_PER_TOKEN, target_output_tokens

PROMPT_V3_LLM_ONLY = "legal_answer_prompt_v3_llm_only"
NO_EVIDENCE = "NO_RETRIEVED_EVIDENCE_AVAILABLE_IN_THIS_CONDITION"
LLM_ONLY_CITATION_POLICY = (
    "No retrieval evidence is provided in this condition. Every citations list (in claims and in the answer) must "
    "be empty. Do not invent evidence IDs, case names, courts, dates, page numbers, paragraph numbers or source URLs."
)


def llm_only_length_rules(mode: AnswerMode) -> str:
    tokens = target_output_tokens(mode)
    words = int(round(tokens * WORDS_PER_TOKEN, -1))
    return f"""Be concise. The whole JSON answer must stay under about {tokens} tokens (about {words} words). Stop once the question is answered; never pad.
State each point once, in the field it belongs to. Do not repeat the summary, an issue, a principle or a claim in another field.
Summaries are at most two sentences. Lists of text hold short bullet-style strings: one sentence each, at most about 20 words. Give at most 3 entries per list, and only the most important. Keep every field's type exactly as the schema defines it: uncertainties are objects with code and message, never plain strings.
Give at most 4 claims. A claim's text is one sentence, and its citations list is empty."""


def build_legal_answer_prompt_v3_llm_only(query: str, *, mode: AnswerMode = AnswerMode.PUBLIC) -> str:
    requirements = PUBLIC_REQUIREMENTS if mode == AnswerMode.PUBLIC else PROFESSIONAL_REQUIREMENTS
    return "\n\n".join(
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
            "<LENGTH_RULES>",
            llm_only_length_rules(mode),
            "</LENGTH_RULES>",
            "<QUERY_CONTEXT>",
            json.dumps({"original_query": query}, indent=2, ensure_ascii=False),
            "</QUERY_CONTEXT>",
            "<EVIDENCE_SET>",
            NO_EVIDENCE,
            "</EVIDENCE_SET>",
            "<CITATION_POLICY>",
            LLM_ONLY_CITATION_POLICY,
            "</CITATION_POLICY>",
        ]
    )
