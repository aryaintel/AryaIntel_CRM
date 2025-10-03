# backend/scripts/upgrade_workflow_schema.py
"""
Workflow & BOQ şemasını güvenle yükseltir.

- scenarios tablosu yoksa minimum şemayla oluşturur
  (models ile uyumlu: business_case_id, name, months, start_date).
- scenarios tablosunda workflow kolonları yoksa ekler:
    is_boq_ready, is_twc_ready, is_capex_ready, **is_services_ready** (BOOLEAN/INTEGER DEFAULT 0)
    workflow_state TEXT DEFAULT 'draft'
- scenario_boq_items tablosu yoksa TAM şemayla oluşturur
  (SQLite: ENUM yerine CHECK'li TEXT).
- Varsa eksik sütunları ADD COLUMN ile ekler.
- Gerekli index’leri kurar.
- Varsayılan değerleri backfill eder.

Çalıştırma:
    cd backend
    python scripts/upgrade_workflow_schema.py
"""
from pathlib import Path
import sqlite3
from typing import Set

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# --- Helpers ---------------------------------------------------------------

def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (name,)
    )
    return cur.fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> Set[str]:
    cols: Set[str] = set()
    for row in cx.execute(f"PRAGMA table_info({table});"):
        # row = (cid, name, type, notnull, dflt_value, pk)
        cols.add(row[1])
    return cols

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?;", (name,)
    )
    if cur.fetchone() is None:
        cx.execute(sql)

# --- DDL (SQLite uyumlu) ---------------------------------------------------

DDL_SCENARIOS_MIN = """
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY,
    business_case_id INTEGER NOT NULL REFERENCES business_cases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    months INTEGER NOT NULL DEFAULT 36,
    start_date DATE NOT NULL,

    -- workflow alanları (ilk yaratılışta gelsin)
    is_boq_ready INTEGER NOT NULL DEFAULT 0,
    is_twc_ready INTEGER NOT NULL DEFAULT 0,
    is_capex_ready INTEGER NOT NULL DEFAULT 0,
    is_services_ready INTEGER NOT NULL DEFAULT 0,
    workflow_state TEXT NOT NULL DEFAULT 'draft'
);
"""

# SQLite'ta ENUM yerine CHECK constraint kullanıyoruz
DDL_SCENARIO_BOQ = """
CREATE TABLE IF NOT EXISTS scenario_boq_items (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,

    section TEXT NULL,
    item_name TEXT NOT NULL,
    unit TEXT NOT NULL,

    quantity NUMERIC(18,4) NOT NULL DEFAULT 0,
    unit_price NUMERIC(18,4) NOT NULL DEFAULT 0,
    unit_cogs NUMERIC(18,4) NULL,

    frequency TEXT NOT NULL DEFAULT 'once',    -- 'once'|'monthly'|'per_shipment'|'per_tonne'
    start_year INTEGER NULL,
    start_month INTEGER NULL,
    months INTEGER NULL,

    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NULL,

    category TEXT NULL
        CHECK (category IN ('bulk_with_freight','bulk_ex_freight','freight'))
);
"""

ADD_COLS_SCENARIOS = {
    "is_boq_ready":       "ALTER TABLE scenarios ADD COLUMN is_boq_ready INTEGER NOT NULL DEFAULT 0;",
    "is_twc_ready":       "ALTER TABLE scenarios ADD COLUMN is_twc_ready INTEGER NOT NULL DEFAULT 0;",
    "is_capex_ready":     "ALTER TABLE scenarios ADD COLUMN is_capex_ready INTEGER NOT NULL DEFAULT 0;",
    "is_services_ready":  "ALTER TABLE scenarios ADD COLUMN is_services_ready INTEGER NOT NULL DEFAULT 0;",
    "workflow_state":     "ALTER TABLE scenarios ADD COLUMN workflow_state TEXT NOT NULL DEFAULT 'draft';",
}

ADD_COLS_BOQ = {
    "section":          "ALTER TABLE scenario_boq_items ADD COLUMN section TEXT NULL;",
    "item_name":        "ALTER TABLE scenario_boq_items ADD COLUMN item_name TEXT NOT NULL;",
    "unit":             "ALTER TABLE scenario_boq_items ADD COLUMN unit TEXT NOT NULL;",
    "quantity":         "ALTER TABLE scenario_boq_items ADD COLUMN quantity NUMERIC(18,4) NOT NULL DEFAULT 0;",
    "unit_price":       "ALTER TABLE scenario_boq_items ADD COLUMN unit_price NUMERIC(18,4) NOT NULL DEFAULT 0;",
    "unit_cogs":        "ALTER TABLE scenario_boq_items ADD COLUMN unit_cogs NUMERIC(18,4) NULL;",
    "frequency":        "ALTER TABLE scenario_boq_items ADD COLUMN frequency TEXT NOT NULL DEFAULT 'once';",
    "start_year":       "ALTER TABLE scenario_boq_items ADD COLUMN start_year INTEGER NULL;",
    "start_month":      "ALTER TABLE scenario_boq_items ADD COLUMN start_month INTEGER NULL;",
    "months":           "ALTER TABLE scenario_boq_items ADD COLUMN months INTEGER NULL;",
    "is_active":        "ALTER TABLE scenario_boq_items ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
    "notes":            "ALTER TABLE scenario_boq_items ADD COLUMN notes TEXT NULL;",
    "category":         "ALTER TABLE scenario_boq_items ADD COLUMN category TEXT NULL;",
}

BACKFILL_SCENARIOS = [
    "UPDATE scenarios SET is_boq_ready      = COALESCE(is_boq_ready, 0);",
    "UPDATE scenarios SET is_twc_ready      = COALESCE(is_twc_ready, 0);",
    "UPDATE scenarios SET is_capex_ready    = COALESCE(is_capex_ready, 0);",
    "UPDATE scenarios SET is_services_ready = COALESCE(is_services_ready, 0);",
    "UPDATE scenarios SET workflow_state    = COALESCE(workflow_state, 'draft');",
]

BACKFILL_BOQ = [
    "UPDATE scenario_boq_items SET quantity   = COALESCE(quantity,   0);",
    "UPDATE scenario_boq_items SET unit_price = COALESCE(unit_price, 0);",
    "UPDATE scenario_boq_items SET is_active  = COALESCE(is_active,  1);",
]

# --- Main -------------------------------------------------------------------

def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # 1) scenarios
    if not table_exists(cx, "scenarios"):
        print("[+] Creating table: scenarios (minimal + workflow)")
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

    ensure_index(
        cx,
        "ix_scenarios_bc",
        "CREATE INDEX IF NOT EXISTS ix_scenarios_bc ON scenarios (business_case_id);",
    )

    # 2) scenario_boq_items
    if not table_exists(cx, "scenario_boq_items"):
        print("[+] Creating table: scenario_boq_items")
        cx.executescript(DDL_SCENARIO_BOQ)
    else:
        print("[=] scenario_boq_items exists. Checking columns…")
        cols = column_names(cx, "scenario_boq_items")
        for col, ddl in ADD_COLS_BOQ.items():
            if col not in cols:
                print(f"[+] Adding scenario_boq_items.{col}")
                cx.execute(ddl)
            else:
                print(f"[=] scenario_boq_items.{col} already present")

    # backfill BOQ
    for sql in BACKFILL_BOQ:
        cx.execute(sql)

    ensure_index(
        cx,
        "ix_boq_scenario",
        "CREATE INDEX IF NOT EXISTS ix_boq_scenario ON scenario_boq_items (scenario_id);",
    )

    cx.commit()

    # Summary
    print("\n=== scenarios columns ===")
    for row in cx.execute("PRAGMA table_info(scenarios);"):
        print(f"- {row[1]:18} | {row[2]:12} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    print("\n=== scenario_boq_items columns ===")
    for row in cx.execute("PRAGMA table_info(scenario_boq_items);"):
        print(f"- {row[1]:18} | {row[2]:12} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    print("\n[✓] Workflow & BOQ schema ready (services flag included).")
    cx.close()

if __name__ == "__main__":
    main()
