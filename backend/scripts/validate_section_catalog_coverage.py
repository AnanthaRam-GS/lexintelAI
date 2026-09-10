import json
import re
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "data/structured/manifests/legal_section_catalog.json"

EXPECTED_CATALOG_COUNT = 62
CORRECTED_REVIEW_TOTALS = {
    "examples": 36,
    "primary": 36,
    "relevant": 24,
    "uncertain": 1,
    "positive_primary_relevant": 60,
    "total_annotated_including_uncertain": 61,
    "zero_positive_examples": ["sec-q026", "sec-q027", "sec-q035"],
}

BASELINE_CATALOG_KEYS = {
    ("IPC", "302"), ("IPC", "304"), ("IPC", "307"), ("IPC", "323"), ("IPC", "325"), ("IPC", "379"),
    ("IPC", "392"), ("IPC", "420"), ("IPC", "406"), ("IPC", "363"), ("IPC", "376"), ("IPC", "498A"),
    ("IPC", "120B"), ("IPC", "34"),
    ("CrPC", "438"), ("CrPC", "439"), ("CrPC", "167(2)"), ("CrPC", "482"), ("CrPC", "41A"),
    ("BNS", "103"), ("BNS", "109"), ("BNS", "115"), ("BNS", "303"), ("BNS", "309"), ("BNS", "318"),
    ("BNS", "316"), ("BNS", "137"), ("BNS", "64"), ("BNS", "85"), ("BNS", "61"), ("BNS", "3(5)"),
    ("BNSS", "482"), ("BNSS", "483"), ("BNSS", "187"), ("BNSS", "528"), ("BNSS", "35"),
    ("NDPS Act", "20"), ("NDPS Act", "21"), ("NDPS Act", "22"), ("NDPS Act", "29"),
    ("POCSO Act", "4"), ("POCSO Act", "8"),
    ("SC/ST Act", "3(1)(r)"), ("SC/ST Act", "3(1)(s)"),
}

APPROVED_HUMAN_REVIEW_ADDITIONS = {
    ("IPC", "394"), ("IPC", "408"), ("IPC", "361"), ("POCSO Act", "7"), ("NDPS Act", "37"),
    ("NDPS Act", "36A(4)"), ("IPC", "380"), ("IPC", "378"), ("BNS", "117"), ("BNS", "116"),
    ("IPC", "375"), ("SC/ST Act", "18"), ("BNS", "358"), ("BNSS", "531"), ("CrPC", "154(3)"),
    ("BNSS", "173(4)"), ("CrPC", "437"), ("BNSS", "187(3)"),
}


def normalize_statute(statute: str) -> str:
    return re.sub(r"\s+", " ", statute.strip()).casefold()


def normalize_section(section: str) -> str:
    return re.sub(r"\s+", "", section.strip()).casefold()


def normalize_key(key: tuple[str, str]) -> tuple[str, str]:
    return (normalize_statute(key[0]), normalize_section(key[1]))


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def catalog_keys(entries: Iterable[dict]) -> list[tuple[str, str]]:
    return [(entry["statute"], entry["section"]) for entry in entries]


def duplicate_normalized_keys(keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for key in keys:
        normalized = normalize_key(key)
        counts[normalized] = counts.get(normalized, 0) + 1
    return {key: count for key, count in counts.items() if count > 1}


def coverage_summary(path: Path = CATALOG_PATH) -> dict:
    entries = load_catalog(path)
    keys = catalog_keys(entries)
    normalized_keys = {normalize_key(key) for key in keys}
    baseline = {normalize_key(key) for key in BASELINE_CATALOG_KEYS}
    approved = {normalize_key(key) for key in APPROVED_HUMAN_REVIEW_ADDITIONS}
    additions = normalized_keys - baseline
    missing = approved - normalized_keys
    unauthorized = additions - approved
    duplicates = duplicate_normalized_keys(keys)

    return {
        "catalog_path": str(path.relative_to(REPO_ROOT)),
        "catalog_entries": len(entries),
        "approved_unique_provisions_checked": len(APPROVED_HUMAN_REVIEW_ADDITIONS),
        "missing": sorted(missing),
        "duplicates": {f"{key[0]}::{key[1]}": value for key, value in sorted(duplicates.items())},
        "normalization_conflicts": len(duplicates),
        "unauthorized_additions": sorted(unauthorized),
        "additions_relative_to_baseline": len(additions),
        "corrected_review_totals": CORRECTED_REVIEW_TOTALS,
        "valid": (
            len(entries) == EXPECTED_CATALOG_COUNT
            and len(APPROVED_HUMAN_REVIEW_ADDITIONS) == 18
            and additions == approved
            and not missing
            and not duplicates
            and not unauthorized
        ),
    }


def main() -> int:
    summary = coverage_summary()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
