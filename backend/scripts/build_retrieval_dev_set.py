"""Build a separate retrieval tuning/development review set."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.retrieval.evaluation import PoolingConfig, bounded_preview, generate_pool, workload_summary
from backend.scripts.build_retrieval_eval_set import RealRetriever, build_parser as eval_parser, make_service
from backend.scripts.build_vector_index import REPO_ROOT, load_chunks

DEV_VERSION = "legalai-retrieval-dev-v1"
DEV_POOL_VERSION = "legalai-retrieval-dev-pool-v1"

DEV_QUERIES_PATH = REPO_ROOT / "data/structured/manifests/retrieval_dev_queries.json"
DEV_JUDGMENTS_PATH = REPO_ROOT / "data/structured/manifests/retrieval_dev_judgments.json"
DEV_TRACES_PATH = REPO_ROOT / "data/structured/manifests/retrieval_dev_pool_traces.json"
DEV_SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/retrieval_dev_summary.json"
DEV_REVIEW_DOC = REPO_ROOT / "docs/RETRIEVAL_DEV_REVIEW.md"
DEV_METHODOLOGY_DOC = REPO_ROOT / "docs/RETRIEVAL_DEV_METHODOLOGY.md"

DEV_QUERY_DEFINITIONS: list[dict[str, Any]] = [
    {"query_id": "dev-q001", "query_text": "BNSS bail for an IPC offence registered before July 2024", "query_type": "legal_regime_transition", "tuning_focus": ["legal_regime", "query_expansion"], "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "rationale": "Targets old offence/new procedure confusion without reusing the benchmark wording.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q002", "query_text": "new criminal law offence with BNSS procedure after commencement", "query_type": "legal_regime_transition", "tuning_focus": ["legal_regime"], "target_family": "other", "target_regime": "bns_bnss", "difficulty": "hard", "rationale": "Tests post-commencement BNS/BNSS routing evidence.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q003", "query_text": "anticipatory bail after new procedural code for old penal offence", "query_type": "legal_regime_transition", "tuning_focus": ["legal_regime", "metadata_reranking"], "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "rationale": "Targets anticipatory-bail transition without exact benchmark phrasing.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q004", "query_text": "savings clause issue when criminal case spans IPC and BNS", "query_type": "legal_regime_transition", "tuning_focus": ["legal_regime"], "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "rationale": "Targets transition/savings style regime resolution.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q005", "query_text": "post July 2024 arrest procedure in criminal petition", "query_type": "legal_regime_transition", "tuning_focus": ["legal_regime", "metadata_reranking"], "target_family": "other", "target_regime": "bns_bnss", "difficulty": "medium", "rationale": "Emphasizes date/procedure metadata while requiring text support.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q006", "query_text": "old CrPC notice practice compared with BNSS arrest safeguards", "query_type": "legal_regime_transition", "tuning_focus": ["legal_regime", "hard_negative"], "target_family": "other", "target_regime": "mixed_or_transition", "difficulty": "hard", "rationale": "Near-neighbor test for CrPC versus BNSS procedure.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q007", "query_text": "fatal assault during property robbery with recovery of articles", "query_type": "composite_ambiguous", "tuning_focus": ["composite_reasoning", "metadata_reranking"], "target_family": "homicide", "target_regime": "ipc_crpc", "difficulty": "hard", "rationale": "Combines homicide, robbery, and recovery without exact benchmark wording.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q008", "query_text": "minor abducted and later subjected to sexual offence", "query_type": "composite_ambiguous", "tuning_focus": ["composite_reasoning"], "target_family": "sexual_offences", "target_regime": "ipc_crpc", "difficulty": "hard", "rationale": "Composite kidnapping/sexual-offence evidence.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q009", "query_text": "business transaction alleging entrusted money and deception", "query_type": "composite_ambiguous", "tuning_focus": ["composite_reasoning", "hard_negative"], "target_family": "criminal_breach_of_trust", "target_regime": "ipc_crpc", "difficulty": "hard", "rationale": "Separates cheating, entrustment, and civil-dispute near neighbors.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q010", "query_text": "multiple accused assault where shared intention must be proved", "query_type": "composite_ambiguous", "tuning_focus": ["composite_reasoning", "query_expansion"], "target_family": "conspiracy_common_intention", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Tests common-intention evidence using plain-language concepts.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q011", "query_text": "drug bail with quantity threshold and statutory bar", "query_type": "composite_ambiguous", "tuning_focus": ["composite_reasoning", "metadata_reranking"], "target_family": "narcotics_related", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Combines bail, NDPS quantity, and statutory restriction.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q012", "query_text": "property taken by force rather than simple stealing", "query_type": "plain_language_expansion", "tuning_focus": ["query_expansion", "hard_negative"], "target_family": "theft_and_robbery", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Plain-language theft versus robbery distinction.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q013", "query_text": "woman harassed by husband and in laws for marriage demands", "query_type": "plain_language_expansion", "tuning_focus": ["query_expansion"], "target_family": "dowry_and_domestic_cruelty", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Tests expansion from factual domestic cruelty wording to legal terms.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q014", "query_text": "guardian complains child was lured away from lawful custody", "query_type": "plain_language_expansion", "tuning_focus": ["query_expansion"], "target_family": "kidnapping", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Plain-language lawful-guardianship concept.", "prior_benchmark_similarity": "related"},
    {"query_id": "dev-q015", "query_text": "investors induced to part with money by false promise", "query_type": "plain_language_expansion", "tuning_focus": ["query_expansion"], "target_family": "cheating_and_fraud", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Lexical mismatch around fraudulent inducement without section numbers.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q016", "query_text": "Supreme Court criminal appeal discussing murder conviction evidence", "query_type": "metadata_sensitive", "tuning_focus": ["metadata_reranking"], "target_family": "homicide", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Court/posture metadata can help, but chunk content still matters.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q017", "query_text": "High Court petition seeking FIR quashing in commercial dispute", "query_type": "metadata_sensitive", "tuning_focus": ["metadata_reranking", "hard_negative"], "target_family": "cheating_and_fraud", "target_regime": "ipc_crpc", "difficulty": "hard", "rationale": "Requires procedural posture and offence-family distinction.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q018", "query_text": "trial court conviction appeal involving prosecutrix testimony", "query_type": "metadata_sensitive", "tuning_focus": ["metadata_reranking"], "target_family": "sexual_offences", "target_regime": "ipc_crpc", "difficulty": "medium", "rationale": "Metadata plus testimony content should distinguish candidates.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q019", "query_text": "breach of contract allegation wrongly framed as cheating", "query_type": "hard_negative", "tuning_focus": ["hard_negative", "query_expansion"], "target_family": "cheating_and_fraud", "target_regime": "ipc_crpc", "difficulty": "hard", "rationale": "Near-neighbor discrimination between civil breach and cheating.", "prior_benchmark_similarity": "none"},
    {"query_id": "dev-q020", "query_text": "culpable homicide discussion where murder conviction may be reduced", "query_type": "hard_negative", "tuning_focus": ["hard_negative", "metadata_reranking"], "target_family": "homicide", "target_regime": "ipc_crpc", "difficulty": "hard", "rationale": "Near-neighbor discrimination between murder and culpable homicide.", "prior_benchmark_similarity": "none"},
]


def build_dev_queries(chunks: list[dict[str, Any]], benchmark_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    benchmark_text = {query["query_text"].strip().lower() for query in benchmark_queries}
    by_family: dict[str, list[dict[str, Any]]] = {}
    by_regime: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        by_family.setdefault(str(chunk.get("effective_offence_family")), []).append(chunk)
        by_regime.setdefault(str(chunk.get("effective_legal_regime")), []).append(chunk)
    rows = []
    for definition in DEV_QUERY_DEFINITIONS:
        if definition["query_text"].strip().lower() in benchmark_text:
            raise ValueError(f"exact benchmark duplicate: {definition['query_id']}")
        candidates = by_family.get(definition["target_family"], []) + by_regime.get(definition["target_regime"], [])
        unique = {chunk["chunk_id"]: chunk for chunk in candidates}
        if not unique:
            raise ValueError(f"unsupported dev query: {definition['query_id']}")
        supporting = sorted(unique.values(), key=lambda chunk: chunk["chunk_id"])[:8]
        rows.append(
            {
                "development_version": DEV_VERSION,
                **definition,
                "supporting_document_ids": sorted({chunk["document_id"] for chunk in supporting}),
                "supporting_chunk_ids": [chunk["chunk_id"] for chunk in supporting[:5]],
                "human_status": "pending",
            }
        )
    validate_dev_queries(rows, chunks)
    return rows


def validate_dev_queries(rows: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    if len(rows) != 20:
        raise ValueError("dev query set must contain exactly 20 queries")
    if [row["query_id"] for row in rows] != [f"dev-q{index:03d}" for index in range(1, 21)]:
        raise ValueError("dev query IDs must be sequential")
    chunk_ids = {chunk["chunk_id"] for chunk in chunks}
    for row in rows:
        if row["prior_benchmark_similarity"] == "near_duplicate":
            raise ValueError(f"near duplicate dev query admitted: {row['query_id']}")
        if not row["supporting_document_ids"] or not row["supporting_chunk_ids"]:
            raise ValueError(f"missing support for {row['query_id']}")
        if any(chunk_id not in chunk_ids for chunk_id in row["supporting_chunk_ids"]):
            raise ValueError(f"invalid support chunk for {row['query_id']}")


def convert_judgment(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["development_version"] = DEV_VERSION
    row.pop("evaluation_version", None)
    row["human_relevance"] = "uncertain"
    row["document_relevant"] = "uncertain"
    row["human_status"] = "pending"
    return row


def convert_trace(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["development_version"] = DEV_VERSION
    row["pooling_version"] = DEV_POOL_VERSION
    row.pop("evaluation_version", None)
    return row


def write_review_doc(queries: list[dict[str, Any]], judgments: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in judgments:
        by_query.setdefault(row["query_id"], []).append(row)
    lines = [
        "# Retrieval Development Set Review Packet",
        "",
        "This packet is blinded: retriever names, ranks, and scores are stored only in the separate trace manifest.",
        "",
        f"- development version: `{DEV_VERSION}`",
        f"- pool version: `{DEV_POOL_VERSION}`",
        f"- queries: {summary['query_count']}",
        f"- pooled candidate chunks: {summary['workload']['total_pooled_chunks']}",
        "",
        "Relevance scale: 2 highly/directly relevant, 1 partially/usefully relevant, 0 not materially relevant, uncertain if insufficient evidence.",
        "",
    ]
    for query in queries:
        lines.extend([f"## {query['query_id']}: {query['query_text']}", "", f"- type: `{query['query_type']}`", f"- tuning focus: `{', '.join(query['tuning_focus'])}`", f"- target family/regime: `{query['target_family']}` / `{query['target_regime']}`", ""])
        for row in sorted(by_query[query["query_id"]], key=lambda item: item["blinded_order"]):
            court = row.get("court") or {}
            lines.extend([f"### Candidate {row['blinded_order']}: `{row['chunk_id']}`", "", f"- judgment: {row['case_title']}", f"- court: {court.get('court_name', '')}", f"- date: {row.get('decision_date') or ''}", f"- page/paragraph: {row['page_start']}-{row['page_end']} / {row['paragraph_start']}-{row['paragraph_end']}", "", row["bounded_chunk_preview"], "", "- [ ] relevance: 2 / 1 / 0 / uncertain", "- [ ] document relevant: yes / no / uncertain", "- [ ] notes:", ""])
    DEV_REVIEW_DOC.write_text("\n".join(lines), encoding="utf-8")


def write_methodology_doc(summary: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Development Set Methodology",
        "",
        "This development set is separate from the frozen 30-query benchmark and is intended only for targeted tuning experiments.",
        "",
        "## Purpose",
        "",
        "The set emphasizes legal-regime filtering/boosting, query expansion, and metadata-aware reranking, based on the frozen error analysis.",
        "",
        "## Query Design",
        "",
        "The set contains 20 corpus-supported queries: 6 legal-regime/transition, 5 composite/ambiguous, 4 query-expansion-sensitive plain-language, 3 metadata-sensitive, and 2 hard-negative queries.",
        "",
        "## Candidate Pooling",
        "",
        "Pooling uses the frozen BM25, BGE-M3 dense, Hybrid RRF, and Hybrid+BGE-reranker stack with unchanged parameters. Candidate pools are deterministic, blinded, and separate from machine traces.",
        "",
        "## Review Workload",
        "",
        f"Total candidate judgments: {summary['workload']['total_pooled_chunks']}. Mean candidates/query: {summary['workload']['mean_candidates_per_query']}.",
        "",
        "No retrieval tuning, query expansion implementation, metadata reranking implementation, RRF change, BM25 change, or answer generation is performed in this step.",
    ]
    DEV_METHODOLOGY_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_payload(args: argparse.Namespace, queries: list[dict[str, Any]], judgments: list[dict[str, Any]], traces: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "development_version": DEV_VERSION,
        "pooling_version": DEV_POOL_VERSION,
        "query_count": len(queries),
        "trusted_chunk_count": len(chunks),
        "trusted_document_count": len({chunk["document_id"] for chunk in chunks}),
        "query_distribution": dict(sorted(Counter(query["query_type"] for query in queries).items())),
        "tuning_focus_distribution": dict(sorted(Counter(focus for query in queries for focus in query["tuning_focus"]).items())),
        "family_distribution": dict(sorted(Counter(query["target_family"] for query in queries).items())),
        "regime_distribution": dict(sorted(Counter(query["target_regime"] for query in queries).items())),
        "workload": workload_summary(judgments),
        "trace_count": len(traces),
        "human_labels_assigned": 0,
        "pooling_policy": {"candidate_depth": args.candidate_depth, "primary_depth": args.primary_depth, "always_retain_top": args.always_retain_top, "max_pool_size": args.max_pool_size},
        "frozen_retrieval_config": {"dense_model": args.embedding_model, "bm25_k1": args.k1, "bm25_b": args.b, "rrf_k": args.rrf_k, "reranker_model": args.reranker_model, "candidate_depth": args.candidate_depth, "top_k": args.top_k},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = eval_parser()
    parser.description = __doc__
    parser.set_defaults(max_pool_size=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    chunks = load_chunks()
    benchmark_queries = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_eval_queries.json").read_text(encoding="utf-8"))
    queries = build_dev_queries(chunks, benchmark_queries)
    if args.dry_run:
        print(json.dumps(summary_payload(args, queries, [], [], chunks), indent=2, ensure_ascii=False))
        return 0
    service = make_service(args)
    raw_judgments, raw_traces = generate_pool(queries, RealRetriever(service), PoolingConfig(args.candidate_depth, args.primary_depth, args.always_retain_top, args.max_pool_size))
    judgments = [convert_judgment(row) for row in raw_judgments]
    traces = [convert_trace(row) for row in raw_traces]
    summary = summary_payload(args, queries, judgments, traces, chunks)
    if summary["workload"]["total_pooled_chunks"] > 600:
        raise ValueError("dev review workload exceeds cap")
    DEV_QUERIES_PATH.write_text(json.dumps(queries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_JUDGMENTS_PATH.write_text(json.dumps(judgments, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_TRACES_PATH.write_text(json.dumps(traces, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEV_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_review_doc(queries, judgments, summary)
    write_methodology_doc(summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
