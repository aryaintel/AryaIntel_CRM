# Path: backend/scripts/20251021_engine_finance_quarterly_from_monthly.py
"""
Engine Finance — Quarterly Backfill (oQ.Finance-*)
--------------------------------------------------
Aylık veriden (kaynak sheet prefix: c.Sales- *veya* oA.Finance-) 'oQ.Finance-<CAT>'
(quarterly, cash) üretir. series: revenue, cogs, gp.

Kullanım:
  cd backend
  $env:DATABASE_URL = "sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db"

  # Varsayılan kaynak: c.Sales-
  python scripts/20251021_engine_finance_quarterly_from_monthly.py --db "$env:DATABASE_URL" --run-id latest --categories AN

  # Geçici: kaynağı oA.Finance- yap
  python scripts/20251021_engine_finance_quarterly_from_monthly.py --db "$env:DATABASE_URL" --run-id latest --categories AN --src oA
"""

import argparse
import os
import re
import sqlite3
from typing import Dict, Tuple, List, Iterable

SERIES = ("revenue", "cogs", "gp")
SRC_CHOICES = {"sales": "c.Sales-", "oA": "oA.Finance-"}  # kaynak prefix
DST_SHEET_PREFIX = "oQ.Finance-"

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DATABASE_URL", "sqlite:///backend/app.db"),
                    help="sqlite DSN (sqlite:///C:/.../app.db) veya dosya yolu")
    ap.add_argument("--run-id", required=True, help="'latest' veya sayısal run_id")
    ap.add_argument("--categories", default="", help="Virgüllü: AN,EM,IE,Services (boşsa otomatik keşif)")
    ap.add_argument("--src", choices=SRC_CHOICES.keys(), default="sales",
                    help="Kaynak sheet: 'sales' (c.Sales-) veya 'oA' (oA.Finance-)")
    return ap.parse_args()

def dsn_to_path(dsn: str) -> str:
    # sqlite:///C:/... | sqlite:////C:/... | plain path
    if dsn.startswith("sqlite:///"):
        path = dsn[len("sqlite:///"):]
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    if dsn.startswith("sqlite:////"):
        return dsn[len("sqlite:////"):]
    return dsn

def quarter_end_yyyymm(yyyymm: int) -> int:
    y = yyyymm // 100
    m = yyyymm % 100
    q = (m - 1) // 3 + 1
    q_end_month = {1: 3, 2: 6, 3: 9, 4: 12}[q]
    return y * 100 + q_end_month

def fetch_one(conn: sqlite3.Connection, sql: str, params: Iterable = ()):
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else None

def fetchall(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    return cur.fetchall()

def main():
    args = parse_args()
    db_path = dsn_to_path(args.db)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
        # 1) run_id
        if args.run_id == "latest":
            run_id = fetch_one(conn, "SELECT MAX(run_id) FROM engine_facts_monthly")
            if run_id is None:
                raise SystemExit("engine_facts_monthly boş; önce engine'i çalıştırın.")
        else:
            run_id = int(args.run_id)

        src_prefix = SRC_CHOICES[args.src]

        # 2) kategori listesi
        if args.categories.strip():
            cats = [c.strip() for c in args.categories.split(",") if c.strip()]
        else:
            rows = fetchall(conn, """
                SELECT DISTINCT category_code
                FROM engine_facts_monthly
                WHERE run_id=? AND sheet_code LIKE ?
            """, (run_id, f"{src_prefix}%"))
            cats = [r["category_code"] for r in rows]

        if not cats:
            raise SystemExit(f"Kaynak veri bulunamadı ({src_prefix}*, {SERIES}).")

        print(f"[info] DB: {db_path}")
        print(f"[info] run_id={run_id} src={src_prefix} categories={cats}")

        # 3) kaynak aylık veriyi çek → quarter bazında topla
        rows = fetchall(conn, f"""
            SELECT category_code, yyyymm, series, value
            FROM engine_facts_monthly
            WHERE run_id=? AND sheet_code LIKE ? AND series IN ({",".join("?"*len(SERIES))})
              AND category_code IN ({",".join("?"*len(cats))})
        """, (run_id, f"{src_prefix}%", *SERIES, *cats))

        if not rows:
            raise SystemExit(f"Kaynak aylık veri yok ({src_prefix}*, {SERIES}).")

        agg: Dict[Tuple[str, int, str], float] = {}
        for r in rows:
            cat = r["category_code"]
            q_end = quarter_end_yyyymm(int(r["yyyymm"]))
            series = r["series"]
            val = float(r["value"] or 0.0)
            agg[(cat, q_end, series)] = agg.get((cat, q_end, series), 0.0) + val

        # 4) idempotent yazım
        with conn:
            conn.execute(f"""
                DELETE FROM engine_facts_monthly
                WHERE run_id=? AND sheet_code LIKE ? AND category_code IN ({",".join("?"*len(cats))})
            """, (run_id, f"{DST_SHEET_PREFIX}%", *cats))

            to_insert = []
            for (cat, q_end, series), val in agg.items():
                sheet_code = f"{DST_SHEET_PREFIX}{cat}"
                to_insert.append((run_id, sheet_code, cat, q_end, series, round(val, 6)))

            conn.executemany("""
                INSERT INTO engine_facts_monthly
                  (run_id, sheet_code, category_code, yyyymm, series, value)
                VALUES (?,?,?,?,?,?)
            """, to_insert)

        print(f"[ok] oQ yazıldı: {len(agg)} satır (run_id={run_id}).")

        # 5) özet
        sums = fetchall(conn, """
            SELECT sheet_code, category_code, series, COUNT(*) AS n_rows,
                   ROUND(SUM(value), 2) AS sum_value
            FROM engine_facts_monthly
            WHERE run_id=? AND sheet_code LIKE ? AND category_code IN ({})
            GROUP BY 1,2,3 ORDER BY 1,2,3
        """.format(",".join("?"*len(cats))), (run_id, f"{DST_SHEET_PREFIX}%", *cats))
        print("\n[summary] oQ counts:")
        for s in sums:
            print(f"  {s['sheet_code']} | {s['category_code']} | {s['series']}: "
                  f"{s['n_rows']} rows, sum={s['sum_value']}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
