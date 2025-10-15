#!/usr/bin/env python3
"""
Diagnostic: Engine inputs for AN sheets (c.Sales-AN / oA.Finance-AN)

- Prints counts & sample rows for scenario_boq_items and category resolution
- Helps explain why engine_facts_monthly might be empty
Usage:
  python scripts/20251014_diag_engine_inputs.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db --scenario 1
"""
from __future__ import annotations
import argparse, sqlite3, re, os

def parse_db_url(db_url: str) -> str:
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    return db_url

def q1(conn, scenario_id: int):
    cur = conn.cursor()
    print("\n[1] BOQ aktif satır sayısı (scenario_boq_items):")
    cur.execute("""
        SELECT COUNT(*) FROM scenario_boq_items
        WHERE scenario_id=? AND is_active=1
    """, (scenario_id,))
    print("  active_boq_rows =", cur.fetchone()[0])

    print("\n[2] AN'e düşen satır sayısı (explicit / map / attr):")
    cur.execute("""
        WITH m AS (
          SELECT s.id,
                 s.product_id,
                 s.category AS explicit_cat,
                 (SELECT category_code FROM engine_category_map
                    WHERE scope='product' AND ref_id=s.product_id AND is_active=1
                    LIMIT 1) AS mapped_cat,
                 (SELECT value FROM product_attributes
                    WHERE product_id=s.product_id AND name='engine_category'
                    LIMIT 1) AS attr_cat
          FROM scenario_boq_items s
          WHERE s.scenario_id=? AND s.is_active=1
        )
        SELECT
          SUM(CASE WHEN COALESCE(TRIM(explicit_cat), '')='AN' THEN 1 ELSE 0 END) AS explicit_AN,
          SUM(CASE WHEN mapped_cat='AN' THEN 1 ELSE 0 END) AS mapped_AN,
          SUM(CASE WHEN attr_cat='AN' THEN 1 ELSE 0 END) AS attr_AN
        FROM m
    """, (scenario_id,))
    print(" ", dict(zip(("explicit_AN","mapped_AN","attr_AN"), cur.fetchone())))

    print("\n[3] AN satırlarında qty/price/cogs doluluk:")
    cur.execute("""
        WITH m AS (
          SELECT s.*,
                 COALESCE(NULLIF(TRIM(s.category),''),
                          (SELECT category_code FROM engine_category_map
                             WHERE scope='product' AND ref_id=s.product_id AND is_active=1 LIMIT 1),
                          (SELECT value FROM product_attributes
                             WHERE product_id=s.product_id AND name='engine_category' LIMIT 1)
                 ) AS resolved_cat
          FROM scenario_boq_items s
          WHERE s.scenario_id=? AND s.is_active=1
        )
        SELECT
          COUNT(*) AS an_rows,
          SUM(CASE WHEN quantity IS NOT NULL THEN 1 ELSE 0 END) AS qty_ok,
          SUM(CASE WHEN unit_price IS NOT NULL THEN 1 ELSE 0 END) AS price_ok,
          SUM(CASE WHEN unit_cogs IS NOT NULL THEN 1 ELSE 0 END) AS cogs_ok
        FROM m
        WHERE resolved_cat='AN'
    """, (scenario_id,))
    row = cur.fetchone()
    print(" ", dict(zip(("an_rows","qty_ok","price_ok","cogs_ok"), row)))

    print("\n[4] Örnek 10 AN satırı (engine hesap için kritik alanlar):")
    cur.execute("""
        WITH m AS (
          SELECT s.*,
                 COALESCE(NULLIF(TRIM(s.category),''),
                          (SELECT category_code FROM engine_category_map
                             WHERE scope='product' AND ref_id=s.product_id AND is_active=1 LIMIT 1),
                          (SELECT value FROM product_attributes
                             WHERE product_id=s.product_id AND name='engine_category' LIMIT 1)
                 ) AS resolved_cat
          FROM scenario_boq_items s
          WHERE s.scenario_id=? AND s.is_active=1
        )
        SELECT id, product_id, resolved_cat AS cat, quantity, unit_price, unit_cogs,
               frequency, start_year, start_month, months
        FROM m
        WHERE resolved_cat='AN'
        ORDER BY id
        LIMIT 10
    """, (scenario_id,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        print("  (no rows)")
        return
    print(" " + " | ".join(cols))
    for r in rows:
        print(" " + " | ".join(str(x) if x is not None else "-" for x in r))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_url", required=True)
    ap.add_argument("--scenario", type=int, required=True)
    args = ap.parse_args()
    db_path = parse_db_url(args.db_url)
    conn = sqlite3.connect(db_path)
    try:
        q1(conn, args.scenario)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
""
