from pathlib import Path
import sqlite3
from decimal import Decimal, getcontext

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"
getcontext().prec = 28  # yüksek hassasiyet

def get_index_value(cx, series_id: int, year: int, month: int):
    row = cx.execute(
        "SELECT value FROM index_points WHERE series_id=? AND year=? AND month=?",
        (series_id, year, month)
    ).fetchone()
    return Decimal(str(row[0])) if row else None

def compute_formulation_factor(cx, formulation_id: int, year: int, month: int) -> Decimal:
    comps = cx.execute("""
        SELECT fc.index_series_id, fc.weight_pct, fc.base_index_value
        FROM formulation_components fc
        WHERE fc.formulation_id = ?
    """, (formulation_id,)).fetchall()
    if not comps:
        raise RuntimeError("Formulation has no components")

    factor = Decimal("0")
    for (series_id, weight_pct, base_val) in comps:
        if base_val is None:
            raise RuntimeError("base_index_value is NULL; set base or implement base_ym logic.")
        curr = get_index_value(cx, series_id, year, month)
        if curr is None:
            raise RuntimeError(f"Missing index point for series={series_id} {year}-{month:02d}")
        ratio = curr / Decimal(str(base_val))
        w = Decimal(str(weight_pct)) / Decimal("100")
        factor += w * ratio
    return factor

def preview(cx, formulation_id: int, year: int, month: int):
    frow = cx.execute(
        "SELECT base_price, base_currency, code, name FROM product_formulations WHERE id=?",
        (formulation_id,)
    ).fetchone()
    if not frow:
        raise RuntimeError("Formulation not found")
    base_price = Decimal(str(frow[0])) if frow[0] is not None else Decimal("0")
    base_ccy = frow[1] or "USD"
    code, name = frow[2], frow[3]

    factor = compute_formulation_factor(cx, formulation_id, year, month)
    price = (base_price * factor).quantize(Decimal("0.01"))

    print(f"Formulation: {code} - {name}")
    print(f"Target period: {year}-{month:02d}")
    print(f"Factor (Σ w_i * Index_i(t)/Base_i): {factor}")
    print(f"Base price: {base_price} {base_ccy}")
    print(f"New price:  {price} {base_ccy}")

def main():
    cx = sqlite3.connect(str(DB_PATH))
    # Örnek: seed script'in oluşturduğu AN formülasyonunu bulalım (son eklenen)
    fid = cx.execute("SELECT id FROM product_formulations WHERE code='AN' ORDER BY id DESC LIMIT 1").fetchone()
    if not fid:
        raise RuntimeError("No 'AN' formulation found. Run seed_indices_formulations_v1.py first.")
    fid = fid[0]

    # 2024-10 için önizleme (seed'te 2024-10 değerleri girdik)
    preview(cx, fid, 2024, 10)
    cx.close()

if __name__ == "__main__":
    main()
