"""Small development `.env` loader for LegalAI scripts.

This helper intentionally supports only simple KEY=VALUE lines needed by the
local project environment. It does not log values and does not override
environment variables already set by the caller or deployment environment.
"""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository root based on this script helper location."""

    return Path(__file__).resolve().parents[2]


def _strip_simple_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_project_env(env_path: Path | None = None) -> None:
    """Load simple root `.env` values without overriding process env."""

    path = env_path or project_root() / ".env"
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_simple_quotes(value.strip())
        if key:
            os.environ.setdefault(key, value)
