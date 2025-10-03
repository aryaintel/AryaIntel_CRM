# backend/scripts/debug_link_formulation_v1.py
from pathlib import Path
import sqlite3

# === KULLANICI AYARI ===
SERVICE_ID = 1       # Hangi servis için kontrol/bağlama yapılacak
PICK_LATEST_FORM = True  # True: en son oluşturulmuş aktif formülasyonu al

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def cx():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con

def main():
    print(f"[i] DB = {DB_PATH}")
    with cx() as con:
        # 1) Servis satırını göster
        svc = con.execute(
            "SELECT id, service_name, formulation_id FROM scenario_services WHERE id=?",
            (SERVICE_ID,)
        ).fetchone()
        if not svc:
            print(f"[!] service id={SERVICE_ID} bulunamadı.")
            return

        print(f"[=] Service #{svc['id']} - {svc['service_name']!r} | formulation_id={svc['formulation_id']}")

        # 2) Zaten bağlıysa sadece bilgi ver
        if svc["formulation_id"]:
            print("[✓] Bu servis zaten formülasyona bağlı.")
            return

        # 3) Bağlanacak formülasyonu seç (en son eklenen)
        if PICK_LATEST_FORM:
            form = con.execute(
                "SELECT id, code, name FROM product_formulations "
                "WHERE is_active=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            form = con.execute(
                "SELECT id, code, name FROM product_formulations WHERE is_active=1 ORDER BY id LIMIT 1"
            ).fetchone()

        if not form:
            print("[!] Aktif bir product_formulations kaydı bulunamadı. Önce bir formül oluştur.")
            return

        print(f"[+] Bağlanacak formül: id={form['id']} code={form['code']} name={form['name']!r}")

        # 4) Servise yaz
        con.execute(
            "UPDATE scenario_services SET formulation_id=? WHERE id=?",
            (form["id"], SERVICE_ID)
        )
        con.commit()

        # 5) Son durumu göster
        svc2 = con.execute(
            "SELECT id, service_name, formulation_id FROM scenario_services WHERE id=?",
            (SERVICE_ID,)
        ).fetchone()
        print(f"[✓] Güncellendi: service_id={svc2['id']} -> formulation_id={svc2['formulation_id']}")

        # 6) Hızlı doğrulama için ilgili formülün bileşenlerini göster (opsiyonel)
        comps = con.execute(
            "SELECT index_series_id, weight_pct, base_index_value "
            "FROM formulation_components WHERE formulation_id=? ORDER BY id",
            (svc2["formulation_id"],)
        ).fetchall()
        print(f"[=] Formül bileşenleri ({len(comps)} adet):")
        for r in comps:
            print(f"    - series={r['index_series_id']}, w={r['weight_pct']}, base={r['base_index_value']}")

if __name__ == "__main__":
    main()
