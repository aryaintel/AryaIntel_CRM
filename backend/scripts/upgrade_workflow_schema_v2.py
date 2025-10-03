# backend/scripts/upgrade_workflow_schema_v2.py
"""
Workflow schema upgrader (FX & TAX flags)

- scenarios tablosu yoksa minimal şema ile oluşturur (workflow sütunları dahil).
- scenarios tablosunda aşağıdaki sütunlar yoksa ekler:
    is_fx_ready INTEGER NOT NULL DEFAULT 0
    is_tax_ready INTEGER NOT NULL DEFAULT 0
- Var olan alanlara zarar vermez, sadece eksikleri tamamlar.
- Çalıştırma:
    cd backend
    python scripts/upgrade_workflow_schema_v2.py
"""
from pathlib import Path
import sqlite3
from typing import Set

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# ---------- Helpers ----------
def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (name,)
    )
    return cur.fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> Set[str]:
    cols: Set[str] = set()
    for row in cx.execute(f"PRAGMA table_info({table});"):
        # (cid, name, type, notnull, dflt_value, pk)
        cols.add(row[1])
    return cols

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?;", (name,)
    )
    if cur.fetchone() is None:
        cx.execute(sql)

# ---------- DDL (SQLite) ----------
DDL_SCENARIOS_MIN = """
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY,
    business_case_id INTEGER NOT NULL REFERENCES business_cases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    months INTEGER NOT NULL DEFAULT 36,
    start_date DATE NOT NULL,

    -- existing workflow flags (minimum set)
    is_boq_ready INTEGER NOT NULL DEFAULT 0,
    is_twc_ready INTEGER NOT NULL DEFAULT 0,
    is_capex_ready INTEGER NOT NULL DEFAULT 0,
    is_services_ready INTEGER NOT NULL DEFAULT 0,
    -- NEW flags if table freshly created
    is_fx_ready INTEGER NOT NULL DEFAULT 0,
    is_tax_ready INTEGER NOT NULL DEFAULT 0,

    workflow_state TEXT NOT NULL DEFAULT 'draft'
);
"""

ADD_COLS_SCENARIOS = {
    # already present in your previous script; kept here defensively
    "is_boq_ready":      "ALTER TABLE scenarios ADD COLUMN is_boq_ready INTEGER NOT NULL DEFAULT 0;",
    "is_twc_ready":      "ALTER TABLE scenarios ADD COLUMN is_twc_ready INTEGER NOT NULL DEFAULT 0;",
    "is_capex_ready":    "ALTER TABLE scenarios ADD COLUMN is_capex_ready INTEGER NOT NULL DEFAULT 0;",
    "is_services_ready": "ALTER TABLE scenarios ADD COLUMN is_services_ready INTEGER NOT NULL DEFAULT 0;",
    "workflow_state":    "ALTER TABLE scenarios ADD COLUMN workflow_state TEXT NOT NULL DEFAULT 'draft';",
    # NEW:
    "is_fx_ready":       "ALTER TABLE scenarios ADD COLUMN is_fx_ready INTEGER NOT NULL DEFAULT 0;",
    "is_tax_ready":      "ALTER TABLE scenarios ADD COLUMN is_tax_ready INTEGER NOT NULL DEFAULT 0;",
}

BACKFILL_SCENARIOS = [
    "UPDATE scenarios SET is_boq_ready      = COALESCE(is_boq_ready, 0);",
    "UPDATE scenarios SET is_twc_ready      = COALESCE(is_twc_ready, 0);",
    "UPDATE scenarios SET is_capex_ready    = COALESCE(is_capex_ready, 0);",
    "UPDATE scenarios SET is_services_ready = COALESCE(is_services_ready, 0);",
    "UPDATE scenarios SET is_fx_ready       = COALESCE(is_fx_ready, 0);",
    "UPDATE scenarios SET is_tax_ready      = COALESCE(is_tax_ready, 0);",
    "UPDATE scenarios SET workflow_state    = COALESCE(workflow_state, 'draft');",
]

def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # 1) scenarios
    if not table_exists(cx, "scenarios"):
        print("[+] Creating table: scenarios (minimal + workflow + fx/tax flags)")
        cx.executescript(DDL_SCENARIOS_MIN)
    else:
        print("[=] scenarios exists. Checking workflow columns…")
        cols = column_names(cx, "scenarios")
        for col, ddl in ADD_COLS_SCENARIOS.items():
            if col not in cols:
                print(f"[+] Adding scenarios.{col}")
                cx.execute(ddl)
            else:
                print(f"[=] scenarios.{col} already present")

    # backfill scenarios
    for sql in BACKFILL_SCENARIOS:
        cx.execute(sql)

    # basic index
    ensure_index(
        cx,
        "ix_scenarios_bc",
        "CREATE INDEX IF NOT EXISTS ix_scenarios_bc ON scenarios (business_case_id);",
    )

    cx.commit()

    # Summary
    print("\n=== scenarios columns ===")
    for row in cx.execute("PRAGMA table_info(scenarios);"):
        print(f"- {row[1]:18} | {row[2]:12} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    print("\n[✓] FX/TAX workflow flags are in place.")
    cx.close()

if __name__ == "__main__":
    main()
