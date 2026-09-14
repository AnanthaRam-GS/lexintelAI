"""Standardize the parsed NCRB 1A dataset without modifying the raw CSV."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


TABLES = {"TABLE1A11", "TABLE1A21", "TABLE1A3", "TABLE1A4", "TABLE1A5"}
FINAL_COLUMNS = [
    "record_id", "publication_year", "crime_year", "table_id", "source_file",
    "source_page", "section", "state_ut", "row_type", "crime_category",
    "offence", "legal_section", "sub_offence", "source_metric", "measure",
    "value", "unit", "header_path", "notes",
]
PAGE_ARTIFACT_RE = re.compile(
    r"TABLE\s*1A\.?\s*\w+\s+Page\s+\d+\s+of\s+\d+", re.IGNORECASE
)
FOOTNOTE_PATTERNS = (
    re.compile(r"states/uts?\s+may\s+not\s+be\s+compared\s+purely", re.IGNORECASE),
    re.compile(r"as\s+per\s+data\s+provided\s+by\s+states/uts?", re.IGNORECASE),
)
LEGAL_SECTION_RE = re.compile(
    r"\(([^()]*?(?:sec\.?|section)[^()]*?)\)", re.IGNORECASE
)
YEAR_RE = re.compile(r"\b(20\d{2})\b")


BASE_MEASURES = {
    "TABLE1A11": {
        "count": "ipc_crime_count",
        "population": "projected_population",
        "rate": "ipc_cognizable_crime_rate",
        "chargesheet": "chargesheeting_rate",
    },
    "TABLE1A21": {
        "count": "sll_crime_count",
        "population": "projected_population",
        "rate": "sll_cognizable_crime_rate",
        "chargesheet": "chargesheeting_rate",
    },
    "TABLE1A3": {
        "count": "ipc_sll_crime_count",
        "population": "projected_population",
        "rate": "ipc_sll_cognizable_crime_rate",
        "chargesheet": "chargesheeting_rate",
    },
}


def nonempty(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def values_in_row(row: pd.Series) -> list[str]:
    return [text for value in row.tolist() if (text := nonempty(value))]


def classify_removal(row: pd.Series) -> str | None:
    values = values_in_row(row)
    if any(PAGE_ARTIFACT_RE.search(value) for value in values):
        return "PAGE_ARTIFACT"
    if any(pattern.search(value) for value in values for pattern in FOOTNOTE_PATTERNS):
        return "FOOTNOTE"
    return None


def clean_numeric(value: Any) -> float | int | None:
    text = nonempty(value)
    if text is None or text in {"-", "--", "NA", "N/A"}:
        return None
    text = text.replace(",", "")
    number = pd.to_numeric(text, errors="coerce")
    if pd.isna(number):
        return None
    return number


def row_type(row: pd.Series) -> str | None:
    state = (nonempty(row.get("state_ut")) or "").upper()
    section = (nonempty(row.get("section")) or "").upper()
    if "TOTAL ALL INDIA" in state:
        return "ALL_INDIA_TOTAL"
    if "TOTAL STATE" in state:
        return "STATE_TOTAL"
    if "TOTAL UT" in state:
        return "UT_TOTAL"
    if "UNION TERRITORIES" in section:
        return "UT"
    if "STATE" in section:
        return "STATE"
    return None


def extract_crime_year(table_id: str, source_metric: str | None, publication_year: int | None) -> int | None:
    if table_id in {"TABLE1A11", "TABLE1A21", "TABLE1A3"}:
        years = YEAR_RE.findall(source_metric or "")
        if years:
            return int(years[0])
        return None
    if table_id in {"TABLE1A4", "TABLE1A5"}:
        return publication_year
    return None


def normalize_base_measure(table_id: str, source_metric: str | None) -> tuple[str | None, str | None]:
    metric = (source_metric or "").strip()
    if table_id in {"TABLE1A4", "TABLE1A5"}:
        if metric == "I":
            return "incidence_cases", "count"
        if metric == "V":
            return "victims", "count"
        if metric == "R":
            return "rate", "per lakh population"
        return None, None
    if metric in {"2021", "2022", "2023"}:
        return BASE_MEASURES[table_id]["count"], "count"
    if "population" in metric.lower():
        return BASE_MEASURES[table_id]["population"], "lakhs"
    if "chargesheeting" in metric.lower():
        return BASE_MEASURES[table_id]["chargesheet"], "percent"
    if "rate" in metric.lower():
        return BASE_MEASURES[table_id]["rate"], "per lakh population"
    return None, None


def parse_hierarchy(header_path: Any) -> tuple[str | None, str | None, str | None, str | None]:
    text = nonempty(header_path)
    if not text:
        return None, None, None, None
    parts = [part.strip() for part in text.split("|") if part.strip()]
    unique_parts: list[str] = []
    for part in parts:
        if not unique_parts or part != unique_parts[-1]:
            unique_parts.append(part)
    legal_matches: list[str] = []
    for match in LEGAL_SECTION_RE.findall(text):
        value = re.sub(r"\s+", " ", match).strip()
        if value not in legal_matches:
            legal_matches.append(value)
    category = unique_parts[0] if unique_parts else None
    offence = unique_parts[1] if len(unique_parts) > 1 else None
    sub_offence = unique_parts[-1] if len(unique_parts) > 2 else None
    legal_section = "; ".join(legal_matches) or None
    return category, offence, legal_section, sub_offence


def stable_record_id(row: pd.Series) -> str:
    fields = ["publication_year", "crime_year", "table_id", "source_file", "section",
              "state_ut", "row_type", "crime_category", "offence", "legal_section",
              "sub_offence", "source_metric", "measure", "value", "unit", "header_path"]
    payload = "\x1f".join("" if pd.isna(row.get(field)) else str(row.get(field)) for field in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def normalize_table_1a11(row: pd.Series) -> tuple[str | None, str | None]:
    return normalize_base_measure("TABLE1A11", nonempty(row.get("metric")))


def normalize_table_1a21(row: pd.Series) -> tuple[str | None, str | None]:
    return normalize_base_measure("TABLE1A21", nonempty(row.get("metric")))


def normalize_table_1a3(row: pd.Series) -> tuple[str | None, str | None]:
    return normalize_base_measure("TABLE1A3", nonempty(row.get("metric")))


def normalize_table_1a4(row: pd.Series) -> tuple[str | None, str | None]:
    return normalize_base_measure("TABLE1A4", nonempty(row.get("metric")))


def normalize_table_1a5(row: pd.Series) -> tuple[str | None, str | None]:
    return normalize_base_measure("TABLE1A5", nonempty(row.get("metric")))


NORMALIZERS = {
    "TABLE1A11": normalize_table_1a11,
    "TABLE1A21": normalize_table_1a21,
    "TABLE1A3": normalize_table_1a3,
    "TABLE1A4": normalize_table_1a4,
    "TABLE1A5": normalize_table_1a5,
}


def standardize(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    raw = raw.replace({"": pd.NA})
    raw["removal_reason"] = raw.apply(classify_removal, axis=1)
    removed = raw[raw.removal_reason.notna()].copy()
    kept = raw[raw.removal_reason.isna()].drop(columns=["removal_reason"]).copy()

    records: list[dict[str, Any]] = []
    for _, row in kept.iterrows():
        table_id = nonempty(row.get("table_id"))
        if table_id not in TABLES:
            continue
        source_metric = nonempty(row.get("metric"))
        publication_year = pd.to_numeric(row.get("year"), errors="coerce")
        publication_year = int(publication_year) if not pd.isna(publication_year) else None
        measure, unit = NORMALIZERS[table_id](row)
        crime_category, offence, legal_section, sub_offence = parse_hierarchy(row.get("header_path"))
        record = {
            "publication_year": publication_year,
            "crime_year": extract_crime_year(table_id, source_metric, publication_year),
            "table_id": table_id,
            "source_file": nonempty(row.get("source_file")),
            "source_page": None,
            "section": nonempty(row.get("section")),
            "state_ut": nonempty(row.get("state_ut")),
            "row_type": row_type(row),
            "crime_category": crime_category,
            "offence": offence,
            "legal_section": legal_section,
            "sub_offence": sub_offence,
            "source_metric": source_metric,
            "measure": measure,
            "value": clean_numeric(row.get("value")),
            "unit": unit,
            "header_path": nonempty(row.get("header_path")),
            "notes": None,
        }
        records.append(record)

    cleaned = pd.DataFrame(records, columns=FINAL_COLUMNS[1:])
    before_dedupe = len(cleaned)
    duplicate_mask = cleaned.duplicated(keep="first")
    duplicate_rows = cleaned[duplicate_mask].copy()
    cleaned = cleaned[~duplicate_mask].copy()
    cleaned.insert(0, "record_id", cleaned.apply(stable_record_id, axis=1))

    removed_frames = []
    if not removed.empty:
        removed_frames.append(removed.drop(columns=["removal_reason"]).assign(removal_reason=raw.loc[removed.index, "removal_reason"].values))
    if not duplicate_rows.empty:
        duplicate_rows.insert(0, "record_id", duplicate_rows.apply(stable_record_id, axis=1))
        removed_frames.append(duplicate_rows.assign(removal_reason="EXACT_DUPLICATE"))
    if removed_frames:
        removed_output = pd.concat(removed_frames, ignore_index=True, sort=False)
    else:
        removed_output = pd.DataFrame(columns=[*raw.columns.drop("removal_reason"), "removal_reason"])

    cleaned = cleaned[FINAL_COLUMNS]
    output_dir.mkdir(parents=True, exist_ok=True)
    cleaned_path = output_dir / "standardised_ncrb_clean.csv"
    removed_path = output_dir / "ncrb_removed_records.csv"
    cleaned.to_csv(cleaned_path, index=False)
    removed_output.to_csv(removed_path, index=False)

    publication_years = sorted(int(x) for x in cleaned.publication_year.dropna().unique())
    crime_years = sorted(int(x) for x in cleaned.crime_year.dropna().unique())
    table_ids = sorted(str(x) for x in cleaned.table_id.dropna().unique())
    measures = sorted(str(x) for x in cleaned.measure.dropna().unique())
    row_types = sorted(str(x) for x in cleaned.row_type.dropna().unique())
    value_non_numeric = int(cleaned.value.notna().sum() - pd.to_numeric(cleaned.value, errors="coerce").notna().sum())
    report = {
        "input_file": str(input_path),
        "output_files": [str(cleaned_path), str(removed_path)],
        "original_row_count": int(len(raw)),
        "final_row_count": int(len(cleaned)),
        "rows_removed": int(len(raw) - len(cleaned)),
        "page_artifacts_removed": int((removed_output.removal_reason == "PAGE_ARTIFACT").sum()),
        "footnotes_removed": int((removed_output.removal_reason == "FOOTNOTE").sum()),
        "exact_duplicates_removed": int((removed_output.removal_reason == "EXACT_DUPLICATE").sum()),
        "publication_years": publication_years,
        "crime_years": crime_years,
        "table_ids": table_ids,
        "number_of_states_uts": int(cleaned.state_ut.dropna().nunique()),
        "missing_state_ut": int(cleaned.state_ut.isna().sum()),
        "missing_crime_year": int(cleaned.crime_year.isna().sum()),
        "missing_value": int(cleaned.value.isna().sum()),
        "unique_measures": measures,
        "unique_row_types": row_types,
        "duplicate_record_ids": int(cleaned.record_id.duplicated().sum()),
        "non_numeric_values": value_non_numeric,
        "exact_duplicates_before_removal": int(before_dedupe - len(cleaned)),
        "dataset_scope_statement": (
            "The current dataset contains only 2023 publication data and is NOT yet a complete 2020–2024 dataset."
            if publication_years == [2023] else "The current dataset contains multiple publication years."
        ),
    }
    (output_dir / "ncrb_standardization_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report_text = [
        "NCRB standardization report", "===========================", "",
        f"Original row count: {report['original_row_count']}",
        f"Final row count: {report['final_row_count']}",
        f"Rows removed: {report['rows_removed']}",
        f"Page artifacts removed: {report['page_artifacts_removed']}",
        f"Footnotes removed: {report['footnotes_removed']}",
        f"Exact duplicates removed: {report['exact_duplicates_removed']}",
        f"Publication years: {publication_years}", f"Crime years: {crime_years}",
        f"Table IDs: {table_ids}", f"Number of states/UTs: {report['number_of_states_uts']}",
        f"Missing state_ut: {report['missing_state_ut']}", f"Missing crime_year: {report['missing_crime_year']}",
        f"Missing value: {report['missing_value']}", f"Unique measures: {measures}",
        f"Unique row_types: {row_types}", f"Duplicate record_ids: {report['duplicate_record_ids']}",
        f"Non-numeric values: {report['non_numeric_values']}", "", report["dataset_scope_statement"],
    ]
    (output_dir / "ncrb_standardization_report.txt").write_text("\n".join(report_text) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="out/standardised_ncrb_2020_2024.csv")
    parser.add_argument("--output-dir", default="out")
    args = parser.parse_args()
    report = standardize(Path(args.input), Path(args.output_dir))
    for key in ["original_row_count", "final_row_count", "rows_removed", "page_artifacts_removed", "footnotes_removed", "exact_duplicates_removed"]:
        print(f"{key}: {report[key]}")
    for key in ["publication_years", "crime_years", "table_ids", "number_of_states_uts", "missing_state_ut", "missing_crime_year", "missing_value", "unique_measures", "unique_row_types", "duplicate_record_ids", "non_numeric_values"]:
        print(f"{key}: {report[key]}")
    print(report["dataset_scope_statement"])


if __name__ == "__main__":
    main()
