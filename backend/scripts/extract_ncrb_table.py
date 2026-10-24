"""Extract NCRB Crime in India 2024, Table 1A.4 (State/UT-wise) from the official Volume I PDF.

Table-aware and reproducible: no OCR, no guessing. The table is a vector PDF
whose grid is drawn as thin filled rectangles (cell borders), so for every page:

- data columns are the cells between the vertical borders of the sub-header
  row (IPC / BNS / Total / V / R, or the page's own variant), each identified
  by its printed column index ``[n]``;
- a crime head is the set of columns under the lowest header cell above the
  sub-header row; wider cells above it are its parents (for example "Murder",
  "Hurt" > "Simple Hurt") and the top cell is the crime group;
- header words are placed in the cell bounded by the nearest borders around
  them, so wrapped head names are joined in reading order;
- each numeric word is assigned to the column whose cell contains it, and to
  the State/UT row whose value line it sits on (multi-line names such as
  "D&N Haveli and Daman & Diu" are joined).

Values are copied exactly as printed; a blank cell stays NULL (never 0).

Outputs (``--out-dir``, default data/processed/ncrb/):
- ``ncrb_2024_table_1A4_v2_cells.csv``: one row per printed cell (page,
  column index, state, head, sub-column, value), the audit trail;
- ``ncrb_stats_2024_v2.csv``: one row per (State/UT, crime head), in the
  loader's format (``load_ncrb.py``) plus provenance columns.

Page mapping (verified, docs/analytics/NCRB_CORRECTION.md): table page n is PDF
page n + 47 in ``data/raw/ncrb/vol1-crimeinindia2024.pdf``. PDF page 108 is
table page 61 although NCRB printed its footer as "Page 51 of 79".

Usage:
    .venv/bin/python backend/scripts/extract_ncrb_table.py [--pdf PATH] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.load_ncrb import aggregate_type  # noqa: E402

DEFAULT_PDF = REPO_ROOT / "data/raw/ncrb/vol1-crimeinindia2024.pdf"
DEFAULT_OUT_DIR = REPO_ROOT / "data/processed/ncrb"
EXPECTED_SHA256 = "5c119c907c8b194e0bcde8cf6ef63392ff9923dfb159a8780607f54719a79cb8"
YEAR = 2024
TABLE_PAGES = 79
PDF_OFFSET = 47  # table page n = PDF page n + 47
SUBCOLUMNS = {"IPC", "BNS", "Total", "V", "R", "IPC+BNS"}
NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
EXTRACTOR_VERSION = "ncrb-1a4-grid-v1"


@dataclass
class Column:
    index: int  # printed column number [n]
    x0: float
    x1: float
    sub: str = ""


@dataclass
class Head:
    columns: list[Column]
    labels: list[str] = field(default_factory=list)  # top (group) .. bottom (head) cell texts

    @property
    def x0(self) -> float:
        return self.columns[0].x0

    @property
    def x1(self) -> float:
        return self.columns[-1].x1


def _borders(page: Any) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """(horizontal: y, x0, x1), (vertical: x, y0, y1) from the thin border rectangles."""
    horizontal, vertical = [], []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] != "re":
                continue
            rect = item[1]
            if rect.height <= 1.5 and rect.width > 2:
                horizontal.append(((rect.y0 + rect.y1) / 2, rect.x0, rect.x1))
            elif rect.width <= 1.5 and rect.height > 2:
                vertical.append(((rect.x0 + rect.x1) / 2, rect.y0, rect.y1))
    return horizontal, vertical


def _cell_of(x: float, y: float, horizontal: list, vertical: list) -> tuple[float, float, float, float]:
    """The grid cell (x0, y0, x1, y1) containing a point, from the nearest borders around it."""
    left = max((vx for vx, vy0, vy1 in vertical if vx <= x and vy0 - 0.5 <= y <= vy1 + 0.5), default=0.0)
    right = min((vx for vx, vy0, vy1 in vertical if vx >= x and vy0 - 0.5 <= y <= vy1 + 0.5), default=1e9)
    top = max((hy for hy, hx0, hx1 in horizontal if hy <= y and hx0 - 0.5 <= x <= hx1 + 0.5), default=0.0)
    bottom = min((hy for hy, hx0, hx1 in horizontal if hy >= y and hx0 - 0.5 <= x <= hx1 + 0.5), default=1e9)
    return (round(left, 1), round(top, 1), round(right, 1), round(bottom, 1))


def _join(words: list[tuple]) -> str:
    """Words in reading order (by line, then x), joined with single spaces."""
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda w: (round(w[1], 0), w[0])):
        if lines and abs(lines[-1][0][1] - word[1]) < 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    text = " ".join(" ".join(w[4] for w in sorted(line, key=lambda w: w[0])) for line in lines)
    return re.sub(r"\s+", " ", text).strip()


def parse_page(page: Any, pdf_page: int) -> tuple[list[Head], list[dict]]:
    words = page.get_text("words")
    horizontal, vertical = _borders(page)
    index_words = [w for w in words if re.fullmatch(r"\[\d+\]", w[4])]
    index_top = min(w[1] for w in index_words)
    sub_words = [w for w in words if w[4] in SUBCOLUMNS and index_top - 30 < w[1] < index_top]
    sub_top = min(w[1] for w in sub_words) - 2
    # Data columns: cells between vertical borders on the sub-header line.
    sub_y = (sub_top + index_top) / 2
    xs = sorted({round(vx, 1) for vx, vy0, vy1 in vertical if vy0 - 0.5 <= sub_y <= vy1 + 0.5})
    columns: list[Column] = []
    for left, right in zip(xs, xs[1:]):
        label = [w for w in index_words if left <= (w[0] + w[2]) / 2 <= right]
        if len(label) != 1:
            continue
        number = int(label[0][4].strip("[]"))
        if number <= 2:
            continue  # [1] SL, [2] State/UT
        sub = [w[4] for w in sub_words if left <= (w[0] + w[2]) / 2 <= right]
        columns.append(Column(number, left, right, sub[0] if sub else ""))
    columns.sort(key=lambda c: c.x0)

    # Header cells: every header word is placed in the cell around it.
    header_top = min(hy for hy, hx0, hx1 in horizontal if hy < 100 and hx1 - hx0 > 300)  # the table's top border
    cells: dict[tuple, list] = {}
    for w in words:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if header_top < cy < sub_top and cx > columns[0].x0 - 1:
            cells.setdefault(_cell_of(cx, cy, horizontal, vertical), []).append(w)

    # Heads: the lowest header cell above the sub-header row covers exactly one head's columns.
    heads: list[Head] = []
    for column in columns:
        cx = (column.x0 + column.x1) / 2
        owners = [cell for cell in cells if cell[0] - 0.5 <= cx <= cell[2] + 0.5]
        lowest = max(owners, key=lambda cell: cell[1])
        if heads and heads[-1].labels and heads[-1].labels[-1] == lowest:
            heads[-1].columns.append(column)
        else:
            heads.append(Head([column], labels=[lowest]))
    for head in heads:
        lowest = head.labels[0]
        stack = sorted(
            (cell for cell in cells if cell[0] - 0.5 <= head.x0 + 1 and cell[2] + 0.5 >= head.x1 - 1 and cell[3] <= lowest[3] + 0.5),
            key=lambda cell: cell[1],
        )
        head.labels = [_join(cells[cell]) for cell in stack]

    # Rows: value lines below the index row; names in the SL / State columns.
    data_words = [w for w in words if w[1] > index_top + 8 and not w[4].startswith("●")]
    # The footer starts at the first bullet, footnote asterisk or "TABLE 1A.4 Page n of 79" word below the data.
    footer = min(
        (w[1] for w in words if w[1] > index_top + 8 and (w[4] in ("●", "TABLE") or w[4].startswith("*"))),
        default=1e9,
    )
    data_words = [w for w in data_words if w[1] < footer - 1]
    first_data_x = columns[0].x0
    value_words = [w for w in data_words if (w[0] + w[2]) / 2 > first_data_x and NUMBER.match(w[4])]
    lines: list[list[tuple]] = []
    for w in sorted(value_words, key=lambda w: w[1]):
        if lines and abs(lines[-1][0][1] - w[1]) < 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    name_words = [w for w in data_words if (w[0] + w[2]) / 2 < first_data_x]
    rows: list[dict] = []
    centers = [sum((v[1] + v[3]) / 2 for v in line) / len(line) for line in lines]
    assigned: dict[int, list] = {i: [] for i in range(len(lines))}
    for w in name_words:
        cy = (w[1] + w[3]) / 2
        if not lines or w[4].endswith(":"):
            continue  # "STATES:" / "UNION TERRITORIES:" captions
        nearest = min(range(len(lines)), key=lambda i: abs(centers[i] - cy))
        if abs(centers[nearest] - cy) <= 12:
            assigned[nearest].append(w)
    for i, line in enumerate(lines):
        names = assigned[i]
        sl_words = [w for w in names if w[2] <= 52.5 and w[4].isdigit()]
        label_words = [w for w in names if w not in sl_words]
        values: dict[int, str] = {}
        for w in line:
            cx = (w[0] + w[2]) / 2
            column = next((c for c in columns if c.x0 <= cx <= c.x1), None)
            if column is None:
                raise ValueError(f"pdf {pdf_page}: value {w[4]!r} at x={cx:.1f} is outside every column")
            if column.index in values:
                raise ValueError(f"pdf {pdf_page}: two values in column [{column.index}] on one row")
            values[column.index] = w[4]
        rows.append({"sl": sl_words[0][4] if sl_words else "", "state": _join(label_words), "values": values})
    return heads, rows


CITATION_START = re.compile(r"\(\s*(?=Sec|\d)")
KEYWORD = re.compile(r"\b(BNS|IPC)\b((?:\s*r/w\s*IT\s*Act|/IT(?:\s*Act)?)?)")


def _balanced(value: str) -> str:
    """Drop only unbalanced brackets at the ends ("(Section 72(1)" -> "72(1)"), never a section's own."""
    value = value.strip()
    while value.startswith("(") and value.count("(") > value.count(")"):
        value = value[1:].strip()
    while value.endswith(")") and value.count(")") > value.count("("):
        value = value[:-1].strip()
    return value


def _clean_section(value: str) -> str:
    value = re.sub(r"\bSec(?:tions?|\.)?\s*", "", value)
    value = _balanced(value.lstrip(" /,&)").strip(" /,&"))  # ") & (Section 327-331 IPC)": a separator, not data
    value = _balanced(value.strip(" /,&"))
    value = re.sub(r"(\d)-\s+(\d)", r"\1-\2", value)  # line-wrap hyphen: "379- 382" -> "379-382"
    value = re.sub(r"\s+\(", "(", value)  # "103 (1)" -> "103(1)"
    value = re.sub(r"\(\s+", "(", value)
    return re.sub(r"\s+", " ", value).strip()


def split_citation(text: str) -> tuple[str, str | None, str | None]:
    """(name, ipc_section, bns_section): the printed '(Section ... BNS/Section ... IPC)' moved out of the name.

    Handles NCRB's printed variants: "Sec"/"Sec."/"Sections", no slash between the two parts, unbalanced
    brackets ("(Section 308 BNS)/Section 384-389 IPC)"), "r/w IT Act" suffixes. A citation cut off by the
    source (no BNS/IPC keyword) is dropped from the name and yields no sections: nothing is guessed.
    """
    start = CITATION_START.search(text)
    if not start:
        return text.strip(), None, None
    rest = text[start.start():]
    keywords = list(KEYWORD.finditer(rest))
    if not keywords:
        return text[: start.start()].strip(), None, None
    end = keywords[-1].end()
    while rest[end:].lstrip().startswith(")"):
        end = len(rest) - len(rest[end:].lstrip()) + 1
    name = re.sub(r"\s+", " ", (text[: start.start()] + " " + rest[end:]).strip())
    values: dict[str, str] = {}
    previous: str | None = None
    position = 0
    for match in keywords:
        segment = rest[position : match.start()]
        position = match.end()
        pieces = [piece for piece in re.split(r"/\s*(?=Sec)", segment) if piece.strip(" /()&,")]
        if previous and len(pieces) > 1:
            # "353 BNS/ Section 353 r/w IT Act/Section 505 IPC": the middle piece still belongs to BNS.
            for piece in pieces[:-1]:
                extra = _clean_section(piece)
                if extra:
                    values[previous] = f"{values[previous]}{'/' if extra[:1].isdigit() else ' '}{extra}"
            pieces = pieces[-1:]
        suffix = re.sub(r"\s+", " ", match.group(2)).strip()
        value = _clean_section(" ".join(pieces)) + ((" " if suffix.startswith("r/w") else "") + suffix if suffix else "")
        if value.strip():
            values[match.group(1)] = value.strip()
        previous = match.group(1) if value.strip() else previous
    return name, values.get("IPC"), values.get("BNS")


def head_name(labels: list[str]) -> tuple[str, str, str | None, str | None]:
    """(crime_group, offense_category, ipc_section, bns_section) from the cell stack.

    The name is the parents and the head joined with " - ", with citations moved to the section columns
    and nothing else changed. A head without its own citation inherits its nearest parent's.
    """
    group, *rest = labels
    split = [split_citation(text) for text in rest]
    parts: list[str] = []
    for name, _ipc, _bns in split:
        body = re.sub(r"^(?:[a-z]{1,4}\)|[A-Z]\.)\s*", "", name)  # the "a)" / "A." marker is not a bracket
        if body.count(")") > body.count("("):
            name = re.sub(r"\s*\)$", "", name)  # a stray ")" printed by NCRB
        parent = re.sub(r"^[a-z]{1,4}\)\s*", "", parts[-1]) if parts else None
        if parts and (name.startswith(parts[-1]) or (parent and name.startswith(parent))):
            # The subtotal head repeats its parent ("Murder" over "Murder (Total a+b+c)", "a) Fraud" over
            # "Fraud (Total i+ii+iii+iv)"): keep the parent's letter and the head's own wording.
            marker = parts[-1][: len(parts[-1]) - len(parent)] if parent and not name.startswith(parts[-1]) else ""
            parts[-1] = marker + name
        elif name:
            parts.append(name)
    ipc = bns = None
    for _name, own_ipc, own_bns in reversed(split):
        if own_ipc or own_bns:
            ipc, bns = own_ipc, own_bns
            break
    return group, " - ".join(parts) if parts else group, ipc, bns


def extract(pdf_path: Path) -> tuple[list[dict], list[dict]]:
    import pymupdf

    cells_out, stats_out = [], []
    with pymupdf.open(pdf_path) as document:
        for table_page in range(1, TABLE_PAGES + 1):
            pdf_page = table_page + PDF_OFFSET
            page = document[pdf_page - 1]
            text = page.get_text()
            if "State/UT-wise" not in text or "TABLE 1A.4" not in text:
                raise ValueError(f"pdf page {pdf_page} is not Table 1A.4 (State/UT-wise)")
            heads, rows = parse_page(page, pdf_page)
            for head in heads:
                group, offense_category, ipc_section, bns_section = head_name(head.labels)
                by_sub = {c.sub: c for c in head.columns}
                count_column = by_sub.get("Total") or by_sub.get("IPC+BNS") or by_sub.get("IPC") or by_sub.get("BNS")
                for row in rows:
                    state = row["state"]
                    for column in head.columns:
                        raw = row["values"].get(column.index)
                        cells_out.append({
                            "year": YEAR, "pdf_page": pdf_page, "table_page": table_page, "column": column.index,
                            "sub_column": column.sub, "sl": row["sl"], "state": state, "crime_group": group,
                            "offense_category": offense_category, "head_printed": " > ".join(head.labels[1:]),
                            "value": "" if raw is None else raw,
                        })
                    value = lambda sub: row["values"].get(by_sub[sub].index) if sub in by_sub else None  # noqa: E731
                    kind = aggregate_type(state, offense_category)
                    stats_out.append({
                        "year": YEAR, "state": state, "offense_category": offense_category,
                        "ipc_section": ipc_section or "", "bns_section": bns_section or "",
                        "case_count": row["values"].get(count_column.index, "") if count_column else "",
                        "conviction_count": "", "acquittal_count": "",
                        "cases_ipc": value("IPC") or "", "cases_bns": value("BNS") or "", "cases_total": value("Total") or "",
                        "cases_ipc_plus_bns": value("IPC+BNS") or "", "victims": value("V") or "", "rate": value("R") or "",
                        "case_count_column": f"[{count_column.index}] {count_column.sub}" if count_column else "",
                        "crime_group": group, "head_printed": " > ".join(head.labels[1:]), "sl": row["sl"],
                        "source_pdf_page": pdf_page, "table_page": table_page,
                        "columns": " ".join(f"[{c.index}]" for c in head.columns),
                        "is_aggregate": "TRUE" if kind else "FALSE", "aggregate_type": kind or "",
                        "extractor_version": EXTRACTOR_VERSION,
                    })
    return cells_out, stats_out


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")  # LF, as git stores it
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"refusing: {args.pdf} sha256 {digest} is not the recorded Volume I ({EXPECTED_SHA256})")
    cells, stats = extract(args.pdf)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "ncrb_2024_table_1A4_v2_cells.csv", cells)
    write_csv(args.out_dir / "ncrb_stats_2024_v2.csv", stats)
    heads = {(row["table_page"], row["offense_category"]) for row in stats}
    states = sorted({row["state"] for row in stats})
    print(f"extracted {len(cells)} cells, {len(stats)} (state, head) rows, {len(heads)} heads, {len(states)} state rows from {args.pdf.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
