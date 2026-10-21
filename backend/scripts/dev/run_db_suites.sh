#!/usr/bin/env bash
# Run the 11 DB-backed test modules, one process each, against the isolated
# test database, and write per-module logs plus a summary.
#
# Usage:
#   TEST_DATABASE_URL=... backend/scripts/dev/run_db_suites.sh <out_dir>
#
# TEST_DATABASE_URL must be set (see docs/TESTING.md); the test bootstrap
# aborts otherwise. Each module's log is <out_dir>/<module>.log and the
# summary is <out_dir>/summary.txt. Exit status is non-zero if any module
# fails.
set -uo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <out_dir>" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT_DIR="$1"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
export PYTHONDONTWRITEBYTECODE=1

MODULES=(
  test_analytics
  test_auth
  test_document_processing_services
  test_ingest
  test_integration_readiness_smoke
  test_query_api
  test_query_history
  test_registration_lawyer_verification
  test_security_hardening
  test_structured_data_loaders
  test_vector_indexing
)

cd "$REPO_ROOT"
for module in "${MODULES[@]}"; do
  log="$OUT_DIR/$module.log"
  start=$(date +%s)
  "$PYTHON" -B -m unittest -v "backend.scripts.tests.$module" > "$log" 2>&1
  rc=$?
  ran=$(grep -oE '^Ran [0-9]+' "$log" | grep -oE '[0-9]+' || echo 0)
  result=$(grep -E '^(OK|FAILED)( \(|$)' "$log" | tail -1)
  printf '%-40s rc=%s ran=%s %-28s %ss\n' "$module" "$rc" "$ran" "${result:-NO_RESULT}" "$(($(date +%s) - start))"
done | tee "$OUT_DIR/summary.txt"

# Fail if any module exited non-zero.
! grep -qvE ' rc=0 ' "$OUT_DIR/summary.txt"
