from pathlib import Path
import sqlite3
from datetime import date

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def ensure_one_service(cx, scenario_id: int) -> int:
    row = cx.execute("SELECT id FROM scenario_services WHERE scenario_id=? ORDER BY id LIMIT 1", (scenario_id,)).fetchone()
    if row:
        return row[0]
    # hiç yoksa minimal bir satır yarat
    today = date.today()
    cx.execute("""
        INSERT INTO scenario_services(
            scenario_id, service_name, unit, quantity, unit_cost, currency,
            start_year, start_month, payment_term, cash_out_month_policy,
            escalation_pct, escalation_freq, tax_rate, expense_includes_tax, is_active
        ) VALUES (?, 'Auto-Created Service', 'month', 1, 0, 'USD',
                  ?, ?, 'monthly', 'service_month', 0, 'none', 0, 0, 1)
    """, (scenario_id, today.year, today.month))
    cx.commit()
    return cx.execute("SELECT last_insert_rowid()").fetchone()[0]

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # 1) Senaryo
    scenario = cx.execute("SELECT id, name FROM scenarios ORDER BY id LIMIT 1").fetchone()
    if not scenario:
        raise RuntimeError("No scenario found.")
    scenario_id = scenario[0]

    # 2) Servis satırını garanti et
    service_id = ensure_one_service(cx, scenario_id)

    # 3) AN formülasyon id'si
    form = cx.execute("SELECT id, code FROM product_formulations WHERE code='AN' ORDER BY id DESC LIMIT 1").fetchone()
    if not form:
        raise RuntimeError("No AN formulation found. Önce seed scriptini çalıştırın.")
    formulation_id = form[0]

    # 4) Bağla
    cx.execute("UPDATE scenario_services SET formulation_id=? WHERE id=?", (formulation_id, service_id))
    cx.commit()
    print(f"[✓] Service id={service_id} → formulation id={formulation_id} ({form[1]})")

    cx.close()

if __name__ == "__main__":
    main()
