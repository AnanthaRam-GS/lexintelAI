"""Materialize approved human retrieval relevance labels."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app.services.retrieval.evaluation import EVALUATION_VERSION, validate_judgment
from backend.scripts.build_retrieval_eval_set import JUDGMENTS_PATH, METHODOLOGY_DOC, QUERIES_PATH, REVIEW_DOC, SUMMARY_PATH, TRACES_PATH
from backend.scripts.build_vector_index import load_chunks

HUMAN_LABEL_SUMMARY_PATH = SUMMARY_PATH.parent / "retrieval_eval_human_label_summary.json"
HUMAN_LABEL_DOC = METHODOLOGY_DOC.parent / "RETRIEVAL_EVALUATION_HUMAN_LABELS.md"

REVIEWER = "Ananthu"
EXPECTED_QUERIES = 30
EXPECTED_JUDGMENTS = 695

APPROVED_LABELS: dict[str, dict[str, Any]] = {
    "eval-q001": {"relevance": {2: "1,2,4,5,6,9,10,13,14,15,16,19,20,24", 1: "3,7,8,11,12,17,18,21,22,23,25", 0: "", "uncertain": ""}, "document": {"yes": "1-25", "no": "", "uncertain": ""}},
    "eval-q002": {"relevance": {2: "1-15,19", 1: "17,18", 0: "16", "uncertain": ""}, "document": {"yes": "1-15,17-19", "no": "16", "uncertain": ""}},
    "eval-q003": {"relevance": {2: "2,3,4,7,8,9,10,13,14", 1: "1,5,6,12,15,16,18", 0: "11,17,19", "uncertain": ""}, "document": {"yes": "1-16,18", "no": "17,19", "uncertain": ""}},
    "eval-q004": {"relevance": {2: "1,2,3,4,5,7,10", 1: "6,21,22", 0: "8,9,11-20,23-25", "uncertain": ""}, "document": {"yes": "1-5,7,10", "no": "6,8,9,11-25", "uncertain": ""}},
    "eval-q005": {"relevance": {2: "2,3,4,5,7,12,15,18,24", 1: "1,8,10,11,17,20,22,23,25", 0: "6,9,13,14,16,19,21", "uncertain": ""}, "document": {"yes": "1-5,7,8,10-12,15,17-20,22-25", "no": "6,9,13,14,16,21", "uncertain": ""}},
    "eval-q006": {"relevance": {2: "1,2,3,4,5,7,10,11,12,13", 1: "8,14,17,19", 0: "6,9,15,16,18", "uncertain": ""}, "document": {"yes": "1-8,10-13,15,16,19", "no": "9,17,18", "uncertain": "14"}},
    "eval-q007": {"relevance": {2: "1,4,5,6,8,12", 1: "2,9,11,13,14,15,17,18,19,21", 0: "3,7,10,16,20", "uncertain": ""}, "document": {"yes": "1-21", "no": "", "uncertain": ""}},
    "eval-q008": {"relevance": {2: "1,3,5,6,7,10,11,12,15,17,23", 1: "2,4,8,9,16,21", 0: "13,14,18,19,20,22", "uncertain": ""}, "document": {"yes": "1-17,21,23", "no": "18,19,20,22", "uncertain": ""}},
    "eval-q009": {"relevance": {2: "4", 1: "2,3,5,7,11,12,13,18", 0: "1,6,8,9,10,14,15,16,17,19,20,21,23", "uncertain": "22"}, "document": {"yes": "4", "no": "1-3,5-12,14-17,19-21,23", "uncertain": "13,18,22"}},
    "eval-q010": {"relevance": {2: "1,3,4,5,6,8,13,18,21", 1: "2,7,9,11,12,22", 0: "14,15,16,17,19,23", "uncertain": "10,20"}, "document": {"yes": "1-13,18,20-22", "no": "14-17,19,23", "uncertain": ""}},
    "eval-q011": {"relevance": {2: "2,3,5,7,8,10,14,19,23", 1: "4,6,9,12,18,21", 0: "1,11,13,15,16,17,20,22", "uncertain": ""}, "document": {"yes": "1-10,12,14,19,23", "no": "11,13,15-18,20-22", "uncertain": ""}},
    "eval-q012": {"relevance": {2: "1-13,15,17-19", 1: "14,16", 0: "", "uncertain": ""}, "document": {"yes": "1-19", "no": "", "uncertain": ""}},
    "eval-q013": {"relevance": {2: "1,2,3,5,6,7,8,9,10,15,17,18,19", 1: "12,13,14,21,23", 0: "4,11,16,20,22,24", "uncertain": ""}, "document": {"yes": "1-3,5-10,13,15,17-19", "no": "4,11,12,14,16,20-24", "uncertain": ""}},
    "eval-q014": {"relevance": {2: "1,2,4,5,6,9,12,14,15,16,21", 1: "7,8,10,11,13,17,20,22,23", 0: "3,18,19,24", "uncertain": ""}, "document": {"yes": "1-17,20-23", "no": "18,19,24", "uncertain": ""}},
    "eval-q015": {"relevance": {2: "4,5,6,8,13,14,16,23,24", 1: "2,3,9,11,18", 0: "1,7,10,12,15,17,19,20,21,22,25", "uncertain": ""}, "document": {"yes": "2-6,8,9,11,13,14,16,18,23,24", "no": "1,7,10,12,15,17,19-22,25", "uncertain": ""}},
    "eval-q016": {"relevance": {2: "6,11", 1: "1,3,20", 0: "2,4,5,7-10,12-19,21-25", "uncertain": ""}, "document": {"yes": "6,11", "no": "2-5,7-10,12-19,21-25", "uncertain": "1,20"}},
    "eval-q017": {"relevance": {2: "1,4,6,15", 1: "2,5,7-11,14,23,25", 0: "3,12,13,16-22,24", "uncertain": ""}, "document": {"yes": "1,2,4-11,13-19,21,23-25", "no": "3,12,20,22", "uncertain": ""}},
    "eval-q018": {"relevance": {2: "1,2,4,5,6,9,11,13,24", 1: "7,8,10,16,17,19,21,22,23", 0: "3,12,14,15,18,20,25", "uncertain": ""}, "document": {"yes": "1,2,4-11,13,16,17,19,21-24", "no": "3,12,14,15,18,20,25", "uncertain": ""}},
    "eval-q019": {"relevance": {2: "1-8,11,13,15", 1: "12,17,18", 0: "9,10,14,16,19", "uncertain": ""}, "document": {"yes": "1-8,11-13,15,17,18", "no": "9,10,14,16,19", "uncertain": ""}},
    "eval-q020": {"relevance": {2: "1,2,3,4,6,7,11,12,18,19,21,22,23,25", 1: "5,8,9,10,13,15,17", 0: "14,16,20,24", "uncertain": ""}, "document": {"yes": "1-13,15,17-19,21-23,25", "no": "14,16,20,24", "uncertain": ""}},
    "eval-q021": {"relevance": {2: "1,4", 1: "2,5,7,14,15,17,18,19,22,23,24,25", 0: "3,6,8-13,16,20,21", "uncertain": ""}, "document": {"yes": "1,2,4,5,7,14,15,17-19,22-25", "no": "3,6,8-13,16,20,21", "uncertain": ""}},
    "eval-q022": {"relevance": {2: "1,2,3,4,7,9,10,12,17,19,25", 1: "5,6,8,11,21,23", 0: "13-16,18,20,22,24", "uncertain": ""}, "document": {"yes": "1-4,6-12,17,19,21,23,25", "no": "5,13-16,18,20,22,24", "uncertain": ""}},
    "eval-q023": {"relevance": {2: "1,2,6,7,10,13,15,16,19,23,24,25", 1: "3,4,5,9,11,12,14,17,20,21,22", 0: "8,18", "uncertain": ""}, "document": {"yes": "1-7,9-17,19-25", "no": "8,18", "uncertain": ""}},
    "eval-q024": {"relevance": {2: "", 1: "2,3,4,5,7,8,11,13,15,18,20,21,22", 0: "1,6,9,10,12,14,16,17,19,23,24,25", "uncertain": ""}, "document": {"yes": "2-5,7,8,11,13,15,18,20-22", "no": "1,6,9,10,12,14,16,17,19,23-25", "uncertain": ""}},
    "eval-q025": {"relevance": {2: "2,3,4,7,9,17", 1: "1,5,6,8,10-13,15,16,18,20", 0: "14,19,21", "uncertain": ""}, "document": {"yes": "1-13,15-18,20", "no": "14,19,21", "uncertain": ""}},
    "eval-q026": {"relevance": {2: "1,2,4,5,6", 1: "3,7,8,9,11,12,15,16,17,19,21", 0: "10,13,14,18,20,22", "uncertain": ""}, "document": {"yes": "1,2,4,5,6,9,15,16,17,19", "no": "3,7,8,10-14,18,20-22", "uncertain": ""}},
    "eval-q027": {"relevance": {2: "2,22,25", 1: "24", 0: "1,3-21,23", "uncertain": ""}, "document": {"yes": "2,22,24,25", "no": "1,3-21,23", "uncertain": ""}},
    "eval-q028": {"relevance": {2: "", 1: "1,2,3,4,5,7,8,10,12,13,14,18,19,21,22,23", 0: "6,9,11,15,16,17,20,24,25", "uncertain": ""}, "document_titles_yes": ["Surendra Koli vs C.B.I.", "The State Of Jharkhand vs Mathura Yadav", "Manoj Pratap Singh vs The State Of Rajasthan", "Sarvan vs The State"]},
    "eval-q029": {"relevance": {2: "2,3,8,14,15,17,24,25", 1: "1,5,6,7,9,11,12,19,20,22", 0: "4,10,13,16,18,21,23", "uncertain": ""}, "document_titles_yes": ["Rinku @ Prempal vs State Of U.P.", "Manoj Pratap Singh vs The State Of Rajasthan", "Surendra Koli vs C.B.I."]},
    "eval-q030": {"relevance": {2: "1,3,4,5,6,9,10,13,15,16,17,20,21", 1: "2,8,12,14,19", 0: "7,11,18", "uncertain": ""}, "document": {"yes": "1-10,12-16,19-21", "no": "11,17,18", "uncertain": ""}},
}


def expand_numbers(spec: str) -> set[int]:
    values: set[int] = set()
    if not spec:
        return values
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(value) for value in part.split("-", 1)]
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    return values


def parse_review_packet(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    query_id = ""
    candidates: dict[tuple[str, int], dict[str, str]] = {}
    current_key: tuple[str, int] | None = None
    query_re = re.compile(r"^## (eval-q\d{3}): ")
    candidate_re = re.compile(r"^### Candidate (\d+): `([^`]+)`")
    judgment_re = re.compile(r"^- judgment: (.+)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        query_match = query_re.match(line)
        if query_match:
            query_id = query_match.group(1)
            current_key = None
            continue
        candidate_match = candidate_re.match(line)
        if candidate_match:
            if not query_id:
                raise ValueError("candidate heading appeared before query heading")
            number = int(candidate_match.group(1))
            current_key = (query_id, number)
            if current_key in candidates:
                raise ValueError(f"duplicate review packet candidate: {current_key}")
            candidates[current_key] = {"chunk_id": candidate_match.group(2), "case_title": ""}
            continue
        judgment_match = judgment_re.match(line)
        if judgment_match and current_key:
            candidates[current_key]["case_title"] = judgment_match.group(1)
    return candidates


def invert_section(section: dict[Any, str]) -> tuple[dict[int, Any], list[int]]:
    assigned: dict[int, Any] = {}
    duplicates: list[int] = []
    for label, spec in section.items():
        for number in expand_numbers(spec):
            if number in assigned:
                duplicates.append(number)
            assigned[number] = label
    return assigned, duplicates


def normalize_title(title: str) -> str:
    return re.sub(r"\s+on\s+\d{1,2}\s+\w+,\s+\d{4}$", "", title, flags=re.IGNORECASE).strip().lower()


def document_labels_from_titles(query_id: str, rows: list[dict[str, Any]], approved: dict[str, Any]) -> dict[int, str]:
    targets = {normalize_title(title) for title in approved["document_titles_yes"]}
    labels: dict[int, str] = {}
    matches: set[str] = set()
    for row in rows:
        number = int(row["blinded_order"])
        normalized = normalize_title(row["case_title"])
        if normalized in targets:
            labels[number] = "yes"
            matches.add(normalized)
        else:
            labels[number] = "no"
    missing = targets - matches
    if missing:
        raise ValueError(f"{query_id} title-based document relevance targets not found: {sorted(missing)}")
    return labels


def build_assignments(judgments: list[dict[str, Any]], review_candidates: dict[tuple[str, int], dict[str, str]]) -> dict[tuple[str, int], tuple[int | str, str]]:
    rows_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in judgments:
        rows_by_query[row["query_id"]].append(row)
        number = int(row["blinded_order"])
        packet = review_candidates.get((row["query_id"], number))
        if not packet or packet["chunk_id"] != row["chunk_id"]:
            raise ValueError(f"review packet mismatch for {row['query_id']} candidate {number}")
    assignments: dict[tuple[str, int], tuple[int | str, str]] = {}
    missing: list[str] = []
    duplicated: list[str] = []
    for query_id, approved in APPROVED_LABELS.items():
        query_rows = sorted(rows_by_query.get(query_id, []), key=lambda item: item["blinded_order"])
        expected_numbers = {int(row["blinded_order"]) for row in query_rows}
        relevance, relevance_dupes = invert_section(approved["relevance"])
        if "document" in approved:
            document, document_dupes = invert_section(approved["document"])
        else:
            document = document_labels_from_titles(query_id, query_rows, approved)
            document_dupes = []
        for number in sorted(expected_numbers - set(relevance)):
            missing.append(f"{query_id}:candidate:{number}:human_relevance")
        for number in sorted(expected_numbers - set(document)):
            missing.append(f"{query_id}:candidate:{number}:document_relevant")
        for number in sorted(set(relevance) - expected_numbers):
            missing.append(f"{query_id}:candidate:{number}:not_in_pool")
        for number in relevance_dupes:
            duplicated.append(f"{query_id}:candidate:{number}:human_relevance")
        for number in document_dupes:
            duplicated.append(f"{query_id}:candidate:{number}:document_relevant")
        for number in expected_numbers:
            if number in relevance and number in document:
                assignments[(query_id, number)] = (relevance[number], document[number])
    if len(assignments) != EXPECTED_JUDGMENTS or missing or duplicated:
        raise ValueError(f"coverage failed assignments={len(assignments)} missing={missing} duplicated={duplicated}")
    return assignments


def apply_labels(judgments: list[dict[str, Any]], assignments: dict[tuple[str, int], tuple[int | str, str]], reviewed_at: str) -> list[dict[str, Any]]:
    labelled: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in judgments:
        key = (row["query_id"], row["chunk_id"])
        if key in seen:
            raise ValueError(f"duplicate judgment key: {key}")
        seen.add(key)
        relevance, document_relevant = assignments[(row["query_id"], int(row["blinded_order"]))]
        updated = dict(row)
        updated.update(
            {
                "human_relevance": relevance,
                "document_relevant": document_relevant,
                "reviewer": REVIEWER,
                "reviewed_at": reviewed_at,
                "human_status": "reviewed",
            }
        )
        validate_judgment(updated)
        labelled.append(updated)
    return labelled


def summary_payload(queries: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> dict[str, Any]:
    query_types = {query["query_id"]: query["query_type"] for query in queries}
    relevance_counts = Counter(row["human_relevance"] for row in judgments)
    document_counts = Counter(row["document_relevant"] for row in judgments)
    per_query: dict[str, dict[str, Any]] = {}
    per_query_type: dict[str, Counter[Any]] = defaultdict(Counter)
    for row in judgments:
        query_id = row["query_id"]
        per_query.setdefault(query_id, {"total": 0, "reviewed": 0, "pending": 0, "relevance": Counter(), "document_relevance": Counter()})
        per_query[query_id]["total"] += 1
        per_query[query_id][row["human_status"]] += 1
        per_query[query_id]["relevance"][row["human_relevance"]] += 1
        per_query[query_id]["document_relevance"][row["document_relevant"]] += 1
        per_query_type[query_types[query_id]][row["human_relevance"]] += 1
    return {
        "evaluation_version": EVALUATION_VERSION,
        "query_count": len(queries),
        "judgment_count": len(judgments),
        "reviewed": sum(1 for row in judgments if row["human_status"] == "reviewed"),
        "pending": sum(1 for row in judgments if row["human_status"] == "pending"),
        "relevance_counts": {"2": relevance_counts[2], "1": relevance_counts[1], "0": relevance_counts[0], "uncertain": relevance_counts["uncertain"]},
        "document_relevance_counts": {"yes": document_counts["yes"], "no": document_counts["no"], "uncertain": document_counts["uncertain"]},
        "per_query_counts": {
            query_id: {
                "total": counts["total"],
                "reviewed": counts["reviewed"],
                "pending": counts["pending"],
                "relevance": {"2": counts["relevance"][2], "1": counts["relevance"][1], "0": counts["relevance"][0], "uncertain": counts["relevance"]["uncertain"]},
                "document_relevance": {"yes": counts["document_relevance"]["yes"], "no": counts["document_relevance"]["no"], "uncertain": counts["document_relevance"]["uncertain"]},
            }
            for query_id, counts in sorted(per_query.items())
        },
        "per_query_type_counts": {
            query_type: {"2": counts[2], "1": counts[1], "0": counts[0], "uncertain": counts["uncertain"]}
            for query_type, counts in sorted(per_query_type.items())
        },
        "reviewer_counts": dict(Counter(row["reviewer"] for row in judgments)),
        "metric_status": "not_calculated_in_label_materialization_step",
    }


def write_human_label_doc(summary: dict[str, Any]) -> None:
    relevance = summary["relevance_counts"]
    document = summary["document_relevance_counts"]
    lines = [
        "# Retrieval Evaluation Human Labels",
        "",
        f"- evaluation version: `{summary['evaluation_version']}`",
        f"- queries: {summary['query_count']}",
        f"- candidate judgments: {summary['judgment_count']}",
        f"- reviewed: {summary['reviewed']}",
        f"- pending: {summary['pending']}",
        f"- reviewer: {REVIEWER}",
        "",
        "## Relevance Semantics",
        "",
        "- 2: highly/directly relevant",
        "- 1: partially/usefully relevant",
        "- 0: not materially relevant",
        "- uncertain: insufficient evidence",
        "",
        f"Counts: grade 2 = {relevance['2']}, grade 1 = {relevance['1']}, grade 0 = {relevance['0']}, uncertain = {relevance['uncertain']}.",
        "",
        "## Document Relevance",
        "",
        "Document relevance is recorded separately as yes, no, or uncertain.",
        "",
        f"Counts: yes = {document['yes']}, no = {document['no']}, uncertain = {document['uncertain']}.",
        "",
        "## Future Metric Policy",
        "",
        "Broad relevance treats grade 1 or grade 2 as relevant. Strict relevance treats grade 2 only as relevant. Uncertain labels are excluded from binary relevance denominators unless a later methodology explicitly states otherwise.",
        "",
        "## Freeze And Blinding",
        "",
        "The review packet remained blinded from retriever ranks and scores. Machine retrieval traces remain separate from the human judgment manifest. The frozen retrieval configuration remains BAAI/bge-m3 dense retrieval, BM25 k1=1.5 b=0.75, hybrid RRF K=60, and BAAI/bge-reranker-v2-m3 reranking.",
        "",
        "## Benchmark Edge Cases",
        "",
        "- right document / wrong chunk",
        "- wrong document / relevant chunk",
        "- sparse transition pools",
        "- q024 has no grade-2 result",
        "- q028 has no grade-2 result",
        "",
        "Retrieval-system performance metrics are not reported in this document.",
    ]
    HUMAN_LABEL_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_freezes(queries: list[dict[str, Any]], traces: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    if len(queries) != EXPECTED_QUERIES:
        raise ValueError("query manifest must contain 30 queries")
    if len(traces) != EXPECTED_JUDGMENTS:
        raise ValueError("trace manifest must contain 695 rows")
    frozen = summary["frozen_retrieval_config"]
    expected = {"dense_model": "BAAI/bge-m3", "bm25_k1": 1.5, "bm25_b": 0.75, "rrf_k": 60, "reranker_model": "BAAI/bge-reranker-v2-m3"}
    for key, value in expected.items():
        if frozen.get(key) != value:
            raise ValueError(f"retrieval config mutated: {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-at", default="")
    args = parser.parse_args(argv)
    reviewed_at = args.reviewed_at or datetime.now(UTC).isoformat()
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
    retrieval_summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    validate_freezes(queries, traces, retrieval_summary)
    chunk_ids = {chunk["chunk_id"] for chunk in load_chunks()}
    if len(judgments) != EXPECTED_JUDGMENTS or not all(row["chunk_id"] in chunk_ids for row in judgments):
        raise ValueError("judgment manifest count or chunk IDs are invalid")
    review_candidates = parse_review_packet(REVIEW_DOC)
    assignments = build_assignments(judgments, review_candidates)
    labelled = apply_labels(judgments, assignments, reviewed_at)
    summary = summary_payload(queries, labelled)
    if summary["reviewed"] != EXPECTED_JUDGMENTS or summary["pending"] != 0:
        raise ValueError("human labels are incomplete after materialization")
    JUDGMENTS_PATH.write_text(json.dumps(labelled, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    HUMAN_LABEL_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_human_label_doc(summary)
    print(json.dumps({"reviewed": summary["reviewed"], "pending": summary["pending"], "relevance_counts": summary["relevance_counts"], "document_relevance_counts": summary["document_relevance_counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
