from pathlib import Path
import sqlite3
from datetime import date

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def ensure_one_boq(cx, scenario_id: int) -> int:
    row = cx.execute("SELECT id FROM scenario_boq_items WHERE scenario_id=? ORDER BY id LIMIT 1",
                     (scenario_id,)).fetchone()
    if row:
        return row[0]
    # hiç yoksa minimal bir BOQ kalemi oluştur
    today = date.today()
    cx.execute("""
        INSERT INTO scenario_boq_items(
            scenario_id, section, item_name, unit, quantity, unit_price, unit_cogs,
            frequency, start_year, start_month, is_active
        ) VALUES (?, 'A', 'Seeded BOQ Item', 'ea', 1, 0, NULL,
                  'monthly', ?, ?, 1)
    """, (scenario_id, today.year, today.month))
    cx.commit()
    return cx.execute("SELECT last_insert_rowid()").fetchone()[0]

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # Senaryo
    scenario = cx.execute("SELECT id, name FROM scenarios ORDER BY id LIMIT 1").fetchone()
    if not scenario:
        raise RuntimeError("No scenario found.")
    scenario_id = scenario[0]

    # BOQ kalemini garanti et
    boq_id = ensure_one_boq(cx, scenario_id)

    # Formülasyon (AN)
    form = cx.execute("SELECT id, code FROM product_formulations WHERE code='AN' ORDER BY id DESC LIMIT 1").fetchone()
    if not form:
        raise RuntimeError("No AN formulation found. Run seed_indices_formulations_v1.py first.")
    formulation_id, code = form

    # Bağla
    cx.execute("UPDATE scenario_boq_items SET formulation_id=? WHERE id=?", (formulation_id, boq_id))
    cx.commit()
    print(f"[✓] BOQ id={boq_id} → formulation id={formulation_id} ({code})")

    cx.close()

if __name__ == "__main__":
    main()
