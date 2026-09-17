"""Phase 1 integration-readiness smoke checks.

These checks are intentionally shallow: they verify boot, health, and route
surface without invoking live LLM providers, mutating indexes, or requiring a
healthy local database.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.main import app


EXPECTED_ROUTES: dict[str, set[str]] = {
    "/health": {"GET"},
    "/auth/login": {"POST"},
    "/auth/logout": {"POST"},
    "/auth/me": {"GET"},
    "/auth/register": {"POST"},
    "/auth/resend-verification": {"POST"},
    "/auth/verify-email": {"POST"},
    "/admin/lawyer-applications": {"GET"},
    "/admin/lawyer-applications/{application_id}": {"GET"},
    "/admin/lawyer-applications/{application_id}/approve": {"POST"},
    "/admin/lawyer-applications/{application_id}/reject": {"POST"},
    "/admin/lawyer-applications/{application_id}/request-resubmission": {"POST"},
    "/ingest/upload": {"POST"},
    "/ingest/status/{job_id}": {"GET"},
    "/ingest/corpus/stats": {"GET"},
    "/lawyer-applications": {"POST"},
    "/lawyer-applications/me": {"GET"},
    "/analytics/offence-frequency": {"GET"},
    "/analytics/offense-frequency": {"GET"},
    "/analytics/outcome-distribution": {"GET"},
    "/analytics/section-cooccurrence": {"GET"},
    "/analytics/ipc-bns": {"GET"},
    "/analytics/ipc-bns-map": {"GET"},
    "/analytics/ncrb": {"GET"},
    "/analytics/ncrb-stats": {"GET"},
    "/query/public": {"POST"},
    "/query/public/pdf": {"POST"},
    "/query/professional": {"POST"},
    "/query/professional/pdf": {"POST"},
    "/query/history": {"GET"},
    "/query-history": {"GET"},
}

ACCEPTED_HEALTH_STATUSES = {"ok", "degraded"}


@dataclass(frozen=True)
class SmokeResult:
    name: str
    ok: bool
    detail: str


def route_methods() -> dict[str, set[str]]:
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        methods_by_path.setdefault(path, set()).update(methods)
    return methods_by_path


def check_expected_routes() -> SmokeResult:
    available = route_methods()
    missing: list[str] = []
    for path, expected_methods in EXPECTED_ROUTES.items():
        actual_methods = available.get(path, set())
        absent_methods = sorted(expected_methods - actual_methods)
        if absent_methods:
            missing.append(f"{path} {'/'.join(absent_methods)}")
    if missing:
        return SmokeResult("routes", False, f"missing routes: {', '.join(missing)}")
    return SmokeResult("routes", True, f"{len(EXPECTED_ROUTES)} expected route contracts present")


def check_health() -> SmokeResult:
    client = TestClient(app)
    response = client.get("/health")
    if response.status_code != 200:
        return SmokeResult("health", False, f"unexpected HTTP {response.status_code}")
    body = response.json()
    status = body.get("status")
    if status not in ACCEPTED_HEALTH_STATUSES:
        return SmokeResult("health", False, f"unexpected status {status!r}")
    database = body.get("database", {})
    if database.get("type") != "postgresql" or "connected" not in database:
        return SmokeResult("health", False, "database health payload is missing expected fields")
    return SmokeResult("health", True, f"backend booted with health status {status}")


def run_smoke() -> list[SmokeResult]:
    return [check_expected_routes(), check_health()]


def summarize(results: Iterable[SmokeResult]) -> dict[str, object]:
    result_list = list(results)
    return {
        "status": "passed" if all(result.ok for result in result_list) else "failed",
        "checks": [asdict(result) for result in result_list],
    }


def main() -> int:
    summary = summarize(run_smoke())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
