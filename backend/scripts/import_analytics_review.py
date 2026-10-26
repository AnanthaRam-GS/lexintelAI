"""Import a reviewed copy of the analytics review CSV into PostgreSQL.

The review CSV comes from ``produce_analytics_data.py --review-dir``. On a
copy, the reviewer fills, for each row they have checked:

- ``reviewer``: their name or ID (required);
- ``review_status``: ``CONFIRMED`` (the produced outcome values are right),
  ``CORRECTED`` (some are wrong; the right values are in ``corrected_*``) or
  ``REJECTED`` (the produced outcomes cannot be trusted; all three are
  cleared);
- ``corrected_conviction_status`` / ``corrected_appeal_result`` /
  ``corrected_case_disposition``: only for CORRECTED. A blank keeps the
  produced value, ``NULL`` clears the field, and any other value must be one
  of the labels the rules use (``judgment_outcomes.ALLOWED_VALUES``);
- ``review_notes``: free text, kept in the CSV only.

Rows still marked ``UNREVIEWED`` (or ``REVIEWED`` by the producer) are skipped.
Each imported document gets ``review_status = REVIEWED``, the decision, the
reviewer and the time, and from then on the producer never overwrites its
outcome values.

The import is all-or-nothing. It refuses the whole file, and writes nothing,
when any row has an unknown ``document_id``, a ``source_document_key`` that
does not match, a duplicate document, a missing reviewer, an unknown status
or value, corrections on a row that is not CORRECTED, or produced values that
no longer match an unreviewed document (the file is stale; produce a new
one). Idempotent: a second import of the same file makes 0 changes.

Usage:
    .venv/bin/python backend/scripts/import_analytics_review.py --database-url-env DATABASE_URL \\
        --review-csv ~/legalai_reviews/<reviewed copy>.csv [--dry-run] [--confirm-dev]
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.judgment_outcomes import ALLOWED_VALUES, FIELDS  # noqa: E402
from backend.scripts.reconcile_common import alembic_version, resolve_database  # noqa: E402

REQUIRED_REVISION = "0011_ipc_bns_source"
DECISIONS = ("CONFIRMED", "CORRECTED", "REJECTED")
NOT_ACTIONABLE = ("", "UNREVIEWED", "REVIEWED")
PRODUCED_STATUSES = ("unknown", "ambiguous")  # what the CSV shows for a field with no stored value
CLEAR = "NULL"
REVIEW_RULE = "reviewer_correction"
REQUIRED_COLUMNS = (
    "document_id",
    "source_document_key",
    "review_status",
    "reviewer",
    *FIELDS,
    *(f"{field}_rule" for field in FIELDS),
    *(f"{field}_evidence_chunk" for field in FIELDS),
    *(f"corrected_{field}" for field in FIELDS),
)


class ReviewImportError(Exception):
    """The review file was refused; nothing was written."""

    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s) in the review file; nothing was written")
        self.problems = problems


def read_review_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).expanduser().open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ReviewImportError([f"missing columns: {', '.join(missing)}"])
        return [{key: (value or "").strip() for key, value in row.items() if key is not None} for row in reader]


def _plan_row(row: dict[str, str], document: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Target review state for one actionable row, or the problems that refuse it."""
    problems: list[str] = []
    decision = row["review_status"].upper()
    if decision not in DECISIONS:
        return None, [f"unknown review_status '{row['review_status']}' (expected {', '.join(DECISIONS)})"]
    if not row["reviewer"]:
        problems.append("reviewer is blank")

    produced: dict[str, str | None] = {}
    for field in FIELDS:
        shown = row[field]
        if shown in ALLOWED_VALUES[field]:
            produced[field] = shown
        elif shown in PRODUCED_STATUSES:
            produced[field] = None
        else:
            problems.append(f"{field} has unexpected produced value '{shown}'")

    corrections = {field: row[f"corrected_{field}"] for field in FIELDS if row[f"corrected_{field}"]}
    if decision != "CORRECTED" and corrections:
        problems.append(f"corrected_* values given on a {decision} row")
    if decision == "CORRECTED" and not corrections:
        problems.append("CORRECTED row has no corrected_* value")
    for field, value in corrections.items():
        if value != CLEAR and value not in ALLOWED_VALUES[field]:
            problems.append(
                f"corrected_{field} '{value}' is not allowed (use {CLEAR} or one of: {', '.join(sorted(ALLOWED_VALUES[field]))})"
            )
    if problems:
        return None, problems

    if document.review_status != "REVIEWED":
        current = {field: getattr(document, field) for field in FIELDS}
        if current != produced:
            stale = ", ".join(f"{field}: file={produced[field]!r} db={current[field]!r}" for field in FIELDS if current[field] != produced[field])
            return None, [f"stale row, the document changed after the file was produced ({stale})"]

    if decision == "REJECTED":
        values = {field: None for field in FIELDS}
    elif decision == "CORRECTED":
        values = {field: (None if corrections.get(field) == CLEAR else corrections.get(field, produced[field])) for field in FIELDS}
    else:
        values = dict(produced)

    evidence = {
        key: value for key, value in dict(document.outcome_evidence or {}).items() if key not in FIELDS
    }
    for field in FIELDS:
        if values[field] is None:
            continue
        if values[field] == produced[field]:
            evidence[field] = {"rule": row[f"{field}_rule"], "chunk_id": row[f"{field}_evidence_chunk"]}
        else:
            evidence[field] = {"rule": REVIEW_RULE, "chunk_id": None}
    return {"decision": decision, "reviewer": row["reviewer"], "values": values, "evidence": evidence or None}, []


def import_review(session: Any, rows: list[dict[str, str]], *, dry_run: bool, now: datetime | None = None) -> dict[str, Any]:
    from backend.app.db.models import Document

    problems: list[str] = []
    plans: list[tuple[Any, dict[str, Any]]] = []
    seen: set[int] = set()
    stats: Counter[str] = Counter()
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        label = f"line {line} (document_id={row['document_id'] or '?'})"
        try:
            document_id = int(row["document_id"])
        except ValueError:
            problems.append(f"{label}: document_id is not an integer")
            continue
        document = session.get(Document, document_id)
        if document is None:
            problems.append(f"{label}: unknown document_id")
            continue
        if row["source_document_key"] and row["source_document_key"] != (document.source_document_key or ""):
            problems.append(f"{label}: source_document_key does not match the document")
            continue
        if row["review_status"].upper() in NOT_ACTIONABLE:
            stats["skipped_not_reviewed"] += 1
            continue
        if document_id in seen:
            problems.append(f"{label}: document appears more than once")
            continue
        seen.add(document_id)
        plan, row_problems = _plan_row(row, document)
        problems.extend(f"{label}: {problem}" for problem in row_problems)
        if plan is not None:
            plans.append((document, plan))
    if problems:
        session.rollback()
        raise ReviewImportError(problems)

    reviewed_at = now or datetime.now(timezone.utc)
    for document, plan in plans:
        unchanged = (
            document.review_status == "REVIEWED"
            and document.review_decision == plan["decision"]
            and document.reviewed_by == plan["reviewer"]
            and all(getattr(document, field) == plan["values"][field] for field in FIELDS)
            and (document.outcome_evidence or None) == plan["evidence"]
        )
        if unchanged:
            stats["unchanged"] += 1
            continue
        stats[plan["decision"].lower()] += 1
        for field in FIELDS:
            setattr(document, field, plan["values"][field])
        document.outcome_evidence = plan["evidence"]
        document.review_status = "REVIEWED"
        document.review_decision = plan["decision"]
        document.reviewed_by = plan["reviewer"]
        document.reviewed_at = reviewed_at

    if dry_run:
        session.rollback()
    else:
        session.commit()
    stats["changes"] = sum(stats[decision.lower()] for decision in DECISIONS)
    return dict(stats)


def main(argv: list[str] | None = None) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--review-csv", type=Path, required=True, help="The reviewed copy of the review CSV.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args(argv)

    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=not args.dry_run)
    engine = create_engine(url)
    session = sessionmaker(bind=engine)()
    try:
        revision = alembic_version(session.connection().connection.cursor())
        if revision != REQUIRED_REVISION:
            raise SystemExit(f"refused: database '{database}' is at revision {revision}; run alembic upgrade head first")
        stats = import_review(session, read_review_csv(args.review_csv), dry_run=args.dry_run)
    except ReviewImportError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    print(f"analytics review import database={database}" + (" (dry-run)" if args.dry_run else ""))
    for key in ("confirmed", "corrected", "rejected", "unchanged", "skipped_not_reviewed"):
        print(f"  {key}: {stats.get(key, 0)}")
    print(f"{'dry run: ' if args.dry_run else ''}changes{' that would be made' if args.dry_run else ''}: {stats['changes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
