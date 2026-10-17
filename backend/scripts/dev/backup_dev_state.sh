#!/usr/bin/env bash
# Back up the development database and the derived retrieval stores.
#
# Creates <backup_root>/<UTC timestamp>/ containing:
#   legalai_dev.dump      pg_dump -Fc of the development database
#   db_row_counts.txt     row count of every public table at dump time
#   chroma_store/         full copy (mtimes preserved)
#   bm25_store/           full copy (mtimes preserved)
#   MANIFEST.txt          sha256 of every file in the backup
#
# Usage:
#   backend/scripts/dev/backup_dev_state.sh <backup_root>
#
# <backup_root> must be outside the repository: the backup contains user
# data and must never be committed. The database URL comes from
# $DATABASE_URL or DATABASE_URL in <repo>/.env and is never printed or
# written. pg_dump and the row counts only read from the database.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <backup_root>" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
mkdir -p "$1"
BACKUP_ROOT="$(cd "$1" && pwd)"
case "$BACKUP_ROOT/" in
  "$REPO_ROOT"/*)
    echo "refusing to write a backup inside the repository: $BACKUP_ROOT" >&2
    exit 2
    ;;
esac

DB_URL="${DATABASE_URL:-}"
if [ -z "$DB_URL" ] && [ -f "$REPO_ROOT/.env" ]; then
  DB_URL="$(grep -E '^DATABASE_URL=' "$REPO_ROOT/.env" | head -1 | cut -d= -f2-)"
fi
if [ -z "$DB_URL" ]; then
  echo "DATABASE_URL is not set and not found in .env" >&2
  exit 2
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"
umask 077
mkdir "$DEST"

read_only_query() {
  psql "$DB_URL" -X -A -t -v ON_ERROR_STOP=1 \
    -c "SET default_transaction_read_only = on" -c "$1" | tail -n +2
}

DB_NAME="$(read_only_query 'SELECT current_database()')"
pg_dump --format=custom --no-password --file="$DEST/legalai_dev.dump" "$DB_URL"
{
  for table in $(read_only_query "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"); do
    printf '%s|%s\n' "$table" "$(read_only_query "SELECT count(*) FROM \"$table\"")"
  done
} > "$DEST/db_row_counts.txt"

cp -Rp "$REPO_ROOT/chroma_store" "$DEST/chroma_store"
cp -Rp "$REPO_ROOT/bm25_store" "$DEST/bm25_store"

# Verify each copied store file against its original.
(cd "$REPO_ROOT" && find chroma_store bm25_store -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$DEST/.originals.sha256"
(cd "$DEST" && shasum -a 256 -c --quiet .originals.sha256)
rm "$DEST/.originals.sha256"

{
  echo "# LegalAI development backup"
  echo "created_utc=$STAMP"
  echo "source_database=$DB_NAME"
  echo "pg_dump_version=$(pg_dump --version)"
  echo "repo_head=$(git -C "$REPO_ROOT" rev-parse HEAD)"
  echo "# sha256  path (relative to this folder)"
  (cd "$DEST" && find . -type f ! -name MANIFEST.txt -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256)
} > "$DEST/MANIFEST.txt"

chmod -R go-rwx "$DEST"
echo "backup written to $DEST"
echo "files: $(grep -cE '^[0-9a-f]{64}  ' "$DEST/MANIFEST.txt"), size: $(du -sh "$DEST" | cut -f1)"
