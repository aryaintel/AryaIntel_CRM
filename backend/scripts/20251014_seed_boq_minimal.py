#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251014_seed_boq_minimal.py
"""
Seed minimal BOQ rows for AN/EM/IE so Run Engine can produce non-zero series (idempotent).

Fix: populate NOT NULL columns `item_name` and `unit` per schema.
- item_name: "Seed {SECTION} item"
- unit: "unit"
- frequency: "monthly" (valid vs. ck_boq_frequency)
- quantity: 1, unit_price: 1000
- start_year/start_month: scenario.start_date (Y/M)
- months/row_months: scenario.months
- is_active: 1

If a column is absent in current DB, it's skipped safely.
"""

import argparse
from sqlalchemy import create_engine, text

SECTIONS = ["AN", "EM", "IE"]

def log(m): print(m, flush=True)

def table_cols(conn, table):
    return {c[1]: {"type": c[2], "notnull": c[3], "dflt": c[4]} for c in conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()}

def has_active_boq(conn, sid, section):
    row = conn.execute(text("""
        SELECT 1
        FROM scenario_boq_items
        WHERE scenario_id=:sid AND section=:sec AND COALESCE(is_active,1)=1
        LIMIT 1
    """), {"sid": sid, "sec": section}).fetchone()
    return bool(row)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLAlchemy URL")
    ap.add_argument("--scenario", type=int, default=None)
    args = ap.parse_args()

    eng = create_engine(args.db)
    with eng.begin() as conn:
        scs = conn.execute(text("SELECT id, start_date, months FROM scenarios ORDER BY id")).mappings().all()
        if not scs:
            log("[warn] no scenarios found"); return
        tbl = table_cols(conn, "scenario_boq_items")

        for sc in scs:
            sid = int(sc["id"])
            if args.scenario and sid != args.scenario:
                continue

            y, m, _ = [int(x) for x in str(sc["start_date"]).split("-")]

            for sec in SECTIONS:
                if has_active_boq(conn, sid, sec):
                    log(f"[skip] scenario {sid} section {sec}: already has active row(s)"); continue

                parts, vals = ["scenario_id", "section"], {"scenario_id": sid, "section": sec}

                def add(col, val):
                    if col in tbl:
                        parts.append(col); vals[col] = val

                # Required NOT NULLs
                add("item_name", f"Seed {sec} item")
                add("unit", "unit")

                # Minimal financials
                add("quantity", 1)
                add("unit_price", 1000.0)

                # Frequency & timing
                add("frequency", "monthly")
                add("start_year", y)
                add("start_month", m)

                # Month span (prefer 'months', else 'row_months' if exists)
                if "months" in tbl:
                    add("months", int(sc["months"]))
                elif "row_months" in tbl:
                    add("row_months", int(sc["months"]))

                # Active flag
                add("is_active", 1)

                # Build & execute INSERT
                sql = f"INSERT INTO scenario_boq_items ({', '.join(parts)}) VALUES ({', '.join(':'+p for p in parts)})"
                conn.execute(text(sql), vals)
                log(f"[ok] scenario {sid}: inserted minimal BOQ for {sec}")

        log("[done] minimal BOQ seeded where missing.")

if __name__ == "__main__":
    main()
