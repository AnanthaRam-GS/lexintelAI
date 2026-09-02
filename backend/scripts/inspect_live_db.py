"""Inspection script for live LegalAI PostgreSQL database catalog."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import text
from backend.app.db.session import engine


def inspect_live_database():
    with engine.connect() as conn:
        print("=== 1. ALL TABLES IN 'public' SCHEMA ===")
        tables = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name;"
        )).fetchall()
        table_names = [t[0] for t in tables]
        print("Tables:", table_names)

        expected_8 = [
            "documents",
            "chunks",
            "document_sections",
            "query_history",
            "users",
            "ingestion_jobs",
            "ipc_bns_mapping",
            "ncrb_stats",
        ]
        for tbl in expected_8:
            assert tbl in table_names, f"Table {tbl} NOT found in live DB!"
        print("[PASS] All 8 required tables exist in live PostgreSQL 'legalai' database.")

        print("\n=== 2. COLUMNS, TYPES, NULLABILITY ===")
        for tbl in expected_8:
            cols = conn.execute(text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                f"WHERE table_schema = 'public' AND table_name = '{tbl}' "
                "ORDER BY ordinal_position;"
            )).fetchall()
            print(f"\n--- {tbl} ({len(cols)} columns) ---")
            for c in cols:
                print(f"  {c[0]}: {c[1]} (nullable={c[2]}, default={c[3]})")

        print("\n=== 3. CONSTRAINTS (PK, FK, UNIQUE, CHECK) ===")
        for tbl in expected_8:
            cons = conn.execute(text(
                "SELECT conname, contype, pg_get_constraintdef(oid) "
                f"FROM pg_constraint WHERE conrelid = '{tbl}'::regclass ORDER BY conname;"
            )).fetchall()
            print(f"\n--- {tbl} constraints ---")
            for c in cons:
                ctype = {'p': 'PRIMARY KEY', 'f': 'FOREIGN KEY', 'u': 'UNIQUE', 'c': 'CHECK'}.get(c[1], c[1])
                print(f"  [{ctype}] {c[0]}: {c[2]}")

        print("\n=== 4. INDEXES ===")
        for tbl in expected_8:
            indexes = conn.execute(text(
                f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename = '{tbl}' ORDER BY indexname;"
            )).fetchall()
            print(f"\n--- {tbl} indexes ---")
            for idx in indexes:
                print(f"  {idx[0]}: {idx[1]}")

        print("\n=== 5. ALEMBIC VERSION TABLE ===")
        v = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        print("Current migration version in DB:", v)


if __name__ == "__main__":
    inspect_live_database()
    print("\n[COMPLETE] Live PostgreSQL database catalog inspection finished successfully!")
