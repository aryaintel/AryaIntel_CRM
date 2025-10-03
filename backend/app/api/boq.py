# backend/app/api/boq.py
from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete, func

from ..models import Scenario, ScenarioBOQItem
from .deps import get_db, get_current_user  # Current user dependency (token)
# Eğer projede izin kontrolü kullanıyorsanız şu satırı açın:
# from .deps import require_permissions

router = APIRouter(
    prefix="/scenarios",
    tags=["boq"],
)


# =========================
# Pydantic Schemas
# =========================
FREQ_ALLOWED = {"once", "monthly", "per_shipment", "per_tonne"}
CAT_ALLOWED = {None, "bulk_with_freight", "bulk_ex_freight", "freight"}


class BOQItemIn(BaseModel):
    section: Optional[str] = Field(None, max_length=50)
    item_name: str = Field(..., min_length=1, max_length=255)
    unit: str = Field(..., min_length=1, max_length=50)

    quantity: Decimal = Field(0, ge=0)
    unit_price: Decimal = Field(0, ge=0)
    unit_cogs: Optional[Decimal] = Field(None, ge=0)

    frequency: str = Field("once")
    start_year: Optional[int] = Field(None, ge=1900, le=3000)
    start_month: Optional[int] = Field(None, ge=1, le=12)
    months: Optional[int] = Field(None, ge=1, le=120)

    is_active: bool = True
    notes: Optional[str] = None

    category: Optional[str] = Field(None)  # SQLite CHECK ile doğrulanıyor

    @validator("frequency")
    def _freq_ok(cls, v: str) -> str:
        if v not in FREQ_ALLOWED:
            raise ValueError(f"frequency must be one of {sorted(FREQ_ALLOWED)}")
        return v

    @validator("category")
    def _cat_ok(cls, v: Optional[str]) -> Optional[str]:
        if v not in CAT_ALLOWED:
            raise ValueError("category must be one of "
                             "['bulk_with_freight','bulk_ex_freight','freight'] or null")
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
    is_active: bool
    notes: Optional[str]
    category: Optional[str]

    class Config:
        orm_mode = True


class BOQBulkIn(BaseModel):
    items: List[BOQItemIn]


# =========================
# Helpers
# =========================
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


# =========================
# Routes
# =========================
@router.get(
    "/{scenario_id}/boq",
    response_model=List[BOQItemOut],
    summary="List BOQ items in a scenario",
)
def list_boq_items(
    scenario_id: int = Path(..., ge=1),
    only_active: bool = Query(False),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    stmt = select(ScenarioBOQItem).where(ScenarioBOQItem.scenario_id == scenario_id)
    if only_active:
        stmt = stmt.where(ScenarioBOQItem.is_active.is_(True))
    stmt = stmt.order_by(ScenarioBOQItem.id.asc())
    rows = db.execute(stmt).scalars().all()
    return rows


@router.post(
    "/{scenario_id}/boq",
    response_model=BOQItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a BOQ item",
)
def create_boq_item(
    payload: BOQItemIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = ScenarioBOQItem(
        scenario_id=scenario_id,
        section=payload.section,
        item_name=payload.item_name,
        unit=payload.unit,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        unit_cogs=payload.unit_cogs,
        frequency=payload.frequency,
        start_year=payload.start_year,
        start_month=payload.start_month,
        months=payload.months,
        is_active=payload.is_active,
        notes=payload.notes,
        category=payload.category,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put(
    "/{scenario_id}/boq/{item_id}",
    response_model=BOQItemOut,
    summary="Update a BOQ item",
)
def update_boq_item(
    payload: BOQItemIn,
    scenario_id: int = Path(..., ge=1),
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioBOQItem, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="BOQ item not found")
    for k, v in payload.dict().items():
        setattr(row, k, v)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{scenario_id}/boq/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a BOQ item",
)
def delete_boq_item(
    scenario_id: int = Path(..., ge=1),
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioBOQItem, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="BOQ item not found")
    db.delete(row)
    db.commit()
    return None


@router.post(
    "/{scenario_id}/boq/bulk",
    response_model=List[BOQItemOut],
    summary="Bulk insert BOQ items (replaces nothing; pure append)",
)
def bulk_insert_boq_items(
    payload: BOQBulkIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    new_rows: List[ScenarioBOQItem] = []
    for item in payload.items:
        new_rows.append(
            ScenarioBOQItem(
                scenario_id=scenario_id,
                section=item.section,
                item_name=item.item_name,
                unit=item.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                unit_cogs=item.unit_cogs,
                frequency=item.frequency,
                start_year=item.start_year,
                start_month=item.start_month,
                months=item.months,
                is_active=item.is_active,
                notes=item.notes,
                category=item.category,
            )
        )
    db.add_all(new_rows)
    db.commit()
    for r in new_rows:
        db.refresh(r)
    return new_rows


@router.post(
    "/{scenario_id}/boq/mark-ready",
    summary="Mark BOQ as ready and move workflow to TWC",
)
def mark_boq_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)

    # En az bir aktif BOQ item olsun (Excel mantığı: boşsa ilerleme yok)
    has_any = db.execute(
        select(func.count(ScenarioBOQItem.id))
        .where(ScenarioBOQItem.scenario_id == scenario_id)
        .where(ScenarioBOQItem.is_active.is_(True))
    ).scalar_one()

    if not has_any:
        raise HTTPException(
            status_code=400,
            detail="No active BOQ items; cannot mark as ready."
        )

    # State transition: draft/boq -> twc
    sc.is_boq_ready = True
    sc.workflow_state = "twc"

    db.add(sc)
    db.commit()
    db.refresh(sc)

    return {
        "scenario_id": sc.id,
        "is_boq_ready": sc.is_boq_ready,
        "workflow_state": sc.workflow_state,
        "message": "BOQ marked as ready. Next step: TWC.",
    }
