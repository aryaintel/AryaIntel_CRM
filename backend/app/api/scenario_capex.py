from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Scenario, ScenarioCapex
from .deps import get_db, get_current_user  # auth token kontrolü (mevcut projedeki bağımlılık)

router = APIRouter(
    prefix="/api/scenarios",   # FIX: /scenarios -> /api/scenarios (global sözleşmeye uyum)
    tags=["capex"],
)

# =========================
# Allowed values (Excel paraleli)
# =========================
DEPR_ALLOWED = {"straight_line", "declining_balance", "sum_of_years"}
PARTIAL_MONTH_POLICY = {"full_month", "half_month", "actual_days"}
REWARD_SPREAD_ALLOWED = {"even", "follow_boq", "custom"}

# =========================
# Schemas
# =========================
class CapexIn(BaseModel):
    # Zaman & tutar (zorunlu)
    year: int = Field(..., ge=1900, le=3000)
    month: int = Field(..., ge=1, le=12)
    amount: Decimal = Field(..., ge=0)

    # Açıklama
    notes: Optional[str] = None

    # V2: varlık / amortisman
    asset_name: Optional[str] = None
    category: Optional[str] = None
    service_start_year: Optional[int] = Field(None, ge=1900, le=3000)
    service_start_month: Optional[int] = Field(None, ge=1, le=12)
    useful_life_months: Optional[int] = Field(None, ge=1, le=600)  # max 50y
    depr_method: Optional[str] = Field("straight_line")
    salvage_value: Optional[Decimal] = Field(0, ge=0)
    is_active: Optional[bool] = Field(True)

    # V3: ek alanlar
    disposal_year: Optional[int] = Field(None, ge=1900, le=3000)
    disposal_month: Optional[int] = Field(None, ge=1, le=12)
    disposal_proceeds: Optional[Decimal] = Field(0, ge=0)
    replace_at_end: Optional[bool] = Field(False)
    per_unit_cost: Optional[Decimal] = Field(None, ge=0)
    quantity: Optional[int] = Field(None, ge=0)
    contingency_pct: Optional[Decimal] = Field(0, ge=0, le=100)
    partial_month_policy: Optional[str] = Field("full_month")

    # NEW: Capex Reward alanları
    reward_enabled: Optional[bool] = Field(False, description="Capex Reward mekanizması açık mı?")
    reward_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Yüzde (örn. 50 → %50)")
    reward_spread_kind: Optional[str] = Field("even", description="even|follow_boq|custom")
    linked_boq_item_id: Optional[int] = Field(None, ge=1)
    term_months_override: Optional[int] = Field(None, ge=1, le=1200)

    # ---- validators ----
    @validator("depr_method")
    def _depr_ok(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in DEPR_ALLOWED:
            raise ValueError(f"depr_method must be one of {sorted(DEPR_ALLOWED)}")
        return v

    @validator("partial_month_policy")
    def _pmp_ok(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in PARTIAL_MONTH_POLICY:
            raise ValueError(f"partial_month_policy must be one of {sorted(PARTIAL_MONTH_POLICY)}")
        return v

    @validator("reward_spread_kind")
    def _reward_spread_ok(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in REWARD_SPREAD_ALLOWED:
            raise ValueError(f"reward_spread_kind must be one of {sorted(REWARD_SPREAD_ALLOWED)}")
        return v

    # Yalnızca para/oran alanlarını güvenle Decimal'e çevir
    @validator(
        "amount",
        "salvage_value",
        "disposal_proceeds",
        "per_unit_cost",
        "contingency_pct",
        "reward_pct",
        pre=True,
    )
    def _coerce_decimal(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            return v


class CapexOut(BaseModel):
    id: int
    scenario_id: int
    year: int
    month: int
    amount: Decimal
    notes: Optional[str]

    asset_name: Optional[str]
    category: Optional[str]
    service_start_year: Optional[int]
    service_start_month: Optional[int]
    useful_life_months: Optional[int]
    depr_method: Optional[str]
    salvage_value: Optional[Decimal]
    is_active: Optional[bool]

    disposal_year: Optional[int]
    disposal_month: Optional[int]
    disposal_proceeds: Optional[Decimal]
    replace_at_end: Optional[bool]
    per_unit_cost: Optional[Decimal]
    quantity: Optional[int]
    contingency_pct: Optional[Decimal]
    partial_month_policy: Optional[str]

    # NEW: Capex Reward alanları
    reward_enabled: Optional[bool]
    reward_pct: Optional[Decimal]
    reward_spread_kind: Optional[str]
    linked_boq_item_id: Optional[int]
    term_months_override: Optional[int]

    class Config:
        orm_mode = True


class CapexBulkIn(BaseModel):
    items: List[CapexIn]


# =========================
# Helpers
# =========================
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _materialize_amount(payload: CapexIn) -> Decimal:
    """
    Eğer per_unit_cost ve quantity doluysa, amount'ı onlardan türet.
    Excel'de sık yapılan bir kullanım; mevcut amount'u override eder.
    """
    if payload.per_unit_cost is not None and payload.quantity is not None:
        try:
            return (Decimal(str(payload.per_unit_cost)) * Decimal(str(payload.quantity))).quantize(Decimal("0.01"))
        except Exception:
            pass
    return Decimal(str(payload.amount))


def _apply_payload(row: ScenarioCapex, payload: CapexIn) -> None:
    """Tek yerde alan eşleme (create/update)."""
    row.year = payload.year
    row.month = payload.month
    row.amount = _materialize_amount(payload)
    row.notes = payload.notes
    row.asset_name = payload.asset_name
    row.category = payload.category
    row.service_start_year = payload.service_start_year
    row.service_start_month = payload.service_start_month
    row.useful_life_months = payload.useful_life_months
    row.depr_method = payload.depr_method
    row.salvage_value = payload.salvage_value
    row.is_active = payload.is_active
    row.disposal_year = payload.disposal_year
    row.disposal_month = payload.disposal_month
    row.disposal_proceeds = payload.disposal_proceeds
    row.replace_at_end = payload.replace_at_end
    row.per_unit_cost = payload.per_unit_cost
    row.quantity = payload.quantity
    row.contingency_pct = payload.contingency_pct
    row.partial_month_policy = payload.partial_month_policy

    # NEW: Capex Reward
    row.reward_enabled = payload.reward_enabled
    row.reward_pct = payload.reward_pct
    row.reward_spread_kind = payload.reward_spread_kind
    row.linked_boq_item_id = payload.linked_boq_item_id
    row.term_months_override = payload.term_months_override


# =========================
# Routes
# =========================
@router.get(
    "/{scenario_id}/capex",
    response_model=List[CapexOut],
    summary="List CAPEX items in a scenario",
)
def list_capex(
    scenario_id: int = Path(..., ge=1),
    only_active: bool = Query(False, description="Only active rows"),
    year: Optional[int] = Query(None, ge=1900, le=3000),
    year_from: Optional[int] = Query(None, ge=1900, le=3000),
    year_to: Optional[int] = Query(None, ge=1900, le=3000),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: Optional[int] = Query(None, ge=1, le=1000),
    offset: Optional[int] = Query(None, ge=0),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    stmt = select(ScenarioCapex).where(ScenarioCapex.scenario_id == scenario_id)

    if only_active:
        stmt = stmt.where(ScenarioCapex.is_active.is_(True))
    if year is not None:
        stmt = stmt.where(ScenarioCapex.year == year)
    if year_from is not None:
        stmt = stmt.where(ScenarioCapex.year >= year_from)
    if year_to is not None:
        stmt = stmt.where(ScenarioCapex.year <= year_to)
    if category:
        stmt = stmt.where(ScenarioCapex.category == category)

    stmt = stmt.order_by(ScenarioCapex.year.asc(), ScenarioCapex.month.asc(), ScenarioCapex.id.asc())

    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    rows = db.execute(stmt).scalars().all()
    return rows


@router.post(
    "/{scenario_id}/capex",
    response_model=CapexOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a CAPEX item",
)
def create_capex(
    payload: CapexIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = ScenarioCapex(scenario_id=scenario_id)
    _apply_payload(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put(
    "/{scenario_id}/capex/{item_id}",
    response_model=CapexOut,
    summary="Update a CAPEX item",
)
def update_capex(
    payload: CapexIn,
    scenario_id: int = Path(..., ge=1),
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioCapex, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="CAPEX item not found")

    _apply_payload(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{scenario_id}/capex/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a CAPEX item",
)
def delete_capex(
    scenario_id: int = Path(..., ge=1),
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioCapex, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="CAPEX item not found")
    db.delete(row)
    db.commit()
    return None


@router.post(
    "/{scenario_id}/capex/bulk",
    response_model=List[CapexOut],
    summary="Bulk insert CAPEX items (append only)",
)
def bulk_insert_capex(
    payload: CapexBulkIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    new_rows: List[ScenarioCapex] = []
    for item in payload.items:
        row = ScenarioCapex(scenario_id=scenario_id)
        _apply_payload(row, item)
        new_rows.append(row)

    db.add_all(new_rows)
    db.commit()
    for r in new_rows:
        db.refresh(r)
    return new_rows
