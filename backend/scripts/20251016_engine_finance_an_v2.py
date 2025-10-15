#!/usr/bin/env python3
# v2.1 — resilient product_family fallback (no crash if column is missing)
from __future__ import annotations
import argparse, sqlite3, re, os, datetime as dt
from typing import Optional, Dict, Tuple, List

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

def ensure_seed(conn: sqlite3.Connection):
    cur = conn.cursor()
    for code,name,order in [('oA.Finance-AN.Revenue','Finance — AN — Revenue',210),
                            ('oA.Finance-AN.COGS','Finance — AN — COGS',211),
                            ('oA.Finance-AN.GP','Finance — AN — Gross Profit',212)]:
        cur.execute("INSERT OR IGNORE INTO engine_sheets(code,name,sort_order) VALUES(?,?,?)",(code,name,order))
    cur.execute("""
        INSERT OR IGNORE INTO engine_categories(code,name,sort_order) VALUES
        ('AN','Ammonium Nitrate',10),
        ('EM','Emulsion',20),
        ('IE','Initiating Explosives',30),
        ('Services','Services',40)
    """)
    conn.commit()

class Scenario:
    __slots__=("id","start_date","months")
    def __init__(self,id:int,start_date:str,months:int):
        y,m,d = [int(x) for x in start_date.split("-")]
        self.id=id; self.start_date=dt.date(y,m,d); self.months=int(months)

def load_scenario(conn: sqlite3.Connection, scenario_id: int) -> Scenario:
    r = conn.execute("SELECT id, start_date, months FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
    if not r: raise SystemExit(f"Scenario {scenario_id} not found")
    return Scenario(r[0], r[1], r[2])

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
    # 1) products.product_family_id column (if exists)
    if col_exists(conn, "products", "product_family_id"):
        r = conn.execute("SELECT product_family_id FROM products WHERE id=?", (product_id,)).fetchone()
        if r and r[0] is not None:
            return int(r[0])
    # 2) alternative naming
    for alt in ("family_id", "pf_id"):
        if col_exists(conn, "products", alt):
            r = conn.execute(f"SELECT {alt} FROM products WHERE id=?", (product_id,)).fetchone()
            if r and r[0] is not None:
                return int(r[0])
    # 3) product_attributes
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

def detect_item_category(conn: sqlite3.Connection, product_id: Optional[int], explicit_cat: Optional[str]) -> Optional[str]:
    if explicit_cat and explicit_cat.strip():
        return explicit_cat.strip()
    cur = conn.cursor()
    if product_id:
        r = cur.execute("""SELECT category_code FROM engine_category_map
                           WHERE scope='product' AND ref_id=? AND is_active=1 LIMIT 1""",(product_id,)).fetchone()
        if r and r[0]: return r[0]
        r = cur.execute("""SELECT value FROM product_attributes
                           WHERE product_id=? AND name='engine_category' LIMIT 1""",(product_id,)).fetchone()
        if r and r[0]: return r[0]
        fam_id = get_product_family_id(conn, product_id)
        if fam_id:
            r = cur.execute("""SELECT category_code FROM engine_category_map
                               WHERE scope='product_family' AND ref_id=? AND is_active=1 LIMIT 1""",(fam_id,)).fetchone()
            if r and r[0]: return r[0]
    return None

def spread(freq: str, start_yyyymm: int, months: int, amount: float) -> Dict[int,float]:
    out: Dict[int,float] = {}
    f=(freq or "monthly").strip().lower()
    if f not in ("monthly","annual"): f="monthly"
    if months<=0: return out
    if f=="monthly":
        for i in range(months):
            ym=yyyymm_add(start_yyyymm,i); out[ym]=out.get(ym,0.0)+amount
    else:
        out[start_yyyymm]=out.get(yyyymm,0.0)+amount
    return out

def compute(conn: sqlite3.Connection, scenario: Scenario, run_id: int):
    CAT='AN'; scen_start = date_to_yyyymm(scenario.start_date)
    cur = conn.cursor()
    cur.execute("""DELETE FROM engine_facts_monthly
                   WHERE run_id=? AND category_code='AN'
                     AND sheet_code IN ('oA.Finance-AN.Revenue','oA.Finance-AN.COGS','oA.Finance-AN.GP')""",(run_id,))

    revenue: Dict[int,float]={}; cogs: Dict[int,float]={}

    rows = cur.execute("""
        SELECT id, product_id, category, quantity, unit_price, unit_cogs, frequency,
               start_year, start_month, months
        FROM scenario_boq_items
        WHERE scenario_id=? AND is_active=1
    """,(scenario.id,)).fetchall()

    for (row_id, product_id, category, qty, unit_price, unit_cogs, freq, sy, sm, mths) in rows:
        cat = detect_item_category(conn, product_id, category)
        if cat != CAT: continue
        if qty is None: continue

        start_yyyymm = scen_start if (sy is None or sm is None) else (int(sy)*100+int(sm))
        total_m = 1 if (mths is None or int(mths)<=0) else int(mths)
        start_yyyymm, total_m = clamp_months(start_yyyymm, total_m, scen_start, scenario.months)
        if total_m<=0: continue

        if unit_price is not None:
            amt=float(qty)*float(unit_price)
            for ym,v in spread(freq,start_yyyymm,total_m,amt).items():
                revenue[ym]=revenue.get(ym,0.0)+v
        if unit_cogs is not None:
            amt=float(qty)*float(unit_cogs)
            for ym,v in spread(freq,start_yyyymm,total_m,amt).items():
                cogs[ym]=cogs.get(ym,0.0)+v

    for ym,val in sorted(revenue.items()):
        cur.execute("""INSERT INTO engine_facts_monthly(run_id,scenario_id,sheet_code,category_code,yyyymm,value,created_at)
                       VALUES(?,?,?,?,?,?,datetime('now'))""",(run_id,scenario.id,'oA.Finance-AN.Revenue',CAT,ym,round(val,6)))
    for ym,val in sorted(cogs.items()):
        cur.execute("""INSERT INTO engine_facts_monthly(run_id,scenario_id,sheet_code,category_code,yyyymm,value,created_at)
                       VALUES(?,?,?,?,?,?,datetime('now'))""",(run_id,scenario.id,'oA.Finance-AN.COGS',CAT,ym,round(val,6)))
    for ym in sorted(set(revenue.keys())|set(cogs.keys())):
        gp=revenue.get(ym,0.0)-cogs.get(ym,0.0)
        cur.execute("""INSERT INTO engine_facts_monthly(run_id,scenario_id,sheet_code,category_code,yyyymm,value,created_at)
                       VALUES(?,?,?,?,?,?,datetime('now'))""",(run_id,scenario.id,'oA.Finance-AN.GP',CAT,ym,round(gp,6)))
    conn.commit()

def begin_run(conn: sqlite3.Connection, scenario_id: int) -> int:
    cur=conn.cursor(); cur.execute("INSERT INTO engine_runs(scenario_id,started_at) VALUES(?,datetime('now'))",(scenario_id,))
    rid=cur.lastrowid; conn.commit(); return rid

def finish_run(conn: sqlite3.Connection, run_id: int):
    conn.execute("UPDATE engine_runs SET finished_at=datetime('now') WHERE id=?", (run_id,)); conn.commit()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_url", required=True)
    ap.add_argument("--scenario", type=int, required=True)
    a=ap.parse_args()
    db_path=parse_db_url(a.db_url)
    conn=sqlite3.connect(db_path)
    try:
        ensure_seed(conn)
        scen=load_scenario(conn,a.scenario)
        run=begin_run(conn,scen.id)
        try:
            compute(conn,scen,run)
        finally:
            finish_run(conn,run)
        print(f"OK - run_id={run}")
    finally:
        conn.close()

if __name__=="__main__":
    main()
