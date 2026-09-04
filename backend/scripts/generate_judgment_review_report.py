"""Generate a deterministic human review report for development judgments."""

from __future__ import annotations

import argparse
from collections import Counter
import html
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import load_manifest  # noqa: E402
from backend.scripts.pdf_text_extraction import extract_pdf_text  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
JUDGMENT_MANIFEST = MANIFEST_DIR / "development_judgments.json"
REVIEW_MANIFEST = MANIFEST_DIR / "development_judgment_review.json"
REPORT_PATH = REPO_ROOT / "docs/DEVELOPMENT_CORPUS_REVIEW.md"
BALANCED_JUDGMENT_MANIFEST = MANIFEST_DIR / "balanced_development_judgments.json"
BALANCED_REVIEW_MANIFEST = MANIFEST_DIR / "balanced_development_review.json"
BALANCED_AUDIT_MANIFEST = MANIFEST_DIR / "balanced_candidate_audit.json"
BALANCED_REPORT_PATH = REPO_ROOT / "docs/BALANCED_DEVELOPMENT_CORPUS_REVIEW.md"
BALANCED_COMPOSITION_PATH = REPO_ROOT / "docs/BALANCED_DEVELOPMENT_CORPUS.md"
PREVIEW_LIMIT = 1500
PDF_PREVIEW_LIMIT = 3000
BALANCED_FAMILY_QUOTAS = {
    "homicide": 4,
    "hurt_and_assault": 3,
    "theft_and_robbery": 3,
    "cheating_and_fraud": 3,
    "criminal_breach_of_trust": 2,
    "kidnapping": 2,
    "sexual_offences": 3,
    "dowry_and_domestic_cruelty": 3,
    "conspiracy_common_intention": 3,
    "narcotics_related": 2,
    "other": 2,
}


def clean_text_preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def preview_for(record: dict[str, Any], repo_root: Path = REPO_ROOT) -> tuple[str, bool, list[str]]:
    raw_file_path = record.get("raw_file_path")
    if not raw_file_path:
        return "Preview unavailable because no local raw path is recorded.", False, ["* Preview source: unavailable"]

    raw_path = repo_root / str(raw_file_path)
    if not raw_path.exists():
        return "Preview unavailable because the local raw file is missing.", False, ["* Preview source: unavailable"]

    mime_type = str(record.get("mime_type") or "").lower()
    suffix = raw_path.suffix.lower()
    if mime_type == "application/pdf" or suffix == ".pdf":
        extraction = extract_pdf_text(raw_path)
        provenance = [
            "* Preview source: PDF native text",
            f"* PDF pages: {extraction.page_count}",
            f"* Pages containing extractable text: {extraction.pages_with_text}",
            f"* Pages without extractable text: {extraction.pages_without_text}",
            f"* PDF extraction status: {extraction.extraction_status}",
        ]
        if extraction.extraction_status == "failed" and extraction.error:
            provenance.append(f"* PDF extraction error: {extraction.error}")
        if extraction.text:
            return extraction.text[:PDF_PREVIEW_LIMIT].rstrip(), extraction.extraction_status in {"usable", "sparse"}, provenance
        return "Preview unavailable because the PDF has no native extractable text. OCR may be required later.", False, provenance

    if mime_type.startswith("text/") or suffix in {".html", ".htm", ".txt", ".json"}:
        text = raw_path.read_text(encoding="utf-8", errors="ignore")
        preview = clean_text_preview(text)
        if preview:
            return preview, True, ["* Preview source: local text/HTML"]
        return "Preview unavailable because no readable text was found.", False, ["* Preview source: local text/HTML"]

    return "Preview unavailable for this raw file type.", False, ["* Preview source: unavailable"]


def review_records_by_source_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record.get("source_document_id")): record for record in records}


def reviewable_records(
    judgment_records: list[dict[str, Any]],
    review_records: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    reviews = review_records_by_source_id(review_records)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for judgment in judgment_records:
        if judgment.get("status") == "excluded_duplicate":
            continue
        review = reviews.get(str(judgment.get("source_document_id")))
        if review is not None:
            pairs.append((judgment, review))
    return pairs


def field(value: Any) -> str:
    if value is None or value == "":
        return ""
    return str(value)


def year_from_title(value: Any) -> int | None:
    if not value:
        return None
    matches = re.findall(r"\bon\s+\d{1,2}\s+[A-Za-z]+,?\s+(\d{4})\b", str(value), flags=re.IGNORECASE)
    if matches:
        return int(matches[-1])
    return None


def metadata_warnings(record: dict[str, Any], provenance: list[str]) -> list[str]:
    warnings: list[str] = []
    case_name = field(record.get("case_name"))
    if not record.get("case_number"):
        warnings.append("missing case number")
    if re.fullmatch(r"[A-Za-z.]+/?\d+/\d+(?:\s+on\s+.+)?", case_name):
        warnings.append("generic case-title format")
    if "daily orders" in field(record.get("court_name")).lower():
        warnings.append("daily-order source")
    title_year = year_from_title(case_name)
    if title_year is not None and record.get("year") not in {title_year, str(title_year)}:
        warnings.append(f"title year {title_year} differs from recorded year {record.get('year')}")
    if any(line.endswith("sparse") for line in provenance):
        warnings.append("sparse PDF/text extraction")
    if any(line.endswith("empty") for line in provenance):
        warnings.append("textless PDF; OCR may be required later")
    if any(line.endswith("failed") for line in provenance):
        warnings.append("PDF text extraction failed")
    return warnings


def generate_report(
    judgment_manifest: Path = JUDGMENT_MANIFEST,
    review_manifest: Path = REVIEW_MANIFEST,
    report_path: Path = REPORT_PATH,
    repo_root: Path = REPO_ROOT,
    title: str = "LegalAI Development Judgment Corpus Review",
) -> tuple[int, int, int]:
    judgments = load_manifest(judgment_manifest)
    reviews = load_manifest(review_manifest)
    pairs = reviewable_records(judgments, reviews)
    available_count = 0
    unavailable_count = 0

    lines: list[str] = [
        f"# {title}",
        "",
        "This report is a deterministic aid for human reviewers. It does not accept,",
        "reject, classify, summarize, or infer legal meaning for any candidate.",
        "",
        "Acquisition status describes automated selection/acquisition behavior.",
        "Human review status determines suitability for the LegalAI development corpus.",
        "These are independent concepts; a human reviewer may accept, reject, or",
        "reclassify a candidate after inspecting the source material.",
        "",
    ]

    for judgment, review in pairs:
        preview, available, provenance = preview_for(judgment, repo_root=repo_root)
        warnings = metadata_warnings(judgment, provenance)
        if available:
            available_count += 1
        else:
            unavailable_count += 1

        lines.extend(
            [
                f"## {field(judgment.get('local_id'))} — {field(judgment.get('case_name'))}",
                "",
                "### Acquisition Record",
                "",
                f"* Source document ID: {field(judgment.get('source_document_id'))}",
                f"* Source URL: {field(judgment.get('source_url'))}",
                f"* Acquisition status: {field(judgment.get('status'))}",
                f"* Acquisition query/query ID: {field(judgment.get('acquisition_query'))}",
                f"* Retrieval rank: {field(judgment.get('retrieval_rank'))}",
                f"* Assigned offence family: {field(judgment.get('offence_family'))}",
                f"* Current legal regime value: {field(judgment.get('legal_regime'))}",
                "",
                "### Court Metadata",
                "",
                f"* Court name: {field(judgment.get('court_name'))}",
                f"* Normalized court level: {field(judgment.get('court_level'))}",
                f"* Decision date: {field(judgment.get('decision_date'))}",
                f"* Year: {field(judgment.get('year'))}",
                f"* Case number if available: {field(judgment.get('case_number'))}",
                f"* Metadata warnings: {', '.join(warnings) if warnings else 'none'}",
                "",
                "### Integrity",
                "",
                f"* Local raw path: {field(judgment.get('raw_file_path'))}",
                f"* MIME type: {field(judgment.get('mime_type'))}",
                f"* File size: {field(judgment.get('file_size_bytes'))}",
                f"* SHA-256: {field(judgment.get('sha256'))}",
                f"* Attribution required: {field(judgment.get('attribution_required'))}",
                "",
                "### Content Preview",
                "",
                *provenance,
                "",
                preview,
                "",
                "### Human Review Checklist",
                "",
                "* [ ] Genuine judicial decision/order",
                "* [ ] Criminal-law relevance confirmed",
                "* [ ] Offence-family assignment confirmed",
                "* [ ] Court metadata confirmed",
                "* [ ] Year/date confirmed",
                "* [ ] Legal regime reviewed",
                "* [ ] Source/provenance confirmed",
                "* [ ] Suitable for development RAG corpus",
                "",
                "Human decision:",
                "",
                f"* {field(review.get('human_review_status')).capitalize() or 'Pending'}",
                "",
                "Review notes:",
                "",
                "* ",
                "",
            ]
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return len(pairs), available_count, unavailable_count


def automated_decision(record: dict[str, Any]) -> str:
    decision = record.get("final_automated_decision")
    if decision:
        return str(decision)
    status = record.get("status")
    if status == "validated":
        return "accept_candidate"
    if status == "needs_review":
        return "needs_review"
    return field(status) or "unknown"


def generate_balanced_composition(
    judgment_manifest: Path = BALANCED_JUDGMENT_MANIFEST,
    review_manifest: Path = BALANCED_REVIEW_MANIFEST,
    audit_manifest: Path = BALANCED_AUDIT_MANIFEST,
    report_path: Path = BALANCED_COMPOSITION_PATH,
) -> None:
    judgments = load_manifest(judgment_manifest)
    reviews = load_manifest(review_manifest)
    audit = load_manifest(audit_manifest)
    reviewable = [
        record
        for record in judgments
        if automated_decision(record) in {"accept_candidate", "needs_review"}
    ]
    targeted_additions = [record for record in reviewable if str(record.get("query_id") or "").startswith("gap_")]
    step_04e_records = [record for record in reviewable if record not in targeted_additions]
    review_by_source = review_records_by_source_id(reviews)
    family_counts = Counter(str(record.get("offence_family")) for record in reviewable)
    court_counts = Counter(str(record.get("court_level")) for record in reviewable)
    year_counts = Counter(str(record.get("year")) for record in reviewable)
    track_counts = Counter(str(record.get("temporal_track")) for record in reviewable)
    regime_counts = Counter(str(record.get("legal_regime")) for record in reviewable)
    automated_counts = Counter(automated_decision(record) for record in reviewable)
    review_counts = Counter(str(record.get("human_review_status")) for record in reviews)
    audit_reasons = Counter(reason for record in audit for reason in record.get("rejection_reasons", []))

    target_total = sum(BALANCED_FAMILY_QUOTAS.values())
    remaining_gaps = {
        family: max(target - family_counts.get(family, 0), 0)
        for family, target in BALANCED_FAMILY_QUOTAS.items()
    }
    corpus_status = "READY FOR HUMAN REVIEW" if len(reviewable) >= target_total and not any(remaining_gaps.values()) else "INCOMPLETE"
    status_reason = (
        "target reached with all configured offence-family quotas filled."
        if corpus_status == "READY FOR HUMAN REVIEW"
        else "provider search results and strict pre-screening exhausted useful candidates before all quotas were filled."
    )

    lines = [
        "# LegalAI Balanced Development Judgment Corpus",
        "",
        "Phase 0 Step 0.4E acquired the initial controlled, balanced development judgment corpus.",
        "Phase 0 Step 0.4F supplemented only underfilled offence-family gaps.",
        "No human suitability decisions are recorded in this document.",
        "",
        "## Status",
        "",
        f"* Target reviewable candidates: {target_total}",
        f"* Actual reviewable candidates: {len(reviewable)}",
        f"* Step 0.4E reviewable candidates: {len(step_04e_records)}",
        f"* Step 0.4F targeted additions: {len(targeted_additions)}",
        f"* Corpus status: {corpus_status}",
        f"* Reason: {status_reason}",
        "",
        "## Configured Quotas",
        "",
        "| Offence Family | Target | Actual |",
        "| --- | ---: | ---: |",
    ]
    for family, target in BALANCED_FAMILY_QUOTAS.items():
        lines.append(f"| {family} | {target} | {family_counts.get(family, 0)} |")

    lines.extend(["", "## Composition", "", "| Metric | Count |", "| --- | ---: |"])
    metrics = {
        "total reviewable": len(reviewable),
        "accept_candidate": automated_counts.get("accept_candidate", 0),
        "needs_review": automated_counts.get("needs_review", 0),
        "pending human review": review_counts.get("pending", 0),
        "automated rejects": sum(1 for record in audit if automated_decision(record) == "reject"),
        "duplicates": audit_reasons.get("duplicate_candidate", 0),
        "failed retrievals": audit_reasons.get("metadata_or_document_fetch_failed", 0),
    }
    for name, count in metrics.items():
        lines.append(f"| {name} | {count} |")

    lines.extend(["", "## Remaining Gaps", "", "| Offence Family | Remaining Gap |", "| --- | ---: |"])
    for family in BALANCED_FAMILY_QUOTAS:
        lines.append(f"| {family} | {remaining_gaps[family]} |")

    for heading, counts in [
        ("Court Distribution", court_counts),
        ("Year Distribution", year_counts),
        ("Temporal Track Distribution", track_counts),
        ("Legal Regime Distribution", regime_counts),
    ]:
        lines.extend(["", f"## {heading}", "", "| Value | Count |", "| --- | ---: |"])
        for value, count in sorted(counts.items()):
            lines.append(f"| {value} | {count} |")

    lines.extend(["", "## Reviewable Case Inventory", "", "| Source ID | Case Name | Court | Year | Offence Family | Track | Criminal Score | Regime | Automated Decision | Human Review |", "| --- | --- | --- | ---: | --- | --- | ---: | --- | --- | --- |"])
    for record in reviewable:
        review = review_by_source.get(str(record.get("source_document_id")), {})
        score = (record.get("quality_scores") or {}).get("criminal_relevance")
        lines.append(
            "| "
            + " | ".join(
                [
                    field(record.get("source_document_id")),
                    field(record.get("case_name")).replace("|", "\\|"),
                    field(record.get("court_level")),
                    field(record.get("year")),
                    field(record.get("offence_family")),
                    field(record.get("temporal_track")),
                    field(score),
                    field(record.get("legal_regime")),
                    automated_decision(record),
                    field(review.get("human_review_status")),
                ]
            )
            + " |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--balanced", action="store_true", help="generate Phase 0 Step 0.4E balanced corpus reports")
    args = parser.parse_args()

    if args.balanced:
        represented, available, unavailable = generate_report(
            judgment_manifest=BALANCED_JUDGMENT_MANIFEST,
            review_manifest=BALANCED_REVIEW_MANIFEST,
            report_path=BALANCED_REPORT_PATH,
            title="LegalAI Balanced Development Judgment Corpus Review",
        )
        generate_balanced_composition()
        print(f"Reviewable records represented: {represented}")
        print(f"Content previews available: {available}")
        print(f"Content previews unavailable: {unavailable}")
        print(f"Wrote {BALANCED_REPORT_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {BALANCED_COMPOSITION_PATH.relative_to(REPO_ROOT)}")
        return 0

    represented, available, unavailable = generate_report()
    print(f"Reviewable records represented: {represented}")
    print(f"Content previews available: {available}")
    print(f"Content previews unavailable: {unavailable}")
    print(f"Wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
