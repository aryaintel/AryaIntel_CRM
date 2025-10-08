from typing import List, Optional, Dict
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import (
    Scenario,
    ScenarioCapex,
    ScenarioService,
    ScenarioServiceMonth,
    ScenarioBOQItem,
)
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
    reward_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Yüzde (örn. 50 → %50) [ANNUAL]")
    reward_spread_kind: Optional[str] = Field("even", description="even|follow_boq|custom")
    linked_boq_item_id: Optional[int] = Field(None, ge=1)
    term_months_override: Optional[int] = Field(None, ge=1, le=1200)

    # NEW: direct service link
    linked_service_id: Optional[int] = Field(None, ge=1)

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
    reward_pct: Optional[Decimal]       # ANNUAL %
    reward_spread_kind: Optional[str]
    linked_boq_item_id: Optional[int]
    term_months_override: Optional[int]

    # NEW
    linked_service_id: Optional[int]

    class Config:
        orm_mode = True


class CapexBulkIn(BaseModel):
    items: List[CapexIn]


class GenerateResult(BaseModel):
    linked_service_id: Optional[int] = None
    linked_boq_item_id: Optional[int] = None
    months: Optional[int] = None
    monthly_amount: Optional[Decimal] = None


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

    # NEW
    row.linked_service_id = payload.linked_service_id


def _ym_to_index(y: int, m: int) -> int:
    return y * 12 + (m - 1)


def _index_to_ym(i: int) -> Dict[str, int]:
    y = i // 12
    m = (i % 12) + 1
    return {"year": y, "month": m}


def _months_between(start_year: int, start_month: int, end_year: int, end_month: int) -> int:
    """start -> end arası ay farkı (start ile aynı ay = 0)."""
    return _ym_to_index(end_year, end_month) - _ym_to_index(start_year, start_month)


def _round2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_return_schedule_excel_monthly(
    scenario: Scenario,
    capex: ScenarioCapex,
) -> Dict[str, Decimal | int]:
    """
    EXCEL PARITY:
      - reward_pct is ANNUAL.
      - monthly_amount = CAPEX * (reward_pct/100) / 12  (constant each month)
      - Start = service_start (varsa) değilse scenario start.
      - Term = term_months_override varsa kullan; yoksa senaryonun kalan süresi (start'tan sona).
    """
    if not capex.reward_enabled:
        raise HTTPException(status_code=400, detail="Reward is not enabled for this CAPEX row.")

    # reward_pct: row > scenario default > error
    reward_pct = capex.reward_pct
    if reward_pct is None:
        reward_pct = getattr(scenario, "default_capex_reward_pct", None)
    if reward_pct is None or Decimal(reward_pct) <= 0:
        raise HTTPException(status_code=400, detail="Reward percent is missing or zero.")

    # Start YM
    if capex.service_start_year and capex.service_start_month:
        start_year = int(capex.service_start_year)
        start_month = int(capex.service_start_month)
    else:
        start_year = int(scenario.start_date.year)
        start_month = int(scenario.start_date.month)

    # Term
    if capex.term_months_override and capex.term_months_override > 0:
        term = int(capex.term_months_override)
    else:
        diff = _months_between(
            scenario.start_date.year, scenario.start_date.month, start_year, start_month
        )
        term = int(scenario.months - diff)
    if term <= 0:
        raise HTTPException(status_code=400, detail="Computed term is not positive. Check service start and scenario dates.")

    monthly_amount = _round2(Decimal(capex.amount) * Decimal(reward_pct) / Decimal(100) / Decimal(12))

    return {
        "start_year": start_year,
        "start_month": start_month,
        "term": term,
        "monthly_amount": monthly_amount,   # sabit, her ay
    }


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


# =========================
# Generators (Excel parity: annual%/12, constant monthly)
# =========================
@router.post(
    "/{scenario_id}/capex/{item_id}/generate/service",
    response_model=GenerateResult,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a Service from CAPEX (Annual return% / 12 → constant monthly, repeated for term)",
)
def generate_service_from_capex(
    scenario_id: int = Path(..., ge=1),
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioCapex, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="CAPEX item not found")

    # Idempotence
    if row.linked_service_id:
        return GenerateResult(linked_service_id=row.linked_service_id)

    sched = _compute_return_schedule_excel_monthly(sc, row)

    # Create parent service
    service = ScenarioService(
        scenario_id=scenario_id,
        service_name=f"CAPEX return – {row.asset_name or f'CAPEX #{row.id}'}",
        category="capex_return",
        vendor=None,
        unit="month",
        quantity=Decimal(1),
        unit_cost=sched["monthly_amount"],  # constant monthly expense
        currency="TRY",
        start_year=int(sched["start_year"]),
        start_month=int(sched["start_month"]),
        duration_months=int(sched["term"]),
        end_year=None,
        end_month=None,
        payment_term="monthly",
        cash_out_month_policy="service_month",
        escalation_pct=Decimal(0),
        escalation_freq="none",
        tax_rate=Decimal(0),
        expense_includes_tax=False,
        notes=f"Auto-generated from CAPEX #{row.id} at {row.reward_pct or sc.default_capex_reward_pct}% (annual) / 12",
        is_active=True,
    )
    db.add(service)
    db.commit()
    db.refresh(service)

    # Create month rows (constant)
    start_idx = _ym_to_index(service.start_year, service.start_month)
    term = int(sched["term"])
    monthly = sched["monthly_amount"]

    for i in range(term):
        ym = _index_to_ym(start_idx + i)
        db.add(
            ScenarioServiceMonth(
                service_id=service.id,
                year=ym["year"],
                month=ym["month"],
                expense_amount=monthly,
                cash_out=monthly,
                tax_amount=Decimal(0),
            )
        )

    # Link back to CAPEX
    row.linked_service_id = service.id
    db.add(row)
    db.commit()

    return GenerateResult(
        linked_service_id=service.id,
        months=term,
        monthly_amount=monthly,
    )


@router.post(
    "/{scenario_id}/capex/{item_id}/generate/boq",
    response_model=GenerateResult,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a BOQ line from CAPEX (Annual return% / 12 → constant monthly revenue, repeated for term)",
)
def generate_boq_from_capex(
    scenario_id: int = Path(..., ge=1),
    item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioCapex, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="CAPEX item not found")

    # Idempotence
    if row.linked_boq_item_id:
        return GenerateResult(linked_boq_item_id=row.linked_boq_item_id)

    sched = _compute_return_schedule_excel_monthly(sc, row)

    # Create BOQ item (monthly revenue)
    boq = ScenarioBOQItem(
        scenario_id=scenario_id,
        section="Services",
        item_name=f"CAPEX return – {row.asset_name or f'CAPEX #{row.id}'}",
        unit="month",
        quantity=Decimal(sched["term"]),                  # total months
        unit_price=sched["monthly_amount"],               # price per month (constant)
        unit_cogs=None,
        frequency="monthly",
        start_year=int(sched["start_year"]),
        start_month=int(sched["start_month"]),
        months=int(sched["term"]),
        formulation_id=None,
        price_escalation_policy_id=None,
        product_id=None,
        price_term=None,
        is_active=True,
        notes=f"Auto-generated from CAPEX #{row.id} at {row.reward_pct or sc.default_capex_reward_pct}% (annual) / 12",
        category=None,
    )
    db.add(boq)
    db.commit()
    db.refresh(boq)

    # Link back to CAPEX
    row.linked_boq_item_id = boq.id
    db.add(row)
    db.commit()

    return GenerateResult(
        linked_boq_item_id=boq.id,
        months=int(sched["term"]),
        monthly_amount=sched["monthly_amount"],
    )
