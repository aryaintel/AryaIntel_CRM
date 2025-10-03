"""
Bir servis satırına formulation_id bağlar (günceller).
- SERVICE_ID: Bağlanacak scenario_services.id
- FORMULATION_ID: Doğrudan bağlanacak formulation (opsiyonel)
- PRODUCT_ID: FORMULATION_ID verilmezse bu ürüne ait en son oluşturulan formül alınır (opsiyonel)

Kullanım:
    cd backend
    python scripts/link_formulation_to_service_v3.py
"""

from pathlib import Path
import sqlite3
from typing import Optional

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# ---- KULLANICI PARAMETRELERİ ----
SERVICE_ID: int = 1             # <- bağlamak istediğiniz service id
FORMULATION_ID: Optional[int] = None
PRODUCT_ID: Optional[int] = None
# ---------------------------------


def db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx


def main() -> None:
    print(f"[i] DB = {DB_PATH}")
    with db() as cx:
        # --- scenario_services kaydını çek
        # Şema v1'de sütun adı 'service_name'
        svc = cx.execute(
            "SELECT id, service_name, formulation_id "
            "FROM scenario_services WHERE id=?;",
            (SERVICE_ID,)
        ).fetchone()

        if not svc:
            raise SystemExit(f"[x] scenario_services id={SERVICE_ID} bulunamadı.")

        print(f"[i] Servis bulundu => id={svc['id']} | name={svc['service_name']} | "
              f"mevcut formulation_id={svc['formulation_id']}")

        # --- Bağlanacak formulation id'yi belirle
        fid: Optional[int] = FORMULATION_ID

        if fid is None:
            if PRODUCT_ID is not None:
                row = cx.execute(
                    "SELECT id, code FROM product_formulations "
                    "WHERE product_id=? ORDER BY id DESC LIMIT 1;",
                    (PRODUCT_ID,)
                ).fetchone()
                if not row:
                    raise SystemExit(f"[x] product_id={PRODUCT_ID} için herhangi bir formulation bulunamadı.")
                fid = row["id"]
                fcode = row["code"]
            else:
                row = cx.execute(
                    "SELECT id, code FROM product_formulations "
                    "ORDER BY id DESC LIMIT 1;"
                ).fetchone()
                if not row:
                    raise SystemExit("[x] product_formulations tablosu boş.")
                fid = row["id"]
                fcode = row["code"]
        else:
            chk = cx.execute(
                "SELECT id, code FROM product_formulations WHERE id=?;",
                (fid,)
            ).fetchone()
            if not chk:
                raise SystemExit(f"[x] formulation_id={fid} bulunamadı.")
            fcode = chk["code"]

        print(f"[i] Bağlanacak formulation: id={fid} (code={fcode})")

        # --- Güncelle
        cx.execute(
            "UPDATE scenario_services SET formulation_id=? WHERE id=?;",
            (fid, SERVICE_ID)
        )
        cx.commit()

        # --- Doğrula
        new_svc = cx.execute(
            "SELECT id, service_name, formulation_id "
            "FROM scenario_services WHERE id=?;",
            (SERVICE_ID,)
        ).fetchone()
        print(f"[✓] Güncellendi: service_id={new_svc['id']} | "
              f"name={new_svc['service_name']} | formulation_id={new_svc['formulation_id']}")


if __name__ == "__main__":
    main()
