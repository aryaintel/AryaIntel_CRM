# backend/scripts/ensure_capex_table.py
"""
scenario_capex tablosu ve indexini (yoksa) OLUSTURUR.
SQLite app.db için tasarlandı.

Calistirma:
    cd backend
    python scripts/ensure_capex_table.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS scenario_capex (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    amount NUMERIC(18,2) NOT NULL,
    notes TEXT NULL,
    CONSTRAINT ck_capex_month CHECK (month >= 1 AND month <= 12)
);
"""

DDL_INDEX = """
CREATE INDEX IF NOT EXISTS ix_capex_scenario_year_month
ON scenario_capex (scenario_id, year, month);
"""

def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (name,))
    return cur.fetchone() is not None

def index_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?;", (name,))
    return cur.fetchone() is not None

def main():
    print(f"[i] DB: {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    if not table_exists(cx, "scenario_capex"):
        print("[+] Creating table scenario_capex ...")
        cx.executescript(DDL_TABLE)
    else:
        print("[=] Table scenario_capex already exists.")

    if not index_exists(cx, "ix_capex_scenario_year_month"):
        print("[+] Creating index ix_capex_scenario_year_month ...")
        cx.executescript(DDL_INDEX)
    else:
        print("[=] Index ix_capex_scenario_year_month already exists.")

    cx.commit()

    # Kısa özet
    cur = cx.execute("SELECT COUNT(*) FROM scenario_capex;")
    count = cur.fetchone()[0]
    print(f"[✓] scenario_capex hazır. Satır sayısı: {count}")

    cx.close()

if __name__ == "__main__":
    main()
