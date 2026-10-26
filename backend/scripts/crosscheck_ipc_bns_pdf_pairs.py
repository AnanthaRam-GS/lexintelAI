"""Cross-check every IPC/BNS correspondence printed in NCRB Table 1A.4 against ipc_bns_mapping (step 19, read-only).

NCRB prints, for each crime head, the IPC sections and the BNS sections that the head counts, e.g. "Theft (Section
303, 305-307 BNS / Section 379-382 IPC)". That is a head-level correspondence (a set of IPC sections against a set of
BNS sections), not a section-by-section one, so nothing here pairs individual sections the PDF does not pair.

For every head that prints both sides, and for each IPC section it lists (the labels stored in
``ncrb_stats.ipc_section_labels``, which must equal the parsed printed text), the mapping is checked:

- ``covered``: a mapping row links that IPC section to one of the BNS sections printed for the head;
- ``missing``: the mapping has no row for that IPC section;
- ``differs``: the mapping maps it, but only to BNS sections not printed for this head (a possible contradiction,
  reported with the page; neither side is changed).

Evidence level. Many mapping rows carry a group IPC label from the old NCRB CSV ("177 to 188, 190, …, 255, 256"), and
each such row's BNS section belongs to only one section of the group, which the stored mapping no longer records. A
status is ``exact`` when it rests on rows whose IPC label is that single section, and ``group`` when only group-label
rows support it (so ``covered (group)`` and ``differs (group)`` are weaker and cannot be pinned to the section).

Mapping rows are compared by statute-qualified section labels (``ncrb_sections.section_labels``), so the mapping's
group labels ("305, 306") and clause forms ("65(1)") match the NCRB labels.

Outputs (``--out-dir``): ``crosscheck.md`` (per head and per section) and ``pdf_pair_candidates.csv``: for each head
with a missing IPC section, one candidate row per printed BNS section, in the mapping's own convention (the printed IPC
group as ``ipc_section``, one BNS section per row), with the printed head as both descriptions, ``change_type`` left
empty (no source gives one) and the PDF page as attribution. Candidates are not loaded anywhere.

Usage:
    .venv/bin/python backend/scripts/crosscheck_ipc_bns_pdf_pairs.py --database-url-env DATABASE_URL --out-dir <dir>
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.ncrb_sections import row_labels, section_labels  # noqa: E402
from backend.scripts.load_ipc_bns import normalize_section_field  # noqa: E402
from backend.scripts.reconcile_common import REPO_ROOT, connect, resolve_database  # noqa: E402

V2_CSV = REPO_ROOT / "data/processed/ncrb/ncrb_stats_2024_v2.csv"
MAPPING_CSV = REPO_ROOT / "data/processed/ipc_bns/ipc_bns_mapping.csv"
ATTRIBUTION = "NCRB Crime in India 2024, Vol. I, Table 1A.4, p. {page}"
CANDIDATE_FIELDS = ("ipc_section", "ipc_description", "bns_section", "bns_description", "change_type", "source", "pdf_page")


def printed_heads() -> dict[str, dict[str, Any]]:
    """One entry per crime head: printed text, table and PDF pages (first State/UT row, as every row repeats them)."""
    heads: dict[str, dict[str, Any]] = {}
    with V2_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            heads.setdefault(row["offense_category"], {
                "head_printed": row["head_printed"],
                "ipc_section": normalize_section_field(row["ipc_section"]),
                "bns_section": normalize_section_field(row["bns_section"]),
                "table_page": int(row["table_page"]),
                "pdf_page": int(row["source_pdf_page"]),
            })
    return heads


def stored_labels(cursor: Any) -> dict[str, tuple[list[str] | None, list[str] | None, set[tuple[str, str]]]]:
    """Per head: the stored label lists (identical on every row of the head) and the printed texts seen."""
    cursor.execute("SELECT offense_category, ipc_section, bns_section, ipc_section_labels, bns_section_labels FROM ncrb_stats WHERE year = 2024")
    labels: dict[str, tuple[list[str] | None, list[str] | None, set[tuple[str, str]]]] = {}
    variants: dict[str, set[tuple[Any, Any]]] = defaultdict(set)
    for head, ipc, bns, ipc_labels, bns_labels in cursor.fetchall():
        variants[head].add((tuple(ipc_labels or []), tuple(bns_labels or [])))
        labels[head] = (ipc_labels, bns_labels, set())
        labels[head][2].add((ipc or "", bns or ""))
    inconsistent = sorted(head for head, seen in variants.items() if len(seen) > 1)
    if inconsistent:
        raise SystemExit(f"stored labels differ between rows of the same head: {inconsistent}")
    return labels


def mapping_index() -> tuple[dict[str, dict[str, set[str]]], int]:
    """IPC label -> {"exact": BNS labels from single-section rows, "group": BNS labels from group-label rows}.

    REPEALED / no-equivalent rows map to no BNS label but still make the IPC section known to the mapping."""
    index: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"exact": set(), "group": set()})
    with MAPPING_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        ipc_labels, _ = section_labels(row["ipc_section"], "IPC")
        bns_labels, _ = section_labels(row["bns_section"], "BNS") if row["bns_section"] else ([], [])
        level = "exact" if len(ipc_labels) == 1 else "group"
        for ipc in ipc_labels:
            index[ipc][level].update(bns_labels)
    return index, len(rows)


def crosscheck(heads: dict[str, dict[str, Any]], stored: dict[str, Any], mapping: dict[str, set[str]]) -> list[dict[str, Any]]:
    results = []
    for head, info in sorted(heads.items(), key=lambda item: (item[1]["table_page"], item[0])):
        ipc_stored, bns_stored, _texts = stored.get(head, (None, None, set()))
        ipc_parsed, bns_parsed, _notes = row_labels(info["ipc_section"], info["bns_section"])
        if (ipc_stored or None, bns_stored or None) != (ipc_parsed, bns_parsed):
            raise SystemExit(f"{head}: stored labels {ipc_stored}/{bns_stored} differ from the printed text's {ipc_parsed}/{bns_parsed}")
        entry = {"head": head, **info, "ipc_labels": ipc_parsed or [], "bns_labels": bns_parsed or [], "sections": []}
        if ipc_parsed and bns_parsed:
            printed_bns = set(bns_parsed)
            for ipc in ipc_parsed:
                if ipc not in mapping:
                    entry["sections"].append({"ipc": ipc, "status": "missing", "level": "", "mapped_bns": [], "matching": []})
                    continue
                exact, group = mapping[ipc]["exact"], mapping[ipc]["group"]
                if exact & printed_bns:
                    status, level = "covered", "exact"
                elif group & printed_bns:
                    status, level = "covered", "group"
                else:
                    status, level = "differs", "exact" if exact else "group"
                mapped = exact | group
                entry["sections"].append({"ipc": ipc, "status": status, "level": level, "mapped_bns": sorted(mapped), "matching": sorted(mapped & printed_bns)})
        entry["status"] = (
            "not a pair (one side printed)" if not (ipc_parsed and bns_parsed)
            else "differs" if any(s["status"] == "differs" for s in entry["sections"])
            else "missing" if any(s["status"] == "missing" for s in entry["sections"])
            else "covered"
        )
        results.append(entry)
    return results


def candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for entry in results:
        if not any(section["status"] == "missing" for section in entry["sections"]):
            continue
        for bns in entry["bns_labels"]:
            rows.append({
                "ipc_section": entry["ipc_section"],
                "ipc_description": entry["head_printed"],
                "bns_section": bns.removeprefix("BNS "),
                "bns_description": entry["head_printed"],
                "change_type": "",
                "source": ATTRIBUTION.format(page=entry["table_page"]),
                "pdf_page": entry["pdf_page"],
            })
    return rows


def write_report(results: list[dict[str, Any]], rows: list[dict[str, Any]], mapping_rows: int, path: Path) -> dict[str, int]:
    per_head = defaultdict(int)
    per_section = defaultdict(int)
    for entry in results:
        per_head[entry["status"]] += 1
        for section in entry["sections"]:
            per_section[section["status"] + (f" ({section['level']})" if section["level"] else "")] += 1
    lines = [
        "# NCRB Table 1A.4 printed IPC/BNS correspondences vs ipc_bns_mapping",
        "",
        f"Mapping rows: {mapping_rows}. Crime heads: {len(results)}.",
        "",
        "| Heads | Count |", "|---|---:|", *[f"| {k} | {v} |" for k, v in sorted(per_head.items())],
        "",
        "| IPC sections in printed pairs | Count |", "|---|---:|", *[f"| {k} | {v} |" for k, v in sorted(per_section.items())],
        "",
        "| Table p. (PDF p.) | Crime head | Printed IPC | Printed BNS | Status | Per IPC section |",
        "|---|---|---|---|---|---|",
    ]
    for entry in results:
        detail = "; ".join(
            f"{s['ipc'].removeprefix('IPC ')}: {s['status']}" + (f" ({s['level']})" if s["level"] == "group" else "")
            + (f" [mapping: {', '.join(x.removeprefix('BNS ') for x in s['mapped_bns'][:6])}{'…' if len(s['mapped_bns']) > 6 else ''}]" if s["status"] == "differs" else "")
            for s in entry["sections"]
        ) or "—"
        lines.append(
            f"| {entry['table_page']} ({entry['pdf_page']}) | {entry['head']} | {entry['ipc_section'] or '—'} | {entry['bns_section'] or '—'} | {entry['status']} | {detail} |"
        )
    lines += ["", f"Candidate rows for missing sections (not loaded): {len(rows)}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {**{f"heads_{k}": v for k, v in per_head.items()}, **{f"sections_{k}": v for k, v in per_section.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    url, _name = resolve_database(args.database_url_env, confirm_dev=False, write=False)
    connection = connect(url, readonly=True)
    try:
        with connection.cursor() as cursor:
            stored = stored_labels(cursor)
    finally:
        connection.close()
    mapping, mapping_rows = mapping_index()
    results = crosscheck(printed_heads(), stored, mapping)
    rows = candidates(results)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "pdf_pair_candidates.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    counts = write_report(results, rows, mapping_rows, args.out_dir / "crosscheck.md")
    print({**counts, "candidate_rows": len(rows)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
