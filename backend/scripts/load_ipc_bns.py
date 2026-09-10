"""Load the processed IPC-BNS mapping CSV into PostgreSQL.

The loader is idempotent: existing (ipc_section, ipc_description, bns_section,
bns_description, change_type) rows are skipped instead of duplicated.
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

from sqlalchemy.orm import Session

from backend.app.db.models import IpcBnsMapping
from backend.app.db.session import SessionLocal

DEFAULT_CSV_PATH = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_mapping.csv"
REQUIRED_COLUMNS = {
    "ipc_section",
    "ipc_description",
    "bns_section",
    "bns_description",
    "change_type",
}


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _mapping_key(row: IpcBnsMapping | dict[str, str | None]) -> tuple:
    if isinstance(row, IpcBnsMapping):
        return (
            row.ipc_section,
            row.ipc_description,
            row.bns_section,
            row.bns_description,
            row.change_type,
        )
    return (
        row["ipc_section"],
        row["ipc_description"],
        row.get("bns_section"),
        row.get("bns_description"),
        row["change_type"],
    )


def load_ipc_bns_mapping(
    db: Session,
    csv_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Insert missing IPC-BNS mapping rows from the processed project CSV."""
    path = Path(csv_path) if csv_path else DEFAULT_CSV_PATH
    if not path.exists():
        raise FileNotFoundError(f"IPC-BNS mapping CSV not found: {path}")

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"IPC-BNS mapping CSV has no header row: {path}")
        columns = {name.strip() for name in reader.fieldnames}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(
                f"IPC-BNS mapping CSV is missing columns: {', '.join(sorted(missing))}"
            )
        source_rows = list(reader)

    existing = {_mapping_key(row) for row in db.query(IpcBnsMapping).all()}
    pending: list[IpcBnsMapping] = []
    skipped_existing = 0
    skipped_invalid = 0
    seen_in_file: set[tuple] = set()

    for raw in source_rows:
        ipc_section = _blank_to_none(raw.get("ipc_section"))
        ipc_description = _blank_to_none(raw.get("ipc_description"))
        change_type = _blank_to_none(raw.get("change_type"))
        if not ipc_section or not ipc_description or not change_type:
            skipped_invalid += 1
            continue

        parsed = {
            "ipc_section": ipc_section,
            "ipc_description": ipc_description,
            "bns_section": _blank_to_none(raw.get("bns_section")),
            "bns_description": _blank_to_none(raw.get("bns_description")),
            "change_type": change_type,
        }
        key = _mapping_key(parsed)
        if key in existing or key in seen_in_file:
            skipped_existing += 1
            continue
        seen_in_file.add(key)
        pending.append(IpcBnsMapping(**parsed))

    inserted = 0
    if pending and not dry_run:
        db.add_all(pending)
        db.commit()
        inserted = len(pending)
    elif pending and dry_run:
        inserted = 0

    return {
        "source_rows": len(source_rows),
        "inserted": inserted if not dry_run else 0,
        "would_insert": len(pending),
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load IPC-BNS mappings into PostgreSQL.")
    parser.add_argument("--csv", dest="csv_path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stats = load_ipc_bns_mapping(db, args.csv_path, dry_run=args.dry_run)
    finally:
        db.close()

    print(
        "IPC-BNS load "
        f"source_rows={stats['source_rows']} "
        f"inserted={stats['inserted']} "
        f"would_insert={stats['would_insert']} "
        f"skipped_existing={stats['skipped_existing']} "
        f"skipped_invalid={stats['skipped_invalid']}"
        + (" (dry-run)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
