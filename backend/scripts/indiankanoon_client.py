"""Safe Indian Kanoon API client scaffold for LegalAI corpus acquisition."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://api.indiankanoon.org"
USER_AGENT = "LegalAI corpus foundation/0.1"


class IndianKanoonClientError(RuntimeError):
    """Raised when the Indian Kanoon API request fails."""


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

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise IndianKanoonClientError("Indian Kanoon API token is not configured.")
        return {
            "Authorization": f"Token {self.token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
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
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read()
        except urllib.error.URLError as exc:
            raise IndianKanoonClientError(f"Indian Kanoon API request failed: {exc}") from exc
        if status < 200 or status >= 300:
            raise IndianKanoonClientError(f"Indian Kanoon API returned HTTP {status}.")
        return body

    def search(self, query: str, page: int = 0) -> dict[str, Any]:
        return self._request_json("/search/", {"formInput": query, "pagenum": page})

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
