# backend/app/api/boq_pricing.py
from pathlib import Path
from decimal import Decimal, getcontext
import sqlite3
from fastapi import APIRouter, HTTPException, Query

getcontext().prec = 28

router = APIRouter(prefix="/api/boq", tags=["pricing"])

DB_PATH = Path(__file__).resolve().parents[2] / "app.db"  # backend/app/api/.. → backend/app.db

def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx

def _parse_ym(ym: str) -> tuple[int, int]:
    try:
        y, m = ym.split("-")
        return int(y), int(m)
    except Exception:
        raise HTTPException(400, "ym must be 'YYYY-MM'")

def _index_value(cx: sqlite3.Connection, series_id: int, year: int, month: int) -> Decimal:
    row = cx.execute(
        "SELECT value FROM index_points WHERE series_id=? AND year=? AND month=?",
        (series_id, year, month),
    ).fetchone()
    if not row:
        raise HTTPException(409, f"missing index point for series_id={series_id} at {year}-{month:02d}")
    return Decimal(str(row["value"]))

def _formulation_factor(cx: sqlite3.Connection, formulation_id: int, year: int, month: int) -> Decimal:
    comps = cx.execute(
        "SELECT index_series_id, weight_pct, base_index_value "
        "FROM formulation_components WHERE formulation_id=?",
        (formulation_id,),
    ).fetchall()
    if not comps:
        raise HTTPException(409, "formulation has no components")

    factor = Decimal("0")
    for c in comps:
        base = c["base_index_value"]
        if base is None:
            raise HTTPException(409, "base_index_value is NULL (set Base Ref)")
        curr = _index_value(cx, c["index_series_id"], year, month)
        ratio = curr / Decimal(str(base))
        w = Decimal(str(c["weight_pct"])) / Decimal("100")
        factor += w * ratio
    return factor

@router.get("/{boq_id}/price-preview")
def boq_price_preview(boq_id: int, ym: str = Query(..., description="YYYY-MM")):
    y, m = _parse_ym(ym)
    with _db() as cx:
        row = cx.execute(
            "SELECT b.id, b.item_name, b.quantity, b.unit_price, "
            "       b.formulation_id, f.base_price, f.base_currency "
            "FROM scenario_boq_items b "
            "LEFT JOIN product_formulations f ON b.formulation_id = f.id "
            "WHERE b.id = ?",
            (boq_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "boq item not found")
        if row["formulation_id"] is None:
            raise HTTPException(409, "boq item has no formulation_id")

        factor = _formulation_factor(cx, row["formulation_id"], y, m)
        base_price = Decimal(str(row["base_price"] or 0))
        unit_price = (base_price * factor).quantize(Decimal("0.01"))
        qty = Decimal(str(row["quantity"] or 1))
        line_total = (unit_price * qty).quantize(Decimal("0.01"))

        return {
            "id": row["id"],
            "name": row["item_name"],
            "period": ym,
            "currency": row["base_currency"] or "USD",
            "base_price": str(base_price),
            "factor": str(factor),
            "unit_price": str(unit_price),
            "quantity": str(qty),
            "line_total": str(line_total),
            "source": "boq",
        }
