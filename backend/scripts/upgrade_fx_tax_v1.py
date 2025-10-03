# backend/scripts/upgrade_fx_tax_v1.py
"""
FX (scenario_fx_rates) ve Tax (scenario_tax_rules) tablolarını oluşturur veya eksik
sütunları ekler. SQLite (app.db) için tasarlanmıştır.

Çalıştırma:
    cd backend
    python scripts/upgrade_fx_tax_v1.py
"""
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# -------------------------------------------------------------------
# DDL: Tablolar (yoksa tam şema ile oluştur)
# -------------------------------------------------------------------
DDL_FX = """
CREATE TABLE IF NOT EXISTS scenario_fx_rates (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    currency TEXT NOT NULL,                                  -- ISO-4217, örn: USD
    rate_to_base NUMERIC(18,6) NOT NULL DEFAULT 1,           -- base para birimine oran
    start_year INTEGER NOT NULL,
    start_month INTEGER NOT NULL,
    end_year INTEGER NULL,
    end_month INTEGER NULL,
    source TEXT NULL,                                        -- manual | cbrt | ecb | oanda ...
    notes  TEXT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT ck_fx_start_month CHECK (start_month >= 1 AND start_month <= 12),
    CONSTRAINT ck_fx_end_month   CHECK (end_month IS NULL OR (end_month >= 1 AND end_month <= 12))
);
"""

DDL_TAX = """
CREATE TABLE IF NOT EXISTS scenario_tax_rules (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                                      -- KDV, Stopaj, Kurumlar
    tax_type TEXT NOT NULL DEFAULT 'custom',                 -- 'vat'|'withholding'|'corp'|'custom'
    applies_to TEXT NOT NULL DEFAULT 'all',                  -- 'revenue'|'services'|'capex'|'profit'|'all'
    rate_pct NUMERIC(8,4) NOT NULL DEFAULT 0,                -- %
    start_year INTEGER NOT NULL,
    start_month INTEGER NOT NULL,
    end_year INTEGER NULL,
    end_month INTEGER NULL,
    is_inclusive INTEGER NOT NULL DEFAULT 0,                 -- fiyatlara dahil mi
    notes TEXT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT ck_tax_type CHECK (tax_type IN ('vat','withholding','corp','custom')),
    CONSTRAINT ck_tax_applies_to CHECK (applies_to IN ('revenue','services','capex','profit','all')),
    CONSTRAINT ck_tax_start_month CHECK (start_month >= 1 AND start_month <= 12),
    CONSTRAINT ck_tax_end_month CHECK (end_month IS NULL OR (end_month >= 1 AND end_month <= 12))
);
"""

# -------------------------------------------------------------------
# ALTER: Eksik sütunlar için add-column komutları
# (SQLite'ta AFTER/BEFORE yok; yalnızca ADD COLUMN)
# -------------------------------------------------------------------
FX_ADD_COLS = {
    "currency":        "ALTER TABLE scenario_fx_rates ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';",
    "rate_to_base":    "ALTER TABLE scenario_fx_rates ADD COLUMN rate_to_base NUMERIC(18,6) NOT NULL DEFAULT 1;",
    "start_year":      "ALTER TABLE scenario_fx_rates ADD COLUMN start_year INTEGER NOT NULL DEFAULT 2025;",
    "start_month":     "ALTER TABLE scenario_fx_rates ADD COLUMN start_month INTEGER NOT NULL DEFAULT 1;",
    "end_year":        "ALTER TABLE scenario_fx_rates ADD COLUMN end_year INTEGER NULL;",
    "end_month":       "ALTER TABLE scenario_fx_rates ADD COLUMN end_month INTEGER NULL;",
    "source":          "ALTER TABLE scenario_fx_rates ADD COLUMN source TEXT NULL;",
    "notes":           "ALTER TABLE scenario_fx_rates ADD COLUMN notes TEXT NULL;",
    "is_active":       "ALTER TABLE scenario_fx_rates ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
}

TAX_ADD_COLS = {
    "name":            "ALTER TABLE scenario_tax_rules ADD COLUMN name TEXT NOT NULL DEFAULT 'Tax';",
    "tax_type":        "ALTER TABLE scenario_tax_rules ADD COLUMN tax_type TEXT NOT NULL DEFAULT 'custom';",
    "applies_to":      "ALTER TABLE scenario_tax_rules ADD COLUMN applies_to TEXT NOT NULL DEFAULT 'all';",
    "rate_pct":        "ALTER TABLE scenario_tax_rules ADD COLUMN rate_pct NUMERIC(8,4) NOT NULL DEFAULT 0;",
    "start_year":      "ALTER TABLE scenario_tax_rules ADD COLUMN start_year INTEGER NOT NULL DEFAULT 2025;",
    "start_month":     "ALTER TABLE scenario_tax_rules ADD COLUMN start_month INTEGER NOT NULL DEFAULT 1;",
    "end_year":        "ALTER TABLE scenario_tax_rules ADD COLUMN end_year INTEGER NULL;",
    "end_month":       "ALTER TABLE scenario_tax_rules ADD COLUMN end_month INTEGER NULL;",
    "is_inclusive":    "ALTER TABLE scenario_tax_rules ADD COLUMN is_inclusive INTEGER NOT NULL DEFAULT 0;",
    "notes":           "ALTER TABLE scenario_tax_rules ADD COLUMN notes TEXT NULL;",
    "is_active":       "ALTER TABLE scenario_tax_rules ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
}

# Backfill (NULL değerleri default'a çek)
FX_BACKFILL = [
    "UPDATE scenario_fx_rates SET rate_to_base = COALESCE(rate_to_base, 1);",
    "UPDATE scenario_fx_rates SET is_active   = COALESCE(is_active, 1);",
]
TAX_BACKFILL = [
    "UPDATE scenario_tax_rules SET tax_type     = COALESCE(tax_type, 'custom');",
    "UPDATE scenario_tax_rules SET applies_to   = COALESCE(applies_to, 'all');",
    "UPDATE scenario_tax_rules SET rate_pct     = COALESCE(rate_pct, 0);",
    "UPDATE scenario_tax_rules SET is_inclusive = COALESCE(is_inclusive, 0);",
    "UPDATE scenario_tax_rules SET is_active    = COALESCE(is_active, 1);",
]

# -------------------------------------------------------------------
# Yardımcılar
# -------------------------------------------------------------------
def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (name,)
    )
    return cur.fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> set[str]:
    cols = set()
    for row in cx.execute(f"PRAGMA table_info({table});"):
        # row = (cid, name, type, notnull, dflt_value, pk)
        cols.add(row[1])
    return cols

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name = ?;", (name,)
    )
    if cur.fetchone() is None:
        cx.execute(sql)

def ensure_unique_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    # SQLite'ta unique index de 'index' tipidir; aynı kontrol yeterli
    ensure_index(cx, name, sql)

# -------------------------------------------------------------------
# Ana akış
# -------------------------------------------------------------------
def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # ---- FX ----
    if not table_exists(cx, "scenario_fx_rates"):
        print("[+] Creating table scenario_fx_rates …")
        cx.executescript(DDL_FX)
    else:
        print("[=] scenario_fx_rates exists. Checking columns…")
        cols = column_names(cx, "scenario_fx_rates")
        for col, add_sql in FX_ADD_COLS.items():
            if col not in cols:
                print(f"[+] Adding column to scenario_fx_rates: {col}")
                cx.execute(add_sql)
            else:
                print(f"[=] Column already present: {col}")

    # Indices for FX
    ensure_index(
        cx,
        "ix_fx_scenario",
        "CREATE INDEX IF NOT EXISTS ix_fx_scenario ON scenario_fx_rates (scenario_id);",
    )
    ensure_index(
        cx,
        "ix_fx_currency",
        "CREATE INDEX IF NOT EXISTS ix_fx_currency ON scenario_fx_rates (currency);",
    )
    ensure_unique_index(
        cx,
        "uix_fx_period_unique",
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_fx_period_unique "
        "ON scenario_fx_rates (scenario_id, currency, start_year, start_month);",
    )

    # Backfill FX
    for sql in FX_BACKFILL:
        cx.execute(sql)

    # ---- TAX ----
    if not table_exists(cx, "scenario_tax_rules"):
        print("[+] Creating table scenario_tax_rules …")
        cx.executescript(DDL_TAX)
    else:
        print("[=] scenario_tax_rules exists. Checking columns…")
        cols = column_names(cx, "scenario_tax_rules")
        for col, add_sql in TAX_ADD_COLS.items():
            if col not in cols:
                print(f"[+] Adding column to scenario_tax_rules: {col}")
                cx.execute(add_sql)
            else:
                print(f"[=] Column already present: {col}")

    # Indices for TAX
    ensure_index(
        cx,
        "ix_tax_scenario",
        "CREATE INDEX IF NOT EXISTS ix_tax_scenario ON scenario_tax_rules (scenario_id);",
    )
    ensure_index(
        cx,
        "ix_tax_active",
        "CREATE INDEX IF NOT EXISTS ix_tax_active ON scenario_tax_rules (is_active);",
    )
    ensure_index(
        cx,
        "ix_tax_period",
        "CREATE INDEX IF NOT EXISTS ix_tax_period ON scenario_tax_rules (start_year, start_month);",
    )

    # Backfill TAX
    for sql in TAX_BACKFILL:
        cx.execute(sql)

    cx.commit()

    # ---- Özet ----
    print("\n=== scenario_fx_rates columns ===")
    for row in cx.execute("PRAGMA table_info(scenario_fx_rates);"):
        print(f"- {row[1]:18} | {row[2]:15} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    fx_count = cx.execute("SELECT COUNT(*) FROM scenario_fx_rates;").fetchone()[0]
    print(f"[✓] scenario_fx_rates ready. Row count: {fx_count}")

    print("\n=== scenario_tax_rules columns ===")
    for row in cx.execute("PRAGMA table_info(scenario_tax_rules);"):
        print(f"- {row[1]:18} | {row[2]:15} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    tax_count = cx.execute("SELECT COUNT(*) FROM scenario_tax_rules;").fetchone()[0]
    print(f"[✓] scenario_tax_rules ready. Row count: {tax_count}")

    cx.close()

if __name__ == "__main__":
    main()
