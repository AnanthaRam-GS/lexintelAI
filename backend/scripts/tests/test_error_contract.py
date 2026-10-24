"""Every error response is {error, code, detail} (step 16, BE-003). No database, no LLM calls.

The route sweep calls every registered route with every way of failing it can reach without a database: no
credentials, invalid input, no input (the stub database then raises, so the handler path ends in the unhandled-error
500), and an unsupported method. Every non-2xx answer must have the unified body and an X-Request-ID header. A new
route that answers an error any other way fails ``test_every_route_answers_errors_in_the_unified_shape``;
``test_the_sweep_catches_a_non_conforming_route`` proves the sweep would notice.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import main as backend_main  # noqa: E402
from backend.app.api import query as query_api  # noqa: E402
from backend.app.core.dependencies import get_current_user  # noqa: E402
from backend.app.core.errors import INTERNAL_ERROR_MESSAGE  # noqa: E402
from backend.app.core.rate_limit import reset_limits  # noqa: E402
from backend.app.core.security import COOKIE_NAME  # noqa: E402
from backend.app.db.session import get_db  # noqa: E402
from backend.main import app  # noqa: E402

CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
LEAK_MARKERS = ("Traceback", 'File "', "/Users/", "probe-secret")


class _NoDatabase:
    """Any use raises, so a handler that reaches the database ends in the unhandled-error path."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("probe-secret: no database in the error-contract sweep")


class _ProbeUser:
    id = 0
    role = "admin"
    is_active = True
    email_verified = True
    email = "probe@legalai.local"
    full_name = "Probe"


def shape_problems(response: Any) -> list[str]:
    """Why a non-2xx response breaks the contract (empty when it conforms)."""
    problems = []
    if not response.headers.get("x-request-id"):
        problems.append("no X-Request-ID header")
    try:
        body = response.json()
    except ValueError:
        return [*problems, f"body is not JSON: {response.text[:80]!r}"]
    if not isinstance(body, dict) or set(body) != {"error", "code", "detail"}:
        return [*problems, f"keys are {sorted(body) if isinstance(body, dict) else type(body).__name__}, not error/code/detail"]
    if not isinstance(body["error"], str) or not body["error"].strip():
        problems.append("error is not a non-empty string")
    if not isinstance(body["code"], str) or not CODE_PATTERN.match(body["code"]):
        problems.append(f"code {body['code']!r} is not an UPPER_SNAKE code")
    if body["detail"] is not None and not isinstance(body["detail"], dict):
        problems.append("detail is neither null nor an object")
    if any(marker in response.text for marker in LEAK_MARKERS):
        problems.append("body leaks internal detail")
    if response.status_code == 500:
        if body["code"] != "INTERNAL_ERROR" or body["error"] != INTERNAL_ERROR_MESSAGE:
            problems.append("a 500 is not the generic INTERNAL_ERROR")
        if not isinstance(body["detail"], dict) or body["detail"].get("request_id") != response.headers.get("x-request-id"):
            problems.append("a 500 does not carry its request ID in detail")
    return problems


def concrete_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def sweep(test_app: Any) -> tuple[list[str], dict[str, set[int]]]:
    """(violations, error statuses seen per route) over every registered API route."""
    violations: list[str] = []
    seen: dict[str, set[int]] = {}
    client = TestClient(test_app, raise_server_exceptions=False)
    invalid_query = {"limit": "not-a-number", "year": "not-a-number", "status_filter": "x" * 300}
    for route in [route for route in test_app.routes if isinstance(route, APIRoute)]:
        path = concrete_path(route.path)
        key = f"{'/'.join(sorted(route.methods))} {route.path}"
        seen.setdefault(key, set())
        calls: list[tuple[str, dict[str, Any], bool]] = []
        for method in sorted(route.methods):
            calls += [
                (method, {}, False),  # no credentials
                (method, {"params": invalid_query, "json": {"probe": ["invalid"]}}, True),  # invalid input
                (method, {}, True),  # no input: the handler may reach the stub database
            ]
        unsupported = next(method for method in METHODS if method not in route.methods)
        calls.append((unsupported, {}, True))
        for method, kwargs, authenticated in calls:
            if authenticated:
                test_app.dependency_overrides[get_current_user] = lambda: _ProbeUser()
            else:
                test_app.dependency_overrides.pop(get_current_user, None)
            response = client.request(method, path, **kwargs)
            if response.status_code < 400:
                continue
            seen[key].add(response.status_code)
            for problem in shape_problems(response):
                violations.append(f"{method} {path} -> {response.status_code}: {problem}")
    test_app.dependency_overrides.pop(get_current_user, None)
    return violations, seen


class ErrorContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        reset_limits()
        self.addCleanup(reset_limits)
        app.dependency_overrides[get_db] = lambda: _NoDatabase()
        app.dependency_overrides[query_api.get_retrieval_service] = lambda: object()
        app.dependency_overrides[query_api.get_answer_adapter] = lambda: object()
        self.addCleanup(app.dependency_overrides.clear)
        patcher = patch.object(backend_main, "check_db_connection", return_value=(False, "not checked in the sweep"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app, raise_server_exceptions=False)

    def add_temporary_route(self, path: str, endpoint: Any) -> None:
        app.add_api_route(path, endpoint, methods=["GET"])
        route = app.router.routes[-1]
        self.addCleanup(app.router.routes.remove, route)

    def assertConforms(self, response: Any, status: int, code: str) -> dict[str, Any]:
        self.assertEqual(shape_problems(response), [])
        self.assertEqual((response.status_code, response.json()["code"]), (status, code))
        return response.json()


class RouteSweepTests(ErrorContractTestCase):
    def test_every_route_answers_errors_in_the_unified_shape(self) -> None:
        with self.assertLogs("legalai.errors", level="ERROR"):  # the stub-database 500s are logged, not returned
            violations, seen = sweep(app)
        self.assertEqual(violations, [])
        routes = {f"{'/'.join(sorted(route.methods))} {route.path}" for route in app.routes if isinstance(route, APIRoute)}
        self.assertEqual(set(seen), routes)
        self.assertEqual([key for key, statuses in seen.items() if not statuses], [])  # every route was made to fail
        statuses = set().union(*seen.values())
        self.assertTrue({401, 405, 422, 500} <= statuses, statuses)

    def test_the_sweep_catches_a_non_conforming_route(self) -> None:
        self.add_temporary_route("/__probe/legacy-error", lambda: JSONResponse({"detail": "legacy shape"}, status_code=400))
        with self.assertLogs("legalai.errors", level="ERROR"):
            violations, _seen = sweep(app)
        self.assertEqual(
            violations[-1:], ["GET /__probe/legacy-error -> 400: keys are ['detail'], not error/code/detail"]
        )


class RepresentativeErrorTests(ErrorContractTestCase):
    def test_validation_error_lists_fields_without_echoing_values(self) -> None:
        body = self.assertConforms(self.client.post("/auth/login", json={"password": "probe-secret-password"}), 422, "VALIDATION_ERROR")
        self.assertEqual(body["detail"], {"fields": [{"field": "body.email", "message": "Field required", "type": "missing"}]})
        self.assertNotIn("probe-secret-password", self.client.post("/auth/login", json={"password": "probe-secret-password"}).text)

    def test_authentication_and_role_errors(self) -> None:
        self.assertConforms(self.client.get("/auth/me"), 401, "NOT_AUTHENTICATED")
        self.assertConforms(self.client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"}), 401, "INVALID_SESSION")
        lawyer = type("Lawyer", (_ProbeUser,), {"role": "lawyer"})
        app.dependency_overrides[get_current_user] = lambda: lawyer()
        body = self.assertConforms(self.client.get("/ingest/corpus/stats"), 403, "FORBIDDEN")
        self.assertNotIn("lawyer", body["error"])

    def test_not_found_and_method_not_allowed(self) -> None:
        self.assertConforms(self.client.get("/no-such-route"), 404, "NOT_FOUND")
        response = self.client.delete("/health")
        self.assertConforms(response, 405, "METHOD_NOT_ALLOWED")
        self.assertEqual(response.headers["allow"], "GET")

    def test_rate_limit_keeps_retry_after(self) -> None:
        with patch.dict(os.environ, {"PUBLIC_QUERY_LIMIT_PER_MINUTE": "1", "PUBLIC_QUERY_LIMIT_PER_DAY": "100"}):
            self.assertConforms(self.client.post("/query/public", json={}), 422, "VALIDATION_ERROR")  # counts as a request
            limited = self.client.post("/query/public", json={"text": "What is bail?"})
        body = self.assertConforms(limited, 429, "RATE_LIMITED")
        retry_after = int(limited.headers["retry-after"])
        self.assertTrue(1 <= retry_after <= 60)
        self.assertEqual(body["detail"], {"retry_after": retry_after})

    def test_domain_and_middleware_errors(self) -> None:
        upload = self.client.post("/query/public/pdf", files={"file": ("notes.txt", b"hello", "text/plain")}, data={"query": "What is bail?"})
        self.assertConforms(upload, 400, "INVALID_PDF_EXTENSION")
        csrf = self.client.post("/auth/logout", headers={"Origin": "https://evil.example", "Cookie": f"{COOKIE_NAME}=x"})
        self.assertConforms(csrf, 403, "CSRF_ORIGIN_REJECTED")
        oversize = self.client.post("/ingest/upload", headers={"Content-Length": str(10**12)}, content=b"")
        self.assertConforms(oversize, 413, "REQUEST_TOO_LARGE")

    def test_unhandled_error_is_a_generic_500_with_the_request_id(self) -> None:
        def explode() -> None:
            raise RuntimeError("probe-secret at /Users/someone/legalai token=abc")

        self.add_temporary_route("/__probe/explode", explode)
        with self.assertLogs("legalai.errors", level="ERROR") as logs:
            response = self.client.get("/__probe/explode", headers={"X-Request-ID": "probe-req-1", "Origin": "http://localhost:3000"})
        body = self.assertConforms(response, 500, "INTERNAL_ERROR")
        self.assertEqual((response.headers["x-request-id"], body["detail"]), ("probe-req-1", {"request_id": "probe-req-1"}))
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:3000")  # readable by the browser
        self.assertIn("[request_id=probe-req-1]", logs.output[0])
        self.assertIn("RuntimeError", logs.output[0])

    def test_request_id_is_reused_only_when_sane(self) -> None:
        self.assertEqual(self.client.get("/health", headers={"X-Request-ID": "abc.DEF_123-x"}).headers["x-request-id"], "abc.DEF_123-x")
        for unsafe in ("has space", "x" * 65, "quote\"", "new\nline"[:3] + "%"):
            with self.subTest(unsafe=unsafe):
                generated = self.client.get("/health", headers={"X-Request-ID": unsafe}).headers["x-request-id"]
                self.assertRegex(generated, r"^[0-9a-f]{32}$")
        first, second = (self.client.get("/health").headers["x-request-id"] for _ in range(2))
        self.assertNotEqual(first, second)


class SourceConventionTests(unittest.TestCase):
    def test_no_error_is_raised_with_a_bare_string_detail_or_built_by_hand(self) -> None:
        """Errors use {code, message} (api_error or HTTPException(detail={...})); only core/errors.py builds bodies."""
        offenders = []
        for path in sorted((REPO_ROOT / "backend" / "app").rglob("*.py")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name == "HTTPException":
                    detail = next((kw.value for kw in node.keywords if kw.arg == "detail"), node.args[1] if len(node.args) > 1 else None)
                    if not isinstance(detail, ast.Dict):
                        offenders.append(f"{relative}:{node.lineno} HTTPException without a {{code, message}} dict")
                if name == "JSONResponse" and relative != "backend/app/core/errors.py":
                    offenders.append(f"{relative}:{node.lineno} JSONResponse built outside core/errors.py")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
