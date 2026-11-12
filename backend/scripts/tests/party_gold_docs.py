"""The step E4 party gold documents (experiments/inlegalbert/party_gold/) as uploads, and the flag-off snapshot.

Each document's text is rendered into a PDF (one page per part; a line holding only ``\\f`` separates pages, as for
the brief fixtures), then parsed, chunked and wrapped like an uploaded professional PDF: ``parse_document`` ->
``chunk_document`` -> ``build_private_chunks``.

``flag_off_outputs`` records what the local document map produces today with the deterministic NER: the parties and
roles, the brief's four document fields and the rendered map (with ``dense_provider=None``, so no model is needed).
``fixtures/party_roles_flag_off_snapshot.json`` was written by ``--write-snapshot`` from the code *before* the E4
change; the unit tests compare the current flag-off output with it byte for byte.

    .venv/bin/python -m backend.scripts.tests.party_gold_docs --write-snapshot
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pymupdf

from backend.app.services.chunker import chunk_document
from backend.app.services.document_parser import parse_document
from backend.app.services.private_pdf_rag import PrivateChunk, build_private_chunks

REPO = Path(__file__).resolve().parents[3]
GOLD_DIR = REPO / "experiments/inlegalbert/party_gold"
SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "party_roles_flag_off_snapshot.json"
PAGE_BREAK = "\\f"
TOKEN_BUDGET = 5000


def documents() -> dict[str, dict]:
    """doc_id -> {"text_file", "source"} for every gold document, the public excerpts included (labelled or not).

    The public excerpts are found from their text files, never from their label files (step E4b: the label files are
    the held-out judge and are not opened by tests).
    """
    out = {}
    for path in sorted((GOLD_DIR / "gold").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        out[record["doc_id"]] = {"text_file": record["text_file"], "source": record["source"]}
    for path in sorted((GOLD_DIR / "public").glob("p*.txt")):
        out[path.stem] = {"text_file": str(path.relative_to(REPO)), "source": "public"}
    return out


def pages(text: str) -> list[str]:
    result, current = [], []
    for line in text.splitlines():
        if line.strip() == PAGE_BREAK:
            result.append("\n".join(current))
            current = []
        else:
            current.append(line)
    result.append("\n".join(current))
    return [page for page in result if page.strip()]


def document_chunks(doc_id: str) -> tuple[str, list[PrivateChunk]]:
    """(filename, private chunks) for a gold document, through the product parser and chunker."""
    text = (REPO / documents()[doc_id]["text_file"]).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"{doc_id}.pdf"
        pdf = pymupdf.open()
        for page_text in pages(text):
            page = pdf.new_page(width=595, height=842)  # A4
            page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), page_text, fontsize=9, fontname="helv")
        pdf.save(path)
        pdf.close()
        document = parse_document(path)
        document["source_file_name"] = path.name
        return path.name, build_private_chunks(chunk_document(document))


def map_outputs(doc_id: str) -> dict:
    from backend.app.services import professional_brief as brief
    from backend.app.services.local_document_map import build_local_document_map, render_local_document_map

    filename, chunks = document_chunks(doc_id)
    document_map = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=TOKEN_BUDGET)
    rendered = render_local_document_map(document_map)
    fields = {"parties_and_roles": brief.parties_and_roles(document_map), "chronology": brief.chronology(document_map),
              "procedural_considerations": brief.procedural_considerations(document_map),
              "evidence_identified": brief.evidence_identified(document_map)}
    return {
        "parties_and_roles": [[p.role, p.name, p.private_evidence_id, p.page_start, p.page_end] for p in document_map.parties_and_roles],
        "brief_fields": fields,
        "brief_fields_sha256": hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "rendered_map_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
    }


def flag_off_outputs() -> dict[str, dict]:
    previous = os.environ.get("LEGALAI_NER_BACKEND")
    os.environ["LEGALAI_NER_BACKEND"] = "deterministic"
    try:
        return {doc_id: map_outputs(doc_id) for doc_id in documents()}
    finally:
        if previous is None:
            os.environ.pop("LEGALAI_NER_BACKEND", None)
        else:
            os.environ["LEGALAI_NER_BACKEND"] = previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write-snapshot", action="store_true")
    args = parser.parse_args()
    outputs = flag_off_outputs()
    if args.write_snapshot:
        SNAPSHOT_PATH.write_text(json.dumps(outputs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {SNAPSHOT_PATH.relative_to(REPO)}: {len(outputs)} documents")
    else:
        print(json.dumps({d: o["parties_and_roles"] for d, o in outputs.items()}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
