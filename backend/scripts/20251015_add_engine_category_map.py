#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251015_add_engine_category_map.py
"""
Create engine_category_map table to map products/families/services to engine categories (AN, EM, IE, Services).
Idempotent: safe to re-run.

Usage:
  python backend/scripts/20251015_add_engine_category_map.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db --seed
"""

import argparse
from datetime import datetime, timezone
from sqlalchemy import create_engine, text

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS engine_category_map (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL CHECK(scope IN ('product_family','product','service')),
  ref_id INTEGER NOT NULL,
  category_code TEXT NOT NULL CHECK(category_code IN ('AN','EM','IE','Services')),
  is_active INTEGER NOT NULL DEFAULT 1,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""
UNIQ_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS ux_ecm_scope_ref ON engine_category_map(scope, ref_id);"

def now_iso():
  return datetime.now(timezone.utc).isoformat()

def seed_defaults(conn):
  # Seed by product_families name heuristics if available
  try:
    fam_rows = conn.execute(text("SELECT id, name FROM product_families")).fetchall()
  except Exception:
    print("[seed] skipped: product_families table not found")
    return 0
  if not fam_rows:
    print("[seed] skipped: product_families empty")
    return 0

  inserted = 0
  for fid, name in fam_rows:
    lname = (name or "").lower()
    # Skip if a mapping already exists
    exists = conn.execute(text(
      "SELECT 1 FROM engine_category_map WHERE scope='product_family' AND ref_id=:rid LIMIT 1"
    ), {"rid": fid}).fetchone()
    if exists:
      continue

    cat = None
    if "bulk emulsion" in lname or "emulsion" in lname:
      cat = "EM"
    elif "anfo" in lname or "ammonium nitrate" in lname or lname.startswith("an ") or lname == "an" or "ammonium" in lname:
      cat = "AN"
    elif "detonat" in lname or "nonel" in lname or "cord" in lname or "booster" in lname or "ignit" in lname or "electronic detona" in lname:
      cat = "IE"

    if cat:
      conn.execute(text("""
        INSERT INTO engine_category_map(scope, ref_id, category_code, is_active, note, created_at, updated_at)
        VALUES('product_family', :rid, :cat, 1, :note, :ts, :ts)
      """), {"rid": fid, "cat": cat, "note": f"seeded by name='{name}'", "ts": now_iso()})
      inserted += 1

  print(f"[seed] inserted default family mappings: {inserted}")
  return inserted

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", required=True, help="SQLAlchemy DB URL")
  ap.add_argument("--seed", action="store_true", help="Seed default mappings by family names")
  args = ap.parse_args()

  engine = create_engine(args.db)
  with engine.begin() as conn:
    conn.execute(text(CREATE_SQL))
    conn.execute(text(UNIQ_SQL))
    print("[ok] engine_category_map ensured.")

    if args.seed:
      seed_defaults(conn)

if __name__ == "__main__":
  main()
