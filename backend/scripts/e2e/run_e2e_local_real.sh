#!/usr/bin/env bash
# Run the browser journeys against the real stack on this machine, without touching the development database or
# stores (docs/TESTING.md, "Local real mode"):
#
#   real retrieval (BGE-M3 and the BGE reranker, on MPS when available) over COPIES of the dev stores, a
#   rehearsal database restored from a dev backup with --clean, and the deterministic fake LLM by default.
#
# Usage:
#   REHEARSAL_DATABASE_URL=<url of legalai_rehearsal> backend/scripts/e2e/run_e2e_local_real.sh \
#       [--backup <dir>] [--real-llm] [--keep-state] [-- <playwright args>]
#
#   --backup <dir>  use this backup_dev_state.sh backup (default: make a fresh one; it only reads dev)
#   --real-llm      call the configured LLM provider instead of the fake (uses API quota; off by default)
#   --keep-state    keep the state directory (store copies, accounts file) after the run
#
# Writes only to legalai_rehearsal, a temporary state directory, and the backup directory.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKUP=""
REAL_LLM=0
KEEP=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup) BACKUP="$2"; shift 2 ;;
    --real-llm) REAL_LLM=1; shift ;;
    --keep-state) KEEP=1; shift ;;
    --) shift; break ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
: "${REHEARSAL_DATABASE_URL:?REHEARSAL_DATABASE_URL must point at legalai_rehearsal}"
if [ "${REHEARSAL_DATABASE_URL##*/}" != "legalai_rehearsal" ]; then
  echo "refused: REHEARSAL_DATABASE_URL must name legalai_rehearsal" >&2
  exit 2
fi

cd "$REPO_ROOT"
if [ -z "$BACKUP" ]; then
  BACKUP="$(env -u DATABASE_URL backend/scripts/dev/backup_dev_state.sh "$HOME/legalai_backups" | sed -n 's/^backup written to //p')"
fi
[ -d "$BACKUP/chroma_store" ] && [ -d "$BACKUP/bm25_store" ] || { echo "not a backup directory: $BACKUP" >&2; exit 2; }
echo "backup: $BACKUP"
# Checksums, store copies against the live stores, and a --clean restore into legalai_rehearsal.
env -u DATABASE_URL backend/scripts/dev/verify_backup_restore.sh "$BACKUP" legalai_rehearsal --clean

STATE="$(mktemp -d "${TMPDIR:-/tmp}/legalai-e2e-real.XXXXXX")"
cleanup() { if [ "$KEEP" = "1" ]; then echo "state kept: $STATE"; else rm -rf "$STATE"; fi; }
trap cleanup EXIT
cp -R "$BACKUP/chroma_store" "$STATE/chroma_store"
cp -R "$BACKUP/bm25_store" "$STATE/bm25_store"

DATABASE_URL="$REHEARSAL_DATABASE_URL" E2E_MODE=real E2E_REAL_LLM="$REAL_LLM" LEGALAI_E2E_STATE_DIR="$STATE" \
  backend/scripts/e2e/run_e2e.sh "$@"
