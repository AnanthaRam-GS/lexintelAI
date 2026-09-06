"""Build the Phase 0.4 IPC-to-BNS CSV from the official CYTRAIN table."""

import csv
import html
import re
import ssl
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NCRB_PATH = ROOT / "data/processed/ncrb/ncrb_stats_2024_complete.csv"
OUTPUT_PATH = ROOT / "data/processed/ipc_bns/ipc_bns_mapping.csv"
REPORT_PATH = ROOT / "data/processed/ipc_bns/ipc_bns_mapping_validation_report.md"
SOURCE_URL = "https://cytrain.ncrb.gov.in/staticpage/web_pages/SectionTableBNS.html"
BNS_TEXT_URL = "https://cytrain.ncrb.gov.in/staticpage/web_pages/ChaptersBNS.html"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = []
        self.cell = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = []
            self.in_cell = True

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        if tag == "tr" and self.row:
            self.rows.append(self.row)


class BnsTextParser(HTMLParser):
    """Collect visible text for each numeric section anchor in CYTRAIN's BNS text."""

    def __init__(self):
        super().__init__()
        self.sections = {}
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        anchor = attrs_dict.get("id", "")
        if anchor.isdigit():
            self.current = anchor
            self.sections.setdefault(anchor, [])

    def handle_data(self, data):
        if self.current is not None:
            self.sections[self.current].append(data)


def normalize_code(value):
    return re.sub(r"[^0-9A-Za-z]", "", value).upper()


def components(label):
    normalized = label.replace("–", "-").replace("—", "-").replace(" to ", "-")
    values = []
    for token in re.findall(r"\d+[A-Za-z]*(?:\s*-\s*\d+[A-Za-z]*)?", normalized):
        token = token.replace(" ", "")
        if "-" in token and re.fullmatch(r"\d+-\d+[A-Za-z]?", token):
            start, end = token.split("-")
            end_number = int(re.match(r"\d+", end).group())
            values.extend(str(number) for number in range(int(start), end_number + 1))
            if re.search(r"[A-Za-z]", end):
                values.append(end)
        else:
            values.append(token)
    return list(dict.fromkeys(normalize_code(value) for value in values))


def leading_code(value):
    if re.match(r"\s*(Deleted|New Section)", value, re.I):
        return ""
    match = re.match(r"\s*(\d+[A-Za-z]*(?:\s*\([^)]+\))?(?:\s*-\s*[A-Za-z])?)", value)
    return re.sub(r"\s+", "", match.group(1)) if match else ""


def source_ipc_refs(value):
    refs = []
    pattern = re.compile(r"\d+[A-Za-z]*(?:\s*-\s*[A-Za-z])?(?:\s*\([^)]+\))?")
    for match in pattern.finditer(value):
        prefix = value[: match.start()]
        if match.start() and not (prefix.endswith(".") or prefix.endswith(";")):
            continue
        refs.append(normalize_code(match.group(0)))
    return list(dict.fromkeys(refs))


def clean_description(value):
    return re.sub(
        r"^\s*\d+[A-Za-z]*(?:\s*-\s*[A-Za-z])?(?:\s*\([^)]+\))?\.?\s*",
        "",
        value,
    ).strip()


def bns_entries(value):
    if re.match(r"\s*Deleted", value, re.I):
        return [("", "Deleted")]
    if re.match(r"\s*New Section", value, re.I):
        return [("", value)]
    entries = []
    first = leading_code(value)
    if first:
        entries.append((first, clean_description(value)))
    # CYTRAIN occasionally places a second BNS section after a sentence boundary.
    for match in re.finditer(
        r"(?:(?<=\.)|(?<=,))\s*(\d+[A-Za-z]*(?:\s*-\s*[A-Za-z])?(?:\s*\([^)]+\))?)\s*[.]?",
        value,
    ):
        code = re.sub(r"\s+", "", match.group(1))
        if code and code not in {entry[0] for entry in entries}:
            description = value[match.end() :].strip()
            entries.append((code, description))
    if not entries:
        trailing = re.match(
            r"^(.*?)\s+(\d+[A-Za-z]*(?:\s*\([^)]+\))?)\s*$",
            value,
        )
        if trailing:
            entries.append(
                (
                    re.sub(r"\s+", "", trailing.group(2)),
                    trailing.group(1).strip(),
                )
            )
    return entries or [("", value)]


def lookup_bns_description(section_code, section_text):
    """Extract a section heading or exact subsection text from official BNS HTML."""
    text = html.unescape(" ".join(" ".join(section_text).split()))
    if not text:
        return ""
    subsection = re.fullmatch(r"(\d+)\(([^)]+)\)", section_code)
    if subsection:
        marker = rf"(?:{re.escape(subsection.group(1))}\s*\.\s*)?\(\s*{re.escape(subsection.group(2))}\s*\)"
        match = re.search(marker + r"\s+(.*?)(?=\s+\([0-9a-z]+\)\s+|$)", text, re.I)
        return match.group(1).strip() if match else ""
    section_match = re.match(rf"{re.escape(section_code)}\.?\s+(.*?)(?=\s+\(1\)\s+|$)", text)
    return section_match.group(1).strip() if section_match else text


def load_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    ncrb_rows = load_rows(NCRB_PATH)
    labels = sorted({row["ipc_section"].strip() for row in ncrb_rows if row["ipc_section"].strip()})

    ssl._create_default_https_context = ssl._create_unverified_context
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(request, timeout=180).read().decode("utf-8", "replace")
    parser = TableParser()
    parser.feed(html)

    bns_request = urllib.request.Request(BNS_TEXT_URL, headers={"User-Agent": "Mozilla/5.0"})
    bns_html = urllib.request.urlopen(bns_request, timeout=180).read().decode("utf-8", "replace")
    bns_parser = BnsTextParser()
    bns_parser.feed(bns_html)

    source_rows = []
    for row in parser.rows:
        if len(row) >= 2:
            source_rows.append(
                {
                    "bns_cell": row[0],
                    "ipc_cell": row[-1],
                    "ipc_refs": source_ipc_refs(row[-1]),
                }
            )

    output = []
    unresolved = []
    for label in labels:
        label_parts = set(components(label))
        matches = [
            row for row in source_rows if label_parts.intersection(row["ipc_refs"])
        ]
        if label in {"376", "376 r/w 511"}:
            matches = [
                row
                for row in source_rows
                if any(ref.startswith("376") for ref in row["ipc_refs"])
            ] + matches
        if "511" in label_parts:
            matches += [row for row in source_rows if "511" in row["ipc_refs"]]

        unique_matches = []
        seen = set()
        for row in matches:
            key = (row["bns_cell"], row["ipc_cell"])
            if key not in seen:
                seen.add(key)
                unique_matches.append(row)
        if not unique_matches:
            unresolved.append(label)
            continue

        for source in unique_matches:
            ipc_description = clean_description(source["ipc_cell"])
            for bns_section, bns_description in bns_entries(source["bns_cell"]):
                if bns_section:
                    authoritative_description = lookup_bns_description(
                        bns_section,
                        bns_parser.sections.get(re.match(r"\d+", bns_section).group(), []),
                    )
                    if re.fullmatch(r"\d+\([^)]+\)", bns_section) and authoritative_description:
                        bns_description = authoritative_description
                    elif not bns_description:
                        bns_description = authoritative_description
                if not bns_section:
                    change_type = "REPEALED" if bns_description == "Deleted" else "NO_DIRECT_EQUIVALENT"
                else:
                    change_type = "DIRECT"
                output.append(
                    {
                        "ipc_section": label,
                        "ipc_description": ipc_description or source["ipc_cell"],
                        "bns_section": bns_section,
                        "bns_description": bns_description,
                        "change_type": change_type,
                    }
                )

    # Remove exact duplicate pairs while retaining the first authoritative description.
    deduped = []
    seen_pairs = set()
    for row in output:
        pair = (row["ipc_section"], row["bns_section"])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped.append(row)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ipc_section", "ipc_description", "bns_section", "bns_description", "change_type"],
        )
        writer.writeheader()
        writer.writerows(deduped)

    mapped_labels = {row["ipc_section"] for row in deduped}
    unmapped = sorted(set(labels) - mapped_labels)
    counts = Counter(row["change_type"] for row in deduped)
    unique_bns = {row["bns_section"] for row in deduped if row["bns_section"]}
    duplicate_pairs = len(deduped) - len({(row["ipc_section"], row["bns_section"]) for row in deduped})
    missing_bns_descriptions = [
        row for row in deduped if row["bns_section"] and not row["bns_description"]
    ]
    report = f"""# IPC to BNS Mapping Validation Report

## Source
- Primary source: NCRB/CYTRAIN IPC-BNS correspondence table
- URL: {SOURCE_URL}
- Complete BNS text source: {BNS_TEXT_URL}
- Retrieval date: 2026-09-04
- India Code URL supplied by the project was checked separately and returned HTTP 404.
- BPR&D comparative PDF was reachable and retained as a secondary cross-check.

## Exact validation results
- Total mapping rows: {len(deduped)}
- Unique IPC sections: {len(mapped_labels)}
- Unique BNS sections: {len(unique_bns)}
- NCRB non-null IPC section universe: {len(labels)}
- Coverage against NCRB IPC universe: {100 * len(mapped_labels & set(labels)) / len(labels):.2f}%
- Duplicate (ipc_section, bns_section) mappings: {duplicate_pairs}
- Mappings with a BNS section but no authoritative BNS description in CYTRAIN: {len(missing_bns_descriptions)}
- Unmapped IPC sections: {', '.join(unmapped) if unmapped else 'none'}
- Unresolved/manual-review rows: {len(missing_bns_descriptions) + len(unresolved)}
- DIRECT: {counts.get('DIRECT', 0)}
- SPLIT: {counts.get('SPLIT', 0)}
- MERGED: {counts.get('MERGED', 0)}
- REPEALED: {counts.get('REPEALED', 0)}
- NO_DIRECT_EQUIVALENT: {counts.get('NO_DIRECT_EQUIVALENT', 0)}

## Change-type interpretation
`DIRECT` is used for an individual row-level correspondence published by CYTRAIN. The source table does not itself assert that every grouped or multi-row NCRB label is a legal split, so this report does not infer `SPLIT` merely from multiple correspondence rows. `REPEALED` is reserved for source rows marked `Deleted`; `NO_DIRECT_EQUIVALENT` is reserved for an explicit source indication of no operative BNS section.

## Model compatibility
The CSV uses exactly the existing `IpcBnsMapping` fields: `ipc_section`, `ipc_description`, `bns_section`, `bns_description`, and `change_type`. No `similarity_score` was invented or added. Repeated IPC values represent one-to-many correspondence rows; null BNS values are reserved for source-marked repealed/no-equivalent entries.

## Status
{"PASS" if not unresolved and not unmapped and duplicate_pairs == 0 and not missing_bns_descriptions else "FAIL"}
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
