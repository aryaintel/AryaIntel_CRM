#!/usr/bin/env python3
"""
Upgrade script (standalone) — adds CAPEX depreciation fields without Alembic.

What it does (idempotent):
- Adds to 'scenario_capex' table if missing:
    * depreciation_method   (VARCHAR(32) / TEXT)
    * salvage_value         (DOUBLE PRECISION / REAL)
    * partial_month_policy  (VARCHAR(32) / TEXT)

Usage:
  DATABASE_URL="postgresql+psycopg2://user:pass@host/dbname" python upgrade_capex_extras.py
  DATABASE_URL="sqlite:///app.db" python upgrade_capex_extras.py
  # Dry run:
  DATABASE_URL="sqlite:///app.db" python upgrade_capex_extras.py --dry-run
"""

import os
import sys
import argparse
from typing import List
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


TARGET_TABLE = "scenario_capex"

# Desired columns (name, ddl per dialect)
COLUMNS = [
    ("depreciation_method", {"postgresql": "VARCHAR(32)", "sqlite": "TEXT"}),
    ("salvage_value", {"postgresql": "DOUBLE PRECISION", "sqlite": "REAL"}),
    ("partial_month_policy", {"postgresql": "VARCHAR(32)", "sqlite": "TEXT"}),
]


def get_db_url() -> str:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        # Reasonable default to avoid accidental prod hits
        db_url = "sqlite:///app.db"
        print(f"[info] DATABASE_URL not set. Falling back to default: {db_url}")
    return db_url


def detect_backend(engine: Engine) -> str:
    name = engine.dialect.name.lower()
    if "postgres" in name:
        return "postgresql"
    if "sqlite" in name:
        return "sqlite"
    # Add more branches if you support others
    return name


def fetch_existing_columns(engine: Engine, table: str) -> List[str]:
    insp = inspect(engine)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
    except Exception as e:
        print(f"[error] Could not inspect table '{table}': {e}")
        raise
    return cols


def ensure_table_exists(engine: Engine, table: str) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        raise RuntimeError(
            f"Table '{table}' not found. Run your base migrations first or verify the table name."
        )


def add_column_sql(table: str, col_name: str, col_type: str, backend: str) -> str:
    # Most backends support simple ADD COLUMN for NULLable columns
    # (We keep these columns nullable to avoid table rewrites on SQLite.)
    if backend == "postgresql":
        return f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type} NULL;'
    elif backend == "sqlite":
        # SQLite supports limited ALTER TABLE ADD COLUMN for nullable columns
        return f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type};'
    else:
        # Fallback: generic SQL (may or may not work on other dialects)
        return f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type};'


def main():
    parser = argparse.ArgumentParser(description="Standalone DB upgrader for CAPEX extras.")
    parser.add_argument("--dry-run", action="store_true", help="Only print actions; do not execute SQL.")
    args = parser.parse_args()

    db_url = get_db_url()
    engine = create_engine(db_url)

    backend = detect_backend(engine)
    print(f"[info] Connecting to {db_url} (backend={backend})")

    if backend not in ("postgresql", "sqlite"):
        print(f"[warn] Unrecognized/untested backend '{backend}'. Proceeding with generic SQL.")
    
    with engine.begin() as conn:
        # Ensure table exists
        ensure_table_exists(engine, TARGET_TABLE)

        # Get current columns
        existing = set(fetch_existing_columns(engine, TARGET_TABLE))
        print(f"[info] Existing columns on {TARGET_TABLE}: {sorted(existing)}")

        # Prepare and (maybe) run ALTERs
        planned_sql = []
        for name, type_map in COLUMNS:
            if name in existing:
                print(f"[skip] Column '{name}' already exists.")
                continue
            # Resolve type for this backend
            col_type = type_map.get(backend) or list(type_map.values())[0]
            sql = add_column_sql(TARGET_TABLE, name, col_type, backend)
            planned_sql.append(sql)

        if not planned_sql:
            print("[ok] No changes needed. All target columns already exist.")
            return

        print("[plan] The following statements will be executed:")
        for s in planned_sql:
            print("  " + s)

        if args.dry_run:
            print("[dry-run] Exiting without applying changes.")
            return

        try:
            for s in planned_sql:
                conn.execute(text(s))
            print("[ok] Schema upgrade completed.")
        except SQLAlchemyError as e:
            print(f"[error] Failed to apply schema changes: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
