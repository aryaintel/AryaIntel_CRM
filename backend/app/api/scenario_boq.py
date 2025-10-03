from __future__ import annotations

from typing import List, Optional, Tuple
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from ..models import Scenario, ScenarioBOQItem
from .deps import get_db, get_current_user

# Router: explicit paths added per endpoint (both legacy and refactor paths)
router = APIRouter(tags=["boq"])


# ---------------------------
# Helpers
# ---------------------------
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _ym(year: Optional[int], month: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    if year is None and month is None:
        return None, None
    if year is None or month is None or not (1 <= int(month) <= 12):
        raise HTTPException(status_code=400, detail="Invalid start year/month")
    return int(year), int(month)


# ---------------------------
# Schemas
# ---------------------------
class BOQItemIn(BaseModel):
    section: Optional[str] = None
    item_name: str
    unit: str
    quantity: Decimal = Field(default=0)
    unit_price: Decimal = Field(default=0)
    unit_cogs: Optional[Decimal] = None

    frequency: str = Field(default="once")  # once|monthly|quarterly|annual
    start_year: Optional[int] = None
    start_month: Optional[int] = Field(default=None, ge=1, le=12)
    months: Optional[int] = None

    formulation_id: Optional[int] = None
    price_escalation_policy_id: Optional[int] = None

    is_active: bool = True
    notes: Optional[str] = None
    category: Optional[str] = None  # bulk_with_freight|bulk_ex_freight|freight

    @validator("frequency")
    def _freq_ok(cls, v: str) -> str:
        allowed = {"once", "monthly", "quarterly", "annual"}
        if v not in allowed:
            raise ValueError(f"frequency must be one of {sorted(allowed)}")
        return v

    @validator("category")
    def _cat_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"bulk_with_freight", "bulk_ex_freight", "freight"}
        if v not in allowed:
            raise ValueError(f"category must be one of {sorted(allowed)}")
        return v


class BOQItemOut(BaseModel):
    id: int
    scenario_id: int
    section: Optional[str]
    item_name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    unit_cogs: Optional[Decimal]
    frequency: str
    start_year: Optional[int]
    start_month: Optional[int]
    months: Optional[int]
    formulation_id: Optional[int]
    price_escalation_policy_id: Optional[int]
    is_active: bool
    notes: Optional[str]
    category: Optional[str]

    class Config:
        orm_mode = True


# ---------------------------
# LIST
# ---------------------------
@router.get("/scenarios/{scenario_id}/boq", response_model=List[BOQItemOut])
@router.get("/business-cases/scenarios/{scenario_id}/boq", response_model=List[BOQItemOut])
def list_boq_items(
    scenario_id: int = Path(..., ge=1),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    q = db.query(ScenarioBOQItem).filter(ScenarioBOQItem.scenario_id == scenario_id)
    if active is not None:
        q = q.filter(ScenarioBOQItem.is_active == bool(active))
    q = q.order_by(ScenarioBOQItem.id.desc())
    items = q.all()
    return items


# ---------------------------
# CREATE
# ---------------------------
@router.post("/scenarios/{scenario_id}/boq", status_code=status.HTTP_201_CREATED)
@router.post("/business-cases/scenarios/{scenario_id}/boq", status_code=status.HTTP_201_CREATED)
def create_boq_item(
    scenario_id: int,
    payload: BOQItemIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    sy, sm = _ym(payload.start_year, payload.start_month)

    item = ScenarioBOQItem(
        scenario_id=scenario_id,
        section=payload.section,
        item_name=payload.item_name,
        unit=payload.unit,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        unit_cogs=payload.unit_cogs,
        frequency=payload.frequency,
        start_year=sy,
        start_month=sm,
        months=payload.months,
        formulation_id=payload.formulation_id,
        price_escalation_policy_id=payload.price_escalation_policy_id,
        is_active=payload.is_active,
        notes=payload.notes,
        category=payload.category,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id}


# ---------------------------
# UPDATE
# ---------------------------
@router.put("/scenarios/{scenario_id}/boq/{item_id}")
@router.put("/business-cases/scenarios/{scenario_id}/boq/{item_id}")
def update_boq_item(
    scenario_id: int,
    item_id: int,
    payload: BOQItemIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    item = db.get(ScenarioBOQItem, item_id)
    if not item or item.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="BOQ item not found")

    sy, sm = _ym(payload.start_year, payload.start_month)

    for k, v in dict(
        section=payload.section,
        item_name=payload.item_name,
        unit=payload.unit,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        unit_cogs=payload.unit_cogs,
        frequency=payload.frequency,
        start_year=sy,
        start_month=sm,
        months=payload.months,
        formulation_id=payload.formulation_id,
        price_escalation_policy_id=payload.price_escalation_policy_id,
        is_active=payload.is_active,
        notes=payload.notes,
        category=payload.category,
    ).items():
        setattr(item, k, v)

    db.commit()
    return {"updated": 1}


# ---------------------------
# DELETE
# ---------------------------
@router.delete("/scenarios/{scenario_id}/boq/{item_id}")
@router.delete("/business-cases/scenarios/{scenario_id}/boq/{item_id}")
def delete_boq_item(
    scenario_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    item = db.get(ScenarioBOQItem, item_id)
    if not item or item.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="BOQ item not found")
    db.delete(item)
    db.commit()
    return {"deleted": True}


# ---------------------------
# MARK READY  (NEW)
# ---------------------------
@router.post("/scenarios/{scenario_id}/boq/mark-ready")
@router.post("/business-cases/scenarios/{scenario_id}/boq/mark-ready")
def mark_boq_ready(
    scenario_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)
    if not sc.is_boq_ready:
        sc.is_boq_ready = True
        db.commit()
    return {"ok": True}
