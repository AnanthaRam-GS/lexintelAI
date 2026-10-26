#!/usr/bin/env bash
# Run the Playwright journeys (frontend/e2e) against a backend in end-to-end test mode (docs/TESTING.md).
#
# Usage:
#   DATABASE_URL=<postgres url of a *_e2e database> backend/scripts/e2e/run_e2e.sh [playwright args]
#
# Environment:
#   DATABASE_URL            required; a *_e2e database (fake mode) or legalai_rehearsal (real mode). Never dev.
#   E2E_MODE                fake (default: fixture corpus, fake embedder/reranker/LLM) or real (stores and DB
#                           already prepared by run_e2e_local_real.sh; real retrieval).
#   E2E_REAL_LLM            1 to call the configured LLM provider (real mode only; off by default).
#   LEGALAI_E2E_STATE_DIR   the run's directory (default: a new temporary directory).
#   E2E_PYTHON              Python to run the backend (default: .venv/bin/python, else python).
#
# Playwright starts the API (uvicorn) and the frontend (next build + next start) itself; see
# frontend/playwright.config.ts. Traces, screenshots and the HTML report go to frontend/test-results and
# frontend/playwright-report.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
: "${DATABASE_URL:?DATABASE_URL must name the end-to-end database}"
MODE="${E2E_MODE:-fake}"
case "$MODE" in fake | real) ;; *) echo "E2E_MODE must be fake or real" >&2; exit 2 ;; esac
if [ "${E2E_REAL_LLM:-0}" = "1" ] && [ "$MODE" != "real" ]; then
  echo "E2E_REAL_LLM=1 is only allowed with E2E_MODE=real" >&2
  exit 2
fi

export E2E_PYTHON="${E2E_PYTHON:-$REPO_ROOT/.venv/bin/python}"
[ -x "$E2E_PYTHON" ] || E2E_PYTHON="$(command -v python)"
export LEGALAI_E2E_STATE_DIR="${LEGALAI_E2E_STATE_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/legalai-e2e.XXXXXX")}"
mkdir -p "$LEGALAI_E2E_STATE_DIR"

export APP_ENV=test
export LEGALAI_E2E_FAKE_PROVIDERS=1
export CHROMA_PERSIST_DIR="$LEGALAI_E2E_STATE_DIR/chroma_store"
export VERIFICATION_DOCUMENT_DIR="$LEGALAI_E2E_STATE_DIR/verification"
export EXPOSE_DEV_VERIFICATION_TOKENS=true  # the registration journey reads the OTP from the API response
export EMAIL_DELIVERY_MODE=console
export FRONTEND_ORIGIN=http://localhost:3000
# The journeys ask more questions than the default per-minute limits allow; the limits have their own tests.
export PUBLIC_QUERY_LIMIT_PER_MINUTE=1000 PROFESSIONAL_QUERY_LIMIT_PER_MINUTE=1000
export PYTHONDONTWRITEBYTECODE=1
export E2E_MODE="$MODE"
# Never download a model: fake mode loads none, real mode uses the local Hugging Face cache.
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
if [ "$MODE" = "fake" ]; then
  export LEGALAI_E2E_RETRIEVAL=fake LEGALAI_MODEL_WARMUP=false
else
  # Warm-up runs as in production; model calls are serialised by backend/app/services/inference_lock.py.
  export LEGALAI_E2E_RETRIEVAL=real
fi
if [ "${E2E_REAL_LLM:-0}" = "1" ]; then
  export LEGALAI_E2E_LLM=real
else
  # No live model: blank the keys so nothing can reach a provider even by mistake.
  export LEGALAI_E2E_LLM=fake GEMINI_API_KEY= GROQ_API_KEY=
fi

cd "$REPO_ROOT"
"$E2E_PYTHON" -m backend.scripts.e2e.setup_e2e --state-dir "$LEGALAI_E2E_STATE_DIR" --mode "$MODE"
cd "$REPO_ROOT/frontend"
npx playwright test "$@"
