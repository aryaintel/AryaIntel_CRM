# backend/scripts/upgrade_capex_reward_v1.py
"""
Upgrade DB schema for CAPEX Reward → Services/BOQ revenue parity (SQLite).

Adds:
- scenario_capex: reward_enabled, reward_pct, reward_spread_kind, linked_boq_item_id, term_months_override
- scenarios: default_capex_reward_pct

Design:
- Idempotent (safe to re-run).
- Uses SQLite PRAGMA to discover existing cols.
- Keeps types REAL/INTEGER/TEXT (avoid Decimal binding issues).
- No data loss; only ADD COLUMN or CREATE TABLE IF NOT EXISTS.

Run:
    cd backend
    python scripts/upgrade_capex_reward_v1.py
"""

from pathlib import Path
import sqlite3
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "app.db"

def cx():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    # Keep foreign keys on
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def table_columns(con: sqlite3.Connection, table: str) -> Dict[str, Dict[str, Any]]:
    cols = {}
    for row in con.execute(f"PRAGMA table_info({table});"):
        # row: cid, name, type, notnull, dflt_value, pk
        cols[row["name"]] = {
            "type": row["type"],
            "notnull": row["notnull"],
            "default": row["dflt_value"],
            "pk": row["pk"],
        }
    return cols

def ensure_table_scenarios(con: sqlite3.Connection):
    # Create minimal scenarios table if it doesn't exist (most projects already have it)
    con.execute("""
    CREATE TABLE IF NOT EXISTS scenarios (
        id INTEGER PRIMARY KEY,
        name TEXT,
        -- Optional contract fields commonly used in this project
        contract_start_year INTEGER,
        contract_start_month INTEGER,
        contract_term_months INTEGER
    );
    """)

def ensure_table_scenario_capex(con: sqlite3.Connection):
    # Create minimal capex table if not exists (many repos already have a richer schema)
    con.execute("""
    CREATE TABLE IF NOT EXISTS scenario_capex (
        id INTEGER PRIMARY KEY,
        scenario_id INTEGER NOT NULL,
        name TEXT,
        one_off_cost REAL,
        start_year INTEGER,
        start_month INTEGER,
        depr_years INTEGER,
        depr_method TEXT,
        FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE
    );
    """)

def add_missing_columns(con: sqlite3.Connection, table: str, add_cols_sql: Dict[str, str]) -> List[str]:
    """
    add_cols_sql: { col_name: "ALTER TABLE ... ADD COLUMN ..." }
    Returns list of added columns (for reporting).
    """
    before = table_columns(con, table)
    added = []
    for col, sql in add_cols_sql.items():
        if col not in before:
            con.execute(sql)
            added.append(col)
    return added

def main():
    print("[*] Opening DB:", DB_PATH)
    with cx() as con:
        # 0) Ensure base tables exist
        ensure_table_scenarios(con)
        ensure_table_scenario_capex(con)

        # 1) scenarios – default_capex_reward_pct
        print("\n[1] Upgrading 'scenarios' table...")
        scenarios_cols = table_columns(con, "scenarios")
        add_map = {
            # default 0.0 means 'off' until user enables % explicitly
            "default_capex_reward_pct": "ALTER TABLE scenarios ADD COLUMN default_capex_reward_pct REAL DEFAULT 0.0",
        }
        added = add_missing_columns(con, "scenarios", add_map)
        if added:
            print("    Added columns:", ", ".join(added))
        else:
            print("    No new columns needed.")

        # 2) scenario_capex – reward fields and optional links
        print("\n[2] Upgrading 'scenario_capex' table...")
        capex_cols = table_columns(con, "scenario_capex")
        add_map_capex = {
            # Enables revenue conversion from CAPEX via Capex Reward
            "reward_enabled": "ALTER TABLE scenario_capex ADD COLUMN reward_enabled INTEGER DEFAULT 0",
            # If NULL, backend should fall back to scenarios.default_capex_reward_pct
            "reward_pct": "ALTER TABLE scenario_capex ADD COLUMN reward_pct REAL",
            # even | follow_boq | custom (MVP uses even or follow_boq)
            "reward_spread_kind": "ALTER TABLE scenario_capex ADD COLUMN reward_spread_kind TEXT DEFAULT 'even'",
            # when follow_boq: FK (not enforced here to keep ALTER simple & idempotent)
            "linked_boq_item_id": "ALTER TABLE scenario_capex ADD COLUMN linked_boq_item_id INTEGER",
            # override if scenario.contract_term_months is absent or user wants custom term
            "term_months_override": "ALTER TABLE scenario_capex ADD COLUMN term_months_override INTEGER"
        }
        added_capex = add_missing_columns(con, "scenario_capex", add_map_capex)
        if added_capex:
            print("    Added columns:", ", ".join(added_capex))
        else:
            print("    No new columns needed.")

        # Optionally, small helper indexes (idempotent CREATE INDEX IF NOT EXISTS)
        print("\n[3] Ensuring helper indexes...")
        con.execute("CREATE INDEX IF NOT EXISTS idx_scenario_capex_scenario_id ON scenario_capex(scenario_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_scenario_capex_linked_boq ON scenario_capex(linked_boq_item_id);")
        print("    Indexes ready.")

        # 4) Show final schemas (like other scripts in the repo do)
        def print_schema(table: str):
            print(f"\n=== {table} columns ===")
            for row in con.execute(f"PRAGMA table_info({table});"):
                print(f"- {row[1]:22} | {row[2]:12} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

        print_schema("scenarios")
        print_schema("scenario_capex")

        # Basic counts for reassurance
        try:
            count_scen = con.execute("SELECT COUNT(*) FROM scenarios;").fetchone()[0]
        except sqlite3.OperationalError:
            count_scen = "n/a"
        try:
            count_capex = con.execute("SELECT COUNT(*) FROM scenario_capex;").fetchone()[0]
        except sqlite3.OperationalError:
            count_capex = "n/a"

        print(f"\n[✓] Upgrade complete. scenarios rows: {count_scen}, scenario_capex rows: {count_capex}")

if __name__ == "__main__":
    main()
