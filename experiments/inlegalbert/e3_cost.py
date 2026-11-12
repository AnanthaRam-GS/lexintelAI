"""Step E3 cost: startup, warm-up, memory, swap and latency of the backend with the NER backend off and on. No LLM.

Local only, with real models (MPS when available) and the deterministic fake LLM, on the rehearsal database and copies
of the stores, prepared as for the step 18 stress test (docs/TESTING.md, "Model concurrency stress"). For each backend
(``deterministic``, then ``combined``) it starts a fresh ``uvicorn`` with the startup warm-up on and
``LEGALAI_QUERY_DEBUG=1``, then measures:

- **startup**: seconds until ``/health`` first answers, and until the warm-up is ready (query models and, with
  ``combined``, the NER model), with the load and warm-up times ``/health`` reports;
- **memory**: the backend process's resident set (``ps``) and physical footprint (``footprint``, which includes the
  MPS/Metal allocations), and the system swap in use (``sysctl vm.swapusage``), idle (after the warm-up) and during
  the queries (maximum of samples every 0.5 s);
- **latency**: 10 fixed professional text queries (``stress_inference.QUERIES``) x 3, sequential, warm: the request
  time, and from the response's debug timings the query understanding, the NER backend stage (``ner_backend_ms``,
  combined only) and the retrieval stage; p50 and p95.

Separately (``--ner-stage``), the NER stage alone in-process: ``ner_backend.extract_entities`` on the same 10 queries
x 3, warm, per backend (the deterministic NER is part of query understanding; this isolates it).

    APP_ENV=test DATABASE_URL=<legalai_rehearsal url> .venv/bin/python experiments/inlegalbert/e3_cost.py \\
        --state-dir <dir> --out experiments/inlegalbert/results
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.scripts.dev.stress_inference import QUERIES, percentile, request, server_env, wait_for_http  # noqa: E402

REPEATS = 3


def swap_used_mb() -> float:
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    match = re.search(r"used = ([\d.]+)M", out)
    return float(match.group(1)) if match else float("nan")


def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return round(int(out) / 1024, 1) if out else float("nan")


def footprint_mb(pid: int) -> float:
    out = subprocess.run(["footprint", "-p", str(pid), "-f", "bytes"], capture_output=True, text=True).stdout
    match = re.search(r"phys_footprint:\s*(\d+)", out) or re.search(r"Footprint:\s*(\d+)\s*B", out)
    return round(int(match.group(1)) / 2**20, 1) if match else float("nan")


def memory(pid: int) -> dict[str, float]:
    return {"rss_mb": rss_mb(pid), "footprint_mb": footprint_mb(pid), "swap_used_mb": swap_used_mb()}


class Sampler(threading.Thread):
    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid, self.samples, self.stop = pid, [], threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            self.samples.append(memory(self.pid))
            self.stop.wait(0.5)

    def peak(self) -> dict[str, float]:
        return {key: max(s[key] for s in self.samples) for key in self.samples[0]} if self.samples else {}


def health(base: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{base}/health", timeout=5) as response:
        return json.loads(response.read())


def ready(status: dict[str, Any], backend: str) -> bool:
    if status["models"].get("warm_up") != "ready":
        return False
    return backend != "combined" or status["ner"].get("model", {}).get("status") in {"ready", "failed"}


def run_server(backend: str, args: argparse.Namespace) -> dict[str, Any]:
    env = server_env(argparse.Namespace(state_dir=args.state_dir, no_warmup=False, device=None, inference_timeout=None))
    env.update({"LEGALAI_NER_BACKEND": backend, "LEGALAI_QUERY_DEBUG": "1"})
    base = f"http://127.0.0.1:{args.port}"
    log_path = args.out / f"e3_cost_server_{backend}.log"
    swap_before = swap_used_mb()
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
                                   cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    result: dict[str, Any] = {"backend": backend, "swap_used_mb_before_start": swap_before}
    try:
        if not wait_for_http(base, process, time.time() + 180):
            raise SystemExit(f"{backend}: server did not answer")
        result["startup_to_http_s"] = round(time.perf_counter() - started, 2)
        deadline = time.time() + 600
        status = health(base)
        while not ready(status, backend) and time.time() < deadline:
            time.sleep(0.25)
            status = health(base)
        result["startup_to_warm_s"] = round(time.perf_counter() - started, 2)
        result["health_models"] = {k: status["models"].get(k) for k in ("status", "warm_up", "load_ms", "warmup_ms", "devices")}
        result["health_ner"] = status["ner"]
        time.sleep(10)
        result["idle"] = memory(process.pid)

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        lawyer = json.loads((args.state_dir / "accounts.json").read_text())["lawyer"]
        login, _t, _c = request(f"{base}/auth/login", {"email": lawyer["email"], "password": lawyer["password"]}, opener, 30)
        if login != 200:
            raise SystemExit(f"login failed: {login}")
        sampler = Sampler(process.pid)
        sampler.start()
        rows = []
        for repeat in range(REPEATS):
            for query in QUERIES:
                body = json.dumps({"text": query}).encode()
                req = urllib.request.Request(f"{base}/query/professional", data=body,
                                             headers={"Content-Type": "application/json", "Origin": "http://localhost:3000"})
                t0 = time.perf_counter()
                with opener.open(req, timeout=180) as response:
                    payload = json.loads(response.read())
                    status_code = response.status
                timings = (payload.get("debug") or {}).get("timings_ms", {})
                rows.append({"repeat": repeat, "status": status_code, "request_ms": round((time.perf_counter() - t0) * 1000, 1),
                             "query_understanding_ms": timings.get("query_understanding_ms"),
                             "ner_backend_ms": timings.get("ner_backend_ms"),
                             "retrieval_total_ms": timings.get("retrieval_total_ms")})
        sampler.stop.set()
        sampler.join()
        result["during_queries_peak"] = sampler.peak()
        result["requests"] = rows
        result["statuses"] = sorted({r["status"] for r in rows})

        def stats(key: str) -> dict[str, float | None]:
            values = [r[key] for r in rows if r[key] is not None]
            return {"n": len(values), "p50": percentile(values, 0.5), "p95": percentile(values, 0.95)}

        result["latency_ms"] = {key: stats(key) for key in ("request_ms", "query_understanding_ms", "ner_backend_ms", "retrieval_total_ms")}
        retrieval_path = [r["query_understanding_ms"] + (r["ner_backend_ms"] or 0) + r["retrieval_total_ms"] for r in rows
                          if r["query_understanding_ms"] is not None and r["retrieval_total_ms"] is not None]
        result["latency_ms"]["understanding_plus_ner_plus_retrieval"] = {
            "n": len(retrieval_path), "p50": percentile(retrieval_path, 0.5), "p95": percentile(retrieval_path, 0.95)}
        result["health_ner_after"] = health(base)["ner"]
    finally:
        exit_code = process.poll()
        result["crashed"] = exit_code is not None
        if exit_code is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
    return result


def ner_stage(backend: str) -> dict[str, Any]:
    from backend.app.core.config import Settings
    from backend.app.services import ner_backend

    os.environ["LEGALAI_NER_BACKEND"] = backend
    ner_backend.reset_ner_backend()
    settings = Settings()
    ner_backend.extract_entities("warm-up", settings)  # load and warm
    ner_backend.extract_entities(QUERIES[0], settings)
    times = []
    for _ in range(REPEATS):
        for query in QUERIES:
            t0 = time.perf_counter()
            ner_backend.extract_entities(query, settings)
            times.append((time.perf_counter() - t0) * 1000)
    return {"n": len(times), "p50": percentile(times, 0.5), "p95": percentile(times, 0.95),
            "mean": round(statistics.fmean(times), 3), "status": ner_backend.ner_status(settings)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--ner-stage", action="store_true", help="only the in-process NER stage timing")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.ner_stage:
        result = {backend: ner_stage(backend) for backend in ("deterministic", "combined")}
        (args.out / "e3_cost_ner_stage.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=1))
        return 0
    if args.state_dir is None:
        raise SystemExit("--state-dir is required")
    result = {"queries": list(QUERIES), "repeats": REPEATS, "servers": [run_server(b, args) for b in ("deterministic", "combined")]}
    summary = [{k: s.get(k) for k in ("backend", "startup_to_http_s", "startup_to_warm_s", "health_models", "health_ner", "idle",
                                      "during_queries_peak", "latency_ms", "statuses", "crashed", "health_ner_after")}
               for s in result["servers"]]
    (args.out / "e3_cost.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
