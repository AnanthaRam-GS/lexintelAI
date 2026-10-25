"""Deterministic stand-ins for the embedder, reranker and answer model (E2E only; see backend/app/testing).

- ``HashingEmbedder``: bag-of-words feature hashing into 1024 dimensions (the production dimension), so dense
  retrieval still prefers chunks that share words with the question. No model files.
- ``OverlapReranker``: the share of question words found in the passage, with a small hash tie-break so scores vary.
- ``FakeAnswerAdapter``: reads the question and the evidence from the prompt and returns a schema-valid answer whose
  claims cite the best-matching retrieved evidence, copying its metadata. When no evidence item shares at least two
  (and a third) of the question's content words, and no private document was uploaded, it returns the prompt's
  no-coverage answer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.legal_answer_generation import LegalAnswerModelResponse, ModelGenerationMetadata
from backend.app.services.legal_answer_prompt_v2 import NO_COVERAGE_STATEMENT
from backend.app.services.reranking.base import Reranker, RerankerConfig
from backend.app.services.vector_store import EXPECTED_EMBEDDING_DIMENSION, RetrievalResult

FAKE_PROVIDER = "e2e-fake"
FAKE_MODEL_ID = "e2e-fake-deterministic"
_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "the and for with that this from what when where which who whom how does do did can could would should may might "
    "are was were has have had not but any all its his her their there here into under over about after before than "
    "then them they you your yours our ours been being also such upon only other some more most very will shall".split()
)


def content_words(text: str) -> list[str]:
    return [word for word in _WORD.findall(text.lower()) if len(word) >= 3 and word not in STOPWORDS]


def _hash(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


class HashingEmbedder:
    """Deterministic bag-of-words vectors in the production dimension."""

    def __init__(self, dimension: int = EXPECTED_EMBEDDING_DIMENSION) -> None:
        self._config = EmbeddingConfig(model_name="e2e-hashing-bag-of-words", dimension=dimension)
        self._dimension = dimension

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    @property
    def embedding_dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for word in content_words(text) or ["empty"]:
            value = _hash(word)
            vector[value % self._dimension] += 1.0 if (value >> 32) & 1 else -1.0
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]


class OverlapReranker(Reranker):
    def __init__(self, config: RerankerConfig | None = None) -> None:
        self.config = config or RerankerConfig(model_name="e2e-overlap-reranker")

    def score_pairs(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        words = set(content_words(query))
        scores = []
        for candidate in candidates:
            passage = set(content_words(candidate.text))
            overlap = len(words & passage) / len(words) if words else 0.0
            scores.append(round(overlap + (_hash(f"{query}\n{candidate.chunk_id}") % 1000) / 1_000_000, 6))
        return scores


_EVIDENCE = re.compile(
    r'<EVIDENCE id="(?P<id>E\d+)">\s*<METADATA>\s*(?P<metadata>\{.*?\})\s*</METADATA>\s*<TEXT>\s*(?P<text>.*?)\s*</TEXT>',
    re.DOTALL,
)
_QUERY_CONTEXT = re.compile(r"<QUERY_CONTEXT>\s*(\{.*?\})\s*</QUERY_CONTEXT>", re.DOTALL)
_PRIVATE = re.compile(r"<PRIVATE_DOCUMENT_(?:EVIDENCE|MAP)\b")


def parse_prompt(prompt: str) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """(query context, evidence items with id/metadata/text, whether a private document is in the prompt)."""
    context_match = _QUERY_CONTEXT.search(prompt)
    context = json.loads(context_match.group(1)) if context_match else {}
    evidence = [
        {"id": match.group("id"), "metadata": json.loads(match.group("metadata")), "text": match.group("text")}
        for match in _EVIDENCE.finditer(prompt)
    ]
    return context, evidence, bool(_PRIVATE.search(prompt))


def first_sentence(text: str, limit: int = 220) -> str:
    flat = " ".join(text.split())
    sentence = re.split(r"(?<=[.;])\s", flat, maxsplit=1)[0]
    return sentence[:limit].rstrip()


def source_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Copied exactly from the evidence METADATA, as the grounding rules require."""
    return {key: metadata.get(key) for key in ("case_name", "court", "judgment_date", "source_url") if metadata.get(key) is not None}


class FakeAnswerAdapter:
    """A deterministic answer model: same prompt, same answer. Never calls a network service."""

    configured_model_id = FAKE_MODEL_ID
    max_attempts = 1

    def __init__(self) -> None:
        self.calls = 0

    def generate_structured_answer(self, prompt: str, *, schema: Any, mode: Any) -> LegalAnswerModelResponse:
        self.calls += 1
        context, evidence, has_private = parse_prompt(prompt)
        question = str(context.get("original_query") or "")
        words = set(content_words(question))
        ranked = sorted(
            ((len(words & set(content_words(item["text"]))), index, item) for index, item in enumerate(evidence)),
            key=lambda entry: (-entry[0], entry[1]),
        )
        # Covered: one item shares at least 2 of the question's content words, and at least a third of them.
        needed = max(2, math.ceil(len(words) / 3))
        cited = [item for overlap, _index, item in ranked if overlap >= needed][:2]
        if not cited and has_private and evidence:
            cited = [evidence[0]]
        public = str(getattr(mode, "value", mode)).lower() == "public"
        if not cited:
            parsed = self._no_coverage(public, context)
        else:
            parsed = self._answer(public, context, cited)
        return LegalAnswerModelResponse(
            raw_response=json.dumps(parsed, sort_keys=True),
            parsed_response=parsed,
            model_metadata=ModelGenerationMetadata(
                provider=FAKE_PROVIDER, configured_model_id=FAKE_MODEL_ID, actual_model_id=FAKE_MODEL_ID, response_mode=mode, finish_reason="stop"
            ),
        )

    @staticmethod
    def _claims(cited: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        claims, citations = [], []
        for number, item in enumerate(cited, start=1):
            claim_id = f"c{number}"
            sentence = first_sentence(item["text"])
            citation = {"evidence_id": item["id"], "claim_id": claim_id, "supported_text": sentence, "source_metadata": source_metadata(item["metadata"])}
            citations.append(citation)
            claims.append({"claim_id": claim_id, "text": f"The retrieved judgment states: {sentence}", "claim_type": "CASE_LAW", "citations": [citation]})
        return claims, citations

    def _answer(self, public: bool, context: dict[str, Any], cited: list[dict[str, Any]]) -> dict[str, Any]:
        claims, citations = self._claims(cited)
        cases = ", ".join(str(item["metadata"].get("case_name") or item["id"]) for item in cited)
        summary = f"Deterministic test answer based on the retrieved judgments ({cases})."
        sections = [f"{section.get('statute', '')} {section.get('section', '')}".strip() for section in context.get("explicit_sections") or []]
        if public:
            answer = {
                "summary": summary,
                "what_this_may_mean": [claim["text"] for claim in claims],
                "possible_legal_provisions": sections,
                "possible_next_steps": ["Speak to a lawyer about the specific facts of your situation."],
                "important_cautions": ["This is general information from retrieved judgments, not legal advice."],
                "citations": citations,
            }
        else:
            answer = {
                "issue_summary": summary,
                "material_facts_from_query": [str(context.get("original_query") or "")],
                "explicit_legal_provisions": sections,
                "procedural_posture": ["Deterministic test posture: the stage described in the question."],
                "legal_regime": str(context.get("legal_regime") or "unknown"),
                "legal_issues": ["Deterministic test issue drawn from the question."],
                "applicable_principles": [claim["text"] for claim in claims],
                "analysis": [f"Deterministic test analysis citing {item['id']}." for item in cited],
                "citations": citations,
            }
        return {"answer": answer, "summary": summary, "claims": claims}

    @staticmethod
    def _no_coverage(public: bool, context: dict[str, Any]) -> dict[str, Any]:
        summary = f"{NO_COVERAGE_STATEMENT} A lawyer who handles this kind of matter can help."
        if public:
            answer = {"summary": summary, "what_this_may_mean": [], "possible_legal_provisions": [], "possible_next_steps": [],
                      "important_cautions": [], "citations": []}
        else:
            answer = {"issue_summary": summary, "legal_regime": str(context.get("legal_regime") or "unknown"), "citations": []}
        return {"answer": answer, "summary": summary, "claims": []}
