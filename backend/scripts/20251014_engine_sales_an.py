#!/usr/bin/env python3
"""
Engine MVB: Compute monthly facts for c.Sales-AN

- Targets sheet_code = 'c.Sales-AN' (Tender Excel parity for AN Sales sheet)
- Writes to engine_facts_monthly (one row per yyyymm)
- Seeds engine_categories and engine_sheets minimally if missing
- Infers AN rows from (priority):
    1) scenario_boq_items.category = 'AN'
    2) engine_category_map where scope='product' and ref_id=product_id -> category_code
    3) product_attributes where name='engine_category' -> value
- Frequency handling (MVB):
    - 'monthly': quantity * unit_price each active month of the row
    - 'annual': book full quantity * unit_price in the starting month only
    - else: treat as 'monthly'
- Active window:
    - If start_year/month missing -> fallback to scenario start_date's year/month
    - If months missing or <=0 -> 1 month (MVB)
    - Clamp to scenario horizon (scenario.months, starting from scenario.start_date)
- Idempotent per (run_id, sheet_code, category_code, yyyymm) via unique index ux_engine_facts

Usage:
    python 20251014_engine_sales_an.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db --scenario 1
    # or
    python 20251014_engine_sales_an.py --db sqlite:///./app.db --scenario 1
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

# ------------------------------ Helpers ---------------------------------

def parse_db_url(db_url: str) -> str:
    """
    Accepts sqlalchemy-style sqlite URLs and returns a filesystem path usable by sqlite3.
    Examples:
      sqlite:///./app.db -> ./app.db
      sqlite:////C:/Dev/AryaIntel_CRM/backend/app.db -> C:/Dev/AryaIntel_CRM/backend/app.db
    """
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        # collapse leading '/' on windows drive paths like /C:/...
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    # If plain path is passed, return as is
    return db_url

def yyyymm_add(yyyymm: int, months: int) -> int:
    y = yyyymm // 100
    m = yyyymm % 100
    m0 = m - 1 + months
    y2 = y + (m0 // 12)
    m2 = (m0 % 12) + 1
    return y2 * 100 + m2

def daterange_yyyymm(start_yyyymm: int, months: int) -> List[int]:
    return [yyyymm_add(start_yyyymm, i) for i in range(months)]

def date_to_yyyymm(d: dt.date) -> int:
    return d.year * 100 + d.month

def clamp_months(start_yyyymm: int, months: int, scenario_start: int, scenario_months: int) -> Tuple[int, int]:
    horizon_end = yyyymm_add(scenario_start, scenario_months)  # exclusive
    # shift start if before scenario
    cur = start_yyyymm
    if cur < scenario_start:
        delta = 0
        # move cur up to scenario_start
        cur = scenario_start
        # reduce months accordingly
        # Compute how many months remain from cur to original end
    end_excl = yyyymm_add(start_yyyymm, months)
    if end_excl > horizon_end:
        end_excl = horizon_end
    # if start is after end, nothing
    if cur >= end_excl:
        return (cur, 0)
    # months between cur and end_excl
    # compute difference in months
    y1, m1 = divmod(cur, 100)
    y2, m2 = divmod(end_excl, 100)
    total = (y2 - y1) * 12 + (m2 - m1)
    return (cur, total)

# ------------------------------ Core ---------------------------------

def ensure_seed(conn: sqlite3.Connection):
    cur = conn.cursor()
    # engine_categories
    cur.execute("SELECT COUNT(1) FROM engine_categories")
    cnt = cur.fetchone()[0] if cur.fetchone is not None else 0
    cur.execute("""
        INSERT OR IGNORE INTO engine_categories(code,name,sort_order) VALUES
        ('AN','Ammonium Nitrate',10),
        ('EM','Emulsion',20),
        ('IE','Initiating Explosives',30),
        ('Services','Services',40)
    """)
    # engine_sheets
    cur.execute("INSERT OR IGNORE INTO engine_sheets(code,name,sort_order) VALUES(?,?,?)",
                ('c.Sales-AN', 'Sales — AN', 110))
    conn.commit()

def begin_run(conn: sqlite3.Connection, scenario_id: int) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO engine_runs(scenario_id, started_at) VALUES(?, datetime('now'))", (scenario_id,))
    run_id = cur.lastrowid
    conn.commit()
    return run_id

def finish_run(conn: sqlite3.Connection, run_id: int):
    cur = conn.cursor()
    cur.execute("UPDATE engine_runs SET finished_at = datetime('now') WHERE id = ?", (run_id,))
    conn.commit()

@dataclass
class Scenario:
    id: int
    start_date: dt.date
    months: int

def load_scenario(conn: sqlite3.Connection, scenario_id: int) -> Scenario:
    cur = conn.cursor()
    cur.execute("SELECT id, start_date, months FROM scenarios WHERE id = ?", (scenario_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"Scenario {scenario_id} not found")
    id_, start_date_str, months = row
    y, m, d = map(int, start_date_str.split("-"))
    return Scenario(id=id_, start_date=dt.date(y, m, d), months=int(months))

def detect_item_category(conn: sqlite3.Connection, product_id: Optional[int], explicit_cat: Optional[str]) -> Optional[str]:
    # Priority 1: explicit category
    if explicit_cat and explicit_cat.strip():
        return explicit_cat.strip()
    # Priority 2: engine_category_map for product
    if product_id:
        cur = conn.cursor()
        cur.execute("""
            SELECT category_code
            FROM engine_category_map
            WHERE scope='product' AND ref_id=? AND is_active=1
            LIMIT 1
        """, (product_id,))
        r = cur.fetchone()
        if r and r[0]:
            return r[0]
        # Priority 3: product_attributes
        cur.execute("""
            SELECT value
            FROM product_attributes
            WHERE product_id=? AND name='engine_category'
            LIMIT 1
        """, (product_id,))
        r = cur.fetchone()
        if r and r[0]:
            return r[0]
    return None

def compute_sales_an(conn: sqlite3.Connection, scenario: Scenario, run_id: int):
    SHEET = 'c.Sales-AN'
    CAT = 'AN'

    scen_start = date_to_yyyymm(scenario.start_date)

    cur = conn.cursor()
    # Clear previous facts for this run + sheet + category
    cur.execute("""
        DELETE FROM engine_facts_monthly
        WHERE run_id=? AND sheet_code=? AND category_code=?
    """, (run_id, SHEET, CAT))

    # Initialize aggregate map: yyyymm -> value
    values: Dict[int, float] = {}

    # Pull active BOQ rows for the scenario
    cur.execute("""
        SELECT id, product_id, category, quantity, unit_price, frequency,
               start_year, start_month, months
        FROM scenario_boq_items
        WHERE scenario_id = ? AND is_active = 1
    """, (scenario.id,))
    rows = cur.fetchall()

    for (row_id, product_id, category, qty, unit_price, freq, sy, sm, mths) in rows:
        cat = detect_item_category(conn, product_id, category)
        if cat != CAT:
            continue
        if qty is None or unit_price is None:
            continue

        # Determine start year/month
        if sy is None or sm is None:
            start_yyyymm = date_to_yyyymm(scenario.start_date)
        else:
            start_yyyymm = int(sy) * 100 + int(sm)

        # Determine months
        if mths is None or int(mths) <= 0:
            total_m = 1
        else:
            total_m = int(mths)

        # Clamp to scenario horizon
        start_yyyymm, total_m = clamp_months(start_yyyymm, total_m, scen_start, scenario.months)
        if total_m <= 0:
            continue

        freq_norm = (freq or "monthly").strip().lower()
        if freq_norm not in ("monthly", "annual"):
            freq_norm = "monthly"

        if freq_norm == "monthly":
            amount_per_month = float(qty) * float(unit_price)
            for i in range(total_m):
                ym = yyyymm_add(start_yyyymm, i)
                values[ym] = values.get(ym, 0.0) + amount_per_month
        else:  # annual: book all on the first (clamped) month
            ym = start_yyyymm
            values[ym] = values.get(ym, 0.0) + float(qty) * float(unit_price)

    # Persist
    for ym, val in sorted(values.items()):
        cur.execute("""
            INSERT INTO engine_facts_monthly(run_id, scenario_id, sheet_code, category_code, yyyymm, value, created_at)
            VALUES(?,?,?,?,?,?, datetime('now'))
        """, (run_id, scenario.id, SHEET, CAT, ym, round(val, 6)))
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_url", default=os.environ.get("DATABASE_URL", "sqlite:///./app.db"))
    ap.add_argument("--scenario", type=int, required=True)
    args = ap.parse_args()

    db_path = parse_db_url(args.db_url)
    conn = sqlite3.connect(db_path)
    try:
        ensure_seed(conn)
        scenario = load_scenario(conn, args.scenario)
        run_id = begin_run(conn, scenario.id)
        try:
            compute_sales_an(conn, scenario, run_id)
        finally:
            finish_run(conn, run_id)
        print(f"OK - run_id={run_id}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
