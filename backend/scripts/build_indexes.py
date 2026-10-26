"""Build the Chroma and BM25 indexes from the curated corpus, enrich their metadata, and verify them (step 20).

One entry point for README "Quick start" step "Build the indexes". In order, stopping at the first failure:

1. checks: the chunk files are the curated corpus (``load_corpus.check_chunk_files``); the database holds that corpus
   (``load_corpus.py`` was run) and its analytics (``produce_analytics_data.py`` was run, so ``document_sections`` is
   not empty); real BGE-M3 is available (no silent fallback to mock embeddings); the target stores are not the
   repository's ``chroma_store/`` or ``bm25_store/`` unless ``--confirm-dev`` is given;
2. ``build_vector_index.py --real --rebuild`` into ``--chroma-dir``;
3. ``build_lexical_index.py --rebuild`` into ``--bm25-dir``;
4. ``enrich_index_metadata.py`` (index_metadata_v1 fields from PostgreSQL);
5. ``verify_store_consistency.py``, which must report CONSISTENT.

The build summaries go to ``--summary-dir``, not to the committed manifests in ``data/structured/manifests/``, and the
generated docs are not rewritten. The database is only read (by the checks and the verifier) and its URL never printed.

Usage:
    .venv/bin/python backend/scripts/build_indexes.py --database-url-env DATABASE_URL \\
        --chroma-dir chroma_store --bm25-dir bm25_store [--summary-dir <dir>] [--confirm-dev]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts import load_corpus, reconcile_backfill  # noqa: E402
from backend.scripts.reconcile_common import REPO_ROOT, check_store_paths, connect, resolve_database  # noqa: E402

SCRIPTS = REPO_ROOT / "backend/scripts"
BM25_FILE_NAME = "legalai_trusted_judgments_bm25_v1.json"


def check_database(url_env: str) -> str:
    url, database = resolve_database(url_env, confirm_dev=False, write=False)
    connection = connect(url, readonly=True)
    try:
        with connection.cursor() as cursor:
            work = reconcile_backfill.plan(cursor, ignore_document_columns=load_corpus.OUTCOME_COLUMNS)
            if work["insert_documents"] or work["insert_chunks"] or work["conflicts"]:
                raise SystemExit(f"refused: database '{database}' does not hold the curated corpus; run load_corpus.py first")
            cursor.execute("SELECT count(*) FROM document_sections")
            if cursor.fetchone()[0] == 0:
                raise SystemExit(f"refused: database '{database}' has no document_sections; run produce_analytics_data.py first")
    finally:
        connection.rollback()
        connection.close()
    return database


def run(step: str, script: str, *arguments: str) -> None:
    print(f"== {step}: {script} {' '.join(arguments)}", flush=True)
    completed = subprocess.run([sys.executable, str(SCRIPTS / script), *arguments], cwd=REPO_ROOT)
    if completed.returncode != 0:
        raise SystemExit(f"FAILED at {step} ({script} exited {completed.returncode})")


def main(argv: list[str] | None = None) -> int:
    from backend.app.core.config import Settings, resolve_chroma_location
    from backend.scripts.build_vector_index import bge_m3_available

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the database URL.")
    parser.add_argument("--chroma-dir", type=Path, required=True)
    parser.add_argument("--bm25-dir", type=Path, required=True)
    parser.add_argument("--collection", help="Chroma collection (default: the configured CHROMA_COLLECTION_NAME).")
    parser.add_argument("--summary-dir", type=Path, help="Where the build summaries go (default: <chroma-dir>/../index_build_summaries).")
    parser.add_argument("--confirm-dev", action="store_true", help="Allow rebuilding the repository's chroma_store/ and bm25_store/.")
    args = parser.parse_args(argv)

    chroma_dir, bm25_dir = args.chroma_dir.resolve(), args.bm25_dir.resolve()
    bm25_file = bm25_dir / BM25_FILE_NAME
    summary_dir = (args.summary_dir or chroma_dir.parent / "index_build_summaries").resolve()
    collection = args.collection or resolve_chroma_location(Settings())[1]

    check_store_paths([chroma_dir, bm25_dir], confirm_dev=args.confirm_dev, write=True)
    corpus = load_corpus.check_chunk_files()
    database = check_database(args.database_url_env)
    if not bge_m3_available():
        raise SystemExit("refused: BGE-M3 is not available locally (FlagEmbedding and the BAAI/bge-m3 model); see README \"Models\"")
    print(f"curated corpus: {corpus['documents']} documents, {corpus['chunks']} chunks; database '{database}'; collection {collection}")
    summary_dir.mkdir(parents=True, exist_ok=True)
    vector_summary = summary_dir / "vector_index_summary.json"

    run("1/4 vectors", "build_vector_index.py", "--real", "--rebuild", "--persist-dir", str(chroma_dir), "--collection", collection,
        "--summary-out", str(vector_summary), "--skip-docs")
    build_mode = json.loads(vector_summary.read_text(encoding="utf-8")).get("build_mode")
    if build_mode != "real_bge_m3":
        raise SystemExit(f"FAILED at 1/4 vectors: build mode is {build_mode}, not real_bge_m3")
    run("2/4 bm25", "build_lexical_index.py", "--rebuild", "--persist-dir", str(bm25_dir),
        "--summary-out", str(summary_dir / "lexical_index_summary.json"))
    stores = ["--database-url-env", args.database_url_env, "--chroma-dir", str(chroma_dir), "--bm25-file", str(bm25_file), "--collection", collection]
    run("3/4 enrich", "enrich_index_metadata.py", *stores, *(["--confirm-dev"] if args.confirm_dev else []))
    run("4/4 verify", "verify_store_consistency.py", *stores, "--output", str(summary_dir / "store_consistency.json"))
    print(f"indexes built and CONSISTENT: {chroma_dir} and {bm25_file}; summaries in {summary_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
