#!/usr/bin/env python3
"""
Add scenario_capex.linked_service_id (nullable) + index (idempotent).

Why:
- Lets a CAPEX row link directly to a Service row (Excel parity).
- We avoid FK constraints to keep SQLite compatibility (like linked_boq_item_id).

Usage examples:
  # Using env var
  set DATABASE_URL=sqlite:///app.db && python 20251008_add_linked_service_link.py
  # Or pass explicitly
  python 20251008_add_linked_service_link.py --db sqlite:///app.db
  python 20251008_add_linked_service_link.py --db postgresql+psycopg2://user:pass@host/db

Dry-run (prints SQL without executing):
  python 20251008_add_linked_service_link.py --db sqlite:///app.db --dry-run
"""

import os
import sys
import argparse
from typing import Set

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

TARGET_TABLE = "scenario_capex"
COLUMN_NAME = "linked_service_id"
INDEX_NAME = "idx_scenario_capex_linked_service"
# NOTE: We intentionally do NOT add a FK constraint to scenario_services(id)
# because SQLite would require a table rewrite. Keep it simple & portable.

def detect_backend(engine: Engine) -> str:
    name = (engine.dialect.name or "").lower()
    if "postgres" in name:
        return "postgresql"
    if "sqlite" in name:
        return "sqlite"
    return name or "unknown"

def has_table(engine: Engine, table: str) -> bool:
    try:
        insp = inspect(engine)
        return insp.has_table(table)
    except Exception:
        return False

def column_names(engine: Engine, table: str) -> Set[str]:
    try:
        insp = inspect(engine)
        cols = insp.get_columns(table)
        return {c["name"] for c in cols}
    except Exception:
        return set()

def index_names(engine: Engine, table: str) -> Set[str]:
    try:
        insp = inspect(engine)
        idx = insp.get_indexes(table)
        return {i.get("name") for i in idx if i.get("name")}
    except Exception:
        return set()

def add_column_sql(table: str, col: str, backend: str) -> str:
    # Keep nullable so SQLite can ADD COLUMN without rebuild
    if backend == "postgresql":
        return f'ALTER TABLE "{table}" ADD COLUMN "{col}" INTEGER NULL;'
    elif backend == "sqlite":
        return f'ALTER TABLE "{table}" ADD COLUMN "{col}" INTEGER;'
    # Generic fallback
    return f'ALTER TABLE {table} ADD COLUMN {col} INTEGER;'

def create_index_sql(table: str, idx: str, col: str, backend: str) -> str:
    # Both Postgres & SQLite support IF NOT EXISTS
    return f'CREATE INDEX IF NOT EXISTS {idx} ON {table}({col});'

def main():
    parser = argparse.ArgumentParser(description="Add linked_service_id to scenario_capex (idempotent).")
    parser.add_argument("--db", dest="db_url", default=os.getenv("DATABASE_URL", "sqlite:///app.db"),
                        help="SQLAlchemy DB URL (default: env DATABASE_URL or sqlite:///app.db)")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing it")
    args = parser.parse_args()

    engine = create_engine(args.db_url, future=True)
    backend = detect_backend(engine)

    print(f"[info] DB: {args.db_url}  (backend={backend})")
    print(f"[info] Target table: {TARGET_TABLE}")

    if not has_table(engine, TARGET_TABLE):
        print(f"[error] Table '{TARGET_TABLE}' not found. Run base migrations first.")
        sys.exit(2)

    cols = column_names(engine, TARGET_TABLE)
    idxs = index_names(engine, TARGET_TABLE)

    add_col_needed = COLUMN_NAME not in cols
    add_idx_needed = INDEX_NAME not in idxs  # still safe to run IF NOT EXISTS anyway

    sql_statements = []

    if add_col_needed:
        sql_statements.append(add_column_sql(TARGET_TABLE, COLUMN_NAME, backend))
    else:
        print(f"[skip] Column already exists: {TARGET_TABLE}.{COLUMN_NAME}")

    if add_idx_needed:
        sql_statements.append(create_index_sql(TARGET_TABLE, INDEX_NAME, COLUMN_NAME, backend))
    else:
        print(f"[skip] Index already exists: {INDEX_NAME}")

    if not sql_statements:
        print("[done] Nothing to do. Schema already up-to-date.")
        return

    print("[plan] Statements to execute:")
    for s in sql_statements:
        print("  " + s)

    if args.dry_run:
        print("[dry-run] No changes applied.")
        return

    with engine.begin() as conn:
        for s in sql_statements:
            conn.execute(text(s))

    print("[done] Migration applied successfully.")

if __name__ == "__main__":
    main()
