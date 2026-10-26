"""Load the IPC-BNS mapping into PostgreSQL from its two sources (migration 0011, step 19b).

Sources (``ipc_bns_mapping.source``):
- ``CYTRAIN``: ``data/processed/ipc_bns/ipc_bns_mapping.csv``, the CYTRAIN correspondence table. ``change_type``
  is required. A row is identified by all five fields (as before 0011).
- ``NCRB_CII_2024_T1A4``: ``data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv``, correspondences printed in
  NCRB Crime in India 2024, Vol. I, Table 1A.4 that CYTRAIN rows lack. ``source_page`` (the table page) is
  required; ``change_type`` is left NULL when blank (no source gives one; it is never guessed). A row is
  identified by (source, ipc_section, bns_section, ipc_description): the description is the printed crime head,
  and a total head and its sub-head ("Burglary (Total a+b)", "Burglary - a) Day Burglary") can print the same
  sections, each a correspondence of its own. A second run inserts nothing.

A source row whose (ipc_section, bns_section) already exists under the other source is a collision: it is
reported (``collisions``) and skipped; existing rows, CYTRAIN rows above all, are never changed.

Validation: required columns; required fields (ipc_section, ipc_description, and change_type for CYTRAIN)
non-blank; change_type, when given, in analytics.ALLOWED_CHANGE_TYPES; field lengths within the column sizes.
Every rejected row is counted by reason; no row is dropped silently. An exact repeat of a row is loaded once and
counted as ``exact_duplicate_in_file``.

Normalization: whitespace is collapsed, and hyphenated letter suffixes are
joined ("366-B" -> "366B"), the same convention as document_sections
(``services/judgment_sections.py``). Section groupings such as "147-151" or
"376 r/w 511" are crime-head ranges and are kept verbatim.

Idempotent: a row is identified by all five fields. Existing rows are left
unchanged, so a second run inserts 0 rows and never duplicates. Rows in the
database that are no longer in the CSV are reported, not deleted.

Usage:
    .venv/bin/python backend/scripts/load_ipc_bns.py --database-url-env DATABASE_URL [--source all|cytrain|ncrb] \
        [--dry-run] [--confirm-dev]
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import re
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy.orm import Session

from backend.app.db.models import IpcBnsMapping
from backend.app.services.analytics import ALLOWED_CHANGE_TYPES

DEFAULT_CSV_PATH = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_mapping.csv"
NCRB_CSV_PATH = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_pdf_pair_candidates.csv"
CYTRAIN = "CYTRAIN"
NCRB_T1A4 = "NCRB_CII_2024_T1A4"
SOURCE_FILES = {CYTRAIN: DEFAULT_CSV_PATH, NCRB_T1A4: NCRB_CSV_PATH}
REQUIRED_COLUMNS = {
    "ipc_section",
    "ipc_description",
    "bns_section",
    "bns_description",
    "change_type",
}
REQUIRED_SOURCE_COLUMNS = {CYTRAIN: REQUIRED_COLUMNS, NCRB_T1A4: REQUIRED_COLUMNS | {"source_page"}}
FIELD_LIMITS = {"ipc_section": 100, "bns_section": 50, "change_type": 50}
_HYPHEN_SUFFIX = re.compile(r"(?<=\d)-([A-Z])\b")


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def normalize_section_field(value: str | None) -> str | None:
    """Collapse whitespace and join hyphenated letter suffixes; keep ranges as written."""
    cleaned = _blank_to_none(value)
    return _HYPHEN_SUFFIX.sub(r"\1", cleaned) if cleaned else None


def _mapping_key(row: IpcBnsMapping | dict[str, str | None]) -> tuple:
    """CYTRAIN rows: all five fields (as before 0011). NCRB rows: (source, ipc_section, bns_section, printed head)."""
    get = (lambda name: getattr(row, name)) if isinstance(row, IpcBnsMapping) else row.get
    if get("source") == NCRB_T1A4:
        return (NCRB_T1A4, get("ipc_section"), get("bns_section"), get("ipc_description"))
    return (get("ipc_section"), get("ipc_description"), get("bns_section"), get("bns_description"), get("change_type"))


def _pair(row: IpcBnsMapping | dict[str, str | None]) -> tuple:
    get = (lambda name: getattr(row, name)) if isinstance(row, IpcBnsMapping) else row.get
    return (get("ipc_section"), get("bns_section"))


def load_ipc_bns_mapping(
    db: Session,
    csv_path: Path | None = None,
    *,
    source: str = CYTRAIN,
    dry_run: bool = False,
) -> dict:
    """Insert missing IPC-BNS mapping rows of one source from its CSV."""
    if source not in SOURCE_FILES:
        raise ValueError(f"unknown mapping source: {source}")
    path = Path(csv_path) if csv_path else SOURCE_FILES[source]
    if not path.exists():
        raise FileNotFoundError(f"IPC-BNS mapping CSV not found: {path}")

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"IPC-BNS mapping CSV has no header row: {path}")
        columns = {name.strip() for name in reader.fieldnames}
        missing = REQUIRED_SOURCE_COLUMNS[source] - columns
        if missing:
            raise ValueError(
                f"IPC-BNS mapping CSV is missing columns: {', '.join(sorted(missing))}"
            )
        source_rows = list(reader)

    existing_rows = db.query(IpcBnsMapping).all()
    existing = {_mapping_key(row) for row in existing_rows if row.source == source}
    other_sources = {_pair(row): row.source for row in existing_rows if row.source != source}
    collisions: list[str] = []
    pending: list[IpcBnsMapping] = []
    rejected: Counter[str] = Counter()
    skipped_existing = 0
    normalized_values = 0
    exact_duplicates = 0
    seen_in_file: set[tuple] = set()

    for raw in source_rows:
        ipc_section = normalize_section_field(raw.get("ipc_section"))
        bns_section = normalize_section_field(raw.get("bns_section"))
        normalized_values += int(ipc_section != _blank_to_none(raw.get("ipc_section")))
        normalized_values += int(bns_section != _blank_to_none(raw.get("bns_section")))
        ipc_description = _blank_to_none(raw.get("ipc_description"))
        change_type = (_blank_to_none(raw.get("change_type")) or "").upper() or None
        if not ipc_section or not ipc_description or (source == CYTRAIN and not change_type):
            rejected["missing_required_field"] += 1
            continue
        if change_type is not None and change_type not in ALLOWED_CHANGE_TYPES:
            rejected["invalid_change_type"] += 1
            continue
        source_page = None
        if source == NCRB_T1A4:
            page = _blank_to_none(raw.get("source_page"))
            if not page or not page.isdigit():
                rejected["missing_source_page"] += 1
                continue
            source_page = int(page)
        parsed = {
            "ipc_section": ipc_section,
            "ipc_description": ipc_description,
            "bns_section": bns_section,
            "bns_description": _blank_to_none(raw.get("bns_description")),
            "change_type": change_type,
            "source": source,
            "source_page": source_page,
        }
        if any(parsed[name] and len(parsed[name]) > limit for name, limit in FIELD_LIMITS.items()):
            rejected["field_too_long"] += 1
            continue
        key = _mapping_key(parsed)
        if key in seen_in_file:
            exact_duplicates += 1  # identical repeat (the key is the whole row): loaded once
            skipped_existing += 1
            continue
        seen_in_file.add(key)
        if key in existing:
            skipped_existing += 1
            continue
        if _pair(parsed) in other_sources:
            # Never change, duplicate or shadow a row of the other source; report it instead.
            collisions.append(f"{ipc_section} -> {bns_section} (exists as {other_sources[_pair(parsed)]})")
            continue
        pending.append(IpcBnsMapping(**parsed))

    if pending and not dry_run:
        db.add_all(pending)
        db.commit()

    return {
        "source": source,
        "source_rows": len(source_rows),
        "inserted": 0 if dry_run else len(pending),
        "would_insert": len(pending),
        "skipped_existing": skipped_existing,
        "skipped_invalid": sum(rejected.values()),
        "rejected": dict(sorted(rejected.items())),
        "normalized_section_values": normalized_values,
        "exact_duplicate_in_file": exact_duplicates,
        "db_rows_not_in_source": len(existing - seen_in_file),
        "collisions": sorted(collisions),
    }


def main(argv: list[str] | None = None) -> int:
    from backend.scripts.reconcile_common import resolve_database

    parser = argparse.ArgumentParser(description="Load IPC-BNS mappings into PostgreSQL.")
    parser.add_argument("--source", choices=("all", "cytrain", "ncrb"), default="all")
    parser.add_argument("--csv", dest="csv_path", type=Path, default=None, help="Override the CSV (only with one --source).")
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the target database URL.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url, database = resolve_database(args.database_url_env, confirm_dev=args.confirm_dev, write=not args.dry_run)
    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    sources = {"all": [CYTRAIN, NCRB_T1A4], "cytrain": [CYTRAIN], "ncrb": [NCRB_T1A4]}[args.source]
    if args.csv_path and len(sources) != 1:
        parser.error("--csv needs a single --source")
    try:
        results = [load_ipc_bns_mapping(db, args.csv_path, source=source, dry_run=args.dry_run) for source in sources]
    finally:
        db.close()
        engine.dispose()
    print(f"IPC-BNS load database={database}" + (" (dry-run)" if args.dry_run else ""))
    for stats in results:
        for key, value in stats.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
