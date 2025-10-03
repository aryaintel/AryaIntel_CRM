# backend/scripts/upgrade_escalations_schema_v1.py
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row

    # columns (idempotent)
    def addcol(tbl, coldef):
        col = coldef.split()[0]
        try:
            cx.execute(f"ALTER TABLE {tbl} ADD COLUMN {coldef}")
            print(f"[+] add column {tbl}.{col}")
        except sqlite3.OperationalError:
            pass

    # base table
    cols = [r["name"] for r in cx.execute("PRAGMA table_info(escalation_policies)")]

    if not cols:
        # minimal create (fields used by API/pricing)
        cx.execute("""
        CREATE TABLE IF NOT EXISTS escalation_policies(
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          scope TEXT,
          rate_pct REAL,
          index_series_id INTEGER,
          start_year INTEGER NOT NULL,
          start_month INTEGER NOT NULL,
          cap_pct REAL,
          floor_pct REAL,
          frequency TEXT,
          compounding TEXT
        );
        """)
        print("[✓] created escalation_policies")

    addcol("escalation_policies", "scope TEXT")
    addcol("escalation_policies", "rate_pct REAL")
    addcol("escalation_policies", "index_series_id INTEGER")
    addcol("escalation_policies", "start_year INTEGER")
    addcol("escalation_policies", "start_month INTEGER")
    addcol("escalation_policies", "cap_pct REAL")
    addcol("escalation_policies", "floor_pct REAL")
    addcol("escalation_policies", "frequency TEXT")
    addcol("escalation_policies", "compounding TEXT")

    cx.execute("""
    CREATE TABLE IF NOT EXISTS escalation_policy_components(
      id INTEGER PRIMARY KEY,
      policy_id INTEGER NOT NULL,
      index_series_id INTEGER NOT NULL,
      weight_pct REAL NOT NULL,
      base_index_value REAL,
      note TEXT,
      FOREIGN KEY(policy_id) REFERENCES escalation_policies(id) ON DELETE CASCADE
    );
    """)
    print("[✓] ensured escalation_policy_components")

    # helpful indexes
    try:
        cx.execute("CREATE INDEX ix_idx_points ON index_points(series_id,year,month)")
    except sqlite3.OperationalError:
        pass

    cx.commit()
    cx.close()
    print("[✓] upgrade_escalations_schema_v1 done.")

if __name__ == "__main__":
    main()
