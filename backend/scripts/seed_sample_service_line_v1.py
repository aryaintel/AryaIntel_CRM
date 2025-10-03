from pathlib import Path
import sqlite3
from datetime import date

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def table_has_rows(cx, table, where=""):
    q = f"SELECT 1 FROM {table} {where} LIMIT 1"
    return cx.execute(q).fetchone() is not None

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # 1) Senaryo al (ilkini kullan)
    scenario = cx.execute("SELECT id, name, start_date FROM scenarios ORDER BY id LIMIT 1").fetchone()
    if not scenario:
        raise RuntimeError("No scenario found. Lütfen önce bir senaryo oluşturun.")
    scenario_id, scenario_name, start_date = scenario
    if start_date:
        y, m, *_ = map(int, str(start_date).split("-"))
    else:
        today = date.today()
        y, m = today.year, today.month

    # 2) Servis yoksa basit bir tane ekle
    exists = table_has_rows(cx, "scenario_services", f"WHERE scenario_id={scenario_id}")
    if not exists:
        cx.execute("""
            INSERT INTO scenario_services(
                scenario_id, service_name, unit, quantity, unit_cost, currency,
                start_year, start_month, payment_term, cash_out_month_policy,
                escalation_pct, escalation_freq, tax_rate, expense_includes_tax,
                is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'monthly', 'service_month', 0, 'none', 0, 0, 1)
        """, (scenario_id, "Seeded FM Service", "month", 1, 0, "USD", y, m))
        cx.commit()
        print(f"[+] scenario_services: örnek satır eklendi (scenario_id={scenario_id})")
    else:
        print(f"[=] scenario_services: zaten satır var (scenario_id={scenario_id})")

    # 3) Bir adet BOQ satırı da eklemek istersen uncomment et
    # cx.execute("""
    #     INSERT INTO scenario_boq_items (scenario_id, item_name, unit, quantity, unit_price, frequency, is_active)
    #     VALUES (?, 'Seeded BOQ Item', 'ea', 1, 0, 'monthly', 1)
    # """, (scenario_id,))
    # cx.commit()

    # Özet
    row = cx.execute("SELECT id, service_name, start_year, start_month FROM scenario_services WHERE scenario_id=? ORDER BY id DESC LIMIT 1", (scenario_id,)).fetchone()
    print(f"[✓] Son servis satırı: id={row[0]}, name={row[1]}, {row[2]}-{row[3]:02d}")

    cx.close()

if __name__ == "__main__":
    main()
