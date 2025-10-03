# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

SERVICE_ID = 2          # -> burada düzenleyin
FORMULATION_ID = 3      # -> burada düzenleyin

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")

    # var mı kontrol
    f = cx.execute("SELECT id, code FROM product_formulations WHERE id=?", (FORMULATION_ID,)).fetchone()
    if not f:
        raise SystemExit(f"[x] formulation_id={FORMULATION_ID} bulunamadı")

    s = cx.execute("SELECT id, service_name FROM scenario_services WHERE id=?", (SERVICE_ID,)).fetchone()
    if not s:
        raise SystemExit(f"[x] service_id={SERVICE_ID} bulunamadı")

    cx.execute("UPDATE scenario_services SET formulation_id=? WHERE id=?", (FORMULATION_ID, SERVICE_ID))
    cx.commit()

    new_row = cx.execute("SELECT id, service_name, formulation_id FROM scenario_services WHERE id=?", (SERVICE_ID,)).fetchone()
    print(f"[✓] Bağlandı: service_id={new_row['id']} '{new_row['service_name']}' -> formulation_id={new_row['formulation_id']} (code={f['code']})")
    cx.close()

if __name__ == "__main__":
    main()
