#!/usr/bin/env python3
"""
Schema checker (standalone)

- Connects to DB using sqlite:///dev.db env var (defaults to sqlite:///app.db)
- Lists columns for a table (default: scenario_capex)
- Verifies presence of expected columns; exits 1 if any are missing

Usage:
  sqlite:///dev.db="sqlite:///dev.db" python check_table_schema.py
  sqlite:///dev.db="postgresql+psycopg2://user:pass@host/db" python check_table_schema.py --table scenario_capex
  sqlite:///dev.db="sqlite:///dev.db" python check_table_schema.py --expect depreciation_method salvage_value partial_month_policy
"""

import os
import sys
import argparse
from typing import List, Tuple
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine


DEFAULT_TABLE = "scenario_capex"
DEFAULT_EXPECT = ["depreciation_method", "salvage_value", "partial_month_policy"]


def get_db_url() -> str:
    url = os.environ.get("sqlite:///dev.db")
    if not url:
        url = "sqlite:///app.db"
        print(f"[info] sqlite:///dev.db not set; using default {url}")
    return url


def connect(url: str) -> Engine:
    return create_engine(url)


def detect_backend(engine: Engine) -> str:
    name = engine.dialect.name.lower()
    if "postgres" in name:
        return "postgresql"
    if "sqlite" in name:
        return "sqlite"
    return name


def fetch_columns(engine: Engine, table: str) -> List[Tuple[str, str, bool]]:
    insp = inspect(engine)
    tables = insp.get_table_names()
    if table not in tables:
        raise SystemExit(f"[error] Table '{table}' not found. Existing tables: {', '.join(tables) or '(none)'}")
    cols = insp.get_columns(table)
    rows: List[Tuple[str, str, bool]] = []
    for c in cols:
        name = c.get("name")
        type_ = str(c.get("type"))
        nullable = bool(c.get("nullable", True))
        rows.append((name, type_, nullable))
    rows.sort(key=lambda r: r[0])
    return rows


def print_table(title: str, rows: List[Tuple[str, str, bool]]) -> None:
    print(f"\n== {title} ==")
    print(f"{'Column':30} {'Type':30} {'Nullable'}")
    print("-" * 75)
    for name, type_, nullable in rows:
        print(f"{name:30} {type_:30} {str(nullable)}")
    print("-" * 75)


def main():
    ap = argparse.ArgumentParser(description="Check DB table schema & verify expected columns.")
    ap.add_argument("--table", default=DEFAULT_TABLE, help=f"Table name (default: {DEFAULT_TABLE})")
    ap.add_argument("--expect", nargs="*", default=DEFAULT_EXPECT, help="Columns expected to exist")
    args = ap.parse_args()

    url = get_db_url()
    engine = connect(url)
    backend = detect_backend(engine)
    print(f"[info] Connected to {url} (backend={backend})")

    rows = fetch_columns(engine, args.table)
    print_table(f"Schema for '{args.table}'", rows)

    existing = {name for (name, _, _) in rows}
    missing = [c for c in args.expect if c not in existing]

    print("\nExpected columns:")
    for c in args.expect:
        mark = "OK" if c in existing else "MISSING"
        print(f"  - {c}: {mark}")

    if missing:
        print(f"\n[FAIL] Missing columns: {', '.join(missing)}")
        sys.exit(1)
    else:
        print("\n[OK] All expected columns are present.")
        sys.exit(0)


if __name__ == "__main__":
    main()
