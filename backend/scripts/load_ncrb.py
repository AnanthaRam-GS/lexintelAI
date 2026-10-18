"""Load NCRB "Crime in India 2024" Table 1A.4 statistics into PostgreSQL.

Validation: required columns; required fields (year, state,
offense_category) non-blank; integer and non-negative counts; field lengths
within the column sizes; duplicate (year, state, offense_category,
ipc_section) keys within the file with different counts. Every rejected row
is counted by reason; no row is dropped silently. An exact repeat of a row is
loaded once and noted as ``exact_duplicate_in_file``.

Missing values stay NULL. A blank case_count (41 source rows) is stored as
NULL, never 0, and is reported as ``case_count_not_reported``. Table 1A.4
reports no conviction or acquittal counts, so those columns are NULL for
every row. The CSV's bns_section is validated but not stored:
ncrb_stats has no BNS column (by schema design); the count of non-blank
values is reported as ``bns_section_not_stored``.

Section fields: whitespace is collapsed and hyphenated letter suffixes are
joined ("366-B" -> "366B"), as in document_sections. Crime-head ranges
("147-151", "376 r/w 511") are kept verbatim.

Idempotent upsert on (year, state, offense_category, ipc_section): new keys
are inserted, keys whose counts changed are updated, and identical rows are
left alone. A second run makes 0 changes and never duplicates.

Usage:
    .venv/bin/python backend/scripts/load_ncrb.py --database-url-env DATABASE_URL [--dry-run] [--confirm-dev]
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.app.db.models import NcrbStat
from backend.scripts.load_ipc_bns import normalize_section_field

DEFAULT_CSV_PATH = REPO_ROOT / "data/processed/ncrb/ncrb_stats_2024_complete.csv"
REQUIRED_COLUMNS = {
    "year",
    "state",
    "offense_category",
    "ipc_section",
    "case_count",
    "conviction_count",
    "acquittal_count",
}
FIELD_LIMITS = {"state": 100, "offense_category": 150, "ipc_section": 100}
COUNT_FIELDS = ("case_count", "conviction_count", "acquittal_count")


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _parse_optional_int(value: str | None) -> int | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    return int(text)


def _ncrb_key(row: NcrbStat | dict) -> tuple:
    if isinstance(row, NcrbStat):
        return (row.year, row.state, row.offense_category, row.ipc_section)
    return (row["year"], row["state"], row["offense_category"], row.get("ipc_section"))


def load_ncrb_stats(
    db: Session,
    csv_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Upsert NCRB statistics rows from the processed project CSV."""
    path = Path(csv_path) if csv_path else DEFAULT_CSV_PATH
    if not path.exists():
        raise FileNotFoundError(f"NCRB statistics CSV not found: {path}")

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"NCRB statistics CSV has no header row: {path}")
        columns = {name.strip() for name in reader.fieldnames}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(
                f"NCRB statistics CSV is missing columns: {', '.join(sorted(missing))}"
            )
        source_rows = list(reader)

    existing = {_ncrb_key(row): row for row in db.query(NcrbStat).all()}
    pending: list[dict] = []
    rejected: Counter[str] = Counter()
    notes: Counter[str] = Counter()
    updated = 0
    skipped_existing = 0
    seen_in_file: dict[tuple, dict] = {}

    for raw in source_rows:
        state = _blank_to_none(raw.get("state"))
        offense_category = _blank_to_none(raw.get("offense_category"))
        ipc_section = normalize_section_field(raw.get("ipc_section"))
        notes["normalized_section_values"] += int(ipc_section != _blank_to_none(raw.get("ipc_section")))
        try:
            year = _parse_optional_int(raw.get("year"))
            counts = {name: _parse_optional_int(raw.get(name)) for name in COUNT_FIELDS}
        except ValueError:
            rejected["non_integer_value"] += 1
            continue

        if year is None or not state or not offense_category:
            rejected["missing_required_field"] += 1
            continue
        if any(value is not None and value < 0 for value in counts.values()):
            rejected["negative_count"] += 1
            continue
        parsed = {"year": year, "state": state, "offense_category": offense_category, "ipc_section": ipc_section, **counts}
        if any(parsed[name] and len(parsed[name]) > limit for name, limit in FIELD_LIMITS.items()):
            rejected["field_too_long"] += 1
            continue
        key = _ncrb_key(parsed)
        if key in seen_in_file:
            if seen_in_file[key] == parsed:
                notes["exact_duplicate_in_file"] += 1  # identical repeat: harmless, loaded once
                skipped_existing += 1
            else:
                rejected["duplicate_key_conflict"] += 1  # same key, different counts
            continue
        seen_in_file[key] = parsed
        if counts["case_count"] is None:
            notes["case_count_not_reported"] += 1
        if _blank_to_none(raw.get("bns_section")):
            notes["bns_section_not_stored"] += 1

        current = existing.get(key)
        if current is None:
            pending.append(parsed)
        elif any(getattr(current, name) != counts[name] for name in COUNT_FIELDS):
            updated += 1
            if not dry_run:
                for name in COUNT_FIELDS:
                    setattr(current, name, counts[name])
        else:
            skipped_existing += 1

    if not dry_run:
        if pending:
            # Insert through the Table so column defaults never turn NULL into 0.
            db.execute(insert(NcrbStat.__table__), pending)
        if pending or updated:
            db.commit()
    else:
        db.rollback()

    return {
        "source_rows": len(source_rows),
        "inserted": 0 if dry_run else len(pending),
        "would_insert": len(pending),
        "updated": 0 if dry_run else updated,
        "would_update": updated,
        "skipped_existing": skipped_existing,
        "skipped_invalid": sum(rejected.values()),
        "rejected": dict(sorted(rejected.items())),
        "notes": dict(sorted(notes.items())),
        "db_rows_not_in_source": len(set(existing) - set(seen_in_file)),
    }


def main(argv: list[str] | None = None) -> int:
    from backend.scripts.reconcile_common import resolve_database

    parser = argparse.ArgumentParser(description="Load NCRB statistics into PostgreSQL.")
    parser.add_argument("--csv", dest="csv_path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=not args.dry_run)
    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    try:
        stats = load_ncrb_stats(db, args.csv_path, dry_run=args.dry_run)
    finally:
        db.close()
        engine.dispose()
    print(f"NCRB load database={database}" + (" (dry-run)" if args.dry_run else ""))
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
