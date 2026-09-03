"""Generate a deterministic human review report for development judgments."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import load_manifest  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
JUDGMENT_MANIFEST = MANIFEST_DIR / "development_judgments.json"
REVIEW_MANIFEST = MANIFEST_DIR / "development_judgment_review.json"
REPORT_PATH = REPO_ROOT / "docs/DEVELOPMENT_CORPUS_REVIEW.md"
PREVIEW_LIMIT = 1500


def clean_text_preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def preview_for(record: dict[str, Any], repo_root: Path = REPO_ROOT) -> tuple[str, bool]:
    raw_file_path = record.get("raw_file_path")
    if not raw_file_path:
        return "Preview unavailable because no local raw path is recorded.", False

    raw_path = repo_root / str(raw_file_path)
    if not raw_path.exists():
        return "Preview unavailable because the local raw file is missing.", False

    mime_type = str(record.get("mime_type") or "").lower()
    suffix = raw_path.suffix.lower()
    if mime_type == "application/pdf" or suffix == ".pdf":
        return "Preview unavailable until PDF parsing dependency is installed.", False

    if mime_type.startswith("text/") or suffix in {".html", ".htm", ".txt", ".json"}:
        text = raw_path.read_text(encoding="utf-8", errors="ignore")
        preview = clean_text_preview(text)
        if preview:
            return preview, True
        return "Preview unavailable because no readable text was found.", False

    return "Preview unavailable for this raw file type.", False


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


def generate_report(
    judgment_manifest: Path = JUDGMENT_MANIFEST,
    review_manifest: Path = REVIEW_MANIFEST,
    report_path: Path = REPORT_PATH,
    repo_root: Path = REPO_ROOT,
) -> tuple[int, int, int]:
    judgments = load_manifest(judgment_manifest)
    reviews = load_manifest(review_manifest)
    pairs = reviewable_records(judgments, reviews)
    available_count = 0
    unavailable_count = 0

    lines: list[str] = [
        "# LegalAI Development Judgment Corpus Review",
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
        preview, available = preview_for(judgment, repo_root=repo_root)
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


def main() -> int:
    represented, available, unavailable = generate_report()
    print(f"Reviewable records represented: {represented}")
    print(f"Content previews available: {available}")
    print(f"Content previews unavailable: {unavailable}")
    print(f"Wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
