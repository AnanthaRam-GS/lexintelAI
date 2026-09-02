"""Reusable corpus integrity helpers for LegalAI acquisition scripts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a file, streaming large files safely."""

    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    """Return file size in bytes."""

    return path.stat().st_size


def safe_filename(value: str) -> str:
    """Convert arbitrary text into a conservative filesystem-safe filename."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "untitled"


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list manifest, returning an empty list if it is missing."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    if not isinstance(data, list):
        raise ValueError(f"Manifest must contain a JSON list: {path}")
    if not all(isinstance(record, dict) for record in data):
        raise ValueError(f"Manifest records must be JSON objects: {path}")
    return data


def write_manifest_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically write manifest records as formatted JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(records, file_obj, ensure_ascii=False, indent=2)
            file_obj.write("\n")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def find_duplicate_by_sha256(
    sha256: str,
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first manifest record with a matching SHA-256 digest."""

    for record in records:
        if record.get("sha256") == sha256:
            return record
    return None
