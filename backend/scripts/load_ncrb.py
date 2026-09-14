"""Load the processed NCRB statistics CSV into PostgreSQL.

The loader is idempotent: existing (year, state, offense_category, ipc_section)
rows are skipped instead of duplicated. Extra CSV columns such as bns_section
are ignored so the complete dataset can load into the existing NcrbStat model.
"""

from __future__ import annotations

import argparse
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
from backend.app.db.session import SessionLocal

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
) -> dict[str, int]:
    """Insert missing NCRB statistics rows from the processed project CSV."""
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

    existing = {_ncrb_key(row) for row in db.query(NcrbStat).all()}
    pending: list[dict] = []
    skipped_existing = 0
    skipped_invalid = 0
    seen_in_file: set[tuple] = set()

    for raw in source_rows:
        state = _blank_to_none(raw.get("state"))
        offense_category = _blank_to_none(raw.get("offense_category"))
        try:
            year = _parse_optional_int(raw.get("year"))
            case_count = _parse_optional_int(raw.get("case_count"))
            conviction_count = _parse_optional_int(raw.get("conviction_count"))
            acquittal_count = _parse_optional_int(raw.get("acquittal_count"))
        except ValueError:
            skipped_invalid += 1
            continue

        if year is None or not state or not offense_category:
            skipped_invalid += 1
            continue

        parsed = {
            "year": year,
            "state": state,
            "offense_category": offense_category,
            "ipc_section": _blank_to_none(raw.get("ipc_section")),
            # Existing NcrbStat.case_count is NOT NULL; missing source values become 0.
            "case_count": 0 if case_count is None else case_count,
            "conviction_count": conviction_count,
            "acquittal_count": acquittal_count,
        }
        key = _ncrb_key(parsed)
        if key in existing or key in seen_in_file:
            skipped_existing += 1
            continue
        seen_in_file.add(key)
        pending.append(parsed)

    inserted = 0
    if pending and not dry_run:
        # Insert through the Table so Python/server defaults do not turn explicit NULL
        # disposal fields into 0.
        db.execute(insert(NcrbStat.__table__), pending)
        db.commit()
        inserted = len(pending)

    return {
        "source_rows": len(source_rows),
        "inserted": inserted,
        "would_insert": len(pending),
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load NCRB statistics into PostgreSQL.")
    parser.add_argument("--csv", dest="csv_path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stats = load_ncrb_stats(db, args.csv_path, dry_run=args.dry_run)
    finally:
        db.close()

    print(
        "NCRB load "
        f"source_rows={stats['source_rows']} "
        f"inserted={stats['inserted']} "
        f"would_insert={stats['would_insert']} "
        f"skipped_existing={stats['skipped_existing']} "
        f"skipped_invalid={stats['skipped_invalid']}"
        + (" (dry-run)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
