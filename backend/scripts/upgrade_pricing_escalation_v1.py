# backend/scripts/upgrade_pricing_escalation_v1.py
"""
AryaIntel CRM - Pricing/Escalation/Formulation/Commercial add-ons (SQLite)

Bu upgrade script'i aşağıdakileri tek seferde kurar/günceller:
- Index kütüphanesi: index_series, index_points (harici/manuel veri için)
- Escalation policies: tek endeks, sabit oran VE çoklu endeks (weighted basket)
- Product formulations (ör. AN/EM) + formulation_components (RnF sepeti)
- Çoklu site desteği
- Satır bağlantıları: escalation (price/cogs), formulation, line_type, pass-through
- Commercial terms: advance/retention/bond + DSO + fatura günü
- Pass-through politikaları (markup/cap)
- SLA politikaları (service credits)
- CAPEX reward politikası
- Senaryo varsayılanları + kısıtlar (min GM, vb.)
- Basit billing plan (milestone/proration) altyapısı

Çalıştırma:
    cd backend
    python scripts/upgrade_pricing_escalation_v1.py
"""

from pathlib import Path
import sqlite3
from typing import Iterable

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (name,)
    )
    return cur.fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> set[str]:
    cols = set()
    for row in cx.execute(f"PRAGMA table_info({table});"):
        cols.add(row[1])
    return cols

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name = ?;", (name,)
    )
    if cur.fetchone() is None:
        cx.execute(sql)

def apply_add_columns(cx: sqlite3.Connection, table: str, add_sql_map: dict) -> None:
    cols = column_names(cx, table)
    for col, add_sql in add_sql_map.items():
        if col not in cols:
            print(f"[+] {table}: ADD COLUMN {col}")
            cx.execute(add_sql)

def exec_many(cx: sqlite3.Connection, statements: Iterable[str]) -> None:
    for s in statements:
        if s.strip():
            cx.execute(s)

# -------------------------------------------------------------------
# DDL: NEW TABLES
# -------------------------------------------------------------------
DDL_INDEX_SERIES = """
CREATE TABLE IF NOT EXISTS index_series (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,                 -- 'CPI', 'AMMONIA', 'FUEL', 'FX_USDTRY'...
  name TEXT NOT NULL,
  unit TEXT NULL,                     -- 'index','pct','price_per_tonne','rate'
  country TEXT NULL,
  currency TEXT NULL,                 -- 3-char ISO (parasal serilerde)
  source TEXT NULL,                   -- human label
  fetch_adapter TEXT NULL,            -- 'oecd'|'fred'|'manual'|'csv'...
  fetch_config TEXT NULL,             -- JSON
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

DDL_INDEX_POINTS = """
CREATE TABLE IF NOT EXISTS index_points (
  id INTEGER PRIMARY KEY,
  series_id INTEGER NOT NULL REFERENCES index_series(id) ON DELETE CASCADE,
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  value NUMERIC(18,6) NOT NULL,
  source_ref TEXT NULL,
  updated_at TEXT DEFAULT (datetime('now')),
  CONSTRAINT ck_ip_month CHECK (month BETWEEN 1 AND 12),
  CONSTRAINT u_ip UNIQUE(series_id, year, month)
);
"""

DDL_ESCALATION_POLICIES = """
CREATE TABLE IF NOT EXISTS escalation_policies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'both',     -- 'price'|'cogs'|'both'
  rate_pct NUMERIC(9,6) NULL,             -- sabit oran (yalnızca tek modda)
  index_series_id INTEGER NULL REFERENCES index_series(id),  -- tek-endeks modu
  start_year INTEGER NOT NULL,
  start_month INTEGER NOT NULL,
  cap_pct NUMERIC(9,6) NULL,
  floor_pct NUMERIC(9,6) NULL,
  frequency TEXT NOT NULL DEFAULT 'annual',   -- 'annual'|'monthly'
  compounding TEXT NOT NULL DEFAULT 'compound', -- 'step'|'compound'
  scenario_id INTEGER NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  CONSTRAINT ck_es_scope CHECK (scope IN ('price','cogs','both')),
  CONSTRAINT ck_es_freq CHECK (frequency IN ('annual','monthly')),
  CONSTRAINT ck_es_comp CHECK (compounding IN ('step','compound'))
);
"""

# Çoklu endeks (weighted basket) desteği
DDL_ESCALATION_COMPONENTS = """
CREATE TABLE IF NOT EXISTS escalation_policy_components (
  id INTEGER PRIMARY KEY,
  policy_id INTEGER NOT NULL REFERENCES escalation_policies(id) ON DELETE CASCADE,
  index_series_id INTEGER NOT NULL REFERENCES index_series(id),
  weight_pct NUMERIC(9,6) NOT NULL,       -- 0..100
  base_index_value NUMERIC(18,6) NULL,    -- Excel 'Base Ref'; NULL ise base_ym'den çek
  note TEXT NULL
);
"""

# Ürün formülasyonları (AN / EM vb.)
DDL_PRODUCT_FORMULATIONS = """
CREATE TABLE IF NOT EXISTS product_formulations (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  code TEXT NOT NULL,                -- 'AN','EM'
  name TEXT NULL,
  description TEXT NULL,
  base_price NUMERIC(18,6) NULL,
  base_currency TEXT NULL,           -- ISO-4217
  is_active INTEGER NOT NULL DEFAULT 1,
  version_no INTEGER NOT NULL DEFAULT 1,
  locked_at TEXT NULL,               -- onaylanmış/kilitli formül
  created_by INTEGER NULL,           -- users.id (varsa)
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

DDL_FORMULATION_COMPONENTS = """
CREATE TABLE IF NOT EXISTS formulation_components (
  id INTEGER PRIMARY KEY,
  formulation_id INTEGER NOT NULL REFERENCES product_formulations(id) ON DELETE CASCADE,
  index_series_id INTEGER NOT NULL REFERENCES index_series(id),
  weight_pct NUMERIC(9,6) NOT NULL,      -- 0..100
  base_index_value NUMERIC(18,6) NULL,
  note TEXT NULL
);
"""

# Çoklu site desteği
DDL_SITES = """
CREATE TABLE IF NOT EXISTS sites (
  id INTEGER PRIMARY KEY,
  scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  code TEXT NOT NULL,              -- 'IDU','OBU' gibi
  name TEXT NOT NULL,
  notes TEXT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
"""

# Pass-through politikaları
DDL_PASS_THROUGH_POLICIES = """
CREATE TABLE IF NOT EXISTS pass_through_policies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applies_to TEXT NOT NULL DEFAULT 'consumables', -- 'consumables'|'spares'|'other'
  markup_pct NUMERIC(9,6) NULL,
  cap_amount NUMERIC(18,6) NULL,
  notes TEXT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);
"""

# Ticari şartlar (advance/retention/bond + DSO + fatura günü)
DDL_COMMERCIAL_TERMS = """
CREATE TABLE IF NOT EXISTS commercial_terms (
  id INTEGER PRIMARY KEY,
  scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  advance_pct NUMERIC(9,6) NULL,
  advance_recovery_months INTEGER NULL,
  retention_pct NUMERIC(9,6) NULL,
  retention_release_rule TEXT NULL,   -- 'end_of_term'|'milestone'|'time_based'
  bond_cost_pct NUMERIC(9,6) NULL,
  dso_days INTEGER NULL,
  invoice_day_of_month INTEGER NULL CHECK (invoice_day_of_month BETWEEN 1 AND 28),
  notes TEXT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
"""

# SLA politikaları
DDL_SLA_POLICIES = """
CREATE TABLE IF NOT EXISTS sla_policies (
  id INTEGER PRIMARY KEY,
  scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  metric TEXT NOT NULL,              -- 'uptime','response_time'...
  threshold NUMERIC(18,6) NOT NULL,
  penalty_pct NUMERIC(9,6) NOT NULL, -- gelire uygulanacak kesinti %
  apply_to TEXT NOT NULL DEFAULT 'monthly_fee', -- 'monthly_fee'|'all_revenue'
  notes TEXT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);
"""

# CAPEX reward politikası
DDL_CAPEX_REWARD_POLICIES = """
CREATE TABLE IF NOT EXISTS capex_reward_policies (
  id INTEGER PRIMARY KEY,
  scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  rate_pct NUMERIC(9,6) NOT NULL,       -- %22 / %30 vb.
  base TEXT NOT NULL DEFAULT 'capex_gross',  -- 'capex_gross'|'capex_net'
  amortization_months INTEGER NOT NULL, -- ödülün dağıtılacağı ay
  include_financing_costs INTEGER NOT NULL DEFAULT 0,
  notes TEXT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);
"""

# Basit billing plan (milestone / proration desteği)
DDL_BILLING_PLANS = """
CREATE TABLE IF NOT EXISTS billing_plans (
  id INTEGER PRIMARY KEY,
  line_type TEXT NOT NULL DEFAULT 'service', -- 'service'|'boq'|'other'
  line_id INTEGER NOT NULL,                  -- tablo-agnostic; referential check yok
  ym TEXT NOT NULL,                          -- 'YYYY-MM'
  pct_or_amount NUMERIC(18,6) NOT NULL,      -- yüzde veya tutar (yorum ile ayrıştır)
  is_percent INTEGER NOT NULL DEFAULT 1
);
"""

# Senaryo kısıtları & varsayılanlar
DDL_SCENARIO_CONSTRAINTS = """
CREATE TABLE IF NOT EXISTS scenario_constraints (
  id INTEGER PRIMARY KEY,
  scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  min_gross_margin_pct NUMERIC(9,6) NULL,
  min_cm1_pct NUMERIC(9,6) NULL,
  require_capex_reward INTEGER NOT NULL DEFAULT 0,
  notes TEXT NULL
);
"""

# (Varsayılan escalation politikaları için pointer tutmak istersen)
DDL_SCENARIO_DEFAULTS_ADD_COLS = {
    "default_price_escalation_policy_id": "ALTER TABLE scenarios ADD COLUMN default_price_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "default_cogs_escalation_policy_id":  "ALTER TABLE scenarios ADD COLUMN default_cogs_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);"
}

# -------------------------------------------------------------------
# ALTERs: mevcut tablolara eklenecek sütunlar
# (gerçek tablo adlarınızı uyarlayabilirsiniz; isimler örnektir)
# -------------------------------------------------------------------
# services tablosuna ekler
SERVICES_ADD_COLS = {
    "site_id": "ALTER TABLE services ADD COLUMN site_id INTEGER NULL REFERENCES sites(id);",
    "line_type": "ALTER TABLE services ADD COLUMN line_type TEXT NULL;",  # 'base_fee'|'variable_fee'|'reimbursable'
    "formulation_id": "ALTER TABLE services ADD COLUMN formulation_id INTEGER NULL REFERENCES product_formulations(id);",
    "price_escalation_policy_id": "ALTER TABLE services ADD COLUMN price_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "cogs_escalation_policy_id":  "ALTER TABLE services ADD COLUMN cogs_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "pass_through_policy_id": "ALTER TABLE services ADD COLUMN pass_through_policy_id INTEGER NULL REFERENCES pass_through_policies(id);"
}

# BOQ tablosuna ekler
BOQ_ADD_COLS = {
    "site_id": "ALTER TABLE boq_lines ADD COLUMN site_id INTEGER NULL REFERENCES sites(id);",
    "line_type": "ALTER TABLE boq_lines ADD COLUMN line_type TEXT NULL;",
    "formulation_id": "ALTER TABLE boq_lines ADD COLUMN formulation_id INTEGER NULL REFERENCES product_formulations(id);",
    "price_escalation_policy_id": "ALTER TABLE boq_lines ADD COLUMN price_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "cogs_escalation_policy_id":  "ALTER TABLE boq_lines ADD COLUMN cogs_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id);",
    "pass_through_policy_id": "ALTER TABLE boq_lines ADD COLUMN pass_through_policy_id INTEGER NULL REFERENCES pass_through_policies(id);"
}

# CAPEX satırlarına reward policy pointer'ı eklemek istersek
CAPEX_ADD_COLS = {
    "site_id": "ALTER TABLE capex_lines ADD COLUMN site_id INTEGER NULL REFERENCES sites(id);",
    "capex_reward_policy_id": "ALTER TABLE capex_lines ADD COLUMN capex_reward_policy_id INTEGER NULL REFERENCES capex_reward_policies(id);"
}

# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # 1) NEW TABLES
    print("[*] Creating core tables if not exists…")
    cx.executescript(DDL_INDEX_SERIES)
    cx.executescript(DDL_INDEX_POINTS)
    cx.executescript(DDL_ESCALATION_POLICIES)
    cx.executescript(DDL_ESCALATION_COMPONENTS)
    cx.executescript(DDL_PRODUCT_FORMULATIONS)
    cx.executescript(DDL_FORMULATION_COMPONENTS)
    cx.executescript(DDL_SITES)
    cx.executescript(DDL_PASS_THROUGH_POLICIES)
    cx.executescript(DDL_COMMERCIAL_TERMS)
    cx.executescript(DDL_SLA_POLICIES)
    cx.executescript(DDL_CAPEX_REWARD_POLICIES)
    cx.executescript(DDL_BILLING_PLANS)
    cx.executescript(DDL_SCENARIO_CONSTRAINTS)

    # 2) ALTER EXISTING TABLES
    # scenarios'a default escalation pointer'ları
    if table_exists(cx, "scenarios"):
        print("[*] Updating scenarios columns…")
        apply_add_columns(cx, "scenarios", DDL_SCENARIO_DEFAULTS_ADD_COLS)
    else:
        print("[!] 'scenarios' table not found. Skipping defaults.")

    # services
    if table_exists(cx, "services"):
        print("[*] Updating services columns…")
        apply_add_columns(cx, "services", SERVICES_ADD_COLS)
    else:
        print("[!] 'services' table not found. Skipping.")

    # boq_lines
    if table_exists(cx, "boq_lines"):
        print("[*] Updating boq_lines columns…")
        apply_add_columns(cx, "boq_lines", BOQ_ADD_COLS)
    else:
        print("[!] 'boq_lines' table not found. Skipping.")

    # capex_lines
    if table_exists(cx, "capex_lines"):
        print("[*] Updating capex_lines columns…")
        apply_add_columns(cx, "capex_lines", CAPEX_ADD_COLS)
    else:
        print("[!] 'capex_lines' table not found. Skipping.")

    # 3) Indexes (örnek, en kritik alanlara)
    print("[*] Ensuring useful indexes…")
    ensure_index(cx, "ix_index_points_series_ym",
                 "CREATE INDEX IF NOT EXISTS ix_index_points_series_ym ON index_points(series_id, year, month);")
    ensure_index(cx, "ix_escalation_components_policy",
                 "CREATE INDEX IF NOT EXISTS ix_escalation_components_policy ON escalation_policy_components(policy_id);")
    ensure_index(cx, "ix_formulation_components_formulation",
                 "CREATE INDEX IF NOT EXISTS ix_formulation_components_formulation ON formulation_components(formulation_id);")
    ensure_index(cx, "ix_sites_scenario",
                 "CREATE INDEX IF NOT EXISTS ix_sites_scenario ON sites(scenario_id);")
    ensure_index(cx, "ix_commercial_terms_scenario",
                 "CREATE INDEX IF NOT EXISTS ix_commercial_terms_scenario ON commercial_terms(scenario_id);")
    ensure_index(cx, "ix_sla_policies_scenario",
                 "CREATE INDEX IF NOT EXISTS ix_sla_policies_scenario ON sla_policies(scenario_id);")
    ensure_index(cx, "ix_capex_reward_scenario",
                 "CREATE INDEX IF NOT EXISTS ix_capex_reward_scenario ON capex_reward_policies(scenario_id);")

    cx.commit()

    # 4) Summary
    def dump_table(table: str):
        if not table_exists(cx, table): 
            print(f"[-] {table} (missing)")
            return
        print(f"\n=== {table} columns ===")
        for row in cx.execute(f"PRAGMA table_info({table});"):
            print(f"- {row[1]:28} | {row[2]:15} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    for t in [
        "index_series","index_points",
        "escalation_policies","escalation_policy_components",
        "product_formulations","formulation_components",
        "sites","pass_through_policies","commercial_terms",
        "sla_policies","capex_reward_policies","billing_plans",
        "scenario_constraints",
        "services","boq_lines","capex_lines","scenarios",
    ]:
        dump_table(t)

    cx.close()
    print("\n[✓] upgrade_pricing_escalation_v1 completed.")

if __name__ == "__main__":
    main()
