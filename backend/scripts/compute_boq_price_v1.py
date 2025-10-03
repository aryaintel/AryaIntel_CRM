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
        raise RuntimeError("Formulation has no components")
    factor = Decimal("0")
    for series_id, weight_pct, base_val in comps:
        if base_val is None:
            raise RuntimeError("base_index_value is NULL; base_ym otomatiği eklenmemiş.")
        curr = get_index_value(cx, series_id, year, month)
        if curr is None:
            raise RuntimeError(f"Missing index point for series={series_id} {year}-{month:02d}")
        ratio = curr / Decimal(str(base_val))
        factor += (Decimal(str(weight_pct))/Decimal("100")) * ratio
    return factor

def fetch_boq_row(cx, boq_id: int | None):
    base_sql = """
        SELECT b.id, b.item_name, b.quantity, b.unit_price, b.formulation_id,
               f.base_price, f.base_currency
        FROM scenario_boq_items b
        LEFT JOIN product_formulations f ON b.formulation_id = f.id
    """
    if boq_id is not None:
        row = cx.execute(base_sql + " WHERE b.id=?", (boq_id,)).fetchone()
        if not row:
            raise RuntimeError(f"BOQ id={boq_id} not found")
        return row
    # önce formülasyon bağlı en yeni
    row = cx.execute(base_sql + " WHERE b.formulation_id IS NOT NULL ORDER BY b.id DESC LIMIT 1").fetchone()
    if row:
        return row
    # yoksa ilk satır
    row = cx.execute(base_sql + " ORDER BY b.id LIMIT 1").fetchone()
    if not row:
        raise RuntimeError("No BOQ item found. Run assign_formulation_to_boq.py first.")
    return row

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boq", type=int, default=None, help="boq item id")
    p.add_argument("--ym", type=str, default="2024-10", help="YYYY-MM (varsayılan 2024-10)")
    args = p.parse_args()
    year, month = map(int, args.ym.split("-"))

    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    boq_id, name, qty, stored_unit_price, formulation_id, base_price, base_ccy = fetch_boq_row(cx, args.boq)

    print(f"BOQ #{boq_id} - {name}")
    print(f"Target period: {year}-{month:02d}")
    print(f"Quantity={qty}, Stored unit_price={stored_unit_price}")

    if formulation_id:
        factor = compute_formulation_factor(cx, formulation_id, year, month)
        base_price = Decimal(str(base_price or 0))
        unit_price = (base_price * factor).quantize(Decimal("0.01"))
        line_total = (unit_price * Decimal(str(qty or 1))).quantize(Decimal("0.01"))
        print(f"Formulation-linked ✓ (factor={factor})")
        print(f"Base price: {base_price} {base_ccy or 'USD'}")
        print(f"Computed unit price: {unit_price} {base_ccy or 'USD'}")
        print(f"Line total (qty x price): {line_total} {base_ccy or 'USD'}")
    else:
        print("Formulation not set → stored unit_price kullanılacak.")

    cx.close()

if __name__ == "__main__":
    main()
