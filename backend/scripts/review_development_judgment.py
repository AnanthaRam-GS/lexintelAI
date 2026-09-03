"""Human-operated review utility for development judgment candidates."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.corpus_utils import load_manifest, write_manifest_atomic  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
JUDGMENT_MANIFEST = MANIFEST_DIR / "development_judgments.json"
REVIEW_MANIFEST = MANIFEST_DIR / "development_judgment_review.json"
QUERY_MANIFEST = MANIFEST_DIR / "development_judgment_queries.json"
SUPPORTED_DECISIONS = {"accepted", "rejected", "needs_review"}
ALLOWED_LEGAL_REGIMES = {"ipc_crpc", "bns_bnss", "mixed_or_transition", "unknown"}
PROTECTED_JUDGMENT_FIELDS = {
    "source_provider",
    "source_document_id",
    "source_url",
    "raw_file_path",
    "sha256",
    "file_size_bytes",
    "mime_type",
    "attribution_required",
    "attribution_text",
    "status",
}


class ReviewError(ValueError):
    """Raised for invalid human review commands."""


def allowed_offence_families(query_manifest: Path = QUERY_MANIFEST) -> set[str]:
    return {
        str(record["offence_family"])
        for record in load_manifest(query_manifest)
        if record.get("offence_family")
    }


def find_record(records: list[dict[str, Any]], source_id: str) -> dict[str, Any] | None:
    for record in records:
        if str(record.get("source_document_id")) == str(source_id):
            return record
    return None


def update_review(
    source_id: str,
    decision: str,
    offence_family: str | None = None,
    legal_regime: str | None = None,
    notes: str | None = None,
    reviewer: str | None = None,
    judgment_manifest: Path = JUDGMENT_MANIFEST,
    review_manifest: Path = REVIEW_MANIFEST,
    query_manifest: Path = QUERY_MANIFEST,
) -> None:
    if decision not in SUPPORTED_DECISIONS:
        raise ReviewError(f"invalid decision: {decision}")
    if legal_regime is not None and legal_regime not in ALLOWED_LEGAL_REGIMES:
        raise ReviewError(f"invalid legal_regime: {legal_regime}")

    families = allowed_offence_families(query_manifest)
    if offence_family is not None and offence_family not in families:
        raise ReviewError(f"invalid offence_family: {offence_family}")

    judgments = load_manifest(judgment_manifest)
    reviews = load_manifest(review_manifest)
    judgment = find_record(judgments, source_id)
    review = find_record(reviews, source_id)
    if judgment is None:
        raise ReviewError(f"unknown source_document_id: {source_id}")
    if review is None:
        raise ReviewError(f"source_document_id is not in review manifest: {source_id}")

    before_protected = {field: judgment.get(field) for field in PROTECTED_JUDGMENT_FIELDS}
    before_status = judgment.get("status")

    review["human_review_status"] = decision
    review["reviewed_at"] = datetime.now(UTC).isoformat()
    review["reviewer"] = reviewer
    if notes is not None:
        review["review_notes"] = notes
    if offence_family is not None:
        review["offence_family"] = offence_family
        judgment["offence_family"] = offence_family
    if legal_regime is not None:
        review["legal_regime"] = legal_regime
        judgment["legal_regime"] = legal_regime

    if judgment.get("status") != before_status:
        raise ReviewError("acquisition status changed unexpectedly")
    after_protected = {field: judgment.get(field) for field in PROTECTED_JUDGMENT_FIELDS}
    if after_protected != before_protected:
        raise ReviewError("protected provenance or raw-file fields changed unexpectedly")

    write_manifest_atomic(review_manifest, reviews)
    if offence_family is not None or legal_regime is not None:
        write_manifest_atomic(judgment_manifest, judgments)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply an explicit human review decision to a development judgment."
    )
    parser.add_argument("--source-id", required=True, help="Existing source_document_id")
    parser.add_argument(
        "--decision",
        required=True,
        choices=sorted(SUPPORTED_DECISIONS),
        help="Human review decision",
    )
    parser.add_argument("--offence-family", help="Optional corrected offence taxonomy value")
    parser.add_argument(
        "--legal-regime",
        choices=sorted(ALLOWED_LEGAL_REGIMES),
        help="Optional corrected legal regime",
    )
    parser.add_argument("--notes", help="Optional human review notes")
    parser.add_argument("--reviewer", help="Optional reviewer name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        update_review(
            source_id=args.source_id,
            decision=args.decision,
            offence_family=args.offence_family,
            legal_regime=args.legal_regime,
            notes=args.notes,
            reviewer=args.reviewer,
        )
    except ReviewError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Updated human review record for source_document_id {args.source_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
