"""Human-labelled retrieval evaluation-set scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
from typing import Any, Protocol


EVALUATION_VERSION = "legalai-retrieval-eval-v1"
POOLING_VERSION = "legalai-retrieval-pool-v1"
TRACE_VERSION = "legalai-retrieval-trace-v1"
LABEL_VERSION = "legalai-relevance-label-v1"
VALID_RELEVANCE = {0, 1, 2, "uncertain"}
VALID_DOCUMENT_RELEVANCE = {"yes", "no", "uncertain"}


QUERY_DEFINITIONS: list[dict[str, Any]] = [
    {"query_id": "eval-q001", "query_text": "murder conviction section 302 IPC", "query_type": "statute_explicit", "target_family": "homicide", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "prior_sanity_query", "rationale": "Section 302 homicide hard case where prior retrieval systems disagreed."},
    {"query_id": "eval-q002", "query_text": "dowry death section 304B IPC", "query_type": "statute_explicit", "target_family": "dowry_and_domestic_cruelty", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "prior_sanity_query", "rationale": "Trusted corpus contains multiple dowry death chunks with explicit 304B references."},
    {"query_id": "eval-q003", "query_text": "criminal breach of trust section 406 IPC", "query_type": "statute_explicit", "target_family": "criminal_breach_of_trust", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "prior_sanity_query", "rationale": "Tests lexical statute matching and business/criminal trust context."},
    {"query_id": "eval-q004", "query_text": "robbery section 392 IPC", "query_type": "statute_explicit", "target_family": "theft_and_robbery", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "prior_sanity_query", "rationale": "Tests robbery-specific sections and theft family separation."},
    {"query_id": "eval-q005", "query_text": "rape section 376 IPC", "query_type": "statute_explicit", "target_family": "sexual_offences", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "prior_sanity_query", "rationale": "Sexual-offence corpus contains direct section 376 references."},
    {"query_id": "eval-q006", "query_text": "common intention section 34 IPC", "query_type": "statute_explicit", "target_family": "conspiracy_common_intention", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "prior_sanity_query", "rationale": "Tests common-intention provisions across multi-accused judgments."},
    {"query_id": "eval-q007", "query_text": "kidnapping section 363 IPC", "query_type": "statute_explicit", "target_family": "kidnapping", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Kidnapping family is well represented and statute-explicit."},
    {"query_id": "eval-q008", "query_text": "cheating section 420 IPC", "query_type": "statute_explicit", "target_family": "cheating_and_fraud", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Fraud and cheating chunks support section 420 retrieval."},
    {"query_id": "eval-q009", "query_text": "voluntarily causing hurt section 323 IPC", "query_type": "statute_explicit", "target_family": "hurt_and_assault", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Hurt-and-assault judgments include explicit hurt provisions."},
    {"query_id": "eval-q010", "query_text": "criminal conspiracy section 120B IPC", "query_type": "statute_explicit", "target_family": "conspiracy_common_intention", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Conspiracy appears across multi-offence corpus chunks."},
    {"query_id": "eval-q011", "query_text": "bail in commercial quantity narcotics case", "query_type": "plain_language", "target_family": "narcotics_related", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "NDPS bail/commercial quantity material exists in trusted chunks."},
    {"query_id": "eval-q012", "query_text": "husband accused of dowry death", "query_type": "plain_language", "target_family": "dowry_and_domestic_cruelty", "target_regime": "ipc_crpc", "difficulty": "easy", "origin": "designed_for_eval", "rationale": "Plain-language dowry death retrieval distinct from section-only query."},
    {"query_id": "eval-q013", "query_text": "cheating involving bank loan", "query_type": "plain_language", "target_family": "cheating_and_fraud", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Fraud corpus includes loan and financial deception contexts."},
    {"query_id": "eval-q014", "query_text": "group assault with shared intention", "query_type": "plain_language", "target_family": "hurt_and_assault", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Combines assault with common-intention style facts."},
    {"query_id": "eval-q015", "query_text": "child taken away without consent", "query_type": "plain_language", "target_family": "kidnapping", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Kidnapping corpus supports consent/abduction language."},
    {"query_id": "eval-q016", "query_text": "cash and jewellery stolen from victim", "query_type": "plain_language", "target_family": "theft_and_robbery", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Theft/robbery chunks contain property-taking fact patterns."},
    {"query_id": "eval-q017", "query_text": "sexual assault testimony of prosecutrix", "query_type": "plain_language", "target_family": "sexual_offences", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Sexual-offence judgments discuss prosecutrix testimony."},
    {"query_id": "eval-q018", "query_text": "fraudulent inducement and dishonest intention", "query_type": "plain_language", "target_family": "cheating_and_fraud", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Tests concept-level fraud retrieval without explicit section number."},
    {"query_id": "eval-q019", "query_text": "anticipatory bail under BNSS", "query_type": "procedural_relief", "target_family": "other", "target_regime": "bns_bnss", "difficulty": "medium", "origin": "prior_sanity_query", "rationale": "Transition-era BNSS anticipatory bail chunks are present."},
    {"query_id": "eval-q020", "query_text": "quashing FIR under section 482 CrPC", "query_type": "procedural_relief", "target_family": "other", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Procedural criminal petitions mention section 482 and FIR quashing."},
    {"query_id": "eval-q021", "query_text": "suspension of sentence in criminal appeal", "query_type": "procedural_relief", "target_family": "other", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Appeal/sentence-stage relief is present across criminal judgments."},
    {"query_id": "eval-q022", "query_text": "regular bail under NDPS Act", "query_type": "procedural_relief", "target_family": "narcotics_related", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "NDPS bail chunks support regular bail relief retrieval."},
    {"query_id": "eval-q023", "query_text": "appeal against conviction for murder", "query_type": "procedural_relief", "target_family": "homicide", "target_regime": "ipc_crpc", "difficulty": "medium", "origin": "designed_for_eval", "rationale": "Homicide corpus includes conviction appeal posture."},
    {"query_id": "eval-q024", "query_text": "bail where accused served section 41A notice", "query_type": "procedural_relief", "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Mixed-regime bail chunks mention section 41A notice and changed laws."},
    {"query_id": "eval-q025", "query_text": "offence under BNS after July 2024", "query_type": "transition_regime", "target_family": "other", "target_regime": "bns_bnss", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "BNS/BNSS chunks test post-commencement regime retrieval."},
    {"query_id": "eval-q026", "query_text": "BNSS anticipatory bail with old IPC offence", "query_type": "transition_regime", "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Mixed transition chunks combine BNSS procedure and IPC offences."},
    {"query_id": "eval-q027", "query_text": "IPC offence tried after new criminal laws commenced", "query_type": "transition_regime", "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Tests old substantive offence/new-law timing ambiguity."},
    {"query_id": "eval-q028", "query_text": "murder with robbery and recovery evidence", "query_type": "hard_ambiguous", "target_family": "homicide", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Multi-offence query tests homicide/theft collision."},
    {"query_id": "eval-q029", "query_text": "kidnapping followed by sexual assault", "query_type": "hard_ambiguous", "target_family": "sexual_offences", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Tests overlap between kidnapping and sexual-offence judgments."},
    {"query_id": "eval-q030", "query_text": "cheating and criminal breach of trust in business dispute", "query_type": "hard_ambiguous", "target_family": "criminal_breach_of_trust", "target_regime": "ipc_crpc", "difficulty": "hard", "origin": "designed_for_eval", "rationale": "Tests cheating versus breach-of-trust section collision."},
]


class Retriever(Protocol):
    def retrieve(self, query: str, mode: str, top_k: int, candidate_k: int, rerank: bool = False) -> list[Any]:
        ...


@dataclass(frozen=True)
class PoolingConfig:
    candidate_depth: int = 20
    primary_depth: int = 15
    always_retain_top: int = 5
    max_pool_size: int = 25


def build_query_manifest(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    document_ids = {chunk["document_id"] for chunk in chunks}
    family_docs: dict[str, list[str]] = {}
    regime_docs: dict[str, list[str]] = {}
    for chunk in chunks:
        family_docs.setdefault(str(chunk.get("effective_offence_family")), []).append(chunk["document_id"])
        regime_docs.setdefault(str(chunk.get("effective_legal_regime")), []).append(chunk["document_id"])
    queries: list[dict[str, Any]] = []
    for query in QUERY_DEFINITIONS:
        supporting = sorted(set(family_docs.get(query["target_family"], []) + regime_docs.get(query["target_regime"], [])))[:8]
        if not supporting:
            raise ValueError(f"query has no corpus support: {query['query_id']}")
        row = {
            "evaluation_version": EVALUATION_VERSION,
            **query,
            "corpus_supporting_document_ids": [doc_id for doc_id in supporting if doc_id in document_ids],
            "human_status": "pending",
        }
        queries.append(row)
    validate_queries(queries)
    return queries


def validate_queries(queries: list[dict[str, Any]]) -> None:
    if len(queries) != 30:
        raise ValueError("evaluation query manifest must contain exactly 30 queries")
    ids = [query["query_id"] for query in queries]
    if len(ids) != len(set(ids)):
        raise ValueError("query IDs must be unique")
    for expected, query_id in enumerate(ids, start=1):
        if query_id != f"eval-q{expected:03d}":
            raise ValueError("query IDs must be sequential eval-qNNN values")
    for query in queries:
        if not query.get("corpus_supporting_document_ids"):
            raise ValueError(f"query has no corpus support: {query['query_id']}")
        if query.get("human_status") != "pending":
            raise ValueError("initial query human_status must be pending")


def validate_judgment(row: dict[str, Any]) -> None:
    if row["human_relevance"] not in VALID_RELEVANCE:
        raise ValueError("invalid human_relevance")
    if row["document_relevant"] not in VALID_DOCUMENT_RELEVANCE:
        raise ValueError("invalid document_relevant")
    if len(str(row.get("notes", ""))) > 500:
        raise ValueError("notes must be bounded to 500 characters")


def bounded_preview(text: str, limit: int = 700) -> str:
    compact = " ".join(text.split())
    return compact[: limit - 3] + "..." if len(compact) > limit else compact


def candidate_key(query_id: str, chunk_id: str) -> str:
    return f"{query_id}:{chunk_id}"


def generate_pool(queries: list[dict[str, Any]], retriever: Retriever, config: PoolingConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    judgments: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for query in queries:
        per_chunk: dict[str, dict[str, Any]] = {}
        for system, mode, rerank in [
            ("bm25", "lexical", False),
            ("dense", "dense", False),
            ("hybrid", "hybrid", False),
            ("hybrid_rerank", "hybrid", True),
        ]:
            results = retriever.retrieve(query["query_text"], mode, top_k=config.candidate_depth, candidate_k=config.candidate_depth, rerank=rerank)
            for result in results:
                if result.rank > config.primary_depth:
                    continue
                existing = per_chunk.setdefault(result.chunk_id, {"result": result, "systems": {}})
                existing["systems"][system] = result
        selected = deterministic_select_pool(per_chunk, config)
        for order, (chunk_id, pooled) in enumerate(selected, start=1):
            result = pooled["result"]
            judgments.append(judgment_row(query["query_id"], result, order))
            traces.append(trace_row(query["query_id"], result, pooled["systems"]))
    return judgments, traces


def deterministic_select_pool(per_chunk: dict[str, dict[str, Any]], config: PoolingConfig) -> list[tuple[str, dict[str, Any]]]:
    mandatory: set[str] = set()
    for chunk_id, pooled in per_chunk.items():
        for result in pooled["systems"].values():
            if result.rank <= config.always_retain_top:
                mandatory.add(chunk_id)
    ranked = sorted(
        per_chunk.items(),
        key=lambda item: (0 if item[0] in mandatory else 1, best_rank(item[1]["systems"]), item[0]),
    )
    return ranked[: config.max_pool_size]


def best_rank(systems: dict[str, Any]) -> int:
    return min(result.rank for result in systems.values())


def judgment_row(query_id: str, result: Any, blinded_order: int) -> dict[str, Any]:
    row = {
        "evaluation_version": EVALUATION_VERSION,
        "label_version": LABEL_VERSION,
        "query_id": query_id,
        "chunk_id": result.chunk_id,
        "document_id": result.document_id,
        "case_title": result.case_title,
        "court": result.court,
        "decision_date": result.decision_date,
        "page_start": result.page_start,
        "page_end": result.page_end,
        "paragraph_start": result.paragraph_start,
        "paragraph_end": result.paragraph_end,
        "effective_offence_family": result.effective_offence_family,
        "effective_legal_regime": result.effective_legal_regime,
        "bounded_chunk_preview": bounded_preview(result.text),
        "blinded_order": blinded_order,
        "human_status": "pending",
        "human_relevance": "uncertain",
        "document_relevant": "uncertain",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
    }
    validate_judgment(row)
    return row


def trace_row(query_id: str, representative: Any, systems: dict[str, Any]) -> dict[str, Any]:
    def value(system: str, field: str) -> Any:
        result = systems.get(system)
        return getattr(result, field) if result else None
    return {
        "evaluation_version": EVALUATION_VERSION,
        "pooling_version": POOLING_VERSION,
        "trace_version": TRACE_VERSION,
        "query_id": query_id,
        "chunk_id": representative.chunk_id,
        "dense_rank": value("dense", "rank"),
        "dense_score": value("dense", "score"),
        "lexical_rank": value("bm25", "rank"),
        "lexical_score": value("bm25", "score"),
        "hybrid_rank": value("hybrid", "rank"),
        "hybrid_score": value("hybrid", "score"),
        "rerank_rank": value("hybrid_rerank", "rank"),
        "rerank_score": value("hybrid_rerank", "rerank_score"),
    }


def apply_review(judgments_path: Path, query_id: str, chunk_id: str, relevance: int | str, document_relevant: str, reviewer: str, reviewed_at: str, notes: str) -> dict[str, Any]:
    judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
    updated: dict[str, Any] | None = None
    for row in judgments:
        if row["query_id"] == query_id and row["chunk_id"] == chunk_id:
            row.update({"human_relevance": relevance, "document_relevant": document_relevant, "reviewer": reviewer, "reviewed_at": reviewed_at, "notes": notes, "human_status": "reviewed"})
            validate_judgment(row)
            updated = row
            break
    if updated is None:
        raise ValueError("judgment row not found")
    judgments_path.write_text(json.dumps(judgments, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return updated


def binary_relevant(grade: Any, threshold: int = 1) -> bool:
    return isinstance(grade, int) and grade >= threshold


def precision_at_k(results: list[str], labels: dict[str, int | str], k: int, threshold: int = 1) -> float | str:
    if not labels:
        return "not_available"
    top = results[:k]
    if not top:
        return 0.0
    return sum(1 for chunk_id in top if binary_relevant(labels.get(chunk_id), threshold)) / len(top)


def pooled_recall_at_k(results: list[str], labels: dict[str, int | str], k: int, threshold: int = 1) -> float | str:
    relevant = {chunk_id for chunk_id, grade in labels.items() if binary_relevant(grade, threshold)}
    if not relevant:
        return "not_available"
    return len(set(results[:k]) & relevant) / len(relevant)


def mrr(results: list[str], labels: dict[str, int | str], threshold: int = 1) -> float | str:
    if not labels:
        return "not_available"
    for index, chunk_id in enumerate(results, start=1):
        if binary_relevant(labels.get(chunk_id), threshold):
            return 1 / index
    return 0.0


def ndcg_at_k(results: list[str], labels: dict[str, int | str], k: int) -> float | str:
    if not labels:
        return "not_available"
    def gain(grade: Any) -> float:
        return float(grade) if isinstance(grade, int) else 0.0
    dcg = sum((2 ** gain(labels.get(chunk_id)) - 1) / math.log2(rank + 1) for rank, chunk_id in enumerate(results[:k], start=1))
    ideal = sorted((gain(grade) for grade in labels.values()), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, start=1))
    return 0.0 if idcg == 0 else dcg / idcg


def workload_summary(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    per_query: dict[str, int] = {}
    docs: set[str] = set()
    for row in judgments:
        per_query[row["query_id"]] = per_query.get(row["query_id"], 0) + 1
        docs.add(row["document_id"])
    counts = list(per_query.values())
    return {
        "query_count": len(per_query),
        "total_pooled_judgments": len(judgments),
        "total_pooled_documents": len(docs),
        "total_pooled_chunks": len(judgments),
        "mean_candidates_per_query": round(statistics.mean(counts), 2) if counts else 0,
        "median_candidates_per_query": statistics.median(counts) if counts else 0,
        "min_candidates_per_query": min(counts) if counts else 0,
        "max_candidates_per_query": max(counts) if counts else 0,
    }
