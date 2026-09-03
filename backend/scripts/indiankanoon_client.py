"""Safe Indian Kanoon API client scaffold for LegalAI corpus acquisition."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.env_utils import load_project_env  # noqa: E402

DEFAULT_BASE_URL = "https://api.indiankanoon.org"
USER_AGENT = "LegalAI corpus foundation/0.1"


class IndianKanoonClientError(RuntimeError):
    """Raised when the Indian Kanoon API request fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class IndianKanoonClient:
    """Small wrapper around documented Indian Kanoon API endpoints."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.token = token or os.getenv("INDIAN_KANOON_API_TOKEN", "")
        self.base_url = (base_url or os.getenv("INDIAN_KANOON_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._request_stats: Counter[str] = Counter()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise IndianKanoonClientError("Indian Kanoon API token is not configured.")
        return {
            "Authorization": f"Token {self.token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

    def _endpoint_for_path(self, path: str) -> str:
        if path.startswith("/search/"):
            return "search"
        if path.startswith("/docmeta/"):
            return "metadata"
        if path.startswith("/origdoc/"):
            return "original_document"
        if path.startswith("/doc/"):
            return "document"
        return "other"

    def _record_response(self, endpoint: str, status: int | None) -> None:
        self._request_stats["total_requests"] += 1
        self._request_stats[f"endpoint:{endpoint}"] += 1
        if status == 429:
            self._request_stats["status:429"] += 1
        elif status is None:
            self._request_stats["status:other"] += 1
        elif 200 <= status < 300:
            self._request_stats["status:2xx"] += 1
        elif 400 <= status < 500:
            self._request_stats["status:4xx"] += 1
        elif 500 <= status < 600:
            self._request_stats["status:5xx"] += 1
        else:
            self._request_stats["status:other"] += 1

    def get_request_stats(self) -> dict[str, Any]:
        return {
            "total_requests": self._request_stats["total_requests"],
            "requests_by_endpoint": {
                "search": self._request_stats["endpoint:search"],
                "document": self._request_stats["endpoint:document"],
                "metadata": self._request_stats["endpoint:metadata"],
                "original_document": self._request_stats["endpoint:original_document"],
                "other": self._request_stats["endpoint:other"],
            },
            "responses_by_category": {
                "2xx": self._request_stats["status:2xx"],
                "4xx": self._request_stats["status:4xx"],
                "429": self._request_stats["status:429"],
                "5xx": self._request_stats["status:5xx"],
                "other": self._request_stats["status:other"],
            },
        }

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self._request_bytes(path, params=params)
        try:
            parsed = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise IndianKanoonClientError("API response was not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise IndianKanoonClientError("API response JSON was not an object.")
        return parsed

    def _request_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(url, headers=self._headers(), data=b"", method="POST")
        endpoint = self._endpoint_for_path(path)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read()
        except urllib.error.HTTPError as exc:
            self._record_response(endpoint, exc.code)
            raise IndianKanoonClientError(
                f"Indian Kanoon API returned HTTP {exc.code}.",
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            self._record_response(endpoint, None)
            raise IndianKanoonClientError(f"Indian Kanoon API request failed: {exc}") from exc
        self._record_response(endpoint, status)
        if status < 200 or status >= 300:
            raise IndianKanoonClientError(
                f"Indian Kanoon API returned HTTP {status}.",
                status_code=status,
            )
        return body

    def search(
        self,
        query: str,
        page: int = 0,
        doctypes: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"formInput": query, "pagenum": page}
        if doctypes:
            params["doctypes"] = doctypes
        if from_date:
            params["fromdate"] = from_date.isoformat() if isinstance(from_date, date) else from_date
        if to_date:
            params["todate"] = to_date.isoformat() if isinstance(to_date, date) else to_date
        return self._request_json("/search/", params)

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request_json(f"/doc/{urllib.parse.quote(document_id)}/")

    def get_document_metadata(self, document_id: str) -> dict[str, Any]:
        return self._request_json(f"/docmeta/{urllib.parse.quote(document_id)}/")

    def get_original_document(self, document_id: str) -> bytes:
        return self._request_bytes(f"/origdoc/{urllib.parse.quote(document_id)}/")


def check_config() -> int:
    token = os.getenv("INDIAN_KANOON_API_TOKEN", "")
    base_url = os.getenv("INDIAN_KANOON_BASE_URL", DEFAULT_BASE_URL)
    print(f"Indian Kanoon base URL: {base_url}")
    if not token:
        print("Indian Kanoon API token is not configured.")
        return 0
    print("Indian Kanoon API token is configured.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_project_env()
    args = parse_args()
    if args.check_config:
        return check_config()
    print(
        "No API request was made. Use IndianKanoonClient from acquisition "
        "code after configuring INDIAN_KANOON_API_TOKEN.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
