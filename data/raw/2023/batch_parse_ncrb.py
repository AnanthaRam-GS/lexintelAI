"""
Batch-converts NCRB "Crime in India" Excel table exports (2020-2024) into
one standardised, long-format dataset.

EXPECTED FOLDER LAYOUT
-----------------------
Two layouts are supported.

1) Year sub-folders (use this once you have more than one year):
    data/
      2020/  TABLE1A12.xlsx  TABLE1A22.xlsx  ...
      2021/  ...
      2024/  TABLE1A41.xlsx  ...
   Year is taken from the sub-folder name.

2) Flat folder, single year (what you use while you only have one
   year's files, e.g. a folder with just the 5 Table-1A xlsx files for
   2023): pass --year explicitly, since NCRB filenames don't reliably
   embed the year (2023's "TABLE1A4.xlsx" has no year in the name at
   all, unlike 2024's "TABLE1A41.xlsx"):
       python batch_parse_ncrb.py --input-dir . --output-dir out --year 2023

table_id is always taken from the filename (without extension).

WHY AUTO-DETECTION (not fixed row numbers)
-------------------------------------------
NCRB's report format is NOT stable across years or tables:
  - Simple tables (e.g. "Total Complaints, State/UT-wise") have 2-3 header
    levels and a single block spanning the sheet.
  - Crime-head-wise tables (e.g. this-repo's TABLE1A41.xlsx) have 4-5
    header levels and are split into ~80 repeating "page" blocks.
  - Metric columns changed with the IPC -> BNS transition: 2020-2023
    files are IPC-only; 2024 files usually have IPC / BNS / Total / V / R.
So instead of hardcoding row numbers, this script *finds* the header rows
and block boundaries in each file, and falls back to per-file error
logging rather than crashing the whole batch when a table doesn't match
the expected shape.

OUTPUT
------
  standardised_ncrb_2020_2024.csv   - one long/tidy table, all years, all
                                       tables, ready to COPY into Postgres.
  parse_report.csv                  - one row per input file: rows parsed,
                                       OR the error, so you can see at a
                                       glance which files need a look.

USAGE
-----
  python batch_parse_ncrb.py --input-dir ./data --output-dir ./out
"""
import argparse
import ast
import re
import sys
import traceback
from pathlib import Path

import openpyxl
import pandas as pd

# ----------------------------------------------------------------------
# Tokens used to recognise which row is the "SL/State" label row and
# which row is the "metric" row (IPC/BNS/Total/V/R, or just IPC, or
# I/V/R, etc). Extend these if a table uses different wording.
# ----------------------------------------------------------------------
SL_TOKENS = {"sl", "sl.no", "sl.no.", "s.no", "s.no."}
STATE_TOKENS = {"state/ut", "state / ut", "states/uts", "state/ut name"}
METRIC_TOKENS = {"ipc", "bns", "ipc+bns", "total", "v", "r", "i", "cases",
                  "rate", "victims", "no.", "number"}
COLREF_RE = re.compile(r"^\[\d+\]$")
SECTION_RE = re.compile(r"section[s]?\s+([0-9a-z,\-\s]+?)\s*(ipc|bns)", re.IGNORECASE)
SECTION_REF_RE = re.compile(r"(?:section|sec\.?)[\s.]*(\d+[a-z]*(?:-[a-z0-9]+)?)", re.IGNORECASE)


def clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def build_merged_lookup(ws):
    lookup = {}
    for rng in ws.merged_cells.ranges:
        top_val = ws.cell(row=rng.min_row, column=rng.min_col).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                lookup[(r, c)] = top_val
    return lookup


def mval(ws, lookup, row, col):
    return lookup.get((row, col), ws.cell(row=row, column=col).value)


def find_blocks(ws, max_col):
    """Detect repeating "page" blocks using ONLY row 1 (the table-title
    row, which NCRB repeats once per printed page in these exports).
    Any other row's merges are part of the header hierarchy within a
    block, not a new block boundary - mixing them in causes false splits.
    Falls back to a single block spanning the whole sheet if row 1 has
    only one non-empty run (simple, non-repeating tables)."""
    starts = set()
    merged_row1_cols = set()
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= 1 <= rng.max_row:
            top_val = ws.cell(row=rng.min_row, column=rng.min_col).value
            if top_val not in (None, ""):
                starts.add(rng.min_col)
            merged_row1_cols.update(range(rng.min_col, rng.max_col + 1))
    for c in range(1, max_col + 1):
        if c in merged_row1_cols:
            continue
        if ws.cell(row=1, column=c).value not in (None, ""):
            starts.add(c)

    if not starts:
        return [(1, max_col)]
    starts = sorted(starts)
    starts.append(max_col + 1)
    return [(starts[i], starts[i + 1] - 1) for i in range(len(starts) - 1)]


def detect_header_structure(ws, lookup, b_start, b_end, max_probe_rows=25):
    """Within one block, find:
      - sl_row: row whose first cell (b_start) reads like 'SL'
      - metric_row: the nearest row below sl_row containing metric tokens
      - colref_row: the row right after metric_row if it looks like [1],[2]..
      - header_rows: sl_row..metric_row inclusive (used to build the full
        crime-head hierarchy string)
      - data_start_row: first row after the header block
    Returns None if it can't find a plausible SL row (caller should skip
    or log the file).
    """
    sl_row = None
    for r in range(1, max_probe_rows + 1):
        v = clean(mval(ws, lookup, r, b_start)).lower()
        if v in SL_TOKENS:
            sl_row = r
            break
    if sl_row is None:
        return None

    metric_row = None
    next_row_vals = [clean(mval(ws, lookup, sl_row + 1, c))
                     for c in range(b_start, b_end + 1)]
    if sum(1 for v in next_row_vals if COLREF_RE.match(v)) >= 2:
        metric_row = sl_row
    else:
        for r in range(sl_row + 1, sl_row + max_probe_rows):
            row_vals = [clean(mval(ws, lookup, r, c)).lower()
                        for c in range(b_start, min(b_end, b_start + 15) + 1)]
            token_hits = sum(1 for v in row_vals if v in METRIC_TOKENS)
            if token_hits >= 2:
                metric_row = r
                break
    if metric_row is None:
        # some very simple tables have no separate metric row - the crime
        # head row itself is the last header row before data
        metric_row = sl_row + 1

    colref_row = None
    probe = metric_row + 1
    probe_vals = [clean(ws.cell(row=probe, column=c).value) for c in range(b_start, b_end + 1)]
    if any(COLREF_RE.match(v) for v in probe_vals if v):
        colref_row = probe

    data_start_row = (colref_row or metric_row) + 1
    header_rows = list(range(sl_row, metric_row + 1))
    return {
        "sl_row": sl_row,
        "metric_row": metric_row,
        "colref_row": colref_row,
        "header_rows": header_rows,
        "data_start_row": data_start_row,
    }


def parse_workbook(path, table_id, year, sheet_name=None, verbose=False):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb[wb.sheetnames[0]]
    lookup = build_merged_lookup(ws)
    max_col, max_row = ws.max_column, ws.max_row

    blocks = find_blocks(ws, max_col)
    if verbose:
        print(f"  {len(blocks)} block(s) detected: {blocks[:5]}{' ...' if len(blocks) > 5 else ''}")
    records = []

    for b_start, b_end in blocks:
        struct = detect_header_structure(ws, lookup, b_start, b_end)
        if verbose:
            print(f"  block cols {b_start}-{b_end}: {struct}")
        if struct is None:
            continue  # not a data block (e.g. stray merged title fragment)

        sl_col, state_col = b_start, b_start + 1
        header_rows = struct["header_rows"]
        data_start_row = struct["data_start_row"]
        colref_row = struct["colref_row"]

        section = None
        for r in range(data_start_row, max_row + 1):
            sl_val = clean(ws.cell(row=r, column=sl_col).value)
            state_val = clean(ws.cell(row=r, column=state_col).value)

            if sl_val.endswith(":") or state_val.endswith(":"):
                section = sl_val or state_val
                continue
            if not sl_val and not state_val:
                continue

            is_total = sl_val == "" and state_val.lower().startswith(("total", "grand total"))

            for c in range(b_start + 2, b_end + 1):
                value = ws.cell(row=r, column=c).value
                if value is None:
                    continue
                colref = clean(ws.cell(row=colref_row, column=c).value).strip("[]") if colref_row else None
                header_levels = [clean(mval(ws, lookup, hr, c)) for hr in header_rows]
                metric = header_levels[-1] if header_levels else ""
                crime_levels = header_levels[:-1]

                records.append({
                    "table_id": table_id,
                    "year": year,
                    "source_file": Path(path).name,
                    "section": section,
                    "sl_no": sl_val or None,
                    "state_ut": state_val,
                    "is_total_row": is_total,
                    "global_col_ref": colref,
                    "header_path": " | ".join(x for x in crime_levels if x),
                    "metric": metric,
                    "value": value,
                })

    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df = df.drop_duplicates(subset=["table_id", "year", "state_ut", "global_col_ref", "header_path", "metric", "sl_no"])
    return df


def infer_year_from_path(path: Path, root: Path, year_override=None):
    """Year resolution order:
      1. --year CLI override, if given (needed for flat folders / years
         whose filenames don't embed a year, e.g. 2023's TABLE1A4.xlsx)
      2. the sub-folder of root the file lives directly under, if it
         looks like a 4-digit year
      3. a 4-digit year found in the filename itself (e.g. 2024's
         TABLE1A41.xlsx doesn't have one, but some NCRB files do)
    Returns None (and the file gets flagged in the report) if none of
    these resolve - better than silently mislabelling data."""
    if year_override is not None:
        return year_override
    try:
        rel = path.relative_to(root)
        first_part = rel.parts[0]
        if re.fullmatch(r"20\d{2}", first_part):
            return int(first_part)
    except ValueError:
        pass
    m = re.search(r"(20\d{2})", path.stem)
    return int(m.group(1)) if m else None


def load_ipc_bns_mapping(path):
    if not path.exists():
        return {}
    reference = pd.read_csv(path)
    mapping = {}
    for response in reference.get("response", []):
        try:
            item = ast.literal_eval(response)
        except (ValueError, SyntaxError):
            continue
        ipc_section = clean(item.get("IPC Section"))
        bns_section = clean(item.get("BNS Section"))
        if ipc_section:
            normalized = ipc_section.lower().replace(" ", "")
            mapping[normalized] = bns_section or None
            mapping[normalized.replace("-", "")] = bns_section or None
    return mapping


def extract_ipc_bns_mapping(df, reference_mapping=None):
    if df.empty:
        return pd.DataFrame()
    reference_mapping = reference_mapping or {}
    paths = df["header_path"].dropna().unique()
    rows = []
    for p in paths:
        ipc = []
        bns = []
        for section in SECTION_REF_RE.findall(p):
            normalized = section.lower().replace(" ", "")
            if normalized not in ipc:
                ipc.append(normalized)
            mapped_values = [reference_mapping.get(normalized),
                             reference_mapping.get(normalized.replace("-", ""))]
            if re.fullmatch(r"\d+-\d+", normalized):
                first, last = (int(x) for x in normalized.split("-"))
                mapped_values.extend(reference_mapping.get(str(number))
                                     for number in range(first, last + 1))
            for mapped in mapped_values:
                if mapped and mapped not in bns:
                    bns.append(mapped)
        if bns or ipc:
            rows.append({
                "header_path": p,
                "bns_sections": "; ".join(bns) or None,
                "ipc_sections": "; ".join(ipc) or None,
            })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", required=True, help="Folder of .xlsx files - either year sub-folders, or a flat folder (use --year with a flat folder)")
    ap.add_argument("--output-dir", default="out", help="Where to write the combined CSV + report")
    ap.add_argument("--sheet-name", default=None, help="Sheet name to read if not the first sheet (e.g. CIIReport)")
    ap.add_argument("--ipc-bns-mapping", default="ipc_bns_mapping_standardized.xls",
                    help="CSV-shaped IPC/BNS reference file (despite the .xls extension)")
    ap.add_argument("--year", type=int, default=None, help="Force this year for every file (required for a flat folder whose filenames don't embed a year, e.g. 2023's TABLE1A4.xlsx)")
    ap.add_argument("--verbose", action="store_true", help="Print detected header structure (sl_row/metric_row/data_start_row) per block - use this to debug a file that parses to 0 rows or looks wrong")
    args = ap.parse_args()

    root = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    xlsx_files = sorted(root.rglob("*.xlsx"))
    if not xlsx_files:
        print(f"No .xlsx files found under {root}", file=sys.stderr)
        sys.exit(1)

    all_frames = []
    report_rows = []

    for f in xlsx_files:
        table_id = f.stem
        year = infer_year_from_path(f, root, year_override=args.year)
        if year is None:
            print(f"[warn] {f}  -> could not resolve a year (pass --year to force one); skipping")
            report_rows.append({"file": str(f), "year": None, "table_id": table_id,
                                 "status": "skipped_no_year", "rows_parsed": 0, "error": "no year resolved"})
            continue
        try:
            df = parse_workbook(f, table_id=table_id, year=year, sheet_name=args.sheet_name, verbose=args.verbose)
            all_frames.append(df)
            report_rows.append({"file": str(f), "year": year, "table_id": table_id,
                                 "status": "ok", "rows_parsed": len(df), "error": None})
            print(f"[ok]   {f}  -> {len(df)} rows")
        except Exception as e:
            report_rows.append({"file": str(f), "year": year, "table_id": table_id,
                                 "status": "failed", "rows_parsed": 0,
                                 "error": f"{type(e).__name__}: {e}"})
            print(f"[FAIL] {f}  -> {e}")
            traceback.print_exc(limit=1)

    combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    combined_path = out_dir / "standardised_ncrb_2020_2024.csv"
    combined.to_csv(combined_path, index=False)

    report = pd.DataFrame(report_rows)
    report_path = out_dir / "parse_report.csv"
    report.to_csv(report_path, index=False)

    mapping_reference = load_ipc_bns_mapping(root / args.ipc_bns_mapping)
    mapping = extract_ipc_bns_mapping(combined, mapping_reference)
    mapping_path = out_dir / "ipc_bns_section_mapping.csv"
    mapping.to_csv(mapping_path, index=False)

    print("\n----- SUMMARY -----")
    print(f"Files processed : {len(xlsx_files)}")
    print(f"Succeeded       : {(report['status'] == 'ok').sum()}")
    print(f"Failed          : {(report['status'] == 'failed').sum()}")
    print(f"Total rows      : {len(combined)}")
    print(f"-> {combined_path}")
    print(f"-> {report_path}")
    print(f"-> {mapping_path}")


if __name__ == "__main__":
    main()
