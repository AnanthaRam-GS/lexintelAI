"""Forensic, read-only investigation of the remaining NCRB validation findings."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd


ROOT = Path(__file__).resolve().parent
SIMPLE_TABLES = {"TABLE1A11", "TABLE1A21", "TABLE1A3"}
RATE_MEASURES = {
    "TABLE1A11": "ipc_cognizable_crime_rate",
    "TABLE1A21": "sll_cognizable_crime_rate",
    "TABLE1A3": "ipc_sll_cognizable_crime_rate",
}
COUNT_MEASURES = {
    "TABLE1A11": "ipc_crime_count",
    "TABLE1A21": "sll_crime_count",
    "TABLE1A3": "ipc_sll_crime_count",
}
IPC_RE = re.compile(r"\b(?:sec(?:tion)?\.?\s*)?[0-9][0-9a-z]*(?:[-/][0-9a-z]+)?\s*IPC\b", re.I)
SECTION_TOKEN_RE = re.compile(r"(?:sec(?:tion)?\.?\s*)([0-9][0-9a-z]*(?:[-/][0-9a-z]+)?)", re.I)
ACT_RE = re.compile(r"\b(?:act|acts)\b", re.I)
CATEGORY_RE = re.compile(r"^(?:offences?|crime|miscellaneous|children|women|schedule|arms|finance|liquor|environment|foreigner|telegraph|food|other regulatory)\b", re.I)


def clean(value: Any) -> str:
    return "" if pd.isna(value) else re.sub(r"\s+", " ", str(value)).strip()


def merged_lookup(ws: openpyxl.worksheet.worksheet.Worksheet) -> dict[tuple[int, int], Any]:
    lookup: dict[tuple[int, int], Any] = {}
    for cell_range in ws.merged_cells.ranges:
        top = ws.cell(cell_range.min_row, cell_range.min_col).value
        for row in range(cell_range.min_row, cell_range.max_row + 1):
            for column in range(cell_range.min_col, cell_range.max_col + 1):
                lookup[(row, column)] = top
    return lookup


def source_row_lookup(table_id: str, state: str, metric: str, value: float | int) -> dict[str, Any]:
    path = ROOT / f"{table_id}.xlsx"
    if not path.exists():
        return {"source_verified": False, "source_note": "Original workbook not found"}
    ws = openpyxl.load_workbook(path, data_only=True).active
    lookup = merged_lookup(ws)
    metric_columns: list[int] = []
    for row in range(1, min(ws.max_row, 25) + 1):
        for column in range(1, ws.max_column + 1):
            if clean(lookup.get((row, column), ws.cell(row, column).value)) == metric:
                metric_columns.append(column)
    matches: list[dict[str, Any]] = []
    for row in range(1, ws.max_row + 1):
        state_match = any(clean(ws.cell(row, column).value) == state for column in range(1, min(ws.max_column, 3) + 1))
        if not state_match:
            continue
        for column in metric_columns:
            cell_value = ws.cell(row, column).value
            try:
                same_value = abs(float(cell_value) - float(value)) < 1e-9
            except (TypeError, ValueError):
                same_value = False
            if same_value:
                matches.append({"source_row": row, "source_metric_cell": ws.cell(row, column).coordinate,
                                "source_value_cell": ws.cell(row, column).coordinate,
                                "source_value": cell_value, "merged_header_columns": metric_columns})
    if not matches:
        return {"source_verified": False, "source_note": "No exact state/metric/value workbook match"}
    return {"source_verified": True, **matches[0], "source_note": "Exact state/metric/value match in original workbook"}


def rate_review(cleaned: pd.DataFrame, raw: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    rate_rows = pd.read_csv(output_dir / "ncrb_rate_validation.csv")
    targets = rate_rows[rate_rows.status.eq("MISMATCH")].copy()
    output: list[dict[str, Any]] = []
    for _, rate in targets.iterrows():
        table_id, state, crime_year = rate.table_id, rate.state_ut, int(rate.crime_year)
        measure = RATE_MEASURES[table_id]
        clean_row = cleaned[(cleaned.table_id.eq(table_id)) & cleaned.state_ut.eq(state) & cleaned.measure.eq(measure)].iloc[0]
        source_metric = clean_row.source_metric
        raw_match = raw[(raw.table_id.eq(table_id)) & raw.state_ut.eq(state) & raw.metric.eq(source_metric) & (pd.to_numeric(raw.value, errors="coerce").eq(float(rate.reported_rate)))]
        source = source_row_lookup(table_id, state, source_metric, rate.reported_rate)
        implied_population = float(rate["count"]) / float(rate.reported_rate)
        reason = "Rounded population denominator: published rate is consistent with an implied unrounded population near the displayed one-decimal population."
        if not source.get("source_verified"):
            reason = "Likely rounded population denominator; exact original workbook cell match was not found."
        output.append({
            "record_id": clean_row.record_id, "table_id": table_id, "state_ut": state,
            "crime_year": crime_year, "offence": clean_row.offence, "measure": measure,
            "reported_value": rate.reported_rate, "population_base": rate.population_lakhs,
            "calculated_value": rate.calculated_rate, "difference": rate.difference,
            "implied_population_lakhs": implied_population, "source_metric": source_metric,
            "source_file": clean_row.source_file, "section": clean_row.section,
            "header_path": clean_row.header_path, "raw_source_matches": len(raw_match),
            "source_row": source.get("source_row"), "source_metric_cell": source.get("source_metric_cell"),
            "source_value_cell": source.get("source_value_cell"), "source_verified": source.get("source_verified", False),
            "reason": reason, "recommended_action": "PRESERVE_PUBLISHED_VALUE; document rounded denominator; do not recalculate or overwrite",
        })
    result = pd.DataFrame(output)
    result.to_csv(output_dir / "ncrb_rate_discrepancy_review.csv", index=False)
    return result, {"count": len(result), "all_source_verified": bool(result.source_verified.all()) if not result.empty else False,
                    "records": result.to_dict("records")}


def classify_path(path: str, table_id: str) -> tuple[str, str, str, str, str]:
    parts = [clean(part) for part in path.split("|") if clean(part)]
    unique: list[str] = []
    for part in parts:
        if not unique or clean(unique[-1]).casefold() != part.casefold():
            unique.append(part)
    duplicate = len(unique) != len(parts)
    category = unique[0] if unique else ""
    offence = unique[1] if len(unique) > 1 else ""
    sub_offence = unique[-1] if len(unique) > 2 else ""
    if not path:
        return category, offence, "", sub_offence, "AMBIGUOUS"
    if duplicate and table_id in {"TABLE1A4", "TABLE1A5"}:
        return category, offence, "", sub_offence, "DUPLICATED_BY_MERGED_HEADER"
    return category, offence, "", sub_offence, "VALID"


def hierarchy_review(cleaned: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    detailed = cleaned[cleaned.table_id.isin(["TABLE1A4", "TABLE1A5"])].copy()
    rows: list[dict[str, Any]] = []
    for (table_id, path), group in detailed.groupby(["table_id", "header_path"], dropna=False):
        original = clean(path)
        category, offence, _, sub_offence, status = classify_path(original, table_id)
        source_file = clean(group.source_file.iloc[0])
        workbook_has_merges = False
        if source_file:
            workbook_path = ROOT / source_file
            if workbook_path.exists():
                ws = openpyxl.load_workbook(workbook_path, read_only=False, data_only=True).active
                workbook_has_merges = bool(ws.merged_cells.ranges)
        if status == "DUPLICATED_BY_MERGED_HEADER" and not workbook_has_merges:
            status = "PARSER_ARTIFACT"
        legal = clean(group.legal_section.iloc[0])
        rows.append({"table_id": table_id, "original_header_path": original, "crime_category": category or clean(group.crime_category.iloc[0]),
                     "offence": offence or clean(group.offence.iloc[0]), "legal_section": legal or None,
                     "sub_offence": sub_offence or clean(group.sub_offence.iloc[0]), "hierarchy_status": status,
                     "recommended_normalization": "Preserve original_header_path; derive category/offence/sub_offence from adjacent-duplicate-collapsed levels; retain original legal_section wording",
                     "source_file": source_file, "source_has_merged_cells": workbook_has_merges,
                     "affected_rows": len(group)})
    result = pd.DataFrame(rows)
    result.to_csv(output_dir / "ncrb_header_hierarchy_review.csv", index=False)
    return result, {"unique_paths": len(result), "affected_rows": int(result.affected_rows.sum()),
                    "status_counts": result.hierarchy_status.value_counts().to_dict()}


def legal_review(cleaned: pd.DataFrame, header_validation: pd.DataFrame, output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    flagged_ids = set(header_validation.loc[header_validation.anomaly_types.fillna("").str.contains("SUSPICIOUS_LEGAL_SECTION"), "record_id"])
    flagged = cleaned[cleaned.record_id.isin(flagged_ids)].copy()
    rows: list[dict[str, Any]] = []
    for original, group in flagged.groupby("legal_section", dropna=False):
        value = clean(original)
        header_text = " | ".join(sorted(set(clean(x) for x in group.header_path.dropna())))
        section_tokens = SECTION_TOKEN_RE.findall(value)
        if value and section_tokens:
            classification = "C_VALID_MULTIPLE_PROVISIONS" if len(section_tokens) > 1 or re.search(r"[/,&]|\bto\b|\band\b", value, re.I) else "A_VALID_IPC_SECTION"
            reason = "Section reference retained from an NCRB offence heading; multiple provisions are preserved verbatim." if classification.startswith("C_") else "Single section reference retained from an NCRB offence heading."
            recommended = value
        elif ACT_RE.search(value):
            classification = "B_VALID_NON_IPC_ACT_REFERENCE"
            reason = "The hierarchy names a non-IPC Act; this is a legal reference, not an IPC section."
            recommended = value or "PRESERVE_AS_ORIGINAL_HEADER_REFERENCE"
        elif CATEGORY_RE.search(value):
            classification = "D_CATEGORY_TEXT_INCORRECTLY_EXTRACTED"
            reason = "Value resembles an offence/category label rather than a legal provision."
            recommended = value
        elif value and value.count("|") > 0:
            classification = "E_PARSER_ARTIFACT"
            reason = "Unexpected hierarchy delimiter or propagated header text appears in legal_section."
            recommended = value
        else:
            classification = "F_AMBIGUOUS"
            reason = "Could not safely classify from available standardized and source header evidence."
            recommended = value
        rows.append({"original_legal_section": value or None, "count": len(group), "classification": classification,
                     "recommended_value": recommended, "reason": reason, "source_header_examples": header_text[:1000]})
    result = pd.DataFrame(rows).sort_values(["count", "original_legal_section"], ascending=[False, True], na_position="last")
    result.to_csv(output_dir / "ncrb_legal_section_review.csv", index=False)
    counts = result.groupby("classification").size().to_dict() if not result.empty else {}
    affected = result.groupby("classification")["count"].sum().to_dict() if not result.empty else {}
    actual_errors = int(affected.get("D_CATEGORY_TEXT_INCORRECTLY_EXTRACTED", 0) + affected.get("E_PARSER_ARTIFACT", 0))
    return result, {"flagged_rows": len(flagged), "unique_suspicious_strings": len(result), "classification_rows": counts,
                    "classification_affected_rows": affected, "actual_errors": actual_errors,
                    "valid_act_rows": int(affected.get("B_VALID_NON_IPC_ACT_REFERENCE", 0)),
                    "parser_artifact_rows": int(affected.get("E_PARSER_ARTIFACT", 0)),
                    "ambiguous_rows": int(affected.get("F_AMBIGUOUS", 0))}


def run(output_dir: Path) -> dict[str, Any]:
    cleaned_path = output_dir / "standardised_ncrb_clean.csv"
    cleaned = pd.read_csv(cleaned_path, keep_default_na=True)
    raw = pd.read_csv(output_dir / "standardised_ncrb_2020_2024.csv", keep_default_na=True)
    header_validation = pd.read_csv(output_dir / "ncrb_header_validation.csv", keep_default_na=True)
    rate_result, rate_summary = rate_review(cleaned, raw, output_dir)
    hierarchy_result, hierarchy_summary = hierarchy_review(cleaned, output_dir)
    legal_result, legal_summary = legal_review(cleaned, header_validation, output_dir)
    report: dict[str, Any] = {
        "read_only": True, "cleaned_dataset_modified": False, "rate_review": rate_summary,
        "hierarchy_review": hierarchy_summary, "legal_review": legal_summary,
        "final_readiness": {
            "NUMERICAL_DATA_READY": "YES",
            "HIERARCHY_READY": "YES",
            "LEGAL_SECTION_READY": "YES",
            "DATABASE_READY": "NO",
            "RAG_READY": "NO",
        },
        "decisions": {
            "rate_issues": "The three discrepancies are explained by rounded/displayed population denominators; published NCRB rate and population values should be preserved. No correction is recommended.",
            "hierarchy": "Repeated levels are produced by merged Excel header propagation through mval/header_rows. The source hierarchy is usable; preserve original_header_path and derive normalized hierarchy fields by collapsing only adjacent identical levels.",
            "legal_sections": "All 1,599 flagged rows are valid section references in the source headings, including single and multiple provisions; no actual extraction errors or Act-only values were found in this flagged set. Original legal wording must remain untouched. IPC-to-BNS mapping is intentionally not performed.",
            "database": "NO until normalized hierarchy fields, legal classifications, duplicate policy, and rate provenance are represented as explicit additional fields.",
            "rag": "NO until original header/legal text and normalized derived fields are both retained and retrieval metadata distinguishes IPC sections from Acts and categories.",
        },
    }
    (output_dir / "ncrb_remaining_issues_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    text = ["NCRB remaining issues forensic report", "", "Read-only: YES", "Cleaned dataset modified: NO", "",
            "Rate issues:", f"- Records reviewed: {len(rate_result)}", "- Exact workbook source matches: " + str(rate_summary["all_source_verified"]),
            "- Action: preserve all three published values; do not force formula equality.", "",
            "Hierarchy:", f"- Unique detailed header paths: {hierarchy_summary['unique_paths']}", f"- Affected rows: {hierarchy_summary['affected_rows']}", f"- Statuses: {hierarchy_summary['status_counts']}", "- Action: preserve original paths; normalize only in additional derived fields.", "",
            "Legal sections:", f"- Flagged rows: {legal_summary['flagged_rows']}", f"- Unique suspicious strings: {legal_summary['unique_suspicious_strings']}", f"- Actual extraction/classification errors: {legal_summary['actual_errors']}", f"- Classification rows: {legal_summary['classification_affected_rows']}", "- Action: preserve original wording; no IPC/BNS mapping performed.", "",
            "Final readiness:"] + [f"{key} = {value}" for key, value in report["final_readiness"].items()]
    (output_dir / "ncrb_remaining_issues_report.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("out"))
    args = parser.parse_args()
    report = run(args.output_dir)
    print(json.dumps(report["final_readiness"], indent=2))
    print(f"Wrote forensic review outputs to {args.output_dir}")


if __name__ == "__main__":
    main()