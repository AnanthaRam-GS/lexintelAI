"""Readiness smoke tests for the Phase 1 shared E2E/UAT handoff."""

from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend.scripts.run_integration_smoke import EXPECTED_ROUTES, route_methods, run_smoke, summarize


REPO_ROOT = Path(__file__).resolve().parents[3]


class IntegrationReadinessSmokeTests(unittest.TestCase):
    def test_backend_health_smoke_allows_degraded_database(self) -> None:
        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["status"], {"ok", "degraded"})
        self.assertEqual(body["database"]["type"], "postgresql")
        self.assertIn("connected", body["database"])

    def test_backend_shared_e2e_route_surface_is_registered(self) -> None:
        available = route_methods()

        for path, methods in EXPECTED_ROUTES.items():
            with self.subTest(path=path):
                self.assertTrue(methods.issubset(available.get(path, set())))

    def test_smoke_script_summary_is_machine_readable(self) -> None:
        summary = summarize(run_smoke())

        self.assertEqual(summary["status"], "passed")
        self.assertEqual({check["name"] for check in summary["checks"]}, {"routes", "health"})
        self.assertTrue(all(check["ok"] for check in summary["checks"]))

    def test_frontend_api_client_contract_uses_cookie_credentials(self) -> None:
        api_client = (REPO_ROOT / "frontend/lib/api.ts").read_text(encoding="utf-8")

        self.assertIn("NEXT_PUBLIC_API_BASE_URL", api_client)
        self.assertIn("credentials: 'include'", api_client)
        self.assertNotIn("Authorization", api_client)

    def test_public_frontend_is_wired_to_live_public_query_api_only(self) -> None:
        query_client = (REPO_ROOT / "frontend/app/public/query-client.ts").read_text(encoding="utf-8")
        landing_page = (REPO_ROOT / "frontend/app/page.tsx").read_text(encoding="utf-8")

        self.assertIn("apiFetch<PublicQueryResponse>('/query/public'", query_client)
        self.assertIn("Public PDF query is not available yet.", query_client)
        self.assertIn("redirect('/public')", landing_page)


if __name__ == "__main__":
    unittest.main()
