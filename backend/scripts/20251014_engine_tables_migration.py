# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251014_engine_tables_migration.py
#!/usr/bin/env python3
"""
Create/ensure official Engine tables & indexes (idempotent).

What it does (safe to run multiple times):
- Creates engine_sheets, engine_categories, engine_runs, engine_facts_monthly
- Adds unique & helper indexes for query performance
- Seeds minimal lookup rows (c.Sales, oA.Finance, oQ.Finance) and (AN, EM, IE, Services, Spare1, Spare2)
- Records a row into schema_migrations for traceability (best-effort)

Usage:
  # Default DB path matches project standard (sqlite on Windows dev)
  python backend/scripts/20251014_engine_tables_migration.py

  # Or explicit DB URL
  python backend/scripts/20251014_engine_tables_migration.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db
  python backend/scripts/20251014_engine_tables_migration.py --db sqlite:///C:/Dev/AryaIntel_CRM/app.db

Notes:
- Designed to be repo-friendly, idempotent, and non-destructive.
- For PostgreSQL/MySQL it uses CREATE IF NOT EXISTS and IF NOT EXISTS indexes where available.
"""

import argparse
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20251014_engine_tables"
DEFAULT_DB = "sqlite:///C:/Dev/AryaIntel_CRM/app.db"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _ensure_migrations_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """))


def _already_applied(conn) -> bool:
    row = conn.execute(text("SELECT 1 FROM schema_migrations WHERE id=:id"), {"id": MIGRATION_ID}).first()
    return bool(row)


def _mark_applied(conn) -> None:
    conn.execute(text("INSERT OR IGNORE INTO schema_migrations (id, applied_at) VALUES (:id, :at)"),
             {"id": MIGRATION_ID,
              "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def _create_tables(conn, dialect: str) -> None:
    # Lookup tables
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_sheets (
            code TEXT PRIMARY KEY,
            name TEXT,
            sort_order INTEGER
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_categories (
            code TEXT PRIMARY KEY,
            name TEXT,
            sort_order INTEGER
        )
    """))

    # Runs & facts
    # Use INTEGER PRIMARY KEY for SQLite (rowid), SERIAL-like for others by relying on dialect auto
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_runs (
            id INTEGER PRIMARY KEY,
            scenario_id INTEGER,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            options_json TEXT
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_facts_monthly (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            scenario_id INTEGER,
            sheet_code TEXT NOT NULL,
            category_code TEXT NOT NULL,
            yyyymm INTEGER NOT NULL,
            value NUMERIC(18,6) NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _create_indexes(conn, dialect: str) -> None:
    # Uniqueness per run+sheet+category+yyyymm
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_engine_facts
        ON engine_facts_monthly(run_id, sheet_code, category_code, yyyymm)
    """))
    # Helpful read paths for FE
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_engine_facts_scenario_yyyymm
        ON engine_facts_monthly(scenario_id, yyyymm)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_engine_facts_sheet_cat_yyyymm
        ON engine_facts_monthly(sheet_code, category_code, yyyymm)
    """))


def _seed_lookups(conn) -> None:
    sheets = [("c.Sales", 0), ("oA.Finance", 1), ("oQ.Finance", 2)]
    for code, order in sheets:
        conn.execute(text("""
            INSERT INTO engine_sheets (code, name, sort_order)
            SELECT :c, :n, :o
            WHERE NOT EXISTS (SELECT 1 FROM engine_sheets WHERE code=:c)
        """), {"c": code, "n": code, "o": order})

    cats = [("AN", 0), ("EM", 1), ("IE", 2), ("Services", 3), ("Spare1", 4), ("Spare2", 5)]
    for code, order in cats:
        conn.execute(text("""
            INSERT INTO engine_categories (code, name, sort_order)
            SELECT :c, :n, :o
            WHERE NOT EXISTS (SELECT 1 FROM engine_categories WHERE code=:c)
        """), {"c": code, "n": code, "o": order})


def migrate(db_url: str) -> None:
    engine: Engine = create_engine(db_url)
    dialect = engine.dialect.name
    _log(f"[info] dialect={dialect} url={db_url}")

    with engine.begin() as conn:
        _ensure_migrations_table(conn)
        if _already_applied(conn):
            _log(f"[skip] migration '{MIGRATION_ID}' already applied.")
            return

        _log("[step] creating tables...")
        _create_tables(conn, dialect)
        _log("[ok] tables ensured.")

        _log("[step] creating indexes...")
        _create_indexes(conn, dialect)
        _log("[ok] indexes ensured.")

        _log("[step] seeding lookups...")
        _seed_lookups(conn)
        _log("[ok] lookups ensured.")

        _mark_applied(conn)
        _log(f"[done] migration '{MIGRATION_ID}' recorded in schema_migrations.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db",
        default=DEFAULT_DB,
        help="SQLAlchemy DB URL. Default: sqlite:///C:/Dev/AryaIntel_CRM/app.db",
    )
    args = ap.parse_args()
    migrate(args.db)


if __name__ == "__main__":
    main()
