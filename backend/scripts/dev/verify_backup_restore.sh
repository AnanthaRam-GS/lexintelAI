#!/usr/bin/env bash
# Verify a backup made by backup_dev_state.sh.
#
# 1. Re-checks every sha256 in MANIFEST.txt.
# 2. Checks that the backed-up store copies match the live stores.
# 3. Restores legalai_dev.dump into a rehearsal database and compares its row
#    counts with db_row_counts.txt for every table.
#
# Usage:
#   backend/scripts/dev/verify_backup_restore.sh <backup_dir> <rehearsal_database_name>
#
# The rehearsal database must already exist, must be empty (no public
# tables), and must not be the development or test database. It is reached
# with the same host, port and credentials as the development DATABASE_URL.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <backup_dir> <rehearsal_database_name>" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKUP_DIR="$(cd "$1" && pwd)"
TARGET_DB="$2"

DB_URL="${DATABASE_URL:-}"
if [ -z "$DB_URL" ] && [ -f "$REPO_ROOT/.env" ]; then
  DB_URL="$(grep -E '^DATABASE_URL=' "$REPO_ROOT/.env" | head -1 | cut -d= -f2-)"
fi
DEV_DB="${DB_URL##*/}"
DEV_DB="${DEV_DB%%\?*}"
case "$TARGET_DB" in
  "$DEV_DB" | *_test | "")
    echo "refusing to restore into '$TARGET_DB': use a dedicated rehearsal database" >&2
    exit 2
    ;;
esac
TARGET_URL="${DB_URL%/*}/$TARGET_DB"

echo "[1/3] MANIFEST.txt checksums"
(cd "$BACKUP_DIR" && grep -E '^[0-9a-f]{64}  ' MANIFEST.txt | shasum -a 256 -c --quiet) && echo "  ok"

echo "[2/3] store copies vs live stores"
(cd "$REPO_ROOT" && find chroma_store bm25_store -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) \
  | (cd "$BACKUP_DIR" && shasum -a 256 -c --quiet) && echo "  ok"

echo "[3/3] restore into $TARGET_DB"
existing="$(psql "$TARGET_URL" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")"
if [ "$existing" != "0" ]; then
  echo "refusing to restore: $TARGET_DB already has $existing public tables" >&2
  exit 2
fi
pg_restore --no-owner --no-privileges --exit-on-error --dbname="$TARGET_URL" "$BACKUP_DIR/legalai_dev.dump"
restored="$(mktemp)"
trap 'rm -f "$restored"' EXIT
for table in $(psql "$TARGET_URL" -X -A -t -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"); do
  printf '%s|%s\n' "$table" "$(psql "$TARGET_URL" -X -A -t -c "SELECT count(*) FROM \"$table\"")"
done > "$restored"
diff "$BACKUP_DIR/db_row_counts.txt" "$restored" && echo "  restored row counts match db_row_counts.txt for all $(wc -l < "$restored" | tr -d ' ') tables"
