#!/usr/bin/env python3
from __future__ import annotations
import argparse, sqlite3, re, os, datetime as dt
from typing import Optional, Tuple

def parse_db_url(db_url: str) -> str:
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    return db_url

def table_exists(conn, name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def col_exists(conn, table: str, col: str) -> bool:
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return any(r[1] == col for r in cur.fetchall())
    except sqlite3.OperationalError:
        return False

def get_product_family_id(conn: sqlite3.Connection, product_id: int) -> Optional[int]:
    if not product_id:
        return None
    if col_exists(conn, "products", "product_family_id"):
        r = conn.execute("SELECT product_family_id FROM products WHERE id=?", (product_id,)).fetchone()
        if r and r[0] is not None:
            return int(r[0])
    for alt in ("family_id", "pf_id"):
        if col_exists(conn, "products", alt):
            r = conn.execute(f"SELECT {alt} FROM products WHERE id=?", (product_id,)).fetchone()
            if r and r[0] is not None:
                return int(r[0])
    if table_exists(conn, "product_attributes"):
        r = conn.execute("""SELECT value FROM product_attributes
                            WHERE product_id=? AND name IN ('product_family_id','family_id') LIMIT 1""",
                         (product_id,)).fetchone()
        if r and r[0] is not None:
            try:
                return int(r[0])
            except Exception:
                return None
    return None

def detect_item_category_verbose(conn: sqlite3.Connection, product_id: Optional[int], explicit_cat: Optional[str]) -> Tuple[Optional[str], str]:
    if explicit_cat and str(explicit_cat).strip():
        return str(explicit_cat).strip(), "row.category"
    if product_id:
        r = conn.execute("""SELECT category_code FROM engine_category_map
                            WHERE scope='product' AND ref_id=? AND is_active=1 LIMIT 1""",(product_id,)).fetchone()
        if r and r[0]:
            return r[0], "map:product"
        r = conn.execute("""SELECT value FROM product_attributes
                            WHERE product_id=? AND name='engine_category' LIMIT 1""",(product_id,)).fetchone()
        if r and r[0]:
            return r[0], "attr:engine_category"
        fam_id = get_product_family_id(conn, product_id)
        if fam_id:
            r = conn.execute("""SELECT category_code FROM engine_category_map
                                WHERE scope='product_family' AND ref_id=? AND is_active=1 LIMIT 1""",(fam_id,)).fetchone()
            if r and r[0]:
                return r[0], f"map:family({fam_id})"
    return None, "unresolved"

def date_to_yyyymm(d: dt.date) -> int:
    return d.year * 100 + d.month

def yyyymm_add(yyyymm: int, months: int) -> int:
    y = yyyymm // 100
    m = yyyymm % 100
    m0 = m - 1 + months
    y2 = y + (m0 // 12)
    m2 = (m0 % 12) + 1
    return y2 * 100 + m2

def clamp_months(start_yyyymm: int, months: int, scenario_start: int, scenario_months: int):
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_url", required=True)
    ap.add_argument("--scenario", type=int, required=True)
    a = ap.parse_args()

    db_path = parse_db_url(a.db_url)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        scen = conn.execute("SELECT id, start_date, months FROM scenarios WHERE id=?", (a.scenario,)).fetchone()
        if not scen:
            print(f"[ERR] Scenario {a.scenario} not found")
            return
        y,m,d = [int(x) for x in scen["start_date"].split("-")]
        scen_start = date_to_yyyymm(dt.date(y,m,d))

        rows = conn.execute("""
            SELECT id, product_id, category, quantity, unit_price, unit_cogs, frequency,
                   start_year, start_month, months
            FROM scenario_boq_items
            WHERE scenario_id=? AND is_active=1
            ORDER BY id
        """, (a.scenario,)).fetchall()

        print(f"[INFO] Active BOQ rows: {len(rows)}")
        printed = 0
        for r in rows:
            rid = r["id"]
            prod = r["product_id"]
            cat, how = detect_item_category_verbose(conn, prod, r["category"])
            if cat != "AN":
                continue

            qty = r["quantity"]; up = r["unit_price"]; uc = r["unit_cogs"]
            freq = (r["frequency"] or "monthly").strip().lower()
            s_ym = scen_start if (r["start_year"] is None or r["start_month"] is None) else (int(r["start_year"])*100 + int(r["start_month"]))
            mths = 1 if (r["months"] is None or int(r["months"]) <= 0) else int(r["months"])
            s_ym2, mths2 = clamp_months(s_ym, mths, scen_start, int(scen["months"]))

            decision = []
            if qty is None: decision.append("skip:qty=None")
            if up is None:  decision.append("rev:unit_price=None")
            if uc is None:  decision.append("cogs:unit_cogs=None")
            if mths2 <= 0:  decision.append("skip:window=0")
            if not decision:
                decision.append("OK")

            print(f"row#{rid} prod={prod} cat={cat} ({how}) qty={qty} up={up} uc={uc} freq={freq} start={s_ym}->[{s_ym2}/{mths2}] :: {';'.join(decision)}")
            printed += 1

        if printed == 0:
            print("[INFO] No rows resolved as AN. Either mappings are different, or all products map to other categories.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
