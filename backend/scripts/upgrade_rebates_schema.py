"""
Rebates şemasını oluşturur/günceller (SQLite/app.db).
- Tablolar yoksa oluşturur.
- Varsa eksik kolonları ADD COLUMN ile ekler (idempotent).
- İndeksler ve CHECK'ler uyumlu tutulur.
Çalıştırma:
    cd backend
    python scripts/upgrade_rebates_schema.py
"""
from __future__ import annotations
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def table_exists(cx, name: str) -> bool:
    return cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone() is not None

def colset(cx, table: str) -> set[str]:
    return {r[1] for r in cx.execute(f"PRAGMA table_info({table});").fetchall()}

def ensure_rebates(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "scenario_rebates"):
        cx.executescript("""
        CREATE TABLE IF NOT EXISTS scenario_rebates (
          id               INTEGER PRIMARY KEY AUTOINCREMENT,
          scenario_id      INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
          name             TEXT NOT NULL,
          scope            TEXT NOT NULL DEFAULT 'all',
          kind             TEXT NOT NULL DEFAULT 'percent',
          basis            TEXT NOT NULL DEFAULT 'revenue',
          product_id       INTEGER REFERENCES products(id) ON DELETE SET NULL,
          valid_from_year  INTEGER,
          valid_from_month INTEGER,
          valid_to_year    INTEGER,
          valid_to_month   INTEGER,
          accrual_method   TEXT NOT NULL DEFAULT 'monthly',
          pay_month_lag    INTEGER DEFAULT 0,
          is_active        INTEGER NOT NULL DEFAULT 1,
          notes            TEXT,
          created_at       TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
          CHECK (scope IN ('all','boq','services','product')),
          CHECK (kind  IN ('percent','tier_percent','lump_sum')),
          CHECK (basis IN ('revenue','volume')),
          CHECK ((valid_from_month IS NULL) OR (valid_from_month BETWEEN 1 AND 12)),
          CHECK ((valid_to_month   IS NULL) OR (valid_to_month   BETWEEN 1 AND 12)),
          CHECK (accrual_method IN ('monthly','quarterly','annual','on_invoice'))
        );
        CREATE INDEX IF NOT EXISTS ix_rebates_scenario ON scenario_rebates(scenario_id);
        CREATE INDEX IF NOT EXISTS ix_rebates_active   ON scenario_rebates(is_active);
        """)
    else:
        # eksik kolonları ekle
        have = colset(cx, "scenario_rebates")
        alters = {
            "product_id":       "ALTER TABLE scenario_rebates ADD COLUMN product_id INTEGER REFERENCES products(id) ON DELETE SET NULL;",
            "valid_from_year":  "ALTER TABLE scenario_rebates ADD COLUMN valid_from_year INTEGER;",
            "valid_from_month": "ALTER TABLE scenario_rebates ADD COLUMN valid_from_month INTEGER;",
            "valid_to_year":    "ALTER TABLE scenario_rebates ADD COLUMN valid_to_year INTEGER;",
            "valid_to_month":   "ALTER TABLE scenario_rebates ADD COLUMN valid_to_month INTEGER;",
            "accrual_method":   "ALTER TABLE scenario_rebates ADD COLUMN accrual_method TEXT NOT NULL DEFAULT 'monthly';",
            "pay_month_lag":    "ALTER TABLE scenario_rebates ADD COLUMN pay_month_lag INTEGER DEFAULT 0;",
            "is_active":        "ALTER TABLE scenario_rebates ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
            "notes":            "ALTER TABLE scenario_rebates ADD COLUMN notes TEXT;",
            "created_at":       "ALTER TABLE scenario_rebates ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'));",
            "updated_at":       "ALTER TABLE scenario_rebates ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));",
        }
        for col, sql in alters.items():
            if col not in have:
                cx.execute(sql)
        cx.execute("CREATE INDEX IF NOT EXISTS ix_rebates_scenario ON scenario_rebates(scenario_id);")
        cx.execute("CREATE INDEX IF NOT EXISTS ix_rebates_active   ON scenario_rebates(is_active);")

def ensure_tiers(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "scenario_rebate_tiers"):
        cx.executescript("""
        CREATE TABLE IF NOT EXISTS scenario_rebate_tiers (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          rebate_id   INTEGER NOT NULL REFERENCES scenario_rebates(id) ON DELETE CASCADE,
          min_value   NUMERIC NOT NULL DEFAULT 0,
          max_value   NUMERIC,
          percent     NUMERIC,
          amount      NUMERIC,
          description TEXT,
          sort_order  INTEGER NOT NULL DEFAULT 0,
          created_at  TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
          CHECK ((percent IS NOT NULL) OR (amount IS NOT NULL))
        );
        CREATE INDEX IF NOT EXISTS ix_tiers_rebate ON scenario_rebate_tiers(rebate_id, sort_order);
        CREATE INDEX IF NOT EXISTS ix_tiers_range  ON scenario_rebate_tiers(min_value, max_value);
        """)
    else:
        have = colset(cx, "scenario_rebate_tiers")
        for col, sql in {
            "created_at": "ALTER TABLE scenario_rebate_tiers ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'));",
            "updated_at": "ALTER TABLE scenario_rebate_tiers ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));",
        }.items():
            if col not in have:
                cx.execute(sql)
        cx.execute("CREATE INDEX IF NOT EXISTS ix_tiers_rebate ON scenario_rebate_tiers(rebate_id, sort_order);")
        cx.execute("CREATE INDEX IF NOT EXISTS ix_tiers_range  ON scenario_rebate_tiers(min_value, max_value);")

def ensure_lumps(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "scenario_rebate_lumps"):
        cx.executescript("""
        CREATE TABLE IF NOT EXISTS scenario_rebate_lumps (
          id        INTEGER PRIMARY KEY AUTOINCREMENT,
          rebate_id INTEGER NOT NULL REFERENCES scenario_rebates(id) ON DELETE CASCADE,
          year      INTEGER NOT NULL,
          month     INTEGER NOT NULL,
          amount    NUMERIC NOT NULL,
          currency  TEXT NOT NULL DEFAULT 'USD',
          note      TEXT,
          created_at  TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
          CHECK (month BETWEEN 1 AND 12)
        );
        CREATE INDEX IF NOT EXISTS ix_lumps_rebate  ON scenario_rebate_lumps(rebate_id);
        CREATE INDEX IF NOT EXISTS ix_lumps_period  ON scenario_rebate_lumps(year, month);
        """)
    else:
        have = colset(cx, "scenario_rebate_lumps")
        for col, sql in {
            "note":       "ALTER TABLE scenario_rebate_lumps ADD COLUMN note TEXT;",
            "created_at": "ALTER TABLE scenario_rebate_lumps ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'));",
            "updated_at": "ALTER TABLE scenario_rebate_lumps ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));",
        }.items():
            if col not in have:
                cx.execute(sql)
        cx.execute("CREATE INDEX IF NOT EXISTS ix_lumps_rebate  ON scenario_rebate_lumps(rebate_id);")
        cx.execute("CREATE INDEX IF NOT EXISTS ix_lumps_period  ON scenario_rebate_lumps(year, month);")

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")
    try:
        ensure_rebates(cx)
        ensure_tiers(cx)
        ensure_lumps(cx)
        cx.commit()
        # kısa özet
        cnt = cx.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'scenario_rebate%';").fetchone()[0]
        print(f"[✓] rebates schema ready (tables: {cnt})")
    finally:
        cx.close()

if __name__ == "__main__":
    main()
