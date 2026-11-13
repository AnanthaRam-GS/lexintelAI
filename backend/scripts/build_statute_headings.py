"""Build official section headings (marginal notes) from India Code, the official legislative repository (step 26).

Source: India Code, https://indiacode.gov.in (the site of https://www.indiacode.nic.in, which now redirects there and
says so). Nothing else is used; no heading is invented. Output: ``data/structured/statute_headings/<act>.csv``
(columns ``statute, section, heading, status, basis``) and ``validation.json``; sources in ``SOURCES.md``. UNREVIEWED.

Two kinds of source, one per Act:
- **Section records** (BNS, BNSS, BSA): India Code publishes every section of these Acts as a structured record whose
  title is the section's heading (``dc.title``) with its number (``dc.identifier.section_number``) and the Act's id
  (``dc.identifier.act_id``). The heading is taken as published, with surrounding spaces and the final full stop
  removed. ``basis = "section_record"``.
- **The Act's PDF** (IPC, Evidence Act, CrPC: repealed Acts, published on India Code as their original PDF). Two
  independent extractions are made from the PDF text: the **arrangement of sections** (the Act's printed list of
  section numbers and headings) and the **section heads in the body** ("120B. Punishment of criminal
  conspiracy.—(1) ..."). The heading is the body's section head with amendment markers removed ("2[" and "]", the
  editorial footnote brackets), and it is used **only when the arrangement corroborates it**:
  ``basis = "pdf_exact"`` (the same text), ``"pdf_arrangement_adds_notes"`` (the arrangement entry starts with the
  heading and adds the sub-notes it lists after it, e.g. "Provisos."), ``"pdf_minor_spelling"`` (similarity
  >= 0.85, e.g. the arrangement's typo "rigorous of simple" for the body's "rigorous or simple"; the body's own text is
  kept, typos included), or ``"pdf_exact_after_footnote_marker"`` (the body prints a footnote digit against the
  number, "1145." for "1[145.", and the heading is the arrangement's word for word). Sections the
  arrangement marks "[Omitted.]" or "[Repealed.]" get ``status`` omitted / repealed and no heading. Every other
  section is left out and listed in ``validation.json`` (no guess).
- A PDF whose text is a noisy OCR layer (CrPC's: "tiie", "agair\\.st") is **not parsed**: the Act is skipped and
  reported (``--skip``).

    .venv/bin/python backend/scripts/build_statute_headings.py --source-dir <dir with the downloaded files>

The source directory holds what ``--fetch`` downloads: ``<act>.pdf``, ``<act>.sections.json`` and ``fetch_log.json``.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data/structured/statute_headings"
API = "https://indiacode.gov.in/server/api"
USER_AGENT = "LegalAI statute headings (research; official source only)"

# statute key used by the resolver -> how India Code holds it
PDF_ACTS = {
    "IPC": {"file": "ipc", "item": "972afbe0-a2de-415d-9df5-8d70038056ad", "numbered_to": 511},
    "Evidence Act": {"file": "evidence", "item": "b62073e0-4d33-4348-8eda-d92af40af24b", "numbered_to": 167},
    "CrPC": {"file": "crpc", "item": "973d60aa-105c-4a2f-94f1-7640f0b5d6a7", "numbered_to": 484},
}
RECORD_ACTS = {
    "BNS": {"file": "bns", "act_id": "AC_CEN_5_23_00048_2023-45_1719292564123", "numbered_to": 358},
    "BNSS": {"file": "bnss", "act_id": "AC_CEN_5_23_00049_202346_1719552320687", "numbered_to": 531},
    "BSA": {"file": "bsa", "act_id": "AC_CEN_5_23_00049_2023-47_1719292804654", "numbered_to": 170},
}
NUM = r"(\d+(?:-?[A-Z]{1,3})?)"
DASH = r"(?:—|–{1,3}|-{2,3})"
MINOR_SPELLING = 0.85


# ---------------------------------------------------------------------------
# Download (official site only)
# ---------------------------------------------------------------------------


def _get(url: str, raw: bool = False):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=180) as response:
                body = response.read()
                return body if raw else json.loads(body)
        except Exception:  # noqa: BLE001 - retried, then raised
            if attempt == 2:
                raise
            time.sleep(10)


def _pdf_text(body: bytes) -> str:
    import pymupdf  # noqa: PLC0415

    with pymupdf.open(stream=body, filetype="pdf") as document:
        return "\n".join(page.get_text() for page in document)


def _original_pdf(item_uuid: str, target: Path) -> dict:
    bundles = _get(f"{API}/core/items/{item_uuid}/bundles")["_embedded"]["bundles"]
    original = next(bundle for bundle in bundles if bundle["name"] == "ORIGINAL")
    pdfs = [s for s in _get(original["_links"]["bitstreams"]["href"])["_embedded"]["bitstreams"] if s["name"].lower().endswith(".pdf")]
    # The English India Code text ("A2023-46.pdf"), not the bilingual/Hindi Gazette ("202346.pdf", "Hh202345.pdf").
    english = [s for s in pdfs if re.fullmatch(r"a\d{4}-\d+\.pdf", s["name"], re.IGNORECASE)]
    stream = (english or pdfs)[0]
    url = f"{API}/core/bitstreams/{stream['uuid']}/content"
    first, second = _get(url, raw=True), _get(url, raw=True)
    if _pdf_text(first) != _pdf_text(second):
        raise SystemExit(f"{target.name}: two downloads differ in text")
    target.write_bytes(first)
    return {"pdf_name": stream["name"], "pdf_url": url, "bytes": len(first), "sha256": hashlib.sha256(first).hexdigest(),
            "md5": hashlib.md5(first).hexdigest(), "server_recorded_md5": (stream.get("checkSum") or {}).get("value"),
            "server_recorded_bytes": stream.get("sizeBytes"),
            "bytes_stable_across_two_downloads": hashlib.sha256(first).digest() == hashlib.sha256(second).digest()}


def fetch(source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    log: dict = {"retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"), "api": API, "acts": {}}
    for statute, spec in PDF_ACTS.items():
        item = _get(f"{API}/core/items/{spec['item']}")
        log["acts"][statute] = {"item_uuid": spec["item"], "title": item["metadata"]["dc.title"][0]["value"],
                                "item_url": f"https://indiacode.gov.in/handle/{item.get('handle')}",
                                **_original_pdf(spec["item"], source_dir / f"{spec['file']}.pdf")}
    for statute, spec in RECORD_ACTS.items():
        query = urllib.parse.quote(f'dc.identifier.act_id:"{spec["act_id"]}"')
        records, page, act_item = [], 0, None
        while True:
            data = _get(f"{API}/discover/search/objects?query={query}&dsoType=ITEM&size=100&page={page}")
            for obj in data["_embedded"]["searchResult"]["_embedded"]["objects"]:
                item = obj["_embedded"]["indexableObject"]
                md = item.get("metadata", {})
                value = lambda key: (md.get(key) or [{}])[0].get("value")  # noqa: E731
                if value("dc.identifier.state_name") != "CENTRAL" or value("dc.identifier.act_id") != spec["act_id"]:
                    continue
                if value("dc.identifier.collection") == "ACT":
                    act_item = item
                elif value("dc.identifier.collection") == "SECTION":
                    records.append({"uuid": item["uuid"], "handle": item.get("handle"), "title": value("dc.title"),
                                    "section_number": value("dc.identifier.section_number"),
                                    "order_number": value("dc.identifier.order_number"),
                                    "repealed": value("dc.identifier.repealed"), "act_name": value("dc.identifier.act_name"),
                                    "text_html": value("dc.identifier.section_page_note")})
            if page + 1 >= data["_embedded"]["searchResult"]["page"]["totalPages"]:
                break
            page += 1
            time.sleep(1)
        path = source_dir / f"{spec['file']}.sections.json"
        path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        entry = {"act_id": spec["act_id"], "section_records": len(records),
                 "sections_query": f"{API}/discover/search/objects?query={query}&dsoType=ITEM",
                 "sections_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if act_item:
            entry.update({"item_uuid": act_item["uuid"], "title": act_item["metadata"]["dc.title"][0]["value"],
                          "item_url": f"https://indiacode.gov.in/handle/{act_item.get('handle')}",
                          **_original_pdf(act_item["uuid"], source_dir / f"{spec['file']}.pdf")})
        log["acts"][statute] = entry
    (source_dir / "fetch_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def section_key(number: str) -> str:
    """'171-I' -> '171I'; '120b' -> '120B'."""
    return re.sub(r"-", "", number).upper()


def clean_heading(text: str) -> str:
    text = re.sub(r"\d+\[", "", text)          # amendment markers: "2[electronic signature]"
    text = re.sub(r"\[|\]", "", text) if "[" in text and "]" in text else text
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[\s.;,:]+$", "", text)


def comparable(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_heading(text).casefold()).strip()


def split_pdf_text(text: str) -> tuple[str, str]:
    start = text.find("ARRANGEMENT OF SECTIONS")
    if start < 0:
        raise ValueError("no arrangement of sections")
    match = re.search(rf"(?m)^\s*1\.\s+[^\n]{{3,200}}?\.?\s*{DASH}", text[start:])
    if not match:
        raise ValueError("no section 1 in the body")
    return text[start:start + match.start()], text[start + match.start():]


def parse_arrangement(arrangement: str) -> dict[str, str]:
    entries: dict[str, list[str]] = {}
    current: str | None = None
    for raw in arrangement.splitlines():
        line = raw.strip()
        if not line or line in {"SECTIONS", "IndiaCode", "PREAMBLE"} or re.fullmatch(r"\d+", line):
            continue
        if line.startswith("CHAPTER") or (line.isupper() and not re.match(rf"^{NUM}\.", line)):
            current = None
            continue
        # an entry, possibly followed by another on the same line ("171H. ... 171-I. ...")
        parts = re.split(rf"(?<=\.)\s+(?={NUM}\.\s)", line)
        for part in parts:
            match = re.match(rf"^{NUM}\.\s*(.*)$", part)
            if match and (current is None or _plausible_next(current, match.group(1))):
                current = section_key(match.group(1))
                entries[current] = [match.group(2)] if match.group(2) else []
            elif current is not None:
                entries[current].append(part)
    return {key: " ".join(value).strip() for key, value in entries.items()}


def _number_value(key: str) -> tuple[int, str]:
    match = re.match(r"(\d+)([A-Z]*)", section_key(key))
    return int(match.group(1)), match.group(2)


def _plausible_next(previous: str, candidate: str) -> bool:
    """A new entry's number never goes backwards (guards against "1." inside a heading)."""
    return _number_value(candidate) >= _number_value(previous)


def parse_body(body: str) -> dict[str, str]:
    heads: dict[str, str] = {}
    pattern = re.compile(rf"(?m)^\s*(?:\d+\[)?{NUM}\.\s+((?:[^\n]|\n(?!\s*(?:\d+\[)?\d+[A-Z]{{0,3}}\.\s)){{2,320}}?)\s*{DASH}")
    for match in pattern.finditer(body):
        key = section_key(match.group(1))
        if key not in heads:
            heads[key] = match.group(2)
    return heads


def merge_pdf(arrangement: dict[str, str], body: dict[str, str]) -> tuple[list[dict], dict]:
    rows, report = [], {"used": {}, "omitted_or_repealed": [], "disagreement": {}, "arrangement_only": {}, "body_only": {}}
    body_consumed: set[str] = set()
    for key, listed in arrangement.items():
        marker = re.fullmatch(r"\[?\s*(Omitted|Repealed)\.?\s*\]?\.?", listed.strip(), re.IGNORECASE)
        if marker:
            rows.append({"section": key, "heading": "", "status": marker.group(1).lower(), "basis": "pdf_arrangement_marker"})
            report["omitted_or_repealed"].append(key)
            continue
        if key not in body:
            # A footnote marker digit glued to the number ("1145." for "1[145."): accepted only when the heading is the
            # arrangement's, word for word.
            glued = [k for k in body if len(k) == len(key) + 1 and k[0].isdigit() and k[1:] == key
                     and comparable(body[k]) == comparable(listed)]
            if glued:
                rows.append({"section": key, "heading": clean_heading(body[glued[0]]), "status": "in_force",
                             "basis": "pdf_exact_after_footnote_marker"})
                report["used"].setdefault("pdf_exact_after_footnote_marker", []).append(key)
                body_consumed.add(glued[0])
                continue
            report["arrangement_only"][key] = clean_heading(listed)
            continue
        head, listed_clean = clean_heading(body[key]), clean_heading(listed)
        a, b = comparable(listed_clean), comparable(head)
        if not b:
            report["disagreement"][key] = {"arrangement": listed_clean, "body": head}
            continue
        if a == b:
            basis = "pdf_exact"
        elif a.startswith(b + " "):
            basis = "pdf_arrangement_adds_notes"
        elif difflib.SequenceMatcher(None, a, b).ratio() >= MINOR_SPELLING:
            basis = "pdf_minor_spelling"
        else:
            report["disagreement"][key] = {"arrangement": listed_clean, "body": head}
            continue
        rows.append({"section": key, "heading": head, "status": "in_force", "basis": basis})
        report["used"].setdefault(basis, []).append(key)
    report["body_only"] = {key: clean_heading(value) for key, value in body.items() if key not in arrangement and key not in body_consumed}
    return rows, report


def rows_from_records(records: list[dict]) -> tuple[list[dict], dict]:
    rows, report = [], {"duplicate_numbers": [], "repealed": [], "empty_title": []}
    seen: set[str] = set()
    for record in sorted(records, key=lambda r: (int(r["order_number"] or 0), r["section_number"] or "")):
        key = section_key(str(record["section_number"]).strip())
        if key in seen:
            report["duplicate_numbers"].append(key)
            continue
        seen.add(key)
        title = clean_heading(record["title"] or "")
        if str(record.get("repealed")).lower() == "true":
            rows.append({"section": key, "heading": "", "status": "repealed", "basis": "section_record"})
            report["repealed"].append(key)
        elif not title:
            report["empty_title"].append(key)
        else:
            rows.append({"section": key, "heading": title, "status": "in_force", "basis": "section_record"})
    return rows, report


def structure_check(rows: list[dict], numbered_to: int) -> dict:
    numbers = [_number_value(row["section"]) for row in rows]
    plain = {value for value, letters in numbers if not letters}
    keys = [row["section"] for row in rows]
    return {"rows": len(rows), "plain_numbers_expected": numbered_to,
            "plain_numbers_missing": [n for n in range(1, numbered_to + 1) if n not in plain],
            "plain_numbers_beyond_range": sorted(n for n in plain if n > numbered_to),
            "lettered_sections": sum(1 for _value, letters in numbers if letters),
            "duplicates": sorted({key for key in keys if keys.count(key) > 1}),
            "in_force_with_heading": sum(1 for row in rows if row["status"] == "in_force"),
            "omitted_or_repealed": sum(1 for row in rows if row["status"] != "in_force")}


def write_csv(statute: str, rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["statute", "section", "heading", "status", "basis"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({"statute": statute, **row})


def build(source_dir: Path, skip: set[str], out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    fetch_log = json.loads((source_dir / "fetch_log.json").read_text(encoding="utf-8"))
    validation: dict = {"retrieved_at": fetch_log["retrieved_at"], "acts": {}}
    for statute, spec in {**PDF_ACTS, **RECORD_ACTS}.items():
        source = fetch_log["acts"].get(statute, {})
        if statute in skip:
            validation["acts"][statute] = {"skipped": skip[statute] if isinstance(skip, dict) else True, "source": source}
            continue
        if statute in PDF_ACTS:
            arrangement, body = split_pdf_text(_pdf_text((source_dir / f"{spec['file']}.pdf").read_bytes()))
            rows, report = merge_pdf(parse_arrangement(arrangement), parse_body(body))
        else:
            records = json.loads((source_dir / f"{spec['file']}.sections.json").read_text(encoding="utf-8"))
            rows, report = rows_from_records(records)
        rows.sort(key=lambda row: _number_value(row["section"]))
        path = out_dir / f"{spec['file']}.csv"
        write_csv(statute, rows, path)
        validation["acts"][statute] = {"csv": str(path.relative_to(REPO_ROOT)), "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                       "structure": structure_check(rows, spec["numbered_to"]), "extraction": report,
                                       "source": source}
    (out_dir / "validation.json").write_text(json.dumps(validation, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="download from India Code into --source-dir first")
    parser.add_argument("--skip", action="append", default=[], metavar="STATUTE=REASON")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.source_dir)
    skip = dict(item.split("=", 1) for item in args.skip)
    validation = build(args.source_dir, skip)
    for statute, result in validation["acts"].items():
        if "skipped" in result:
            print(f"{statute}: SKIPPED ({result['skipped']})")
            continue
        s, e = result["structure"], result["extraction"]
        used = {k: len(v) for k, v in e.get("used", {}).items()}
        print(f"{statute}: rows {s['rows']} (headings {s['in_force_with_heading']}, omitted/repealed {s['omitted_or_repealed']}, "
              f"lettered {s['lettered_sections']}); missing plain numbers {len(s['plain_numbers_missing'])} "
              f"{s['plain_numbers_missing'][:12]}; beyond range {s['plain_numbers_beyond_range'][:6]}; duplicates {s['duplicates']}; "
              f"used {used}; disagreements {len(e.get('disagreement', {}))}; arrangement-only {len(e.get('arrangement_only', {}))}; "
              f"body-only {len(e.get('body_only', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
