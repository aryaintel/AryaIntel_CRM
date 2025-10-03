from pathlib import Path
import sqlite3
from typing import Optional, Tuple

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def get_one(cx, sql, args=()):
    cur = cx.execute(sql, args)
    return cur.fetchone()

def upsert_index_series(cx, code: str, name: str, unit: str="index",
                        country: Optional[str]=None, currency: Optional[str]=None) -> int:
    row = get_one(cx, "SELECT id FROM index_series WHERE code = ?", (code,))
    if row:
        cx.execute("UPDATE index_series SET name=?, unit=?, country=?, currency=? WHERE id=?",
                   (name, unit, country, currency, row[0]))
        return row[0]
    cur = cx.execute(
        "INSERT INTO index_series(code, name, unit, country, currency, source, fetch_adapter, is_active) "
        "VALUES (?,?,?,?,?, 'manual','manual',1)",
        (code, name, unit, country, currency)
    )
    return cur.lastrowid

def upsert_index_point(cx, series_id: int, year: int, month: int, value: float, source_ref: str="seed"):
    cx.execute(
        "INSERT OR REPLACE INTO index_points(series_id, year, month, value, source_ref) "
        "VALUES (?,?,?,?,?)",
        (series_id, year, month, value, source_ref)
    )

def ensure_product(cx, name: str, group: Optional[str]=None) -> int:
    # ürün tablosu projede farklı adla olabilir; varsayılan 'products'
    # yoksa minimal bir products tablosu açalım
    tbl_exists = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
    if not tbl_exists:
        cx.executescript("""
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          group_id INTEGER NULL
        );
        """)
    row = get_one(cx, "SELECT id FROM products WHERE name=?", (name,))
    if row: return row[0]
    cur = cx.execute("INSERT INTO products(name) VALUES (?)", (name,))
    return cur.lastrowid

def create_formulation(cx, product_id: int, code: str, name: str,
                       base_price: float, base_currency: str="USD",
                       version_no: int=1) -> int:
    cur = cx.execute(
        "INSERT INTO product_formulations(product_id, code, name, base_price, base_currency, version_no, is_active) "
        "VALUES (?,?,?,?,?,?,1)",
        (product_id, code, name, base_price, base_currency, version_no)
    )
    return cur.lastrowid

def add_formulation_component(cx, formulation_id: int, index_series_id: int,
                              weight_pct: float, base_index_value: Optional[float], note: str=""):
    cx.execute(
        "INSERT INTO formulation_components(formulation_id, index_series_id, weight_pct, base_index_value, note) "
        "VALUES (?,?,?,?,?)",
        (formulation_id, index_series_id, weight_pct, base_index_value, note)
    )

def main():
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # --- 1) Endeks serileri ---
    # Örnek: Excel ekranındaki gibi baz değerler: Ammonia=58.0, CPI=55.0
    cpi_id = upsert_index_series(cx, code="CPI_ALL_CAP", name="CPI All Capital Cities", unit="index", country="AU")
    amm_id = upsert_index_series(cx, code="AMMONIA", name="Ammonia (FOB Middle East)", unit="USD/tonne", country=None, currency="USD")

    # Aylık değerler (örnek)
    # Base ay = 2024-01  → Excel'deki "Base Ref"
    upsert_index_point(cx, cpi_id, 2024, 1, 55.0, "base-ref")
    upsert_index_point(cx, amm_id, 2024, 1, 58.0, "base-ref")

    # 2024-10 ayı için örnek güncel değerler (ekran örneği gibi yakın rakamlar)
    upsert_index_point(cx, cpi_id, 2024, 10, 56.0, "seed")
    upsert_index_point(cx, amm_id, 2024, 10, 61.0, "seed")

    # --- 2) Örnek ürün ve AN formülasyonu (45%/55%) ---
    prod_id = ensure_product(cx, "AN (Ammonium Nitrate)")

    # Base price = 100 birim (örnek). İstersen teklif baz fiyatını yaz.
    f_id = create_formulation(cx, product_id=prod_id, code="AN", name="Ammonium Nitrate AN (45% Amm + 55% CPI)",
                              base_price=100.0, base_currency="USD")

    # Bileşenler (Excel'deki RnF yapısı)
    add_formulation_component(cx, f_id, amm_id, weight_pct=45.0, base_index_value=58.0, note="Ammonia 45%")
    add_formulation_component(cx, f_id, cpi_id, weight_pct=55.0, base_index_value=55.0, note="CPI 55%")

    cx.commit()
    print("[✓] Seed tamamlandı.")
    print(f"  - index_series: CPI id={cpi_id}, AMMONIA id={amm_id}")
    print(f"  - formulation AN id={f_id} (product_id={prod_id})")
    cx.close()

if __name__ == "__main__":
    main()
