#!/usr/bin/env bash
# Read-only snapshot of development state, for before/after comparisons.
#
# Writes two files:
#   <out_prefix>.db.txt     row count of every public table in the dev database
#   <out_prefix>.files.txt  sha256, mtime and path of every file under each path
#
# Usage:
#   backend/scripts/dev/snapshot_dev_state.sh <out_prefix> [path ...]
#
# Paths are relative to the repository root. With no paths, the protected
# defaults below are used. The database URL comes from $DATABASE_URL, or from
# DATABASE_URL in <repo>/.env; it is never printed. Every query runs in a
# read-only transaction.
#
# Compare two snapshots with:
#   diff <before>.db.txt <after>.db.txt && diff <before>.files.txt <after>.files.txt
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <out_prefix> [path ...]" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT_PREFIX="$1"
shift
case "$OUT_PREFIX" in
  /*) ;;
  *) OUT_PREFIX="$PWD/$OUT_PREFIX" ;;
esac

if [ "$#" -gt 0 ]; then
  PATHS=("$@")
else
  PATHS=(
    chroma_store
    bm25_store
    data/raw/uploads
    data/processed/judgment_chunks
    data/processed/judgments_normalized
    data/processed/acquisition_runs
    data/raw/judgments
    data/structured/manifests
  )
fi

DB_URL="${DATABASE_URL:-}"
if [ -z "$DB_URL" ] && [ -f "$REPO_ROOT/.env" ]; then
  DB_URL="$(grep -E '^DATABASE_URL=' "$REPO_ROOT/.env" | head -1 | cut -d= -f2-)"
fi
if [ -z "$DB_URL" ]; then
  echo "DATABASE_URL is not set and not found in .env" >&2
  exit 2
fi

read_only_query() {
  psql "$DB_URL" -X -A -t -v ON_ERROR_STOP=1 \
    -c "SET default_transaction_read_only = on" -c "$1" | tail -n +2
}

{
  echo "database=$(read_only_query 'SELECT current_database()')"
  for table in $(read_only_query "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"); do
    printf '%s|%s\n' "$table" "$(read_only_query "SELECT count(*) FROM \"$table\"")"
  done
} > "$OUT_PREFIX.db.txt"

cd "$REPO_ROOT"
{
  for path in "${PATHS[@]}"; do
    if [ -e "$path" ]; then
      find "$path" -type f -print0 | LC_ALL=C sort -z | while IFS= read -r -d '' file; do
        printf '%s  %s  %s\n' "$(shasum -a 256 "$file" | cut -d' ' -f1)" "$(stat -f '%m' "$file" 2>/dev/null || stat -c '%Y' "$file")" "$file"
      done
    else
      echo "MISSING $path"
    fi
  done
} > "$OUT_PREFIX.files.txt"

echo "snapshot: $(($(wc -l < "$OUT_PREFIX.db.txt") - 1)) tables, $(wc -l < "$OUT_PREFIX.files.txt" | tr -d ' ') file entries -> $OUT_PREFIX.{db,files}.txt"
