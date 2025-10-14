#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251013_create_engine_tables.py
"""
Create NEW Engine tables and seed ONLY their own static data.
- Does NOT read/modify scenarios or any existing scenario_* tables.

Tables:
  engine_sheets            (code PK)           -- sheet families: 'c.Sales','oA.Finance','oQ.Finance'
  engine_categories        (code PK)           -- categories: 'AN','EM','IE','Services','Spare1','Spare2'
  engine_runs              (id PK, options_json, timestamps, scenario_id nullable)
  engine_facts_monthly     (monthly facts; FK to sheets/categories; optional run_id/scenario_id)

Idempotent: safe to re-run.

Usage:
  python backend/scripts/20251013_create_engine_tables.py --db sqlite:///C:/Dev/AryaIntel_CRM/app.db
"""

import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

SHEETS = ["c.Sales", "oA.Finance", "oQ.Finance"]
CATEGORIES = ["AN","EM","IE","Services","Spare1","Spare2"]

def _log(msg): print(msg, flush=True)

def ensure_tables(engine: Engine):
    with engine.begin() as conn:
        dialect = engine.dialect.name

        # engine_sheets
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_sheets (
                code TEXT PRIMARY KEY,
                name TEXT,
                sort_order INTEGER
            )
        """))

        # engine_categories
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_categories (
                code TEXT PRIMARY KEY,
                name TEXT,
                sort_order INTEGER
            )
        """))

        # engine_runs
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_runs (
                id INTEGER PRIMARY KEY,
                scenario_id INTEGER,            -- nullable on purpose; engine çalışabilir ama bağlamak zorunda değil
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                options_json TEXT
            )
        """))

        # engine_facts_monthly
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_facts_monthly (
                id INTEGER PRIMARY KEY,
                run_id INTEGER,
                scenario_id INTEGER,
                sheet_code TEXT NOT NULL,
                category_code TEXT NOT NULL,
                yyyymm INTEGER NOT NULL,
                value NUMERIC(18,6) NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(sheet_code) REFERENCES engine_sheets(code),
                FOREIGN KEY(category_code) REFERENCES engine_categories(code)
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_engine_facts
            ON engine_facts_monthly(run_id, sheet_code, category_code, yyyymm)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_engine_facts_scenario
            ON engine_facts_monthly(scenario_id, yyyymm)
        """))

def seed_static(engine: Engine):
    with engine.begin() as conn:
        # seed sheets
        for i, code in enumerate(SHEETS):
            conn.execute(text("""
                INSERT INTO engine_sheets (code, name, sort_order)
                SELECT :c, :n, :o
                WHERE NOT EXISTS (SELECT 1 FROM engine_sheets WHERE code=:c)
            """), {"c": code, "n": code, "o": i})

        # seed categories
        for i, code in enumerate(CATEGORIES):
            conn.execute(text("""
                INSERT INTO engine_categories (code, name, sort_order)
                SELECT :c, :n, :o
                WHERE NOT EXISTS (SELECT 1 FROM engine_categories WHERE code=:c)
            """), {"c": code, "n": code, "o": i})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLAlchemy DB URL (e.g. sqlite:///C:/Dev/AryaIntel_CRM/app.db)")
    args = ap.parse_args()

    engine = create_engine(args.db)
    _log(f"[info] Dialect: {engine.dialect.name}")

    _log("[step] Ensuring engine tables...")
    ensure_tables(engine)
    _log("[ok] Tables are in place.")

    _log("[step] Seeding static rows (sheets & categories)...")
    seed_static(engine)
    _log("[done] Engine static data seeded. No scenarios were touched.")

if __name__ == "__main__":
    main()
