# C:/Dev/AryaIntel_CRM/backend/app/migrations/20251010_add_opex_labor_and_detail.py
"""
Add flexible OPEX detail structure to capture Excel parity, including:
- 'type' (e.g., 'labor', 'material', 'service', 'overhead', ...)
- 'detail' (e.g., 'manager', 'technician', 'analyst', ...)
- Normalized per-line breakdown with rates/quantities
- Arbitrary extra Excel columns via a KV store

Tables (idempotent):
1) scenario_opex                    -- header (already exists in prior migration)
2) scenario_opex_month              -- monthly amounts (already exists)
3) scenario_opex_alloc (+basis)     -- allocations (already exists with basis)

NEW:
4) scenario_opex_line               -- normalized line items per OPEX (labor/material/service etc.)
5) scenario_opex_line_kv            -- arbitrary column capture for Excel parity

Notes:
- Keep existing behavior intact; this only extends the model.
- Currency at line level is allowed; app can fallback to header currency if NULL.
- Basis-based allocation is computed at aggregate OPEX (sum of lines) unless app wishes to allocate per line.
- Safe to re-run.
"""

import sqlite3
from pathlib import Path

DB_PATH = r"C:/Dev/AryaIntel_CRM/app.db"

# --- helper DDL to ensure base tables from earlier steps exist (safe no-ops) ---
DDL_BASE = [
    # scenario_opex (header)
    """
    CREATE TABLE IF NOT EXISTS scenario_opex (
        id              INTEGER PRIMARY KEY,
        scenario_id     INTEGER NOT NULL,
        name            TEXT NOT NULL,
        category        TEXT,
        currency        TEXT,
        allocation_mode TEXT NOT NULL DEFAULT 'none',    -- none|fixed|percent|driver
        periodicity     TEXT NOT NULL DEFAULT 'monthly', -- monthly|annual
        start_year      INTEGER,
        start_month     INTEGER,                          -- 1..12
        end_year        INTEGER,
        end_month       INTEGER,
        notes           TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_scenario_opex_scenario ON scenario_opex (scenario_id);",

    # scenario_opex_month (monthly rollup)
    """
    CREATE TABLE IF NOT EXISTS scenario_opex_month (
        id       INTEGER PRIMARY KEY,
        opex_id  INTEGER NOT NULL,
        year     INTEGER NOT NULL,
        month    INTEGER NOT NULL, -- 1..12
        amount   NUMERIC NOT NULL DEFAULT 0,
        UNIQUE (opex_id, year, month)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_opex_month_opex ON scenario_opex_month (opex_id);",

    # scenario_opex_alloc (allocation with basis)
    """
    CREATE TABLE IF NOT EXISTS scenario_opex_alloc (
        id         INTEGER PRIMARY KEY,
        opex_id    INTEGER NOT NULL,
        service_id INTEGER NOT NULL,
        weight_pct NUMERIC NOT NULL,
        UNIQUE (opex_id, service_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_opex_alloc_opex ON scenario_opex_alloc (opex_id);",
    "CREATE INDEX IF NOT EXISTS idx_opex_alloc_service ON scenario_opex_alloc (service_id);",
]

# --- new detail tables ---
DDL_NEW = [
    # scenario_opex_line: normalized line-level capture
    """
    CREATE TABLE IF NOT EXISTS scenario_opex_line (
        id              INTEGER PRIMARY KEY,
        opex_id         INTEGER NOT NULL,      -- FK to scenario_opex.id
        line_no         INTEGER,               -- Excel row order (optional)
        type            TEXT,                  -- 'labor' | 'material' | 'service' | 'overhead' | ...
        detail          TEXT,                  -- e.g., 'manager', 'technician', 'analyst', vendor role, etc.
        vendor          TEXT,                  -- optional vendor/supplier
        unit            TEXT,                  -- 'hour', 'day', 'each', ...
        qty_per_month   NUMERIC,               -- e.g., headcount or hours per month
        unit_rate       NUMERIC,               -- rate per unit (e.g., hourly rate)
        currency        TEXT,                  -- override currency; null → use header currency
        fixed_monthly   NUMERIC,               -- direct monthly amount if provided in Excel
        valid_from_year INTEGER,
        valid_from_month INTEGER,              -- 1..12
        valid_to_year   INTEGER,
        valid_to_month  INTEGER,               -- 1..12
        notes           TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_opex_line_opex ON scenario_opex_line (opex_id);",
    "CREATE INDEX IF NOT EXISTS idx_opex_line_type ON scenario_opex_line (type);",
    "CREATE INDEX IF NOT EXISTS idx_opex_line_detail ON scenario_opex_line (detail);",

    # scenario_opex_line_kv: arbitrary Excel columns as key/value (stringified)
    """
    CREATE TABLE IF NOT EXISTS scenario_opex_line_kv (
        id        INTEGER PRIMARY KEY,
        line_id   INTEGER NOT NULL,           -- FK to scenario_opex_line.id
        key       TEXT NOT NULL,              -- normalized column name from Excel
        value     TEXT,                       -- raw/stringified value
        UNIQUE (line_id, key)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_opex_line_kv_line ON scenario_opex_line_kv (line_id);",
    "CREATE INDEX IF NOT EXISTS idx_opex_line_kv_key ON scenario_opex_line_kv (key);",
]

def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    for row in cur.fetchall():
        if row[1].lower() == column.lower():
            return True
    return False

def ensure_alloc_basis(conn: sqlite3.Connection):
    # add 'basis' to scenario_opex_alloc if missing (percent|revenue|volume|gross_margin)
    if not column_exists(conn, "scenario_opex_alloc", "basis"):
        conn.execute("ALTER TABLE scenario_opex_alloc ADD COLUMN basis TEXT;")
        conn.execute("UPDATE scenario_opex_alloc SET basis = COALESCE(basis, 'percent');")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_opex_alloc_basis ON scenario_opex_alloc (basis);")

def run():
    db = Path(DB_PATH)
    if not db.exists():
        raise SystemExit(f"DB not found at {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()

        # Ensure base tables (safe)
        for stmt in DDL_BASE:
            cur.execute(stmt)

        # Ensure basis column on alloc
        ensure_alloc_basis(conn)

        # Create new detail tables
        for stmt in DDL_NEW:
            cur.execute(stmt)

        conn.commit()

if __name__ == "__main__":
    run()
