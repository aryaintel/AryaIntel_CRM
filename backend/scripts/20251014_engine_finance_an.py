#!/usr/bin/env python3
"""
Engine MVB: Compute monthly facts for oA.Finance-AN

- Targets Finance AN parity at MVB level:
  * Revenue (recomputed here, same logic as c.Sales-AN)
  * COGS (qty * unit_cogs with same timing rules)
  * Gross Profit (Revenue - COGS)

- Writes into engine_facts_monthly with distinct sheet codes:
    'oA.Finance-AN.Revenue'
    'oA.Finance-AN.COGS'
    'oA.Finance-AN.GP'

- Category detection priority:
    1) scenario_boq_items.category
    2) engine_category_map (scope='product')
    3) product_attributes (name='engine_category')

- Frequency (MVB):
    - 'monthly': spread evenly: qty * unit_price/unit_cogs every active month
    - 'annual': book the full amount in the first active month only
    - else: treat as 'monthly'

Usage:
    python 20251014_engine_finance_an.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db --scenario 1
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

# ------------------------------ Helpers ---------------------------------

def parse_db_url(db_url: str) -> str:
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    return db_url

def yyyymm_add(yyyymm: int, months: int) -> int:
    y = yyyymm // 100
    m = yyyymm % 100
    m0 = m - 1 + months
    y2 = y + (m0 // 12)
    m2 = (m0 % 12) + 1
    return y2 * 100 + m2

def date_to_yyyymm(d: dt.date) -> int:
    return d.year * 100 + d.month

def clamp_months(start_yyyymm: int, months: int, scenario_start: int, scenario_months: int) -> Tuple[int, int]:
    horizon_end = yyyymm_add(scenario_start, scenario_months)  # exclusive
    cur = start_yyyymm
    if cur < scenario_start:
        cur = scenario_start
    end_excl = yyyymm_add(start_yyyymm, months)
    if end_excl > horizon_end:
        end_excl = horizon_end
    if cur >= end_excl:
        return (cur, 0)
    y1, m1 = divmod(cur, 100)
    y2, m2 = divmod(end_excl, 100)
    total = (y2 - y1) * 12 + (m2 - m1)
    return (cur, total)

# ------------------------------ Core ---------------------------------

def ensure_seed(conn: sqlite3.Connection):
    cur = conn.cursor()
    # sheets
    cur.execute("INSERT OR IGNORE INTO engine_sheets(code,name,sort_order) VALUES(?,?,?)",
                ('oA.Finance-AN.Revenue', 'Finance — AN — Revenue', 210))
    cur.execute("INSERT OR IGNORE INTO engine_sheets(code,name,sort_order) VALUES(?,?,?)",
                ('oA.Finance-AN.COGS', 'Finance — AN — COGS', 211))
    cur.execute("INSERT OR IGNORE INTO engine_sheets(code,name,sort_order) VALUES(?,?,?)",
                ('oA.Finance-AN.GP', 'Finance — AN — Gross Profit', 212))
    # categories
    cur.execute("""
        INSERT OR IGNORE INTO engine_categories(code,name,sort_order) VALUES
        ('AN','Ammonium Nitrate',10),
        ('EM','Emulsion',20),
        ('IE','Initiating Explosives',30),
        ('Services','Services',40)
    """)
    conn.commit()

class Scenario:
    __slots__ = ("id", "start_date", "months")
    def __init__(self, id: int, start_date: dt.date, months: int):
        self.id, self.start_date, self.months = id, start_date, months

def load_scenario(conn: sqlite3.Connection, scenario_id: int) -> Scenario:
    cur = conn.cursor()
    cur.execute("SELECT id, start_date, months FROM scenarios WHERE id=?", (scenario_id,))
    r = cur.fetchone()
    if not r:
        raise SystemExit(f"Scenario {scenario_id} not found")
    y, m, d = map(int, r[1].split("-"))
    return Scenario(r[0], dt.date(y, m, d), int(r[2]))

def detect_item_category(conn: sqlite3.Connection, product_id: Optional[int], explicit_cat: Optional[str]) -> Optional[str]:
    if explicit_cat and explicit_cat.strip():
        return explicit_cat.strip()
    if product_id:
        cur = conn.cursor()
        cur.execute("""
            SELECT category_code
            FROM engine_category_map
            WHERE scope='product' AND ref_id=? AND is_active=1
            LIMIT 1
        """, (product_id,))
        t = cur.fetchone()
        if t and t[0]:
            return t[0]
        cur.execute("""
            SELECT value
            FROM product_attributes
            WHERE product_id=? AND name='engine_category'
            LIMIT 1
        """, (product_id,))
        t = cur.fetchone()
        if t and t[0]:
            return t[0]
    return None

def spread_amounts(freq: str, start_yyyymm: int, months: int, amount: float) -> Dict[int, float]:
    out: Dict[int, float] = {}
    f = (freq or "monthly").strip().lower()
    if f not in ("monthly", "annual"):
        f = "monthly"
    if months <= 0:
        return out
    if f == "monthly":
        for i in range(months):
            ym = yyyymm_add(start_yyyymm, i)
            out[ym] = out.get(ym, 0.0) + amount
    else:
        out[start_yyyymm] = out.get(start_yyyymm, 0.0) + amount
    return out

def compute_finance_an(conn: sqlite3.Connection, scenario: Scenario, run_id: int):
    CAT = 'AN'
    scen_start = date_to_yyyymm(scenario.start_date)

    cur = conn.cursor()

    # Wipe previous facts for this run (safety if re-run)
    cur.execute("""DELETE FROM engine_facts_monthly
                   WHERE run_id=? AND category_code='AN'
                     AND sheet_code IN ('oA.Finance-AN.Revenue','oA.Finance-AN.COGS','oA.Finance-AN.GP')""",
                (run_id,))

    revenue: Dict[int, float] = {}
    cogs: Dict[int, float] = {}

    cur.execute("""
        SELECT id, product_id, category, quantity, unit_price, unit_cogs, frequency,
               start_year, start_month, months
        FROM scenario_boq_items
        WHERE scenario_id=? AND is_active=1
    """, (scenario.id,))
    rows = cur.fetchall()

    for (row_id, product_id, category, qty, unit_price, unit_cogs, freq, sy, sm, mths) in rows:
        cat = detect_item_category(conn, product_id, category)
        if cat != CAT:
            continue
        if qty is None:
            continue

        # Start and span
        if sy is None or sm is None:
            start_yyyymm = scen_start
        else:
            start_yyyymm = int(sy) * 100 + int(sm)
        total_m = 1 if (mths is None or int(mths) <= 0) else int(mths)
        start_yyyymm, total_m = clamp_months(start_yyyymm, total_m, scen_start, scenario.months)
        if total_m <= 0:
            continue

        # Revenue
        if unit_price is not None:
            rev_amt = float(qty) * float(unit_price)
            for ym, v in spread_amounts(freq or "monthly", start_yyyymm, total_m, rev_amt).items():
                revenue[ym] = revenue.get(ym, 0.0) + v

        # COGS
        if unit_cogs is not None:
            cogs_amt = float(qty) * float(unit_cogs)
            for ym, v in spread_amounts(freq or "monthly", start_yyyymm, total_m, cogs_amt).items():
                cogs[ym] = cogs.get(ym, 0.0) + v

    # Insert Revenue
    for ym, val in sorted(revenue.items()):
        cur.execute("""
            INSERT INTO engine_facts_monthly(run_id, scenario_id, sheet_code, category_code, yyyymm, value, created_at)
            VALUES(?,?,?,?,?,?, datetime('now'))
        """, (run_id, scenario.id, 'oA.Finance-AN.Revenue', CAT, ym, round(val, 6)))

    # Insert COGS
    for ym, val in sorted(cogs.items()):
        cur.execute("""
            INSERT INTO engine_facts_monthly(run_id, scenario_id, sheet_code, category_code, yyyymm, value, created_at)
            VALUES(?,?,?,?,?,?, datetime('now'))
        """, (run_id, scenario.id, 'oA.Finance-AN.COGS', CAT, ym, round(val, 6)))

    # Insert GP = Revenue - COGS (align on union of months)
    months = set(revenue.keys()) | set(cogs.keys())
    for ym in sorted(months):
        gp = revenue.get(ym, 0.0) - cogs.get(ym, 0.0)
        cur.execute("""
            INSERT INTO engine_facts_monthly(run_id, scenario_id, sheet_code, category_code, yyyymm, value, created_at)
            VALUES(?,?,?,?,?,?, datetime('now'))
        """, (run_id, scenario.id, 'oA.Finance-AN.GP', CAT, ym, round(gp, 6)))

    conn.commit()

def begin_run(conn: sqlite3.Connection, scenario_id: int) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO engine_runs(scenario_id, started_at) VALUES(?, datetime('now'))", (scenario_id,))
    rid = cur.lastrowid
    conn.commit()
    return rid

def finish_run(conn: sqlite3.Connection, run_id: int):
    cur = conn.cursor()
    cur.execute("UPDATE engine_runs SET finished_at = datetime('now') WHERE id=?", (run_id,))
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_url", default=os.environ.get("DATABASE_URL", "sqlite:///./app.db"))
    ap.add_argument("--scenario", type=int, required=True)
    args = ap.parse_args()

    # connect
    db_path = parse_db_url(args.db_url)
    conn = sqlite3.connect(db_path)
    try:
        ensure_seed(conn)
        scenario = load_scenario(conn, args.scenario)
        run_id = begin_run(conn, scenario.id)
        try:
            compute_finance_an(conn, scenario, run_id)
        finally:
            finish_run(conn, run_id)
        print(f"OK - run_id={run_id}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
