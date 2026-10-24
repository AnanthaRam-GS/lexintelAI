"""Validate an NCRB Table 1A.4 extraction with the table's own arithmetic (re-runnable, read-only).

Checks, for every State/UT row and crime head (the CSV written by extract_ncrb_table.py):

1. row identity: Total = IPC + BNS where all three are printed;
2. column totals, per head and count sub-column (IPC, BNS, Total, IPC+BNS, V):
   sum of the 28 states = TOTAL STATE(S); sum of the 8 UTs = TOTAL UT(S);
   TOTAL STATE(S) + TOTAL UT(S) = TOTAL ALL INDIA;
3. head hierarchy, per State/UT row and count column:
   - a subtotal head "X (Total a+b+c)", "(Total a to g)", "(Total i+ii)" equals the sum of its direct
     children "X - a) ...", and the printed letters match the children found;
   - "Hurt (Simple +Grievous)" equals Simple Hurt + Grievous Hurt;
   - a group total "... (Total)" / "(Total a+b)" equals the group's top-level heads;
   - "Total Cognizable IPC/BNS crimes" equals the group totals plus "Other IPC/BNS crimes";
4. every row's "Total Cognizable IPC/BNS crimes" (IPC, BNS, Total) equals the 2024 figures of Table 1A.1,
   an independent summary table in the same PDF (``--pdf``, PDF page 45).

Every exception is printed with State/UT, head, column, expected, actual and PDF page. Exit status 1 if any
exception is found. The rate column R is a derived figure and is not summed.

Usage:
    .venv/bin/python backend/scripts/validate_ncrb_table.py [--csv PATH] [--pdf PATH]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "data/processed/ncrb/ncrb_stats_2024_v2.csv"
DEFAULT_PDF = REPO_ROOT / "data/raw/ncrb/vol1-crimeinindia2024.pdf"
TOTALS = ("TOTAL STATE(S)", "TOTAL UT(S)", "TOTAL ALL INDIA")
COUNT_COLUMNS = ("cases_ipc", "cases_bns", "cases_total", "cases_ipc_plus_bns", "victims")
GRAND_TOTAL = "Total Cognizable IPC/BNS crimes"
LETTERS = "abcdefghijklmnopqrstuvwxyz"
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]


def number(value: str) -> int | None:
    return int(value) if value not in ("", None) else None


def expected_markers(name: str) -> list[str] | None:
    """Child markers named by a subtotal head: 'a+b+c' -> [a, b, c]; 'a to g' -> [a .. g]; 'i + ii' -> [i, ii]."""
    match = re.search(r"\(Total\s+([^)]*)\)", name)
    if not match or not match.group(1).strip():
        return None
    spec = match.group(1).replace(" ", "")
    if "to" in spec:
        first, last = spec.split("to")
        return list(LETTERS[LETTERS.index(first) : LETTERS.index(last) + 1])
    return spec.split("+")


def load(path: Path) -> tuple[list[str], dict, dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    heads: list[str] = []
    meta: dict[str, dict] = {}
    data: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row["offense_category"] not in meta:
            heads.append(row["offense_category"])
            meta[row["offense_category"]] = {"group": row["crime_group"], "page": row["source_pdf_page"]}
        data[(row["state"], row["offense_category"])] = row
    return heads, meta, data


def hierarchy(heads: list[str], meta: dict) -> list[tuple[str, list[str], str]]:
    """(total head, its component heads, kind)."""
    rules = []
    for head in heads:
        base = re.sub(r"\s*\((?:Total\b[^)]*|Simple \+Grievous)\)\s*$", "", head)
        if head == GRAND_TOTAL:
            continue
        if head.endswith("(Simple +Grievous)"):
            children = [h for h in heads if h.startswith(base + " - ") and " - " not in h[len(base) + 3 :]]
            rules.append((head, children, "sum of parts"))
        elif base != head and " - " in head or (base != head and any(h.startswith(base + " - ") for h in heads)):
            children = [h for h in heads if h.startswith(base + " - ") and " - " not in h[len(base) + 3 :]]
            rules.append((head, children, "subtotal"))
        elif base != head:
            group = meta[head]["group"]
            children = [h for h in heads if meta[h]["group"] == group and " - " not in h and h != head]
            rules.append((head, children, "group total"))
    group_totals = [head for head, _children, kind in rules if kind == "group total"]
    rules.append((GRAND_TOTAL, group_totals + ["Other IPC/BNS crimes"], "grand total"))
    return rules


def marker(name: str) -> str:
    last = name.split(" - ")[-1]
    match = re.match(r"([a-z]+|[ivx]+)\)", last)
    return match.group(1) if match else ""


def table_1a1_rows(pdf: Path) -> dict[str, tuple[int, int, int]]:
    """{State/UT or total row: (IPC 2024, BNS 2024, Total 2024)} from Table 1A.1 (PDF page 45).

    Each row prints: 2022, 2023, IPC 2024, BNS 2024, Total 2024, population, rate, charge-sheeting rate.
    """
    import pymupdf

    with pymupdf.open(pdf) as document:
        lines = [line.strip() for line in document[45 - 1].get_text().splitlines() if line.strip()]
    if not any("1A.1" in line for line in lines):
        raise ValueError("PDF page 45 is not Table 1A.1")
    rows: dict[str, tuple[int, int, int]] = {}
    numeric = lambda value: re.fullmatch(r"\d+(?:\.\d+)?", value) is not None  # noqa: E731
    for index, line in enumerate(lines):
        for span in (1, 2, 3):  # a name may wrap: "D&N Haveli and" / "Daman & Diu"
            name_lines = lines[index : index + span]
            following = lines[index + span : index + span + 8]
            if any(numeric(part) for part in name_lines) or len(following) < 8 or not all(numeric(v) for v in following):
                continue
            name = re.sub(r"^\d+\s+", "", " ".join(name_lines))
            rows.setdefault(name, (int(following[2]), int(following[3]), int(following[4])))
            break
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--json", type=Path, help="also write the results as JSON")
    parser.add_argument("--skip-table-1a1", action="store_true", help="skip check 4 (needs the PDF, which is not committed)")
    args = parser.parse_args(argv)
    heads, meta, data = load(args.csv)
    states = [s for s in dict.fromkeys(state for state, _head in data) if s not in TOTALS]
    sl = {state: int(data[(state, heads[0])]["sl"]) for state in states}
    member = {"TOTAL STATE(S)": [s for s in states if sl[s] <= 28], "TOTAL UT(S)": [s for s in states if sl[s] > 28]}
    exceptions: list[dict] = []
    checked = defaultdict(int)

    def check(kind: str, state: str, head: str, column: str, expected: int, actual: int | None, detail: str = "") -> None:
        checked[kind] += 1
        if actual != expected:
            exceptions.append({"check": kind, "state": state, "head": head, "column": column, "expected": expected,
                               "actual": actual, "pdf_page": meta[head]["page"], "detail": detail})

    for (state, head), row in data.items():
        ipc, bns, total = number(row["cases_ipc"]), number(row["cases_bns"]), number(row["cases_total"])
        if None not in (ipc, bns, total):
            check("row: Total = IPC + BNS", state, head, "Total", ipc + bns, total)
    for head in heads:
        for column in COUNT_COLUMNS:
            if all(data[(s, head)][column] == "" for s in states):
                continue
            for total_row, members in member.items():
                values = [number(data[(s, head)][column]) for s in members]
                if None in values:
                    exceptions.append({"check": "missing value", "state": total_row, "head": head, "column": column,
                                       "expected": None, "actual": None, "pdf_page": meta[head]["page"], "detail": "a member row is blank"})
                    continue
                check(f"column: {total_row} = sum of members", total_row, head, column, sum(values), number(data[(total_row, head)][column]))
            parts = [number(data[(t, head)][column]) for t in ("TOTAL STATE(S)", "TOTAL UT(S)")]
            if None not in parts:
                check("column: ALL INDIA = STATE(S) + UT(S)", "TOTAL ALL INDIA", head, column, sum(parts), number(data[("TOTAL ALL INDIA", head)][column]))

    rules = hierarchy(heads, meta)
    structure = []
    for total_head, children, kind in rules:
        wanted = expected_markers(total_head) if kind == "subtotal" else None
        found = [marker(child) for child in children]
        structure.append({"head": total_head, "kind": kind, "children": len(children), "markers_expected": wanted, "markers_found": found})
        if wanted is not None and found != wanted:
            exceptions.append({"check": "structure: printed letters vs children", "state": "-", "head": total_head, "column": "-",
                               "expected": "+".join(wanted), "actual": "+".join(found), "pdf_page": meta[total_head]["page"], "detail": ""})
        for state in [*states, *TOTALS]:
            total_row = data[(state, total_head)]
            column = "case_count"
            expected_values = [number(data[(state, child)][column]) for child in children]
            if None in expected_values:
                continue
            check(f"hierarchy: {kind}", state, total_head, column, sum(expected_values), number(total_row[column]),
                  detail=" + ".join(children) if state == "TOTAL ALL INDIA" else "")

    printed_1a1 = {} if args.skip_table_1a1 else table_1a1_rows(args.pdf)
    for state in [] if args.skip_table_1a1 else [*states, *TOTALS]:
        row = data[(state, GRAND_TOTAL)]
        if state not in printed_1a1:
            exceptions.append({"check": "Table 1A.1 cross-check", "state": state, "head": GRAND_TOTAL, "column": "-",
                               "expected": None, "actual": None, "pdf_page": 45, "detail": "row not found in Table 1A.1"})
            continue
        for column, expected in zip(("cases_ipc", "cases_bns", "cases_total"), printed_1a1[state]):
            check("Table 1A.1 cross-check (Total Cognizable IPC/BNS crimes)", state, GRAND_TOTAL, column, expected, number(row[column]))
    all_india = number(data[("TOTAL ALL INDIA", GRAND_TOTAL)]["case_count"])

    print(f"validated {args.csv.name}: {len(heads)} heads x {len(states) + 3} rows")
    for kind, count in checked.items():
        failures = sum(1 for item in exceptions if item["check"] == kind)
        print(f"  {kind}: {count} checks, {failures} exceptions")
    print(f"  structure: {sum(1 for item in exceptions if item['check'].startswith('structure'))} exceptions over {len(rules)} total heads")
    print(f"  TOTAL ALL INDIA {GRAND_TOTAL} = {all_india}; Table 1A.1 prints (IPC, BNS, Total) {printed_1a1.get('TOTAL ALL INDIA')}")
    print(f"exceptions: {len(exceptions)}")
    for item in exceptions[:200]:
        print(f"  - [{item['check']}] pdf {item['pdf_page']} | {item['state']} | {item['head']} | {item['column']} | expected {item['expected']} actual {item['actual']} {item['detail'][:160]}")
    if args.json:
        args.json.write_text(json.dumps({"checked": checked, "exceptions": exceptions, "structure": structure}, indent=1) + "\n")
    return 1 if exceptions else 0


if __name__ == "__main__":
    raise SystemExit(main())
