# backend/scripts/upgrade_services_schema.py
"""
Services (OPEX) şemasını güvenle yükseltir / kurar.

- scenarios tablosu yoksa, minimal + workflow alanlarıyla oluşturur
  (business_case_id, name, months, start_date, is_*_ready, workflow_state).
- scenario_services tablosunu TAM şemayla oluşturur (yoksa).
- Varsa eksik sütunları ALTER TABLE ile ekler (SQLite uyumlu).
- scenario_service_month tablosunu TAM şemayla oluşturur (yoksa).
- Varsa eksik sütunları ALTER TABLE ile ekler.
- Gerekli index’leri ve (varsa) trigger’ları kurar.
- Varsayılan değerleri backfill eder ve özet döküm basar.

Çalıştırma:
    cd backend
    python scripts/upgrade_services_schema.py
"""
from pathlib import Path
import sqlite3
from typing import Set

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

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

def trigger_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?;", (name,)
    )
    return cur.fetchone() is not None

# -----------------------------------------------------------------------------
# DDL (SQLite uyumlu)
# -----------------------------------------------------------------------------

# Senaryolar (güvenli çalışsın diye minimal + workflow ile garanti altına alıyoruz)
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
    workflow_state TEXT NOT NULL DEFAULT 'draft'
);
"""

# === 1) scenario_services =====================================================
# Not: SQLite ENUM desteklemediği için CHECK constraint ile kısıtlıyoruz.
DDL_SCENARIO_SERVICES = """
CREATE TABLE IF NOT EXISTS scenario_services (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,

    service_name TEXT NOT NULL,
    category TEXT NULL,
    vendor TEXT NULL,
    unit TEXT NULL,
    quantity NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit_cost NUMERIC(18,4) NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'TRY',

    start_year INTEGER NOT NULL,
    start_month INTEGER NOT NULL,
    duration_months INTEGER NULL,
    end_year INTEGER NULL,
    end_month INTEGER NULL,

    payment_term TEXT NOT NULL DEFAULT 'monthly'
        CHECK (payment_term IN ('monthly','annual_prepaid','one_time')),
    cash_out_month_policy TEXT NOT NULL DEFAULT 'service_month'
        CHECK (cash_out_month_policy IN ('service_month','start_month','contract_anniversary')),

    escalation_pct NUMERIC(8,4) NOT NULL DEFAULT 0,
    escalation_freq TEXT NOT NULL DEFAULT 'none'
        CHECK (escalation_freq IN ('annual','none')),

    tax_rate NUMERIC(8,4) NOT NULL DEFAULT 0,
    expense_includes_tax INTEGER NOT NULL DEFAULT 0,

    notes TEXT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,

    created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
"""

# ALTER eklemeleri (kolon -> DDL). Sadece eksikse uygulanır.
ADD_COLS_SERVICES = {
    "scenario_id":             "ALTER TABLE scenario_services ADD COLUMN scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE;",
    "service_name":            "ALTER TABLE scenario_services ADD COLUMN service_name TEXT NOT NULL;",
    "category":                "ALTER TABLE scenario_services ADD COLUMN category TEXT NULL;",
    "vendor":                  "ALTER TABLE scenario_services ADD COLUMN vendor TEXT NULL;",
    "unit":                    "ALTER TABLE scenario_services ADD COLUMN unit TEXT NULL;",
    "quantity":                "ALTER TABLE scenario_services ADD COLUMN quantity NUMERIC(18,4) NOT NULL DEFAULT 1;",
    "unit_cost":               "ALTER TABLE scenario_services ADD COLUMN unit_cost NUMERIC(18,4) NOT NULL DEFAULT 0;",
    "currency":                "ALTER TABLE scenario_services ADD COLUMN currency VARCHAR(3) NOT NULL DEFAULT 'TRY';",
    "start_year":              "ALTER TABLE scenario_services ADD COLUMN start_year INTEGER NOT NULL;",
    "start_month":             "ALTER TABLE scenario_services ADD COLUMN start_month INTEGER NOT NULL;",
    "duration_months":         "ALTER TABLE scenario_services ADD COLUMN duration_months INTEGER NULL;",
    "end_year":                "ALTER TABLE scenario_services ADD COLUMN end_year INTEGER NULL;",
    "end_month":               "ALTER TABLE scenario_services ADD COLUMN end_month INTEGER NULL;",
    "payment_term":            "ALTER TABLE scenario_services ADD COLUMN payment_term TEXT NOT NULL DEFAULT 'monthly';",
    "cash_out_month_policy":   "ALTER TABLE scenario_services ADD COLUMN cash_out_month_policy TEXT NOT NULL DEFAULT 'service_month';",
    "escalation_pct":          "ALTER TABLE scenario_services ADD COLUMN escalation_pct NUMERIC(8,4) NOT NULL DEFAULT 0;",
    "escalation_freq":         "ALTER TABLE scenario_services ADD COLUMN escalation_freq TEXT NOT NULL DEFAULT 'none';",
    "tax_rate":                "ALTER TABLE scenario_services ADD COLUMN tax_rate NUMERIC(8,4) NOT NULL DEFAULT 0;",
    "expense_includes_tax":    "ALTER TABLE scenario_services ADD COLUMN expense_includes_tax INTEGER NOT NULL DEFAULT 0;",
    "notes":                   "ALTER TABLE scenario_services ADD COLUMN notes TEXT NULL;",
    "is_active":               "ALTER TABLE scenario_services ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
    "created_at":              "ALTER TABLE scenario_services ADD COLUMN created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP);",
    "updated_at":              "ALTER TABLE scenario_services ADD COLUMN updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP);",
}

# === 2) scenario_service_month ===============================================
DDL_SCENARIO_SERVICE_MONTH = """
CREATE TABLE IF NOT EXISTS scenario_service_month (
    id INTEGER PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES scenario_services(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    cash_out NUMERIC(18,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    UNIQUE(service_id, year, month)
);
"""

ADD_COLS_SERVICE_MONTH = {
    "service_id":      "ALTER TABLE scenario_service_month ADD COLUMN service_id INTEGER NOT NULL REFERENCES scenario_services(id) ON DELETE CASCADE;",
    "year":            "ALTER TABLE scenario_service_month ADD COLUMN year INTEGER NOT NULL;",
    "month":           "ALTER TABLE scenario_service_month ADD COLUMN month INTEGER NOT NULL;",
    "expense_amount":  "ALTER TABLE scenario_service_month ADD COLUMN expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0;",
    "cash_out":        "ALTER TABLE scenario_service_month ADD COLUMN cash_out NUMERIC(18,2) NOT NULL DEFAULT 0;",
    "tax_amount":      "ALTER TABLE scenario_service_month ADD COLUMN tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0;",
}

# Backfill
BACKFILL_SERVICES = [
    "UPDATE scenario_services SET quantity = COALESCE(quantity, 1);",
    "UPDATE scenario_services SET unit_cost = COALESCE(unit_cost, 0);",
    "UPDATE scenario_services SET currency = COALESCE(currency, 'TRY');",
    "UPDATE scenario_services SET payment_term = COALESCE(payment_term, 'monthly');",
    "UPDATE scenario_services SET cash_out_month_policy = COALESCE(cash_out_month_policy, 'service_month');",
    "UPDATE scenario_services SET escalation_pct = COALESCE(escalation_pct, 0);",
    "UPDATE scenario_services SET escalation_freq = COALESCE(escalation_freq, 'none');",
    "UPDATE scenario_services SET tax_rate = COALESCE(tax_rate, 0);",
    "UPDATE scenario_services SET expense_includes_tax = COALESCE(expense_includes_tax, 0);",
    "UPDATE scenario_services SET is_active = COALESCE(is_active, 1);",
]

BACKFILL_SERVICE_MONTH = [
    "UPDATE scenario_service_month SET expense_amount = COALESCE(expense_amount, 0);",
    "UPDATE scenario_service_month SET cash_out = COALESCE(cash_out, 0);",
    "UPDATE scenario_service_month SET tax_amount = COALESCE(tax_amount, 0);",
]

# Indices
INDEXES = [
    ("ix_services_scenario", "CREATE INDEX IF NOT EXISTS ix_services_scenario ON scenario_services (scenario_id);"),
    ("ix_services_active",   "CREATE INDEX IF NOT EXISTS ix_services_active ON scenario_services (is_active);"),
    ("ix_service_month_sid", "CREATE INDEX IF NOT EXISTS ix_service_month_sid ON scenario_service_month (service_id);"),
    ("ix_service_month_ym",  "CREATE INDEX IF NOT EXISTS ix_service_month_ym ON scenario_service_month (year, month);"),
]

# updated_at trigger (SQLite auto-update yok)
TRIGGER_UPDATE_TS = """
CREATE TRIGGER IF NOT EXISTS trg_scenario_services_updated_at
AFTER UPDATE ON scenario_services
FOR EACH ROW
BEGIN
    UPDATE scenario_services
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;
"""

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # 0) scenarios güvence
    if not table_exists(cx, "scenarios"):
        print("[+] Creating table: scenarios (minimal + workflow)")
        cx.executescript(DDL_SCENARIOS_MIN)
    else:
        print("[=] scenarios exists.")

    # 1) scenario_services
    if not table_exists(cx, "scenario_services"):
        print("[+] Creating table: scenario_services (full schema)")
        cx.executescript(DDL_SCENARIO_SERVICES)
    else:
        print("[=] scenario_services exists. Checking columns…")
        cols = column_names(cx, "scenario_services")
        for col, ddl in ADD_COLS_SERVICES.items():
            if col not in cols:
                print(f"[+] Adding scenario_services.{col}")
                cx.execute(ddl)
            else:
                print(f"[=] scenario_services.{col} already present")

    # 1a) CHECK constraints için bilgi notu:
    # SQLite'ta ALTER ile CHECK ekleyemiyoruz; tablo baştan yaratmadan mümkün değil.
    # Bu nedenle CREATE aşamasında zaten CHECK var; ALTER ile eklenen ortamlarda
    # uygulama seviyesinde doğrulama yapılmalı.

    # 1b) updated_at trigger
    if not trigger_exists(cx, "trg_scenario_services_updated_at"):
        print("[+] Creating trigger: trg_scenario_services_updated_at")
        cx.executescript(TRIGGER_UPDATE_TS)
    else:
        print("[=] trigger trg_scenario_services_updated_at already present")

    # 2) scenario_service_month
    if not table_exists(cx, "scenario_service_month"):
        print("[+] Creating table: scenario_service_month (full schema)")
        cx.executescript(DDL_SCENARIO_SERVICE_MONTH)
    else:
        print("[=] scenario_service_month exists. Checking columns…")
        cols = column_names(cx, "scenario_service_month")
        for col, ddl in ADD_COLS_SERVICE_MONTH.items():
            if col not in cols:
                print(f"[+] Adding scenario_service_month.{col}")
                cx.execute(ddl)
            else:
                print(f"[=] scenario_service_month.{col} already present")

    # 3) Backfill
    print("[~] Backfilling defaults for scenario_services…")
    for sql in BACKFILL_SERVICES:
        cx.execute(sql)

    print("[~] Backfilling defaults for scenario_service_month…")
    for sql in BACKFILL_SERVICE_MONTH:
        cx.execute(sql)

    # 4) Indexler
    for name, sql in INDEXES:
        ensure_index(cx, name, sql)

    cx.commit()

    # 5) Özet
    def dump_table(table: str) -> None:
        print(f"\n=== {table} columns ===")
        for row in cx.execute(f"PRAGMA table_info({table});"):
            print(f"- {row[1]:24} | {row[2]:14} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    dump_table("scenarios")
    dump_table("scenario_services")
    dump_table("scenario_service_month")

    print("\n[✓] Services schema ready.")
    cx.close()

if __name__ == "__main__":
    main()
