"""Produce document_sections and outcome columns from PostgreSQL chunk text.

For every document with chunks:

- **Sections:** each statute-bound section citation found by
  ``services/judgment_sections.py`` (the existing deterministic
  query_analysis extractor) becomes one ``document_sections`` row. The row
  records how many mentions were found, in how many chunks, the first
  evidence chunk, and the extraction method.
- **Outcomes:** ``conviction_status``, ``appeal_result`` and
  ``case_disposition`` come from ``services/judgment_outcomes.py`` (operative
  rules over the concluding chunks). Only values a rule found are written;
  unknown or ambiguous fields stay NULL. ``documents.outcome_evidence`` keeps
  the rule and evidence chunk for each written value.
- **Court level:** derived from ``court_name`` only when ``court_level`` is
  NULL and the name is unambiguous. Existing values are kept, and any
  disagreement with the name is reported.

Idempotent: rows and values are compared before writing, so a second run
reports 0 changes. Section rows produced by this method that are no longer
supported are removed. Rows from any other method are never touched.
Existing outcome values written by another method are kept. Documents a
reviewer has marked ``REVIEWED`` (``import_analytics_review.py``) keep their
outcome values: the producer reports them as ``outcomes_skipped_reviewed`` and
never overwrites them. Their sections and court level are still produced,
because the review covers the three outcome fields only.

A review CSV, with short evidence excerpts, every unreviewed row marked
``UNREVIEWED`` and empty reviewer columns (``reviewer``,
``corrected_<field>``, ``review_notes``), is written to ``--review-dir``, which must be outside the
repository because it contains judgment text. ``--summary-out`` writes an
ID-only Markdown summary that is safe to commit.

Usage:
    .venv/bin/python backend/scripts/produce_analytics_data.py --database-url-env DATABASE_URL \\
        --review-dir ~/legalai_reviews [--summary-out docs/analytics/REVIEW_SUMMARY.md] [--dry-run] [--confirm-dev]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.judgment_outcomes import FIELDS, OUTCOME_METHOD, extract_outcomes, operative_chunks  # noqa: E402
from backend.app.services.judgment_sections import EXTRACTION_METHOD, extract_section_mentions, regime_for, statute_regimes  # noqa: E402
from backend.scripts.reconcile_common import REPO_ROOT, alembic_version, resolve_database  # noqa: E402

REQUIRED_REVISION = "0008_ncrb_bns_review"
EXCERPT_CHARS = 160
REVIEWED = "REVIEWED"
UNREVIEWED = "UNREVIEWED"
COURT_LEVEL_RULES = (
    (re.compile(r"\bsupreme court\b", re.IGNORECASE), "supreme_court"),
    (re.compile(r"\bhigh court\b", re.IGNORECASE), "high_court"),
    (re.compile(r"\b(?:district|sessions)\b", re.IGNORECASE), "district_or_sessions"),
)


def derive_court_level(court_name: str | None) -> str | None:
    """Court level from the court name when exactly one rule matches."""
    if not court_name:
        return None
    levels = {level for pattern, level in COURT_LEVEL_RULES if pattern.search(court_name)}
    return next(iter(levels)) if len(levels) == 1 else None


def desired_sections(chunks: list[tuple[int, str, str]]) -> tuple[dict[tuple[str, str], dict[str, Any]], Counter]:
    """{(statute, section): provenance} for one document, plus rejection counts."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    rejected: Counter = Counter()
    for chunk_index, chunk_id, text in sorted(chunks):
        extraction = extract_section_mentions(text)
        rejected.update(extraction.rejected)
        for key, mentions in Counter(extraction.mentions).items():
            row = found.setdefault(key, {"mention_count": 0, "chunks": [], "evidence_chunk_id": chunk_id})
            row["mention_count"] += mentions
            row["chunks"].append(chunk_id)
    for row in found.values():
        row["chunk_count"] = len(set(row.pop("chunks")))
        row["extraction_method"] = EXTRACTION_METHOD
    return found, rejected


def excerpt(text: str, start: int | None, end: int | None) -> str:
    if start is None:
        return ""
    flat = " ".join(text.split())
    return flat[max(0, start - EXCERPT_CHARS // 2): min(len(flat), end + EXCERPT_CHARS // 2)]


def new_stats() -> dict[str, Any]:
    return {
        "documents": 0,
        "sections": Counter(),
        "section_rejections": Counter(),
        "outcomes_changed": Counter(),
        "outcomes_kept_other_method": Counter(),
        "outcomes_skipped_reviewed": 0,
        "court_level": Counter(),
    }


def produce_document(
    session: Any,
    document: Any,
    chunks: list[tuple[int, str, str]],
    stats: dict[str, Any],
    regimes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Sections, outcomes and court level for one document; returns its review row.

    ``chunks`` is (chunk_index, chunk_id, text). Writes go to ``session``
    only; the caller commits or rolls back. Admin ingestion calls this inside
    its PostgreSQL transaction (``services/ingestion.py``).
    """
    from backend.app.db.models import DocumentSection

    regimes = regimes or statute_regimes()
    stats["documents"] += 1
    texts = {chunk_id: text for _, chunk_id, text in chunks}

    # Sections
    wanted, rejected = desired_sections(chunks)
    stats["section_rejections"].update(rejected)
    existing = {(row.statute, row.section): row for row in session.query(DocumentSection).filter_by(document_id=document.id)}
    for key, provenance in wanted.items():
        row = existing.get(key)
        if row is None:
            session.add(DocumentSection(document_id=document.id, statute=key[0], section=key[1], **provenance))
            stats["sections"]["inserted"] += 1
        elif any(getattr(row, name) != value for name, value in provenance.items()):
            for name, value in provenance.items():
                setattr(row, name, value)
            stats["sections"]["updated"] += 1
        else:
            stats["sections"]["unchanged"] += 1
    for key, row in existing.items():
        if key not in wanted:
            if row.extraction_method == EXTRACTION_METHOD:
                session.delete(row)
                stats["sections"]["deleted"] += 1
            else:
                stats["sections"]["kept_other_method"] += 1

    # Outcomes (a reviewed document's values are the reviewer's: never overwritten)
    findings = extract_outcomes(operative_chunks(chunks))
    reviewed = document.review_status == REVIEWED
    if reviewed:
        stats["outcomes_skipped_reviewed"] += 1
    evidence = dict(document.outcome_evidence or {})
    changed = False
    for field in FIELDS if not reviewed else ():
        finding = findings[field]
        value = finding.value if finding.status == "found" else None
        current = getattr(document, field)
        if current is not None and field not in evidence:
            # A value this producer did not write (manual or another method): never overwrite.
            stats["outcomes_kept_other_method"][field] += 1
            continue
        wanted_evidence = {"rule": finding.rule, "chunk_id": finding.chunk_id} if value is not None else None
        if current != value or evidence.get(field) != wanted_evidence:
            setattr(document, field, value)
            if wanted_evidence is None:
                evidence.pop(field, None)
            else:
                evidence[field] = wanted_evidence
            stats["outcomes_changed"][field] += 1
            changed = True
    if not reviewed and (changed or document.outcome_method != OUTCOME_METHOD):
        document.outcome_evidence = evidence or None
        if document.outcome_method != OUTCOME_METHOD:
            stats["outcomes_changed"]["outcome_method"] += 1
        document.outcome_method = OUTCOME_METHOD

    # Court level
    derived = derive_court_level(document.court_name)
    if document.court_level is None and derived is not None:
        document.court_level = derived
        stats["court_level"]["filled"] += 1
    elif document.court_level is None:
        stats["court_level"]["left_null_ambiguous_or_missing_name"] += 1
    elif derived is not None and derived != document.court_level:
        stats["court_level"]["existing_disagrees_with_name"] += 1
    else:
        stats["court_level"]["existing_kept"] += 1

    return {
        "document_id": document.id,
        "source_document_key": document.source_document_key or "",
        "court_level": document.court_level or "",
        "sections": "; ".join(
            f"{statute} {section} [{regime_for(statute, regimes)}; mentions={wanted[(statute, section)]['mention_count']}]"
            for statute, section in sorted(wanted)
        ),
        **{
            f"{field}": findings[field].value or findings[field].status
            for field in FIELDS
        },
        **{f"{field}_rule": findings[field].rule or "" for field in FIELDS},
        **{f"{field}_evidence_chunk": findings[field].chunk_id or "" for field in FIELDS},
        **{f"{field}_candidates": ", ".join(findings[field].candidates) for field in FIELDS},
        **{
            f"{field}_excerpt": excerpt(texts.get(findings[field].chunk_id, ""), findings[field].start, findings[field].end)
            for field in FIELDS
        },
        "review_status": REVIEWED if reviewed else UNREVIEWED,
        "reviewer": "",
        **{f"corrected_{field}": "" for field in FIELDS},
        "review_notes": "",
    }


def produce(session: Any, *, dry_run: bool) -> dict[str, Any]:
    from backend.app.db.models import Chunk, Document

    regimes = statute_regimes()
    stats = new_stats()
    review_rows: list[dict[str, Any]] = []
    for document in session.query(Document).order_by(Document.id).all():
        chunk_rows = (
            session.query(Chunk.chunk_index, Chunk.chroma_id, Chunk.text)
            .filter(Chunk.document_id == document.id)
            .all()
        )
        if not chunk_rows:
            continue
        review_rows.append(produce_document(session, document, [(row[0], row[1], row[2]) for row in chunk_rows], stats, regimes))

    if dry_run:
        session.rollback()
    else:
        session.commit()
    stats["review_rows"] = review_rows
    return stats


def write_review(rows: list[dict[str, Any]], review_dir: Path, database: str) -> Path:
    review_dir = review_dir.expanduser().resolve()
    if review_dir == REPO_ROOT or REPO_ROOT in review_dir.parents:
        raise SystemExit("refused: --review-dir must be outside the repository (the review file contains judgment text)")
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"analytics_review_{database}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["document_id"])
        writer.writeheader()
        writer.writerows(rows)
    path.chmod(0o600)
    return path


def write_summary(rows: list[dict[str, Any]], path: Path) -> None:
    """ID-only summary: keys, section codes, outcome labels and rule names, no text."""
    lines = [
        "# Analytics Data Review Summary",
        "",
        "Generated by `backend/scripts/produce_analytics_data.py`. IDs, section codes, outcome labels and rule names only;",
        "evidence excerpts live in the review CSV outside the repository. **UNREVIEWED** rows are rule-based",
        "extractions awaiting qualified legal review; REVIEWED rows keep the reviewer's values.",
        "",
        "| Document key | Sections | conviction_status | appeal_result | case_disposition | Rules | Review |",
        "|---|---:|---|---|---|---|---|",
    ]
    for row in rows:
        rules = ", ".join(filter(None, (row[f"{field}_rule"] for field in FIELDS))) or "—"
        sections = row["sections"].count("[")
        lines.append(
            f"| `{row['source_document_key'] or row['document_id']}` | {sections} | {row['conviction_status']} | "
            f"{row['appeal_result']} | {row['case_disposition']} | {rules} | {row['review_status']} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--review-dir", type=Path, help="Directory outside the repo for the review CSV.")
    parser.add_argument("--summary-out", type=Path, help="Path for the ID-only Markdown summary.")
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
        stats = produce(session, dry_run=args.dry_run)
    finally:
        session.close()
        engine.dispose()

    rows = stats.pop("review_rows")
    print(f"analytics producer database={database}" + (" (dry-run)" if args.dry_run else ""))
    print(f"  documents: {stats['documents']}")
    print(f"  outcomes_skipped_reviewed: {stats['outcomes_skipped_reviewed']}")
    for key in ("sections", "section_rejections", "outcomes_changed", "outcomes_kept_other_method", "court_level"):
        print(f"  {key}: {dict(sorted(stats[key].items()))}")
    changes = sum(stats["sections"][k] for k in ("inserted", "updated", "deleted")) + sum(stats["outcomes_changed"].values()) + stats["court_level"]["filled"]
    print(f"{'dry run: ' if args.dry_run else ''}changes{' that would be made' if args.dry_run else ''}: {changes}")
    if args.review_dir:
        print(f"  review file: {write_review(rows, args.review_dir, database)}")
    if args.summary_out:
        write_summary(rows, args.summary_out)
        print(f"  summary: {args.summary_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
