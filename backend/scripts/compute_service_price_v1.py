# backend/scripts/compute_service_price_v1.py
from pathlib import Path
import argparse
import sqlite3
from decimal import Decimal, getcontext

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"
getcontext().prec = 28

def get_index_value(cx, series_id: int, year: int, month: int):
    row = cx.execute(
        "SELECT value FROM index_points WHERE series_id=? AND year=? AND month=?",
        (series_id, year, month)
    ).fetchone()
    return Decimal(str(row[0])) if row else None

def compute_formulation_factor(cx, formulation_id: int, year: int, month: int) -> Decimal:
    comps = cx.execute("""
        SELECT index_series_id, weight_pct, base_index_value
        FROM formulation_components
        WHERE formulation_id = ?
    """, (formulation_id,)).fetchall()
    if not comps:
        raise RuntimeError("Formulation has no components.")
    factor = Decimal("0")
    for series_id, weight_pct, base_val in comps:
        if base_val is None:
            raise RuntimeError("base_index_value is NULL; base_ym otomatiği henüz yok.")
        curr = get_index_value(cx, series_id, year, month)
        if curr is None:
            raise RuntimeError(f"Missing index point for series={series_id} {year}-{month:02d}")
        ratio = curr / Decimal(str(base_val))
        w = Decimal(str(weight_pct)) / Decimal("100")
        factor += w * ratio
    return factor

def fetch_service_row(cx, service_id: int | None):
    base_sql = """
        SELECT s.id, s.service_name, s.quantity, s.unit_cost, s.currency,
               s.formulation_id, f.base_price, f.base_currency
        FROM scenario_services s
        LEFT JOIN product_formulations f ON s.formulation_id = f.id
    """
    if service_id is not None:
        row = cx.execute(base_sql + " WHERE s.id=?", (service_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Service id={service_id} bulunamadı.")
        return row
    # önce formülasyon bağlı en yeni satır
    row = cx.execute(base_sql + " WHERE s.formulation_id IS NOT NULL ORDER BY s.id DESC LIMIT 1").fetchone()
    if row:
        return row
    # yoksa ilk satır
    row = cx.execute(base_sql + " ORDER BY s.id LIMIT 1").fetchone()
    if not row:
        raise RuntimeError("No service line found. Önce seed_sample_service_line_v1.py çalıştır.")
    return row

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--service", type=int, default=None, help="service_id (opsiyonel)")
    p.add_argument("--ym", type=str, default="2024-10", help="YYYY-MM (varsayılan 2024-10)")
    args = p.parse_args()
    year, month = map(int, args.ym.split("-"))

    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    service_id, name, qty, unit_cost, cur, formulation_id, base_price, base_ccy = fetch_service_row(cx, args.service)

    print(f"Service #{service_id} - {name}")
    print(f"Target period: {year}-{month:02d}")
    print(f"Quantity={qty}, Stored unit_cost={unit_cost} {cur}")

    if formulation_id:
        factor = compute_formulation_factor(cx, formulation_id, year, month)
        base_price = Decimal(str(base_price or 0))
        price = (base_price * factor).quantize(Decimal("0.01"))
        line_total = (price * Decimal(str(qty or 1))).quantize(Decimal("0.01"))
        print(f"Formulation-linked ✓  (factor = {factor})")
        print(f"Base price: {base_price} {base_ccy or cur}")
        print(f"Computed unit price: {price} {base_ccy or cur}")
        print(f"Line total (qty x price): {line_total} {base_ccy or cur}")
    else:
        print("Formulation not set → stored unit_cost kullanılacak.")

    cx.close()

if __name__ == "__main__":
    main()
