from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# Muhtemel tablo adları (soldan sağa öncelik)
CANDIDATES = {
    "services":   ["services", "scenario_services", "service_lines"],
    "boq_lines":  ["boq_lines", "scenario_boq", "scenario_boq_items", "boq_items"],
    "capex_lines":["capex_lines", "scenario_capex", "capex_items"],
}

# Bu kolonları ekleyeceğiz
SERVICES_ADD_COLS = {
    "site_id": "ALTER TABLE {tbl} ADD COLUMN site_id INTEGER NULL REFERENCES sites(id);",
    "line_type": "ALTER TABLE {tbl} ADD COLUMN line_type TEXT NULL;",  # 'base_fee'|'variable_fee'|'reimbursable'
    "formulation_id": "ALTER TABLE {tbl} ADD COLUMN formulation_id INTEGER NULL REFERENCES product_formulations(id);",
    "price_escalation_policy_id": "ALTER TABLE {tbl} ADD COLUMN price_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "cogs_escalation_policy_id":  "ALTER TABLE {tbl} ADD COLUMN cogs_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "pass_through_policy_id": "ALTER TABLE {tbl} ADD COLUMN pass_through_policy_id INTEGER NULL REFERENCES pass_through_policies(id);"
}

BOQ_ADD_COLS = {
    "site_id": "ALTER TABLE {tbl} ADD COLUMN site_id INTEGER NULL REFERENCES sites(id);",
    "line_type": "ALTER TABLE {tbl} ADD COLUMN line_type TEXT NULL;",
    "formulation_id": "ALTER TABLE {tbl} ADD COLUMN formulation_id INTEGER NULL REFERENCES product_formulations(id);",
    "price_escalation_policy_id": "ALTER TABLE {tbl} ADD COLUMN price_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "cogs_escalation_policy_id":  "ALTER TABLE {tbl} ADD COLUMN cogs_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "pass_through_policy_id": "ALTER TABLE {tbl} ADD COLUMN pass_through_policy_id INTEGER NULL REFERENCES pass_through_policies(id);"
}

CAPEX_ADD_COLS = {
    "site_id": "ALTER TABLE {tbl} ADD COLUMN site_id INTEGER NULL REFERENCES sites(id);",
    "capex_reward_policy_id": "ALTER TABLE {tbl} ADD COLUMN capex_reward_policy_id INTEGER NULL REFERENCES capex_reward_policies(id);"
}

DDL_DEFAULT = {
    "services": """
    CREATE TABLE IF NOT EXISTS services (
      id INTEGER PRIMARY KEY,
      scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
      service_name TEXT NOT NULL,
      category TEXT NULL,
      vendor TEXT NULL,
      unit TEXT NULL,
      quantity NUMERIC(18,6) NOT NULL DEFAULT 0,
      unit_cost NUMERIC(18,6) NOT NULL DEFAULT 0,
      currency TEXT NOT NULL DEFAULT 'USD',
      start_year INTEGER NOT NULL,
      start_month INTEGER NOT NULL CHECK (start_month BETWEEN 1 AND 12),
      end_year INTEGER NULL,
      end_month INTEGER NULL,
      notes TEXT NULL
    );
    """,
    "boq_lines": """
    CREATE TABLE IF NOT EXISTS boq_lines (
      id INTEGER PRIMARY KEY,
      scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
      item_name TEXT NOT NULL,
      category TEXT NULL,
      quantity NUMERIC(18,6) NOT NULL DEFAULT 0,
      unit_price NUMERIC(18,6) NOT NULL DEFAULT 0,
      currency TEXT NOT NULL DEFAULT 'USD',
      start_year INTEGER NOT NULL,
      start_month INTEGER NOT NULL CHECK (start_month BETWEEN 1 AND 12),
      notes TEXT NULL
    );
    """,
    "capex_lines": """
    CREATE TABLE IF NOT EXISTS capex_lines (
      id INTEGER PRIMARY KEY,
      scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
      year INTEGER NOT NULL,
      month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
      amount NUMERIC(18,6) NOT NULL,
      asset_name TEXT NULL,
      category TEXT NULL,
      service_start_year INTEGER NULL,
      service_start_month INTEGER NULL CHECK (service_start_month BETWEEN 1 AND 12),
      useful_life_months INTEGER NULL,
      notes TEXT NULL
    );
    """
}

def table_exists(cx, name):
    return cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone() is not None

def find_existing_table(cx, candidates):
    for name in candidates:
        if table_exists(cx, name):
            return name
    return None

def colset(cx, table):
    return {r[1] for r in cx.execute(f"PRAGMA table_info({table});")}

def add_cols(cx, table, mapping):
    existing = colset(cx, table)
    for col, tmpl in mapping.items():
        if col not in existing:
            sql = tmpl.format(tbl=table)
            print(f"[+] {table}: ADD COLUMN {col}")
            cx.execute(sql)
        else:
            print(f"[=] {table}: column exists {col}")

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")
    print(f"[i] DB = {DB_PATH}")

    # SERVICES
    sv_table = find_existing_table(cx, CANDIDATES["services"])
    if not sv_table:
        sv_table = CANDIDATES["services"][0]  # 'services'
        print(f"[!] services-like table not found → creating default '{sv_table}'")
        cx.executescript(DDL_DEFAULT["services"])
    add_cols(cx, sv_table, SERVICES_ADD_COLS)

    # BOQ
    boq_table = find_existing_table(cx, CANDIDATES["boq_lines"])
    if not boq_table:
        boq_table = CANDIDATES["boq_lines"][0]
        print(f"[!] boq-like table not found → creating default '{boq_table}'")
        cx.executescript(DDL_DEFAULT["boq_lines"])
    add_cols(cx, boq_table, BOQ_ADD_COLS)

    # CAPEX
    capex_table = find_existing_table(cx, CANDIDATES["capex_lines"])
    if not capex_table:
        capex_table = CANDIDATES["capex_lines"][0]
        print(f"[!] capex-like table not found → creating default '{capex_table}'")
        cx.executescript(DDL_DEFAULT["capex_lines"])
    add_cols(cx, capex_table, CAPEX_ADD_COLS)

    cx.commit()

    # Özet
    for t in [sv_table, boq_table, capex_table]:
        print(f"\n=== {t} columns ===")
        for r in cx.execute(f"PRAGMA table_info({t});"):
            print(f"- {r[1]:28} | {r[2]:15} | notnull={r[3]} | default={r[4]!r} | pk={r[5]}")

    cx.close()
    print("\n[✓] patch completed.")

if __name__ == "__main__":
    main()
