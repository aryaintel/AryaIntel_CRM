# Pathway: C:/Dev/AryaIntel_CRM/backend/app/api/boq_diagnostics_api.py
from __future__ import annotations

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from .deps import get_db

router = APIRouter(prefix="/api", tags=["boq"])

class CoverageResult(BaseModel):
    scenario_id: int
    section: str
    scenario_start: str
    scenario_months: int
    total_active_rows: int
    rows_in_window: int
    rows_before_window: int
    rows_after_window: int
    zero_value_rows: int
    notes: List[str]
    samples: List[Dict[str, Any]]

@router.get("/scenarios/{scenario_id}/boq/check-coverage", response_model=CoverageResult, summary="Diagnose BOQ coverage for a section (default AN)")
def check_boq_coverage(
    scenario_id: int = Path(..., ge=1),
    section: str = Query("AN", description="Section code: AN, EM, IE"),
    db: Session = Depends(get_db),
):
    sc = db.execute(text("""
        SELECT start_date, months FROM scenarios WHERE id=:sid
    """), {"sid": scenario_id}).mappings().first()
    if not sc:
        return CoverageResult(
            scenario_id=scenario_id, section=section, scenario_start="", scenario_months=0,
            total_active_rows=0, rows_in_window=0, rows_before_window=0, rows_after_window=0, zero_value_rows=0,
            notes=["scenario_not_found"], samples=[]
        )
    start_date = str(sc["start_date"])
    months = int(sc["months"])

    rows = db.execute(text("""
        SELECT id, section, quantity, unit_price, frequency, start_year, start_month, months as row_months, is_active
        FROM scenario_boq_items
        WHERE scenario_id=:sid AND is_active=1 AND (section=:section)
    """), {"sid": scenario_id, "section": section}).mappings().all()

    y0, m0, _ = [int(x) for x in start_date.split("-")]
    total = len(rows)
    before = after = inw = zero = 0
    samples: List[Dict[str, Any]] = []

    def _in_window(sy, sm, dur):
        if sy is None or sm is None:
            return True
        off = (int(sy) - y0) * 12 + (int(sm) - m0)
        dur = int(dur or months)
        if off >= months:      # starts after scenario end
            return False
        if off + max(1, dur) <= 0:  # ends before scenario start
            return False
        return True

    for r in rows:
        qty = float(r["quantity"] or 0.0)
        price = float(r["unit_price"] or 0.0)
        dur = int(r["row_months"] or months)
        sy = r["start_year"]; sm = r["start_month"]

        if qty * price == 0:
            zero += 1

        if sy is not None and sm is not None:
            off = (int(sy) - y0) * 12 + (int(sm) - m0)
            if off >= months:
                after += 1
            elif off + max(1, dur) <= 0:
                before += 1
            else:
                inw += 1
        else:
            inw += 1

        if len(samples) < 5:
            samples.append({
                "id": int(r["id"]),
                "start_year": sy,
                "start_month": sm,
                "duration_months": dur,
                "quantity": qty,
                "unit_price": price,
                "frequency": r["frequency"],
                "classification": "in_window" if _in_window(sy, sm, dur) else "out_of_window",
            })

    notes: List[str] = []
    if total == 0:
        notes.append("no_active_rows_for_section")
    if total > 0 and inw == 0:
        notes.append("all_rows_outside_scenario_window")
    if zero == total and total > 0:
        notes.append("all_rows_zero_value")

    return CoverageResult(
        scenario_id=scenario_id, section=section, scenario_start=start_date, scenario_months=months,
        total_active_rows=total, rows_in_window=inw, rows_before_window=before, rows_after_window=after,
        zero_value_rows=zero, notes=notes or ["ok"], samples=samples
    )
