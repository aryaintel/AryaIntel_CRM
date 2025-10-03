# backend/scripts/link_formulation_to_service_v2.py
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# ---- Parametreler ----
SERVICE_ID = 1             # Swagger'da denediğin service_id'yi yaz
FORMULATION_CODE = None    # Belirli bir kodu bağlamak istersen: "AN_45_55_v2" gibi
PRODUCT_ID = None          # Belirli bir product için en son formülasyonu seçmek istersen: 1 vb. (opsiyonel)

def db():
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys=ON;")
    return cx

def main():
    cx = db()

    # 1) Servis var mı?
    svc = cx.execute("SELECT id, name, formulation_id FROM scenario_services WHERE id=?;", (SERVICE_ID,)).fetchone()
    if not svc:
        raise SystemExit(f"[x] service_id={SERVICE_ID} bulunamadı.")
    print(f"[i] Service: id={svc['id']} name={svc['name']} (mevcut formulation_id={svc['formulation_id']})")

    # 2) Bağlanacak formülasyonu seç
    if FORMULATION_CODE:
        q = "SELECT id, code FROM product_formulations WHERE code=? ORDER BY id DESC LIMIT 1"
        f = cx.execute(q, (FORMULATION_CODE,)).fetchone()
        if not f:
            raise SystemExit(f"[x] FORMULATION_CODE={FORMULATION_CODE} bulunamadı.")
    elif PRODUCT_ID:
        q = "SELECT id, code FROM product_formulations WHERE product_id=? ORDER BY id DESC LIMIT 1"
        f = cx.execute(q, (PRODUCT_ID,)).fetchone()
        if not f:
            raise SystemExit(f"[x] product_id={PRODUCT_ID} için formülasyon bulunamadı.")
    else:
        # En son eklenen formülasyonu al
        f = cx.execute("SELECT id, code FROM product_formulations ORDER BY id DESC LIMIT 1").fetchone()
        if not f:
            raise SystemExit("[x] product_formulations tablosunda kayıt yok.")

    print(f"[i] Bağlanacak formulation: id={f['id']} code={f['code']}")

    # 3) Güncelle
    cx.execute("UPDATE scenario_services SET formulation_id=? WHERE id=?;", (f["id"], SERVICE_ID))
    cx.commit()

    # 4) Kontrol
    new_svc = cx.execute("SELECT id, name, formulation_id FROM scenario_services WHERE id=?;", (SERVICE_ID,)).fetchone()
    print(f"[✓] Güncellendi: service_id={new_svc['id']} formulation_id={new_svc['formulation_id']}")
    cx.close()

if __name__ == "__main__":
    main()
