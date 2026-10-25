"""Concurrency stress for the local query models (step 18; docs/performance/PERFORMANCE_BASELINE.md).

Local only: real BGE-M3 and the BGE reranker (MPS when available), the deterministic fake LLM, a rehearsal
database and copies of the stores, prepared as for the local real-mode end-to-end run (docs/TESTING.md).

Each repetition starts a fresh backend with the startup warm-up ON and, as soon as it answers HTTP:
1. sends N simultaneous professional text queries (they overlap the warm-up);
2. runs R more rounds of N simultaneous queries;
3. measures single-request latency (sequential queries).
It records every response status and latency, whether the process died (and by which signal), and keeps the
server log (faulthandler is on, so a native crash prints every thread's Python stack).

Usage:
    APP_ENV=test DATABASE_URL=<legalai_rehearsal url> .venv/bin/python backend/scripts/dev/stress_inference.py \\
        --state-dir <dir with chroma_store, bm25_store, accounts.json> --repetitions 5 --out <dir>
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import os
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "http://localhost:3000"
QUERIES = (
    "Regular bail after long custody for an accused under Section 61 BNS",
    "Anticipatory bail in a dowry death case under Section 304B IPC",
    "Quashing an FIR for cheating under Section 420 IPC in a commercial dispute",
    "Circumstantial evidence needed to convict for murder under Section 302 IPC",
    "Abetment of suicide under Section 306 IPC and the need for instigation",
    "Test identification parade delay in a robbery case",
    "Cruelty by husband under Section 498A IPC and the evidence of the parents",
    "Default bail when the charge sheet is not filed in time",
    "Common intention under Section 34 IPC for a group attack",
    "Recovery of stolen property and the presumption under Section 114 of the Evidence Act",
)


def server_env(args: argparse.Namespace) -> dict[str, str]:
    state = str(args.state_dir)
    env = {
        **os.environ,
        "APP_ENV": "test",
        "LEGALAI_E2E_FAKE_PROVIDERS": "1",
        "LEGALAI_E2E_STATE_DIR": state,
        "LEGALAI_E2E_RETRIEVAL": "real",
        "LEGALAI_E2E_LLM": "fake",
        "CHROMA_PERSIST_DIR": str(args.state_dir / "chroma_store"),
        "VERIFICATION_DOCUMENT_DIR": str(args.state_dir / "verification"),
        "LEGALAI_MODEL_WARMUP": "false" if args.no_warmup else "true",
        "GEMINI_API_KEY": "",
        "GROQ_API_KEY": "",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PUBLIC_QUERY_LIMIT_PER_MINUTE": "100000",
        "PUBLIC_QUERY_LIMIT_PER_DAY": "100000",
        "PROFESSIONAL_QUERY_LIMIT_PER_MINUTE": "100000",
        "PROFESSIONAL_QUERY_LIMIT_PER_DAY": "100000",
        "LLM_MAX_CONCURRENT_GENERATIONS": "64",
        "FRONTEND_ORIGIN": ORIGIN,
        "PYTHONFAULTHANDLER": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if args.device:
        env["LEGALAI_MODEL_DEVICE"] = args.device
    if args.inference_timeout is not None:
        env["LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS"] = str(args.inference_timeout)
    return env


def request(url: str, body: dict[str, Any] | None, opener: urllib.request.OpenerDirector, timeout: float) -> tuple[int | str, float, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Origin": ORIGIN})
    started = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as response:
            response.read()
            return response.status, time.perf_counter() - started, ""
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            code = json.loads(payload).get("code", "")
        except ValueError:
            code = ""
        return exc.code, time.perf_counter() - started, code
    except Exception as exc:  # connection refused/reset: the server died
        return type(exc).__name__, time.perf_counter() - started, ""


def wait_for_http(base: str, process: subprocess.Popen, deadline: float) -> bool:
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            time.sleep(0.2)
    return False


def concurrent_round(base: str, opener: urllib.request.OpenerDirector, n: int, timeout: float) -> list[dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(request, f"{base}/query/professional", {"text": QUERIES[i % len(QUERIES)]}, opener, timeout) for i in range(n)]
        return [{"status": s, "seconds": round(t, 3), "code": c} for s, t, c in (f.result() for f in futures)]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))], 3)


def run_repetition(index: int, args: argparse.Namespace) -> dict[str, Any]:
    base = f"http://127.0.0.1:{args.port}"
    log_path = args.out / f"server_{index:02d}.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-X", "faulthandler", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=REPO_ROOT, env=server_env(args), stdout=log, stderr=subprocess.STDOUT,
        )
    result: dict[str, Any] = {"repetition": index}
    try:
        if not wait_for_http(base, process, time.time() + 120):
            result["error"] = "server did not answer HTTP"
            return result
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        lawyer = json.loads((args.state_dir / "accounts.json").read_text())["lawyer"]
        status, _t, _c = request(f"{base}/auth/login", {"email": lawyer["email"], "password": lawyer["password"]}, opener, 30)
        result["login"] = status
        rounds = [concurrent_round(base, opener, args.concurrency, args.request_timeout)]  # overlaps the warm-up
        for _ in range(args.rounds):
            if process.poll() is not None:
                break
            rounds.append(concurrent_round(base, opener, args.concurrency, args.request_timeout))
        single = []
        for i in range(args.single):
            if process.poll() is not None:
                break
            single.append(request(f"{base}/query/professional", {"text": QUERIES[i % len(QUERIES)]}, opener, args.request_timeout))
        result["rounds"] = rounds
        result["single"] = [{"status": s, "seconds": round(t, 3), "code": c} for s, t, c in single]
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=5) as response:
                result["health_models"] = json.loads(response.read())["models"]
        except Exception as exc:
            result["health_models"] = f"unreachable: {type(exc).__name__}"
    finally:
        exit_code = process.poll()
        result["crashed"] = exit_code is not None
        result["exit_code"] = exit_code
        result["exit_signal"] = signal.Signals(-exit_code).name if exit_code is not None and exit_code < 0 else None
        if exit_code is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
        text = log_path.read_text(encoding="utf-8", errors="replace")
        result["segfault_in_log"] = "Segmentation fault" in text
        result["fatal_threads"] = sorted({line.split("[", 1)[1].split("]", 1)[0] for line in text.splitlines()
                                          if line.startswith(("Thread 0x", "Current thread 0x")) and "[" in line})
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    concurrent_ok = [r["seconds"] for rep in results for rnd in rep.get("rounds", []) for r in rnd if r["status"] == 200]
    single_ok = [r["seconds"] for rep in results for r in rep.get("single", []) if r["status"] == 200]
    statuses: dict[str, int] = {}
    for rep in results:
        for r in [x for rnd in rep.get("rounds", []) for x in rnd] + rep.get("single", []):
            key = f"{r['status']}{':' + r['code'] if r['code'] else ''}"
            statuses[key] = statuses.get(key, 0) + 1
    return {
        "repetitions": len(results),
        "crashes": sum(1 for r in results if r["crashed"]),
        "crash_signals": [r["exit_signal"] for r in results if r["crashed"]],
        "statuses": statuses,
        "concurrent_latency_s": {"n": len(concurrent_ok), "p50": percentile(concurrent_ok, 0.5), "p95": percentile(concurrent_ok, 0.95),
                                 "max": max(concurrent_ok) if concurrent_ok else None},
        "single_latency_s": {"n": len(single_ok), "p50": percentile(single_ok, 0.5), "p95": percentile(single_ok, 0.95),
                             "mean": round(statistics.mean(single_ok), 3) if single_ok else None},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--single", type=int, default=5)
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--request-timeout", type=float, default=180)
    parser.add_argument("--inference-timeout", type=float, default=None)
    parser.add_argument("--no-warmup", action="store_true", help="start without the warm-up (requests only)")
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default=None, help="LEGALAI_MODEL_DEVICE (default: .env)")
    args = parser.parse_args(argv)
    if (os.environ.get("APP_ENV") or "") != "test" or not (os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1] == "legalai_rehearsal"):
        print("refused: needs APP_ENV=test and DATABASE_URL naming legalai_rehearsal", file=sys.stderr)
        return 2
    args.state_dir = args.state_dir.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for index in range(1, args.repetitions + 1):
        result = run_repetition(index, args)
        results.append(result)
        print(json.dumps({"repetition": index, "crashed": result["crashed"], "exit_signal": result["exit_signal"],
                          "segfault": result.get("segfault_in_log"), "threads": result.get("fatal_threads"),
                          "statuses": summarize([result])["statuses"]}), flush=True)
    summary = summarize(results)
    (args.out / "results.json").write_text(json.dumps({"summary": summary, "repetitions": results}, indent=2))
    print(json.dumps(summary, indent=2))
    return 1 if summary["crashes"] else 0


if __name__ == "__main__":
    sys.exit(main())
