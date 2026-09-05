"""Validate the original NCRB Table 1A.4 pages 1-47 segment.

Checks file existence, schema conformity, missing values, duplicates,
numerical consistency, state/UT coverage, crime-head coverage, and aggregates.

This script validates the original 47-page segment only. It does not validate
the completed 6,139-row combined dataset.
"""

import sys
import os
import csv
from typing import Dict, List, Any

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')


def validate_table_1a4() -> Dict[str, Any]:
    print("=" * 70)
    print("NCRB TABLE 1A.4 VALIDATION AUDIT")
    print("=" * 70)

    # -------------------------------------------------------------
    # A. File Existence
    # -------------------------------------------------------------
    pdf_path = "data/raw/ncrb/crime_in_india_2024_volume1_table_1A4.pdf"
    raw_path = "data/processed/ncrb/ncrb_2024_table_1A4_raw.csv"
    std_path = "data/processed/ncrb/ncrb_stats_2024.csv"

    pdf_exists = os.path.isfile(pdf_path)
    raw_exists = os.path.isfile(raw_path)
    std_exists = os.path.isfile(std_path)

    print(f"\nA. FILE EXISTENCE:")
    print(f"  Source PDF ({pdf_path}): {'EXISTS' if pdf_exists else 'MISSING'}")
    print(f"  Raw CSV ({raw_path}): {'EXISTS' if raw_exists else 'MISSING'}")
    print(f"  Standardized CSV ({std_path}): {'EXISTS' if std_exists else 'MISSING'}")

    if not (raw_exists and std_exists):
        print("\n[ERROR] Required datasets missing! Aborting validation.")
        return {"status": "FAIL", "reason": "Missing output datasets"}

    # -------------------------------------------------------------
    # B. Load Datasets and Check Required Columns
    # -------------------------------------------------------------
    with open(raw_path, mode="r", encoding="utf-8") as f:
        raw_reader = csv.DictReader(f)
        raw_rows = list(raw_reader)
        raw_cols = raw_reader.fieldnames or []

    with open(std_path, mode="r", encoding="utf-8") as f:
        std_reader = csv.DictReader(f)
        std_rows = list(std_reader)
        std_cols = std_reader.fieldnames or []

    expected_raw_cols = ["year", "state", "offense_category", "ipc_section", "bns_section", "source_incidence_value"]
    expected_std_cols = ["year", "state", "offense_category", "ipc_section", "case_count", "conviction_count", "acquittal_count"]

    missing_raw_cols = [c for c in expected_raw_cols if c not in raw_cols]
    missing_std_cols = [c for c in expected_std_cols if c not in std_cols]

    print(f"\nB. REQUIRED COLUMNS AUDIT:")
    print(f"  Raw total columns: {len(raw_cols)}")
    print(f"  Raw required columns present: {'YES' if not missing_raw_cols else 'NO, missing: ' + str(missing_raw_cols)}")
    print(f"  Standardized total columns: {len(std_cols)}")
    print(f"  Standardized required columns present: {'YES' if not missing_std_cols else 'NO, missing: ' + str(missing_std_cols)}")

    # -------------------------------------------------------------
    # C. Basic Validity & Row Counts
    # -------------------------------------------------------------
    print(f"\nC. DATASET ROW COUNTS & BASIC VALIDITY:")
    print(f"  Total Raw Rows: {len(raw_rows)}")
    print(f"  Total Standardized Rows: {len(std_rows)}")

    # Check year is 2024; outcomes remain blank because this source grain does
    # not provide conviction or acquittal results.
    invalid_years = [r for r in std_rows if r.get("year") != "2024"]
    non_null_conviction = [r for r in std_rows if r.get("conviction_count") not in ("", None)]
    non_null_acquittal = [r for r in std_rows if r.get("acquittal_count") not in ("", None)]

    print(f"  Invalid year rows (expected 2024): {len(invalid_years)}")
    print(f"  Non-null conviction_count rows (expected NULL): {len(non_null_conviction)}")
    print(f"  Non-null acquittal_count rows (expected NULL): {len(non_null_acquittal)}")

    # -------------------------------------------------------------
    # D. Missing-Value & Zero-Value Audit
    # -------------------------------------------------------------
    missing_state = sum(1 for r in std_rows if not r.get("state"))
    missing_offense = sum(1 for r in std_rows if not r.get("offense_category"))
    missing_ipc_sec = sum(1 for r in std_rows if not r.get("ipc_section"))
    missing_case_count = sum(1 for r in std_rows if r.get("case_count") in ("", None))
    zero_case_count = sum(1 for r in std_rows if r.get("case_count") == "0")

    print(f"\nD. MISSING VS ZERO AUDIT (STANDARDIZED):")
    print(f"  Missing states: {missing_state}")
    print(f"  Missing offense_category: {missing_offense}")
    print(f"  Rows without IPC section: {missing_ipc_sec} (new BNS offenses or broad aggregate categories)")
    print(f"  Missing case_count: {missing_case_count}")
    print(f"  Zero case_count: {zero_case_count} (Source explicitly reports 0 cases)")

    # -------------------------------------------------------------
    # E. Duplicate Audit
    # -------------------------------------------------------------
    seen_keys = set()
    duplicate_rows = []
    for idx, r in enumerate(std_rows):
        key = (r.get("year"), r.get("state"), r.get("offense_category"), r.get("ipc_section"))
        if key in seen_keys:
            duplicate_rows.append((idx + 2, key))
        else:
            seen_keys.add(key)

    print(f"\nE. DUPLICATE AUDIT:")
    print(f"  Duplicate logical rows (year + state + offense + ipc): {len(duplicate_rows)}")
    if duplicate_rows:
        print(f"  Example duplicate: {duplicate_rows[:2]}")

    # -------------------------------------------------------------
    # F. State/UT Coverage Audit
    # -------------------------------------------------------------
    all_states = sorted(list(set(r.get("state", "") for r in std_rows if r.get("state"))))
    individual_states_uts = [s for s in all_states if not s.startswith("TOTAL")]
    aggregate_states = [s for s in all_states if s.startswith("TOTAL")]

    print(f"\nF. STATE / UT COVERAGE AUDIT:")
    print(f"  Total unique state entities: {len(all_states)}")
    print(f"  Individual States & UTs count: {len(individual_states_uts)} (Expected: 36: 29 States + 7 UTs)")
    print(f"  Aggregate entities count: {len(aggregate_states)}: {aggregate_states}")

    # -------------------------------------------------------------
    # G. Crime-Head Coverage Audit
    # -------------------------------------------------------------
    all_crime_heads = sorted(list(set(r.get("offense_category", "") for r in std_rows if r.get("offense_category"))))
    print(f"\nG. CRIME-HEAD COVERAGE AUDIT:")
    print(f"  Total unique Crime Heads: {len(all_crime_heads)}")
    print(f"  Sample Crime Heads:")
    for ch in all_crime_heads[:5]:
        print(f"    - {ch}")

    # -------------------------------------------------------------
    # H. Section Audit (Raw)
    # -------------------------------------------------------------
    raw_with_ipc = sum(1 for r in raw_rows if r.get("ipc_section"))
    raw_without_ipc = sum(1 for r in raw_rows if not r.get("ipc_section"))
    raw_with_bns = sum(1 for r in raw_rows if r.get("bns_section"))
    raw_without_bns = sum(1 for r in raw_rows if not r.get("bns_section"))

    print(f"\nH. STATUTORY SECTION AUDIT (RAW):")
    print(f"  Rows with IPC section: {raw_with_ipc}")
    print(f"  Rows without IPC section: {raw_without_ipc}")
    print(f"  Rows with BNS section: {raw_with_bns}")
    print(f"  Rows without BNS section: {raw_without_bns}")

    # -------------------------------------------------------------
    # I. Numeric & Integrity Audit
    # -------------------------------------------------------------
    negative_counts = []
    non_integer_counts = []
    for idx, r in enumerate(std_rows):
        val = r.get("case_count")
        if val not in ("", None):
            try:
                ival = int(val)
                if ival < 0:
                    negative_counts.append((idx + 2, val))
            except ValueError:
                non_integer_counts.append((idx + 2, val))

    print(f"\nI. NUMERIC INTEGRITY AUDIT:")
    print(f"  Negative case_count values: {len(negative_counts)}")
    print(f"  Non-integer case_count values: {len(non_integer_counts)}")

    # -------------------------------------------------------------
    # Final Assessment
    # -------------------------------------------------------------
    passed = (
        pdf_exists and raw_exists and std_exists
        and not missing_raw_cols and not missing_std_cols
        and len(invalid_years) == 0
        and len(non_null_conviction) == 0
        and len(non_null_acquittal) == 0
        and missing_state == 0
        and missing_offense == 0
        and len(individual_states_uts) == 36
        and len(negative_counts) == 0
        and len(non_integer_counts) == 0
    )

    status = "PASS" if passed else "FAIL"
    print("\n" + "=" * 70)
    print(f"FINAL AUDIT RESULT: {status}")
    print("=" * 70)

    return {
        "status": status,
        "total_raw_rows": len(raw_rows),
        "total_std_rows": len(std_rows),
        "unique_states_uts": len(individual_states_uts),
        "unique_crime_heads": len(all_crime_heads),
        "missing_ipc": missing_ipc_sec,
        "missing_case_counts": missing_case_count,
        "zero_case_counts": zero_case_count,
        "duplicate_rows": len(duplicate_rows)
    }


if __name__ == "__main__":
    validate_table_1a4()
