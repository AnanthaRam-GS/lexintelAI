"""Read-only semantic and mathematical validation for the cleaned NCRB data."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


SIMPLE_TABLES = {"TABLE1A11", "TABLE1A21", "TABLE1A3"}
DETAILED_TABLES = {"TABLE1A4", "TABLE1A5"}
COUNT_MEASURES = {
    "TABLE1A11": "ipc_crime_count",
    "TABLE1A21": "sll_crime_count",
    "TABLE1A3": "ipc_sll_crime_count",
}
RATE_MEASURES = {
    "TABLE1A11": "ipc_cognizable_crime_rate",
    "TABLE1A21": "sll_cognizable_crime_rate",
    "TABLE1A3": "ipc_sll_cognizable_crime_rate",
}
TOTAL_TYPES = {"STATE_TOTAL", "UT_TOTAL", "ALL_INDIA_TOTAL"}
YEARS = {2021, 2022, 2023}
SECTION_RE = re.compile(r"(?:sec(?:tion)?\.?\s*)([0-9][0-9a-z]*(?:[-/][0-9a-z]+)?)", re.I)
IPC_RE = re.compile(r"\b(?:sec(?:tion)?\.?\s*)?[0-9][0-9a-z]*(?:[-/][0-9a-z]+)?\s*IPC\b", re.I)
ACT_RE = re.compile(r"\b(?:act|acts)\b", re.I)


def json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (int, str, bool)):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    return str(value)


def records(df: pd.DataFrame, mask: pd.Series) -> list[dict[str, Any]]:
    return [{key: json_value(value) for key, value in row.items()} for row in df.loc[mask].to_dict("records")]


def clean_text(value: Any) -> str:
    return "" if pd.isna(value) else re.sub(r"\s+", " ", str(value)).strip()


def measure_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for table_id in sorted(SIMPLE_TABLES):
        subset = df[df.table_id.eq(table_id)]
        grouped = (subset.groupby(["state_ut", "crime_year", "measure"], dropna=False)
                   .size().reset_index(name="record_count"))
        grouped.insert(0, "table_id", table_id)
        rows.extend(grouped.to_dict("records"))
        count_rows = subset[subset.measure.eq(COUNT_MEASURES[table_id]) & subset.row_type.isin(["STATE", "UT"])]
        expected = (count_rows.groupby("state_ut")["crime_year"].apply(lambda values: sorted(set(values.dropna().astype(int))))
                   .to_dict())
        missing = {state: sorted(YEARS - set(years)) for state, years in expected.items() if YEARS - set(years)}
        summary[table_id] = {
            "measure_counts": subset.measure.value_counts(dropna=False).to_dict(),
            "crime_years": sorted(int(x) for x in subset.crime_year.dropna().unique()),
            "crime_count_rows": int(len(count_rows)),
            "states_or_uts_with_missing_crime_years": missing,
            "population_rows": int(subset.measure.eq("projected_population").sum()),
            "crime_rate_rows": int(subset.measure.eq(RATE_MEASURES[table_id]).sum()),
            "chargesheeting_rate_rows": int(subset.measure.eq("chargesheeting_rate").sum()),
        }
    return pd.DataFrame(rows), summary


def cross_table_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    parts = []
    for table_id, measure, name in [
        ("TABLE1A11", "ipc_crime_count", "ipc_count"),
        ("TABLE1A21", "sll_crime_count", "sll_count"),
        ("TABLE1A3", "ipc_sll_crime_count", "ipc_sll_count"),
    ]:
        part = df[(df.table_id.eq(table_id)) & df.measure.eq(measure) & df.row_type.isin(["STATE", "UT"])]
        part = part.groupby(["state_ut", "crime_year"], as_index=False).value.sum().rename(columns={"value": name})
        parts.append(part)
    merged = parts[0].merge(parts[1], on=["state_ut", "crime_year"], how="outer")
    merged = merged.merge(parts[2], on=["state_ut", "crime_year"], how="outer")
    for column in ["ipc_count", "sll_count", "ipc_sll_count"]:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged["calculated_sum"] = merged["ipc_count"] + merged["sll_count"]
    merged["difference"] = merged["calculated_sum"] - merged["ipc_sll_count"]
    merged["status"] = "MISSING_SOURCE"
    complete = merged[["ipc_count", "sll_count", "ipc_sll_count"]].notna().all(axis=1)
    merged.loc[complete & merged.difference.abs().le(0.5), "status"] = "MATCH"
    merged.loc[complete & merged.difference.abs().gt(0.5), "status"] = "MISMATCH"
    columns = ["state_ut", "crime_year", "ipc_count", "sll_count", "ipc_sll_count", "calculated_sum", "difference", "status"]
    result = merged[columns].sort_values(["state_ut", "crime_year"], na_position="last")
    return result, {"status_counts": result.status.value_counts().to_dict(), "mismatch_rows": records(result, result.status.eq("MISMATCH"))}


def ivr_validation(df: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table_id in sorted(DETAILED_TABLES):
        subset = df[df.table_id.eq(table_id)]
        grouped = subset.groupby(["state_ut", "header_path"], dropna=False).measure.agg(lambda values: sorted(set(values)))
        incomplete = grouped[grouped.apply(lambda values: not {"incidence_cases", "victims", "rate"}.issubset(values))]
        result[table_id] = {
            "measure_counts": subset.measure.value_counts(dropna=False).to_dict(),
            "unexpected_measures": sorted(set(subset.measure.dropna()) - {"incidence_cases", "victims", "rate"}),
            "offence_state_combinations": int(len(grouped)),
            "complete_ivr_combinations": int(len(grouped) - len(incomplete)),
            "incomplete_ivr_combinations": int(len(incomplete)),
            "incomplete_examples": [{"state_ut": key[0], "header_path": key[1], "measures": value} for key, value in incomplete.head(25).items()],
            "null_value_rows": int(subset.value.isna().sum()),
        }
    return result


def legal_and_header_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    legal = df.legal_section.fillna("").map(clean_text)
    for index, row in df.iterrows():
        values = {field: clean_text(row[field]) for field in ["crime_category", "offence", "legal_section", "sub_offence", "header_path"]}
        issue_types: list[str] = []
        path_parts = [part.strip() for part in values["header_path"].split("|") if part.strip()]
        normalized = [re.sub(r"\s+", " ", part).casefold() for part in path_parts]
        if len(normalized) != len(set(normalized)):
            issue_types.append("DUPLICATED_HIERARCHY_LEVEL")
        if values["header_path"] and len(path_parts) < 2 and row.table_id in DETAILED_TABLES:
            issue_types.append("SHORT_HEADER_PATH")
        if row.table_id in DETAILED_TABLES and any(not values[field] for field in ["crime_category", "offence", "header_path"]):
            issue_types.append("EMPTY_HIERARCHY_LEVEL")
        if any(category in values["offence"].casefold() for category in ["offences affecting", "offences against", "miscellaneous ipc crimes"]):
            issue_types.append("CATEGORY_AS_OFFENCE")
        if values["legal_section"] and not (IPC_RE.search(values["legal_section"]) or ACT_RE.search(values["legal_section"])):
            issue_types.append("SUSPICIOUS_LEGAL_SECTION")
        if values["header_path"] and ACT_RE.search(values["header_path"]) and not IPC_RE.search(values["header_path"]):
            issue_types.append("ACT_NOT_IPC")
        if issue_types:
            issues.append({"record_id": row.record_id, "table_id": row.table_id, "state_ut": row.state_ut,
                           "crime_year": row.crime_year, "crime_category": row.crime_category,
                           "offence": row.offence, "legal_section": row.legal_section,
                           "sub_offence": row.sub_offence, "header_path": row.header_path,
                           "anomaly_types": ";".join(issue_types)})
    issue_df = pd.DataFrame(issues, columns=["record_id", "table_id", "state_ut", "crime_year", "crime_category", "offence", "legal_section", "sub_offence", "header_path", "anomaly_types"])
    legal_present = legal.ne("")
    return issue_df, {
        "legal_section_rows": int(legal_present.sum()),
        "missing_legal_section_rows": int((~legal_present).sum()),
        "ipc_section_rows": int(legal.map(lambda value: bool(IPC_RE.search(value))).sum()),
        "act_only_rows": int(df.header_path.fillna("").map(lambda value: bool(ACT_RE.search(value)) and not bool(IPC_RE.search(value))).sum()),
        "suspicious_legal_section_rows": int(issue_df.anomaly_types.fillna("").str.contains("SUSPICIOUS_LEGAL_SECTION").sum()),
        "header_anomaly_rows": int(len(issue_df)),
    }


def total_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (table_id, crime_year, measure), group in df[df.measure.notna()].groupby(["table_id", "crime_year", "measure"], dropna=False):
        if measure not in set(COUNT_MEASURES.values()) | {"projected_population"}:
            continue
        if table_id in DETAILED_TABLES:
            keys = ["header_path"]
        else:
            keys = [None]
        for key in keys:
            current = group if key is None else group[group.header_path.eq(key)]
            state_total = current[current.row_type.eq("STATE_TOTAL")].value.sum()
            ut_total = current[current.row_type.eq("UT_TOTAL")].value.sum()
            all_total = current[current.row_type.eq("ALL_INDIA_TOTAL")].value.sum()
            state_sum = current[current.row_type.eq("STATE")].value.sum()
            ut_sum = current[current.row_type.eq("UT")].value.sum()
            if not (state_total or ut_total or all_total):
                continue
            checks = [("STATE_TOTAL", state_sum, state_total), ("UT_TOTAL", ut_sum, ut_total), ("ALL_INDIA_TOTAL", state_total + ut_total, all_total)]
            for check_name, calculated, reported in checks:
                if not reported:
                    status = "NOT_APPLICABLE"
                elif abs(calculated - reported) <= 0.5:
                    status = "MATCH"
                else:
                    status = "MISMATCH"
                rows.append({"table_id": table_id, "crime_year": crime_year, "measure": measure,
                             "header_path": key, "check": check_name, "calculated": calculated,
                             "reported": reported, "difference": calculated - reported, "status": status})
    result = pd.DataFrame(rows)
    return result, {"status_counts": result.status.value_counts().to_dict() if not result.empty else {},
                    "mismatch_rows": records(result, result.status.eq("MISMATCH")) if not result.empty else []}


def rate_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table_id in sorted(SIMPLE_TABLES):
        subset = df[df.table_id.eq(table_id) & df.row_type.isin(["STATE", "UT", "STATE_TOTAL", "UT_TOTAL", "ALL_INDIA_TOTAL"])]
        for (state_ut, crime_year), group in subset.groupby(["state_ut", "crime_year"], dropna=False):
            count = group[group.measure.eq(COUNT_MEASURES[table_id])].value.sum()
            population = group[group.measure.eq("projected_population")].value.sum()
            reported = group[group.measure.str.contains("_rate", na=False) & ~group.measure.eq("chargesheeting_rate")].value.sum()
            if count and population and reported:
                calculated = count / population
                difference = calculated - reported
                rows.append({"table_id": table_id, "state_ut": state_ut, "crime_year": crime_year,
                             "count": count, "population_lakhs": population, "reported_rate": reported,
                             "calculated_rate": calculated, "difference": difference,
                             "status": ("MATCH" if abs(difference) <= 0.2 else
                                        "ROUNDING_OR_ROUNDED_DENOMINATOR" if abs(difference) <= 2 else "MISMATCH"),
                             "rate_unit": "per lakh population", "formula": "count / population_lakhs"})
    result = pd.DataFrame(rows)
    charge = df[df.measure.eq("chargesheeting_rate")]
    invalid_charge = int((~charge.value.between(0, 100)).sum())
    summary = {"recomputed_rate_rows": len(result), "status_counts": result.status.value_counts().to_dict() if not result.empty else {},
               "chargesheeting_rate_out_of_range": invalid_charge,
               "rate_anomaly_rows": records(result, result.status.eq("MISMATCH")) if not result.empty else []}
    return result, summary


def duplicate_candidates(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["publication_year", "crime_year", "table_id", "state_ut", "offence", "measure", "value"]
    mask = df.duplicated(keys, keep=False)
    return df.loc[mask, keys + ["record_id", "header_path"]].sort_values(keys)


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    df = pd.read_csv(input_path, keep_default_na=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["crime_year"] = pd.to_numeric(df["crime_year"], errors="coerce").astype("Int64")
    measure_counts, table_summary = measure_validation(df)
    cross, cross_summary = cross_table_validation(df)
    ivr_summary = ivr_validation(df)
    header, header_summary = legal_and_header_validation(df)
    totals, total_summary = total_validation(df)
    rates, rate_summary = rate_validation(df)
    duplicates = duplicate_candidates(df)
    null_value_details = df[df.value.isna()][["record_id", "table_id", "state_ut", "offence", "source_metric", "header_path"]].copy()
    measure_counts.to_csv(output_dir / "ncrb_measure_counts.csv", index=False)
    cross.to_csv(output_dir / "ncrb_cross_table_validation.csv", index=False)
    header.to_csv(output_dir / "ncrb_header_validation.csv", index=False)
    totals.to_csv(output_dir / "ncrb_total_validation.csv", index=False)
    rates.to_csv(output_dir / "ncrb_rate_validation.csv", index=False)
    duplicates.to_csv(output_dir / "ncrb_duplicate_candidates.csv", index=False)
    null_value_details.to_csv(output_dir / "ncrb_null_value_details.csv", index=False)
    null_columns = {column: int(df[column].isna().sum()) for column in df.columns if df[column].isna().any()}
    table_counts = df.table_id.value_counts(dropna=False).to_dict()
    year_counts = df.crime_year.value_counts(dropna=False).sort_index().to_dict()
    summary: dict[str, Any] = {
        "input_file": str(input_path), "read_only": True, "total_records": int(len(df)),
        "records_per_table": table_counts, "records_per_crime_year": {str(json_value(k)): int(v) for k, v in year_counts.items()},
        "measures": sorted(str(x) for x in df.measure.dropna().unique()),
        "state_ut_count": int(df.state_ut.dropna().nunique()), "null_values": null_columns,
        "table_semantic_validation": table_summary, "cross_table_validation": cross_summary,
        "ivr_validation": ivr_summary, "legal_and_header_validation": header_summary,
        "total_validation": total_summary, "rate_validation": rate_summary,
        "duplicate_candidates": int(len(duplicates)),
        "null_value_details": records(null_value_details, pd.Series(True, index=null_value_details.index)),
        "conclusions": {
            "TABLE1A11": "PASS" if not table_summary["TABLE1A11"]["states_or_uts_with_missing_crime_years"] else "FINDINGS",
            "TABLE1A21": "PASS" if not table_summary["TABLE1A21"]["states_or_uts_with_missing_crime_years"] else "FINDINGS",
            "TABLE1A3": "PASS" if not cross_summary["mismatch_rows"] else "FINDINGS",
            "I/V/R": "PASS" if all(item["unexpected_measures"] == [] for item in ivr_summary.values()) else "FINDINGS",
            "totals": "PASS" if not total_summary["mismatch_rows"] else "FINDINGS",
            "rates": "PASS" if not rate_summary["rate_anomaly_rows"] and not rate_summary["chargesheeting_rate_out_of_range"] else "FINDINGS",
            "legal_sections": "PASS" if header_summary["suspicious_legal_section_rows"] == 0 else "FINDINGS",
            "reuse": "CONDITIONAL" if header_summary["header_anomaly_rows"] or cross_summary["mismatch_rows"] else "SAFE_PENDING_NEW_YEAR_TESTS",
        },
    }
    (output_dir / "ncrb_semantic_validation_report.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    text = ["NCRB semantic validation report", "", f"Input: {input_path}", f"Read-only: {summary['read_only']}", f"Total records: {len(df)}", ""]
    text += ["Conclusions:"] + [f"- {key}: {value}" for key, value in summary["conclusions"].items()]
    text += ["", "Key findings:", f"- Cross-table status counts: {cross_summary['status_counts']}", f"- Total status counts: {total_summary['status_counts']}", f"- Rate status counts: {rate_summary['status_counts']}", f"- Header/legal anomaly rows: {header_summary['header_anomaly_rows']}", f"- Legal rows with IPC sections: {header_summary['ipc_section_rows']}", f"- Legal rows with Acts only: {header_summary['act_only_rows']}", f"- Duplicate candidates: {len(duplicates)}", f"- NULL values: {null_columns}"]
    (output_dir / "ncrb_semantic_validation_report.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path("out/standardised_ncrb_clean.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("out"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = run(args.input, args.output_dir)
    print(json.dumps(summary["conclusions"], indent=2))
    print(f"Wrote semantic validation outputs to {args.output_dir}")


if __name__ == "__main__":
    main()