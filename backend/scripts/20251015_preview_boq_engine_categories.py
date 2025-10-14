#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251015_preview_boq_engine_categories.py
"""
Preview BOQ lines for a scenario with *both* BOQ category (bulk_with_freight...) and Engine category (AN/EM/IE/Services).
- Robust to schema variants (detects active column)
- LEFT JOIN products and (if present) product_families
- Falls back to item_name if product not found
- Always computes engine category via app.models.engine_category when product_id is present

Usage:
  python backend/scripts/20251015_preview_boq_engine_categories.py --db sqlite:///C:/Dev/AryaIntel_CRM/app.db --scenario 1
  python backend/scripts/20251015_preview_boq_engine_categories.py --db sqlite:///C:/Dev/AryaIntel_CRM/app.db --scenario 1 --include-inactive
"""

import argparse
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

# Bootstrap import path for "app" package
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.engine_category import product_category  # noqa: E402

CANDIDATE_TABLES = [
    "scenario_boq_items",   # new
    "scenario_boq",         # legacy
    "scenario_products",    # alt legacy
    "scenario_boq_lines",   # rare alt
]

def find_boq_table(conn):
    names = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
    for t in CANDIDATE_TABLES:
        if t in names:
            return t
    hints = [n for n in names if n.lower().startswith("scenario")]
    raise SystemExit(f"[error] Could not locate a BOQ table. scenario* tables found: {hints}")

def table_has(conn, name):
    return bool(conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}).fetchone())

def get_columns(conn, table):
    rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
    return {r[1] for r in rows}  # column names

def build_sql(conn, table, cols, include_inactive: bool):
    # Active flag detection
    where_active = "1=1"
    active_col = None
    if "is_active" in cols:
        active_col = "is_active"
    elif "active" in cols:
        active_col = "active"
    if active_col and not include_inactive:
        where_active = f"b.{active_col}=1"

    # product id detection (fallback to 'product_id')
    prod_col = "product_id" if "product_id" in cols else "product_id"

    # BOQ category passthrough if present
    boq_cat_select = "NULL AS boq_category"
    if "category" in cols:
        boq_cat_select = "b.category AS boq_category"

    # item_name passthrough if present
    name_expr = "p.name"
    if "item_name" in cols:
        name_expr = f"COALESCE(p.name, b.item_name)"

    # select active flag if exists (for printing)
    act_select = "NULL AS active"
    if active_col:
        act_select = f"b.{active_col} AS active"

    # Optional family join
    family_join = ""
    family_select = "NULL AS family_name"
    if table_has(conn, "product_families"):
        family_join = "LEFT JOIN product_families f ON f.id = p.family_id"
        family_select = "f.name AS family_name"

    sql = f"""
        SELECT b.id, b.{prod_col} AS product_id, {name_expr} as product_name,
               {boq_cat_select}, {act_select}, {family_select}
        FROM {table} b
        LEFT JOIN products p ON p.id=b.{prod_col}
        {family_join}
        WHERE b.scenario_id=:sid AND {where_active}
        ORDER BY b.id
    """
    return sql

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLAlchemy DB URL")
    ap.add_argument("--scenario", type=int, required=True)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--include-inactive", action="store_true", help="Do not filter by active flag; list all rows")
    args = ap.parse_args()

    eng = create_engine(args.db)
    with eng.connect() as conn:
        table = find_boq_table(conn)
        cols = get_columns(conn, table)
        print(f"[info] using BOQ table: {table} | columns={sorted(cols)}")
        sql = build_sql(conn, table, cols, args.include_inactive)
        rows = conn.execute(text(sql), {"sid": args.scenario}).fetchall()

        if not rows:
            print(f"[warn] no BOQ rows found in {table} for scenario {args.scenario}")
            try:
                c = conn.execute(text(f"SELECT scenario_id, COUNT(*) FROM {table} GROUP BY scenario_id")).fetchall()
                if c:
                    print("[hint] counts per scenario:", c)
            except Exception:
                pass
            return

        header = "boq_id | product_id | active | boq_cat           | engine_cat | family              | product_name"
        print(header)
        print("-"*len(header))
        for r in rows[:args.limit]:
            boq_cat = getattr(r, "boq_category", None)
            active_val = getattr(r, "active", None)
            active_str = "-" if active_val is None else str(active_val)
            # engine category only if product_id available
            engine_cat = None
            if getattr(r, "product_id", None) is not None:
                try:
                    engine_cat = product_category(conn, int(r.product_id))
                except Exception:
                    engine_cat = None
            pid_str = "-" if r.product_id is None else str(int(r.product_id))
            family_name = getattr(r, "family_name", None) or "-"
            pname = r.product_name or "-"
            print(f"{int(r.id):6d} | {pid_str:10s} | {active_str:6s} | {(boq_cat or '-'):16s} | {(engine_cat or '-'):9s} | {family_name:18s} | {pname}")
        if len(rows) > args.limit:
            print(f"... ({len(rows)-args.limit} more)")

if __name__ == "__main__":
    main()
