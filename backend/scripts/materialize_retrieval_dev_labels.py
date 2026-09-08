"""Materialize approved human labels for the retrieval development set."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.build_retrieval_dev_set import DEV_JUDGMENTS_PATH, DEV_QUERIES_PATH, DEV_REVIEW_DOC, DEV_SUMMARY_PATH, DEV_TRACES_PATH, DEV_VERSION

SUMMARY_PATH = DEV_SUMMARY_PATH.parent / "retrieval_dev_human_label_summary.json"
LABEL_DOC = DEV_REVIEW_DOC.parent / "RETRIEVAL_DEV_HUMAN_LABELS.md"
REVIEWER = "Ananthu"
EXPECTED_COUNTS = {
    "dev-q001": 19, "dev-q002": 25, "dev-q003": 23, "dev-q004": 25, "dev-q005": 21,
    "dev-q006": 24, "dev-q007": 25, "dev-q008": 25, "dev-q009": 24, "dev-q010": 24,
    "dev-q011": 25, "dev-q012": 25, "dev-q013": 25, "dev-q014": 23, "dev-q015": 25,
    "dev-q016": 24, "dev-q017": 21, "dev-q018": 25, "dev-q019": 22, "dev-q020": 24,
}
EXPECTED_RELEVANCE = {2: 103, 1: 174, 0: 197, "uncertain": 0}

APPROVED: dict[str, dict[str, dict[Any, str]]] = {
    "dev-q001": {"relevance": {2: "4,10,11,12,13", 1: "1,2,3,5,6,8,9,16,17,18", 0: "7,14,15,19", "uncertain": ""}, "document": {"yes": "1-6,8-13,16-18", "no": "7,14,15,19", "uncertain": ""}},
    "dev-q002": {"relevance": {2: "2,18", 1: "1,3,4,5,6,7,8,9", 0: "10-17,19-25", "uncertain": ""}, "document": {"yes": "1-9,18", "no": "10-17,19-25", "uncertain": ""}},
    "dev-q003": {"relevance": {2: "5,8,11,14", 1: "1,2,3,6,10", 0: "4,7,9,12,13,15-23", "uncertain": ""}, "document": {"yes": "1-3,5,6,8,10,11,14", "no": "4,7,9,12,13,15-23", "uncertain": ""}},
    "dev-q004": {"relevance": {2: "2,3,12,25", 1: "1,14,21", 0: "4-11,13,15-20,22-24", "uncertain": ""}, "document": {"yes": "1-3,12,14,21,25", "no": "4-11,13,15-20,22-24", "uncertain": ""}},
    "dev-q005": {"relevance": {2: "7,9,12,14,18", 1: "1,2,3,4,5,6,8,11,13,15,16,17", 0: "10,19,20,21", "uncertain": ""}, "document": {"yes": "1-9,11-18", "no": "10,19-21", "uncertain": ""}},
    "dev-q006": {"relevance": {2: "", 1: "1,2,3,4,5,6,8,9,10,13", 0: "7,11,12,14-24", "uncertain": ""}, "document": {"yes": "1-6,8-10,13", "no": "7,11,12,14-24", "uncertain": ""}},
    "dev-q007": {"relevance": {2: "", 1: "1-7,9-11,13-16,18,21-25", 0: "8,12,17,19,20", "uncertain": ""}, "document": {"yes": "1,2,3,4,5,9,11,14,16,22", "no": "6-8,10,12,13,15,17-21,23-25", "uncertain": ""}},
    "dev-q008": {"relevance": {2: "2,4,5,12,20,22", 1: "1,7-11,13-18,21,23-25", 0: "3,6,19", "uncertain": ""}, "document": {"yes": "1-5,7-9,12,16-18,20,22,24,25", "no": "6,10,11,13-15,19,21,23", "uncertain": ""}},
    "dev-q009": {"relevance": {2: "1,2,23", 1: "4,5,8,9,10,11,13-18,20,22", 0: "3,6,7,12,19,21,24", "uncertain": ""}, "document": {"yes": "1-5,8-11,13-18,20,22,23", "no": "6,7,12,19,21,24", "uncertain": ""}},
    "dev-q010": {"relevance": {2: "1,2,3,4,6,9,11,14", 1: "5,8,10,12", 0: "7,13,15-24", "uncertain": ""}, "document": {"yes": "1-6,8-12,14", "no": "7,13,15-24", "uncertain": ""}},
    "dev-q011": {"relevance": {2: "2,3,4,6,15,23", 1: "1,10,12,13,14,16,25", 0: "5,7-9,11,17-22,24", "uncertain": ""}, "document": {"yes": "1-4,6,10,12-16,23,25", "no": "5,7-9,11,17-22,24", "uncertain": ""}},
    "dev-q012": {"relevance": {2: "1,2,10", 1: "3,7", 0: "4-6,8,9,11-25", "uncertain": ""}, "document": {"yes": "1-3,7,10", "no": "4-6,8,9,11-25", "uncertain": ""}},
    "dev-q013": {"relevance": {2: "2,3,5,7,9,11,12,20,21,22,24", 1: "4,8,10,13,14,15,16,17,23", 0: "1,6,18,19,25", "uncertain": ""}, "document": {"yes": "2-17,20-24", "no": "1,18,19,25", "uncertain": ""}},
    "dev-q014": {"relevance": {2: "1,2,3,6,10,13,15,19,21", 1: "4,5,7,8,11,12,16,18,22,23", 0: "9,14,17,20", "uncertain": ""}, "document": {"yes": "1-16,18-23", "no": "17", "uncertain": ""}},
    "dev-q015": {"relevance": {2: "1,2,4,12,15,25", 1: "3,5,7,10,16,18", 0: "6,8,9,11,13,14,17,19-24", "uncertain": ""}, "document": {"yes": "1-5,7-9,11,12,15,16,25", "no": "6,10,13,14,17-24", "uncertain": ""}},
    "dev-q016": {"relevance": {2: "7,8,13,15,16,19,24", 1: "3,5,6,10,11,17,18,20,21,22,23", 0: "1,2,4,9,12,14", "uncertain": ""}, "document": {"yes": "3,5,7,8,13,15,16,19,20,23,24", "no": "1,2,4,6,9-12,14,17,18,21,22", "uncertain": ""}},
    "dev-q017": {"relevance": {2: "1,2,4,6,12,16", 1: "3,7,9,13,14,17,19,21", 0: "5,8,10,11,15,18,20", "uncertain": ""}, "document": {"yes": "1-4,6,7,9,12-14,16,17,19,21", "no": "5,8,10,11,15,18,20", "uncertain": ""}},
    "dev-q018": {"relevance": {2: "3,15", 1: "6,8,11,19,21", 0: "1,2,4,5,7,9,10,12-14,16-18,20,22-25", "uncertain": ""}, "document": {"yes": "3,6,8,11,15,19,21", "no": "1,2,4,5,7,9,10,12-14,16-18,20,22-25", "uncertain": ""}},
    "dev-q019": {"relevance": {2: "2,3,4,5,6,9,17,21", 1: "1,7,8,10,11,12,13,14", 0: "15,16,18,19,20,22", "uncertain": ""}, "document": {"yes": "1-14,17,21", "no": "15,16,18-20,22", "uncertain": ""}},
    "dev-q020": {"relevance": {2: "2,6,8,11,12,18,21,23", 1: "3,4,5,7,10,24", 0: "1,9,13-17,19,20,22", "uncertain": ""}, "document": {"yes": "2-8,10-12,18,21,23,24", "no": "1,9,13-17,19,20,22", "uncertain": ""}},
}


def expand(spec: str) -> set[int]:
    values: set[int] = set()
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


def invert(section: dict[Any, str]) -> tuple[dict[int, Any], list[int]]:
    labels: dict[int, Any] = {}
    duplicates: list[int] = []
    for label, spec in section.items():
        for number in expand(spec):
            if number in labels:
                duplicates.append(number)
            labels[number] = label
    return labels, duplicates


def parse_review_packet() -> dict[tuple[str, int], str]:
    query_id = ""
    mapping: dict[tuple[str, int], str] = {}
    query_re = re.compile(r"^## (dev-q\d{3}): ")
    candidate_re = re.compile(r"^### Candidate (\d+): `([^`]+)`")
    for line in DEV_REVIEW_DOC.read_text(encoding="utf-8").splitlines():
        query_match = query_re.match(line)
        if query_match:
            query_id = query_match.group(1)
            continue
        candidate_match = candidate_re.match(line)
        if candidate_match:
            key = (query_id, int(candidate_match.group(1)))
            if key in mapping:
                raise ValueError(f"duplicate review packet candidate: {key}")
            mapping[key] = candidate_match.group(2)
    return mapping


def build_assignments(judgments: list[dict[str, Any]], packet: dict[tuple[str, int], str]) -> dict[tuple[str, int], tuple[int | str, str]]:
    rows_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in judgments:
        rows_by_query[row["query_id"]].append(row)
        number = int(row["blinded_order"])
        if packet.get((row["query_id"], number)) != row["chunk_id"]:
            raise ValueError(f"packet mismatch for {row['query_id']} candidate {number}")
    missing: list[str] = []
    duplicated: list[str] = []
    assignments: dict[tuple[str, int], tuple[int | str, str]] = {}
    for query_id, expected_count in EXPECTED_COUNTS.items():
        expected = set(range(1, expected_count + 1))
        actual = {int(row["blinded_order"]) for row in rows_by_query[query_id]}
        if actual != expected:
            missing.extend(f"{query_id}:candidate:{number}:missing_from_manifest" for number in sorted(expected - actual))
            missing.extend(f"{query_id}:candidate:{number}:unexpected_manifest_candidate" for number in sorted(actual - expected))
        relevance, relevance_dupes = invert(APPROVED[query_id]["relevance"])
        document, document_dupes = invert(APPROVED[query_id]["document"])
        missing.extend(f"{query_id}:candidate:{number}:missing_relevance" for number in sorted(expected - set(relevance)))
        missing.extend(f"{query_id}:candidate:{number}:missing_document_relevance" for number in sorted(expected - set(document)))
        missing.extend(f"{query_id}:candidate:{number}:unexpected_label_candidate" for number in sorted((set(relevance) | set(document)) - expected))
        duplicated.extend(f"{query_id}:candidate:{number}:duplicate_relevance" for number in relevance_dupes)
        duplicated.extend(f"{query_id}:candidate:{number}:duplicate_document_relevance" for number in document_dupes)
        for number in expected:
            if number in relevance and number in document:
                assignments[(query_id, number)] = (relevance[number], document[number])
    counts = Counter(relevance for relevance, _ in assignments.values())
    normalized_counts = {label: counts[label] for label in EXPECTED_RELEVANCE}
    if len(assignments) != 474 or normalized_counts != EXPECTED_RELEVANCE or missing or duplicated:
        raise ValueError(f"coverage failed assignments={len(assignments)} counts={normalized_counts} missing={missing} duplicated={duplicated}")
    return assignments


def materialize(judgments: list[dict[str, Any]], assignments: dict[tuple[str, int], tuple[int | str, str]], reviewed_at: str) -> list[dict[str, Any]]:
    labelled = []
    seen: set[tuple[str, str]] = set()
    for row in judgments:
        key = (row["query_id"], row["chunk_id"])
        if key in seen:
            raise ValueError(f"duplicate judgment key: {key}")
        seen.add(key)
        relevance, document_relevant = assignments[(row["query_id"], int(row["blinded_order"]))]
        updated = dict(row)
        updated.update({"human_relevance": relevance, "document_relevant": document_relevant, "reviewer": REVIEWER, "reviewed_at": reviewed_at, "human_status": "reviewed"})
        labelled.append(updated)
    return labelled


def summary_payload(queries: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> dict[str, Any]:
    qtype = {query["query_id"]: query["query_type"] for query in queries}
    focus = {query["query_id"]: query["tuning_focus"] for query in queries}
    relevance = Counter(row["human_relevance"] for row in judgments)
    document = Counter(row["document_relevant"] for row in judgments)
    per_query = {}
    per_type: dict[str, Counter[Any]] = defaultdict(Counter)
    per_focus: dict[str, Counter[Any]] = defaultdict(Counter)
    for row in judgments:
        per_query.setdefault(row["query_id"], {"total": 0, "reviewed": 0, "pending": 0, "relevance": Counter(), "document_relevance": Counter()})
        bucket = per_query[row["query_id"]]
        bucket["total"] += 1
        bucket[row["human_status"]] += 1
        bucket["relevance"][row["human_relevance"]] += 1
        bucket["document_relevance"][row["document_relevant"]] += 1
        per_type[qtype[row["query_id"]]][row["human_relevance"]] += 1
        for item in focus[row["query_id"]]:
            per_focus[item][row["human_relevance"]] += 1
    return {
        "development_version": DEV_VERSION,
        "query_count": len(queries),
        "judgment_count": len(judgments),
        "reviewed": sum(row["human_status"] == "reviewed" for row in judgments),
        "pending": sum(row["human_status"] == "pending" for row in judgments),
        "human_relevance_counts": {"grade_2": relevance[2], "grade_1": relevance[1], "grade_0": relevance[0], "uncertain": relevance["uncertain"]},
        "document_relevance_counts": {"yes": document["yes"], "no": document["no"], "uncertain": document["uncertain"]},
        "per_query_counts": {query_id: compact_counts(counts) for query_id, counts in sorted(per_query.items())},
        "per_query_type_counts": {name: label_counts(counts) for name, counts in sorted(per_type.items())},
        "per_tuning_focus_counts": {name: label_counts(counts) for name, counts in sorted(per_focus.items())},
        "reviewer_counts": dict(Counter(row["reviewer"] for row in judgments)),
        "metric_status": "not_calculated_in_dev_label_materialization_step",
    }


def label_counts(counts: Counter[Any]) -> dict[str, int]:
    return {"grade_2": counts[2], "grade_1": counts[1], "grade_0": counts[0], "uncertain": counts["uncertain"]}


def compact_counts(counts: dict[str, Any]) -> dict[str, Any]:
    return {"total": counts["total"], "reviewed": counts["reviewed"], "pending": counts["pending"], "human_relevance": label_counts(counts["relevance"]), "document_relevance": {"yes": counts["document_relevance"]["yes"], "no": counts["document_relevance"]["no"], "uncertain": counts["document_relevance"]["uncertain"]}}


def write_doc(summary: dict[str, Any]) -> None:
    rel = summary["human_relevance_counts"]
    doc = summary["document_relevance_counts"]
    lines = [
        "# Retrieval Development Set Human Labels",
        "",
        f"- development version: `{DEV_VERSION}`",
        f"- queries: {summary['query_count']}",
        f"- candidate judgments: {summary['judgment_count']}",
        f"- reviewed: {summary['reviewed']}",
        f"- pending: {summary['pending']}",
        f"- reviewer: {REVIEWER}",
        "",
        "## Relevance Policy",
        "",
        "- 2 = highly/directly relevant",
        "- 1 = partially/usefully relevant",
        "- 0 = not materially relevant",
        "- uncertain = insufficient evidence",
        "",
        f"Counts: grade 2 = {rel['grade_2']}, grade 1 = {rel['grade_1']}, grade 0 = {rel['grade_0']}, uncertain = {rel['uncertain']}.",
        "",
        "## Document Relevance",
        "",
        f"Document relevance counts: yes = {doc['yes']}, no = {doc['no']}, uncertain = {doc['uncertain']}.",
        "",
        "## Future Metric Interpretation",
        "",
        "Broad relevance treats grade 1 or grade 2 as relevant. Strict sensitivity treats grade 2 only as relevant.",
        "",
        "## Development-Set Status",
        "",
        "THIS IS A TUNING / DEVELOPMENT SET. It may be inspected and reused during tuning. It must not replace the frozen 30-query benchmark as the unbiased baseline reference.",
        "",
        "## Edge Cases",
        "",
        "- dev-q006 grade-2 count = 0",
        "- dev-q007 grade-2 count = 0",
        "- dev-q012 preserves robbery-vs-theft discrimination",
        "- dev-q016 preserves court metadata sensitivity",
        "",
        "No dev performance metrics are reported here.",
    ]
    LABEL_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    queries = json.loads(DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(DEV_JUDGMENTS_PATH.read_text(encoding="utf-8"))
    traces_before = DEV_TRACES_PATH.read_text(encoding="utf-8")
    packet = parse_review_packet()
    assignments = build_assignments(judgments, packet)
    labelled = materialize(judgments, assignments, datetime.now(UTC).isoformat())
    summary = summary_payload(queries, labelled)
    if summary["reviewed"] != 474 or summary["pending"] != 0:
        raise ValueError("dev labels incomplete")
    DEV_JUDGMENTS_PATH.write_text(json.dumps(labelled, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_doc(summary)
    if DEV_TRACES_PATH.read_text(encoding="utf-8") != traces_before:
        raise ValueError("dev trace mutated")
    print(json.dumps({"reviewed": summary["reviewed"], "pending": summary["pending"], "human_relevance_counts": summary["human_relevance_counts"], "document_relevance_counts": summary["document_relevance_counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
