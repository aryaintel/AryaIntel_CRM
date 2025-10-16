# C:/Dev/AryaIntel_CRM/backend/scripts/20251015_add_series_to_engine_facts_monthly.py
"""
Idempotent migration: add 'series' column and unique index to engine_facts_monthly.

Fix: Robust PRAGMA parsing for SQLAlchemy 2.0 Row objects (use row._mapping when available).
"""
import argparse
from typing import List, Set
from sqlalchemy import create_engine, text

DEFAULT_DB = "sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db"

def _row_get_name(r):
    """Return 'name' field from PRAGMA outputs across tuple/Row variants."""
    # PRAGMA table_info -> (cid, name, type, notnull, dflt_value, pk)
    # PRAGMA index_list -> (seq, name, unique, origin, partial)
    if hasattr(r, "_mapping"):
        m = r._mapping
        if "name" in m:
            return m["name"]
        # Fall back to index 1
        return m.get(1) if 1 in m else None
    try:
        return r[1]
    except Exception:
        try:
            return r["name"]  # some drivers allow key access
        except Exception:
            return None

def get_columns(conn, table: str) -> List[str]:
    rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
    cols: List[str] = []
    for r in rows:
        nm = _row_get_name(r)
        if nm is not None:
            cols.append(str(nm))
    return cols

def get_indexes(conn, table: str) -> Set[str]:
    rows = conn.execute(text(f"PRAGMA index_list('{table}')")).fetchall()
    names: Set[str] = set()
    for r in rows:
        nm = _row_get_name(r)
        if nm is not None:
            names.add(str(nm))
    return names

def main(db_url: str):
    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        # 1) Ensure table exists
        exists = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='engine_facts_monthly'")).fetchone()
        if not exists:
            raise SystemExit("Table 'engine_facts_monthly' not found. Run base migrations first.")

        # 2) Add 'series' column if missing
        cols = [c.lower() for c in get_columns(conn, "engine_facts_monthly")]
        if "series" not in cols:
            conn.execute(text("ALTER TABLE engine_facts_monthly ADD COLUMN series TEXT"))
            print("[ok] Added column engine_facts_monthly.series (TEXT)")
        else:
            print("[skip] Column 'series' already present")

        # 3) Optional backfill: set NULL series to 'total' when only one row exists for (run_id,sheet_code,category_code,yyyymm)
        conn.execute(text("""
            WITH singles AS (
              SELECT run_id, sheet_code, category_code, yyyymm
              FROM engine_facts_monthly
              GROUP BY run_id, sheet_code, category_code, yyyymm
              HAVING COUNT(*)=1
            )
            UPDATE engine_facts_monthly AS ef
               SET series = COALESCE(series, 'total')
             WHERE ef.series IS NULL
               AND EXISTS (
                 SELECT 1 FROM singles s
                 WHERE s.run_id=ef.run_id AND s.sheet_code=ef.sheet_code
                   AND s.category_code=ef.category_code AND s.yyyymm=ef.yyyymm
               )
        """))
        print("[ok] Backfilled NULL 'series' to 'total' where safe")

        # 4) Ensure unique index on the composite key (includes 'series')
        idx_name = "ux_engine_facts_run_sheet_cat_ym_series"
        indexes = get_indexes(conn, "engine_facts_monthly")
        if idx_name not in indexes:
            conn.execute(text(f"""
                CREATE UNIQUE INDEX {idx_name}
                ON engine_facts_monthly (run_id, sheet_code, category_code, yyyymm, series)
            """))
            print(f"[ok] Created UNIQUE index {idx_name}")
        else:
            print(f"[skip] UNIQUE index {idx_name} already present")

    print("[done] Migration complete. Safe to re-run.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB, help="SQLAlchemy DB URL (default: %(default)s)")
    args = ap.parse_args()
    main(args.db)
