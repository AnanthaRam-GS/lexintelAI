"""Local-only stress test of the process-wide model lock with the real models (step 18).

Runs ``backend/scripts/dev/stress_inference.py``: startup with the warm-up plus 10 simultaneous professional text
queries, then 3 rounds of 10, for 5 repetitions, with real BGE-M3 and reranker (MPS when available) and the fake LLM,
against ``legalai_rehearsal`` and copies of the stores. It asserts 0 crashes and every response 200.

Skipped unless ``LEGALAI_RUN_LOCAL_STRESS=1`` (with ``DATABASE_URL`` naming ``legalai_rehearsal`` and
``LEGALAI_STRESS_STATE_DIR`` prepared as in docs/TESTING.md): CI has no model files, no rehearsal database and no
GPU, and the run takes minutes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENABLED = os.environ.get("LEGALAI_RUN_LOCAL_STRESS") == "1"


@unittest.skipUnless(
    ENABLED,
    "local-only: needs the real models (local cache, MPS), legalai_rehearsal and store copies; "
    "set LEGALAI_RUN_LOCAL_STRESS=1 (docs/TESTING.md)",
)
class RealModelStressTests(unittest.TestCase):
    def test_no_crash_under_warm_up_and_concurrent_queries(self) -> None:
        state = os.environ["LEGALAI_STRESS_STATE_DIR"]
        with tempfile.TemporaryDirectory() as out:
            completed = subprocess.run(
                [sys.executable, "backend/scripts/dev/stress_inference.py", "--state-dir", state, "--out", out,
                 "--repetitions", os.environ.get("LEGALAI_STRESS_REPETITIONS", "5")],
                cwd=REPO_ROOT, env={**os.environ, "APP_ENV": "test"}, capture_output=True, text=True, timeout=7200,
            )
            summary = json.loads((Path(out) / "results.json").read_text())["summary"]
        self.assertEqual(summary["crashes"], 0, completed.stdout[-2000:])
        self.assertEqual(set(summary["statuses"]), {"200"}, summary["statuses"])
        self.assertEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
