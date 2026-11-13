"""Round 2 review sheet for the 2026-10 evaluation: full cited passages for the authority rows not judged supported.

Round 1 (``review_sheet_reviewed.csv``) showed each cited passage cut at 600 characters (``run_three_config_eval.py``
stores ``text[:600]``), and 11 of 83 authority rows note that the support was not in the excerpt. Round 2 re-asks only
the ``citation`` and ``text_reference`` rows whose round 1 ``citation_support`` is not ``supported``, with the full
text of the cited chunk.

**Blinding is kept.** This script never reads ``review_key.json``. Rows keep their ``review_id``, ``example_id`` and
X/Y/Z ``answer_label``. The cited chunk is found without knowing the configuration: the candidates for a row are the
saved evidence chunk IDs of *all three* configurations for that query (``generation/per_query_scores.json``), and the
chunk is the one whose PostgreSQL text starts with the row's 600-character excerpt. Exactly one distinct text must
match, or the script stops.

The chunk text is read from PostgreSQL in a read-only transaction (``chunks.chroma_id`` = the evidence chunk ID).
A ``text_reference`` row (a case named in the answer text) cites no chunk; it keeps its round 1 evidence note and
empty ``chunk_id`` / ``chunk_chars``.

Output (outside the repository, it holds answer and judgment text): the round 1 columns with ``evidence_excerpt``
replaced by the full chunk text, plus ``chunk_id``, ``chunk_chars``, ``r1_support`` and ``r1_notes``; the reviewer fills
``citation_support``, ``reviewer`` and ``notes``. ``import_human_review.py --round 2`` imports it next to round 1.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.build_review_sheet import COLUMNS  # noqa: E402

EXCERPT_CHARS = 600
AUTHORITY_ROWS = {"citation", "text_reference"}
ROUND2_COLUMNS = COLUMNS[: COLUMNS.index("evidence_excerpt") + 1] + ["chunk_id", "chunk_chars"] + [
    column for column in COLUMNS[COLUMNS.index("evidence_excerpt") + 1:] if column != "legal_correctness"
] + ["r1_support", "r1_notes"]


def evidence_ids_by_example(scores: dict[str, Any]) -> dict[str, set[str]]:
    """Evidence chunk IDs per query, pooled over the configurations (the configuration is never kept)."""
    pooled: dict[str, set[str]] = defaultdict(set)
    for record in scores["rows"]:
        pooled[record["example_id"]].update(record.get("evidence_chunk_ids") or [])
    return pooled


def round2_rows(round1: list[dict[str, str]], pooled_ids: dict[str, set[str]], chunk_text: dict[str, str]) -> list[dict[str, Any]]:
    """The round 2 rows; raises ``SystemExit`` when a cited chunk cannot be identified unambiguously."""
    rows, problems = [], []
    for row in round1:
        if row["row_type"] not in AUTHORITY_ROWS or row["citation_support"].strip() == "supported":
            continue
        out = {column: row.get(column, "") for column in COLUMNS if column != "legal_correctness"}
        out.update({"citation_support": "", "reviewer": "", "notes": "", "chunk_id": "", "chunk_chars": "",
                    "r1_support": row["citation_support"].strip(), "r1_notes": row.get("notes", "")})
        if row["row_type"] == "citation":
            excerpt = row["evidence_excerpt"]
            matches = {chunk_id for chunk_id in pooled_ids.get(row["example_id"], ())
                       if chunk_id in chunk_text and chunk_text[chunk_id].startswith(excerpt)}
            texts = {chunk_text[chunk_id] for chunk_id in matches}
            if len(excerpt) < EXCERPT_CHARS and len(texts) == 1 and next(iter(texts)) != excerpt:
                problems.append(f"{row['review_id']}: excerpt shorter than {EXCERPT_CHARS} but not the whole chunk")
            if len(texts) != 1:
                problems.append(f"{row['review_id']}: {len(matches)} matching chunks ({len(texts)} distinct texts)")
                continue
            chunk_id = sorted(matches)[0]
            out.update({"evidence_excerpt": chunk_text[chunk_id], "chunk_id": chunk_id, "chunk_chars": len(chunk_text[chunk_id])})
        rows.append(out)
    if problems:
        raise SystemExit("refused: cited chunks not identified:\n" + "\n".join(problems))
    return rows


def fetch_chunk_texts(database_url: str, chunk_ids: set[str]) -> dict[str, str]:
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url, connect_args={"options": "-c default_transaction_read_only=on"})
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT chroma_id, text FROM chunks WHERE chroma_id = ANY(:ids)"), {"ids": sorted(chunk_ids)})
            return {chunk_id: chunk for chunk_id, chunk in result}
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--round1-sheet", type=Path, required=True, help="the reviewed round 1 sheet")
    parser.add_argument("--scores", type=Path, default=REPO_ROOT / "data/evaluation/runs/2026-10_v3_groq/generation/per_query_scores.json")
    parser.add_argument("--out", type=Path, required=True, help="the round 2 sheet, outside the repository")
    parser.add_argument("--database-url-env", default="DATABASE_URL", help="environment variable holding the database URL")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if REPO_ROOT in out.parents:
        raise SystemExit("refused: the review sheet holds answer text and goes outside the repository")
    if any(path.name == "review_key.json" for path in (args.round1_sheet, args.scores, args.out)):
        raise SystemExit("refused: the blinding key is never read or written here")
    database_url = os.environ.get(args.database_url_env)
    if not database_url:
        raise SystemExit(f"refused: {args.database_url_env} is not set")

    with args.round1_sheet.open(newline="", encoding="utf-8") as handle:
        round1 = list(csv.DictReader(handle))
    pooled = evidence_ids_by_example(json.loads(args.scores.read_text(encoding="utf-8")))
    wanted = {chunk_id for ids in pooled.values() for chunk_id in ids}
    chunk_text = fetch_chunk_texts(database_url, wanted)
    rows = round2_rows(round1, pooled, chunk_text)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROUND2_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    citations = [row for row in rows if row["row_type"] == "citation"]
    print(json.dumps({
        "sheet": str(out),
        "rows": len(rows),
        "citation_rows": len(citations),
        "text_reference_rows": len(rows) - len(citations),
        "chunks_found": sum(1 for row in citations if row["chunk_id"]),
        "distinct_chunks": len({row["chunk_id"] for row in citations}),
        "chunk_ids_in_run_found_in_postgres": f"{len(chunk_text)} of {len(wanted)}",
        "chunk_chars_min_max": [min((row["chunk_chars"] for row in citations), default=0), max((row["chunk_chars"] for row in citations), default=0)],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
