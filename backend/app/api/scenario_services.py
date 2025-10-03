# backend/app/api/scenario_services.py
from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Scenario, ScenarioService, ScenarioServiceMonth
from .deps import get_db, get_current_user  # auth token kontrolü (mevcut projedeki bağımlılık)

router = APIRouter(
    prefix="/scenarios",
    tags=["services"],
)

# =========================
# Allowed values (Excel paraleli)
# =========================
PAYMENT_TERM = {"monthly", "annual_prepaid", "one_time"}
CASH_OUT_POLICY = {"service_month", "start_month", "contract_anniversary"}
ESCALATION_FREQ = {"annual", "none"}

# =========================
# Schemas
# =========================
class ServiceIn(BaseModel):
    # Temel bilgiler
    service_name: str = Field(..., min_length=1)
    category: Optional[str] = None
    vendor: Optional[str] = None
    unit: Optional[str] = None

    # Fiyat / miktar
    quantity: Decimal = Field(1, gt=0)
    unit_cost: Decimal = Field(0, ge=0)
    currency: str = Field("TRY", min_length=3, max_length=3)

    # Zamanlama
    start_year: int = Field(..., ge=1900, le=3000)
    start_month: int = Field(..., ge=1, le=12)
    duration_months: Optional[int] = Field(None, ge=1, le=1200)
    end_year: Optional[int] = Field(None, ge=1900, le=3000)
    end_month: Optional[int] = Field(None, ge=1, le=12)

    # Ödeme & Nakit
    payment_term: str = Field("monthly")
    cash_out_month_policy: str = Field("service_month")

    # Endeks / Artış
    escalation_pct: Decimal = Field(0, ge=0)      # 0.10 = %10
    escalation_freq: str = Field("none")          # 'annual' | 'none'

    # Vergi
    tax_rate: Decimal = Field(0, ge=0)            # 0.20 = %20
    expense_includes_tax: bool = Field(False)

    # Diğer
    notes: Optional[str] = None
    is_active: bool = Field(True)

    # ---- Validators ----
    @validator("payment_term")
    def _pt_ok(cls, v: str) -> str:
        if v not in PAYMENT_TERM:
            raise ValueError(f"payment_term must be one of {sorted(PAYMENT_TERM)}")
        return v

    @validator("cash_out_month_policy")
    def _cop_ok(cls, v: str) -> str:
        if v not in CASH_OUT_POLICY:
            raise ValueError(f"cash_out_month_policy must be one of {sorted(CASH_OUT_POLICY)}")
        return v

    @validator("escalation_freq")
    def _ef_ok(cls, v: str) -> str:
        if v not in ESCALATION_FREQ:
            raise ValueError(f"escalation_freq must be one of {sorted(ESCALATION_FREQ)}")
        return v


class ServiceOut(ServiceIn):
    id: int
    scenario_id: int

    class Config:
        orm_mode = True


class ServiceBulkIn(BaseModel):
    items: List[ServiceIn]


class ServiceMonthOut(BaseModel):
    year: int
    month: int
    expense_amount: Decimal
    cash_out: Decimal
    tax_amount: Decimal

    class Config:
        orm_mode = True


# =========================
# Helpers
# =========================
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _ensure_service(db: Session, scenario_id: int, service_id: int) -> ScenarioService:
    svc = db.get(ScenarioService, service_id)
    if not svc or svc.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="Service item not found")
    return svc


# =========================
# Routes (Services CRUD)
# =========================
@router.get(
    "/{scenario_id}/services",
    response_model=List[ServiceOut],
    summary="List service (OPEX) items in a scenario",
)
def list_services(
    scenario_id: int = Path(..., ge=1),
    only_active: bool = Query(False),
    year: Optional[int] = Query(None, ge=1900, le=3000, description="Opsiyonel filtre: start_year"),
    vendor: Optional[str] = Query(None, description="Opsiyonel filtre"),
    category: Optional[str] = Query(None, description="Opsiyonel filtre"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    stmt = select(ScenarioService).where(ScenarioService.scenario_id == scenario_id)
    if only_active:
        stmt = stmt.where(ScenarioService.is_active.is_(True))
    if year is not None:
        stmt = stmt.where(ScenarioService.start_year == year)
    if vendor:
        stmt = stmt.where(ScenarioService.vendor == vendor)
    if category:
        stmt = stmt.where(ScenarioService.category == category)
    stmt = stmt.order_by(
        ScenarioService.start_year.asc(),
        ScenarioService.start_month.asc(),
        ScenarioService.id.asc(),
    )
    rows = db.execute(stmt).scalars().all()
    return rows


@router.post(
    "/{scenario_id}/services",
    response_model=ServiceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a service (OPEX) item",
)
def create_service(
    payload: ServiceIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = ScenarioService(
        scenario_id=scenario_id,
        service_name=payload.service_name,
        category=payload.category,
        vendor=payload.vendor,
        unit=payload.unit,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        currency=payload.currency,
        start_year=payload.start_year,
        start_month=payload.start_month,
        duration_months=payload.duration_months,
        end_year=payload.end_year,
        end_month=payload.end_month,
        payment_term=payload.payment_term,
        cash_out_month_policy=payload.cash_out_month_policy,
        escalation_pct=payload.escalation_pct,
        escalation_freq=payload.escalation_freq,
        tax_rate=payload.tax_rate,
        expense_includes_tax=payload.expense_includes_tax,
        notes=payload.notes,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put(
    "/{scenario_id}/services/{service_id}",
    response_model=ServiceOut,
    summary="Update a service (OPEX) item",
)
def update_service(
    payload: ServiceIn,
    scenario_id: int = Path(..., ge=1),
    service_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = _ensure_service(db, scenario_id, service_id)

    # Pydantic dict -> model alanlarına set
    for k, v in payload.dict().items():
        setattr(row, k, v)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{scenario_id}/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a service (OPEX) item",
)
def delete_service(
    scenario_id: int = Path(..., ge=1),
    service_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = _ensure_service(db, scenario_id, service_id)
    db.delete(row)
    db.commit()
    return None


@router.post(
    "/{scenario_id}/services/bulk",
    response_model=List[ServiceOut],
    summary="Bulk insert service items (append only)",
)
def bulk_insert_services(
    payload: ServiceBulkIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    new_rows: List[ScenarioService] = []
    for item in payload.items:
        # validator’lar Pydantic’te zaten çalıştı
        new_rows.append(
            ScenarioService(
                scenario_id=scenario_id,
                service_name=item.service_name,
                category=item.category,
                vendor=item.vendor,
                unit=item.unit,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                currency=item.currency,
                start_year=item.start_year,
                start_month=item.start_month,
                duration_months=item.duration_months,
                end_year=item.end_year,
                end_month=item.end_month,
                payment_term=item.payment_term,
                cash_out_month_policy=item.cash_out_month_policy,
                escalation_pct=item.escalation_pct,
                escalation_freq=item.escalation_freq,
                tax_rate=item.tax_rate,
                expense_includes_tax=item.expense_includes_tax,
                notes=item.notes,
                is_active=item.is_active,
            )
        )
    db.add_all(new_rows)
    db.commit()
    for r in new_rows:
        db.refresh(r)
    return new_rows


# =========================
# Routes (Months – opsiyonel görünüm)
# =========================
@router.get(
    "/{scenario_id}/services/{service_id}/months",
    response_model=List[ServiceMonthOut],
    summary="List monthly breakdown for a service item (if precomputed)",
)
def list_service_months(
    scenario_id: int = Path(..., ge=1),
    service_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    _ensure_service(db, scenario_id, service_id)

    stmt = (
        select(ScenarioServiceMonth)
        .where(ScenarioServiceMonth.service_id == service_id)
        .order_by(ScenarioServiceMonth.year.asc(), ScenarioServiceMonth.month.asc())
    )
    rows = db.execute(stmt).scalars().all()
    return rows
