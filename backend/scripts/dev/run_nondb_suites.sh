#!/usr/bin/env bash
# Run every non-DB test module (all backend/scripts/tests/test_*.py not listed in db_test_modules.txt) in one
# unittest process. No database, network or model files are needed (docs/TESTING.md).
#
# Usage:
#   backend/scripts/dev/run_nondb_suites.sh [extra unittest args, e.g. -v]
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python)"  # CI has no .venv
export PYTHONDONTWRITEBYTECODE=1

DB_MODULES=" $(grep -vE '^[[:space:]]*(#|$)' "$REPO_ROOT/backend/scripts/dev/db_test_modules.txt" | tr '\n' ' ') "
MODULES=()
for path in "$REPO_ROOT"/backend/scripts/tests/test_*.py; do
  module="$(basename "$path" .py)"
  case "$DB_MODULES" in *" $module "*) ;; *) MODULES+=("backend.scripts.tests.$module") ;; esac
done

cd "$REPO_ROOT"
# The DB bootstrap refuses to run without TEST_DATABASE_URL; non-DB modules must not depend on it.
env -u TEST_DATABASE_URL "$PYTHON" -B -m unittest "$@" "${MODULES[@]}"
