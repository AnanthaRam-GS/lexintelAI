"""Reconcile the five analytics endpoints with direct SQL (read-only).

Each endpoint is called through the FastAPI app (TestClient, with the
lawyer/admin dependency overridden; nothing is written). Its result is
compared with an independent SQL query against the same database:

| Endpoint | SQL check |
|---|---|
| /analytics/offense-frequency | count(distinct document) per (statute section, year) |
| /analytics/outcome-distribution | per (statute section, court_level): distinct documents in each outcome bucket |
| /analytics/section-cooccurrence | self-join of document_sections, distinct documents per label pair |
| /analytics/ipc-bns-map | every ipc_bns_mapping row |
| /analytics/ncrb-stats | every ncrb_stats row |

Exits 1 on any mismatch, or if ``--require-non-empty`` is set and an
endpoint returns no rows.

Usage:
    .venv/bin/python backend/scripts/verify_analytics.py --database-url-env DATABASE_URL [--require-non-empty]
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ENDPOINTS = (
    "/analytics/offense-frequency",
    "/analytics/outcome-distribution",
    "/analytics/section-cooccurrence",
    "/analytics/ipc-bns-map",
    "/analytics/ncrb-stats",
)


def _sql_label_set(values: set[str]) -> str:
    return "(" + ", ".join("'" + value.replace("'", "''") + "'" for value in sorted(values)) + ")"


def sql_results(cursor: Any) -> dict[str, Any]:
    from backend.app.services import analytics

    norm = lambda column: f"lower(regexp_replace(trim(coalesce({column}, '')), '\\s+', ' ', 'g'))"  # noqa: E731
    label = "(s.statute || ' ' || s.section)"
    results: dict[str, Any] = {}

    cursor.execute(
        f"""SELECT {label}, d.year, count(DISTINCT d.id) FROM document_sections s JOIN documents d ON d.id = s.document_id
            WHERE d.year IS NOT NULL AND s.section IS NOT NULL AND s.section <> '' GROUP BY 1, 2"""
    )
    results["/analytics/offense-frequency"] = Counter({(row[0], row[1]): row[2] for row in cursor.fetchall()})

    conviction = (
        f"CASE WHEN {norm('d.conviction_status')} IN {_sql_label_set(analytics.CONVICTED_LABELS)} THEN 'convicted' "
        f"WHEN {norm('d.conviction_status')} IN {_sql_label_set(analytics.ACQUITTED_LABELS)} THEN 'acquitted' "
        f"WHEN {norm('d.case_disposition')} IN {_sql_label_set(analytics.CONVICTED_LABELS)} THEN 'convicted' "
        f"WHEN {norm('d.case_disposition')} IN {_sql_label_set(analytics.ACQUITTED_LABELS)} THEN 'acquitted' END"
    )
    appeal = (
        f"CASE WHEN {norm('d.appeal_result')} IN {_sql_label_set(analytics.APPEAL_ALLOWED_LABELS)} THEN 'appeal_allowed' "
        f"WHEN {norm('d.appeal_result')} IN {_sql_label_set(analytics.APPEAL_DISMISSED_LABELS)} THEN 'appeal_dismissed' END"
    )
    cursor.execute(
        f"""SELECT {label}, d.court_level,
                   count(DISTINCT d.id) FILTER (WHERE {conviction} = 'convicted'),
                   count(DISTINCT d.id) FILTER (WHERE {conviction} = 'acquitted'),
                   count(DISTINCT d.id) FILTER (WHERE {appeal} = 'appeal_allowed'),
                   count(DISTINCT d.id) FILTER (WHERE {appeal} = 'appeal_dismissed')
            FROM document_sections s JOIN documents d ON d.id = s.document_id
            WHERE d.court_level IS NOT NULL AND d.court_level <> '' AND s.section IS NOT NULL AND s.section <> ''
            GROUP BY 1, 2"""
    )
    results["/analytics/outcome-distribution"] = {(row[0], row[1]): tuple(row[2:]) for row in cursor.fetchall()}

    cursor.execute(
        f"""SELECT (a.statute || ' ' || a.section) COLLATE "C", (b.statute || ' ' || b.section) COLLATE "C",
                   count(DISTINCT a.document_id)
            FROM document_sections a JOIN document_sections b ON a.document_id = b.document_id
            WHERE (a.statute || ' ' || a.section) COLLATE "C" < (b.statute || ' ' || b.section) COLLATE "C"
              AND a.section <> '' AND b.section <> ''
            GROUP BY 1, 2"""
    )
    results["/analytics/section-cooccurrence"] = Counter({(row[0], row[1]): row[2] for row in cursor.fetchall()})

    cursor.execute("SELECT ipc_section, ipc_description, bns_section, bns_description, change_type FROM ipc_bns_mapping")
    results["/analytics/ipc-bns-map"] = Counter(tuple(row) for row in cursor.fetchall())

    cursor.execute(
        "SELECT year, state, offense_category, ipc_section, case_count, conviction_count, acquittal_count FROM ncrb_stats"
    )
    results["/analytics/ncrb-stats"] = Counter(tuple(row) for row in cursor.fetchall())
    return results


def endpoint_results(client: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}
    raw: dict[str, list[dict[str, Any]]] = {}
    for path in ENDPOINTS:
        response = client.get(path)
        if response.status_code != 200:
            raise SystemExit(f"{path} returned HTTP {response.status_code}")
        raw[path] = response.json()
    results["/analytics/offense-frequency"] = Counter({(r["section"], r["year"]): r["count"] for r in raw[ENDPOINTS[0]]})
    results["/analytics/outcome-distribution"] = {
        (r["section"], r["court_level"]): (r["convicted"], r["acquitted"], r["appeal_allowed"], r["appeal_dismissed"])
        for r in raw[ENDPOINTS[1]]
    }
    results["/analytics/section-cooccurrence"] = Counter({(r["section_a"], r["section_b"]): r["count"] for r in raw[ENDPOINTS[2]]})
    results["/analytics/ipc-bns-map"] = Counter(
        (r["ipc_section"], r["ipc_description"], r["bns_section"], r["bns_description"], r["change_type"]) for r in raw[ENDPOINTS[3]]
    )
    results["/analytics/ncrb-stats"] = Counter(
        (r["year"], r["state"], r["offense_category"], r["ipc_section"], r["case_count"], r["conviction_count"], r["acquittal_count"])
        for r in raw[ENDPOINTS[4]]
    )
    return results, {path: len(rows) for path, rows in raw.items()}


def summarize(path: str, result: Any) -> dict[str, Any]:
    if path == "/analytics/offense-frequency":
        return {"rows": len(result), "sum_count": sum(result.values())}
    if path == "/analytics/outcome-distribution":
        totals = [sum(values[i] for values in result.values()) for i in range(4)]
        return {"rows": len(result), "convicted": totals[0], "acquitted": totals[1], "appeal_allowed": totals[2], "appeal_dismissed": totals[3]}
    if path == "/analytics/section-cooccurrence":
        return {"rows": len(result), "sum_count": sum(result.values())}
    if path == "/analytics/ncrb-stats":
        return {"rows": sum(result.values()), "sum_case_count": sum((key[4] or 0) * n for key, n in result.items())}
    return {"rows": sum(result.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--database-url-env", required=True, help="Name of the env var holding the database URL.")
    parser.add_argument("--require-non-empty", action="store_true")
    args = parser.parse_args(argv)

    from backend.scripts.reconcile_common import connect, resolve_database

    url, database = resolve_database(args.database_url_env, confirm_dev=False, write=False)
    os.environ["DATABASE_URL"] = url  # the app's engine is bound at import time
    from fastapi.testclient import TestClient

    from backend.app.core.dependencies import require_lawyer_or_admin
    from backend.app.db import session as db_session
    from backend.main import app

    if db_session.engine.url.database != database:
        raise SystemExit("refused: the application engine is bound to a different database; run in a fresh process")
    app.dependency_overrides[require_lawyer_or_admin] = lambda: type("ReconcileUser", (), {"id": 0, "role": "admin"})()
    try:
        api, sizes = endpoint_results(TestClient(app))
    finally:
        app.dependency_overrides.clear()

    connection = connect(url, readonly=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise SystemExit("PostgreSQL session is not read-only; aborting.")
            sql = sql_results(cursor)
    finally:
        connection.rollback()
        connection.close()

    ok = True
    report = {}
    for path in ENDPOINTS:
        match = api[path] == sql[path]
        empty = sizes[path] == 0
        ok &= match and not (args.require_non_empty and empty)
        report[path] = {"endpoint": summarize(path, api[path]), "sql": summarize(path, sql[path]), "identical": match}
        print(f"{'OK  ' if match and not (args.require_non_empty and empty) else 'FAIL'} {path}: endpoint {report[path]['endpoint']} | sql {report[path]['sql']} | identical={match}")
    print(f"database={database} RECONCILED" if ok else f"database={database} MISMATCH")
    print(json.dumps(report, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
