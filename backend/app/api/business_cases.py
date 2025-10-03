# backend/app/api/business_cases.py
from datetime import date
from typing import List, Optional, Dict, Any, Tuple, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, conint, confloat
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..models import (
    BusinessCase,
    Scenario,
    ScenarioProduct,
    ScenarioProductMonth,
    ScenarioOverhead,
    ScenarioService,               # <-- NEW: services P&L'e katılıyor
    Opportunity,
)
from .deps import get_db, get_current_user, CurrentUser, require_permissions

router = APIRouter(prefix="/business-cases", tags=["business-cases"])

# ---------------------------
# Pydantic Schemas
# ---------------------------

class BusinessCaseCreate(BaseModel):
    opportunity_id: int = Field(..., description="Opportunity ID (1:1 relationship)")
    name: str = Field(..., min_length=1, max_length=255)

class ScenarioCreate(BaseModel):
    business_case_id: int
    name: str = Field(..., min_length=1, max_length=255)
    months: conint(gt=0, le=120) = 36
    start_date: date

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    price: confloat(ge=0) = 0.0
    unit_cogs: confloat(ge=0) = 0.0

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    price: Optional[confloat(ge=0)] = None
    unit_cogs: Optional[confloat(ge=0)] = None
    is_active: Optional[bool] = None

class MonthQty(BaseModel):
    year: conint(ge=1900, le=2200)
    month: conint(ge=1, le=12)
    quantity: confloat(ge=0) = 0.0

class PLParams(BaseModel):
    # MVP için boş – gelecekte: WACC, discount toggle vs.
    pass

class ScenarioOut(BaseModel):
    id: int
    name: str
    months: int
    start_date: date

    class Config:
        from_attributes = True

class BusinessCaseOut(BaseModel):
    id: int
    opportunity_id: int
    name: str
    scenarios: List[ScenarioOut]

    class Config:
        from_attributes = True

# ---- Scenario Detail Schemas ----
class ProductMonthOut(BaseModel):
    year: int
    month: int
    quantity: float

class ProductWithMonthsOut(BaseModel):
    id: int
    name: str
    price: float
    unit_cogs: float
    is_active: bool
    months: List[ProductMonthOut]

class OverheadOut(BaseModel):
    id: int
    name: str
    type: str
    amount: float

class ScenarioDetailOut(BaseModel):
    id: int
    business_case_id: int
    name: str
    months: int
    start_date: date
    products: List[ProductWithMonthsOut]
    overheads: List[OverheadOut]

# ---- Overhead Create/Update Schemas ----
class OverheadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["fixed", "%_revenue"]
    amount: confloat(ge=0) = 0.0

class OverheadUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[Literal["fixed", "%_revenue"]] = None
    amount: Optional[confloat(ge=0)] = None

# ---------------------------
# Helpers
# ---------------------------

def _ensure_opportunity_in_tenant(
    db: Session, tenant_id: int, opportunity_id: int
) -> Opportunity:
    opp = (
        db.query(Opportunity)
        .filter(Opportunity.id == opportunity_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not opp:
        raise HTTPException(
            status_code=404, detail="Opportunity not found for this tenant"
        )
    return opp

def _ensure_business_case_in_tenant(db: Session, tenant_id: int, bc_id: int) -> BusinessCase:
    bc = (
        db.query(BusinessCase)
        .join(Opportunity, BusinessCase.opportunity_id == Opportunity.id)
        .filter(BusinessCase.id == bc_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not bc:
        raise HTTPException(status_code=404, detail="Business case not found")
    return bc

def _ensure_scenario_in_tenant(db: Session, tenant_id: int, scenario_id: int) -> Scenario:
    sc = (
        db.query(Scenario)
        .join(BusinessCase, Scenario.business_case_id == BusinessCase.id)
        .join(Opportunity, BusinessCase.opportunity_id == Opportunity.id)
        .filter(Scenario.id == scenario_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc

def _ensure_product_in_tenant(
    db: Session, tenant_id: int, product_id: int
) -> ScenarioProduct:
    prod = (
        db.query(ScenarioProduct)
        .join(Scenario, ScenarioProduct.scenario_id == Scenario.id)
        .join(BusinessCase, Scenario.business_case_id == BusinessCase.id)
        .join(Opportunity, BusinessCase.opportunity_id == Opportunity.id)
        .filter(ScenarioProduct.id == product_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not prod:
        raise HTTPException(status_code=404, detail="Scenario product not found")
    return prod

def _ensure_overhead_in_tenant(
    db: Session, tenant_id: int, overhead_id: int
) -> ScenarioOverhead:
    ovh = (
        db.query(ScenarioOverhead)
        .join(Scenario, ScenarioOverhead.scenario_id == Scenario.id)
        .join(BusinessCase, Scenario.business_case_id == BusinessCase.id)
        .join(Opportunity, BusinessCase.opportunity_id == Opportunity.id)
        .filter(ScenarioOverhead.id == overhead_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not ovh:
        raise HTTPException(status_code=404, detail="Scenario overhead not found")
    return ovh

# ---------------------------
# Endpoints
# ---------------------------

@router.post(
    "/",
    response_model=BusinessCaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Business Case (1:1 with Opportunity)",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def create_business_case(
    body: BusinessCaseCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _ensure_opportunity_in_tenant(db, current.tenant_id, body.opportunity_id)

    # Enforce 1:1 – aynı opportunity için mevcut BC var mı?
    exists = (
        db.query(BusinessCase.id)
        .filter(BusinessCase.opportunity_id == body.opportunity_id)
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=409, detail="This opportunity already has a business case"
        )

    bc = BusinessCase(opportunity_id=body.opportunity_id, name=body.name)
    db.add(bc)
    db.commit()
    db.refresh(bc)

    return BusinessCaseOut.model_validate(
        {"id": bc.id, "opportunity_id": bc.opportunity_id, "name": bc.name, "scenarios": []}
    )

@router.get(
    "/{business_case_id}",
    response_model=BusinessCaseOut,
    summary="Get Business Case (includes scenarios)",
    dependencies=[Depends(require_permissions(["cases:read"]))],
)
def get_business_case(
    business_case_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    bc = _ensure_business_case_in_tenant(db, current.tenant_id, business_case_id)

    scenarios = (
        db.query(Scenario)
        .filter(Scenario.business_case_id == bc.id)
        .order_by(Scenario.id.asc())
        .all()
    )
    return BusinessCaseOut.model_validate(
        {
            "id": bc.id,
            "opportunity_id": bc.opportunity_id,
            "name": bc.name,
            "scenarios": scenarios,
        }
    )

# ---------- NEW: Get Business Case by Opportunity (includes scenarios) ----------
@router.get(
    "/by-opportunity/{opportunity_id}",
    response_model=BusinessCaseOut,
    summary="Get Business Case by Opportunity (includes scenarios)",
    dependencies=[Depends(require_permissions(["cases:read"]))],
)
def get_business_case_by_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    # Önce tenant doğrulaması
    _ensure_opportunity_in_tenant(db, current.tenant_id, opportunity_id)

    bc = db.query(BusinessCase).filter(BusinessCase.opportunity_id == opportunity_id).first()
    if not bc:
        raise HTTPException(
            status_code=404, detail="Business case not found for this opportunity"
        )

    scenarios = (
        db.query(Scenario)
        .filter(Scenario.business_case_id == bc.id)
        .order_by(Scenario.id.asc())
        .all()
    )
    return BusinessCaseOut.model_validate(
        {
            "id": bc.id,
            "opportunity_id": bc.opportunity_id,
            "name": bc.name,
            "scenarios": scenarios,
        }
    )

# -------- Scenarios --------
scenarios_router = APIRouter(prefix="/scenarios", tags=["scenarios"])

@scenarios_router.post(
    "",
    response_model=ScenarioOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Scenario under Business Case",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def create_scenario(
    body: ScenarioCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _ = _ensure_business_case_in_tenant(db, current.tenant_id, body.business_case_id)

    sc = Scenario(
        business_case_id=body.business_case_id,
        name=body.name,
        months=body.months,
        start_date=body.start_date,
    )
    db.add(sc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Scenario name must be unique per business case"
        )
    db.refresh(sc)
    return sc

@scenarios_router.get(
    "/{scenario_id}",
    response_model=ScenarioDetailOut,
    summary="Get Scenario detail with products, monthly quantities and overheads",
    dependencies=[Depends(require_permissions(["cases:read"]))],
)
def get_scenario_detail(
    scenario_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    sc = _ensure_scenario_in_tenant(db, current.tenant_id, scenario_id)

    # Products
    products: List[ScenarioProduct] = (
        db.query(ScenarioProduct)
        .filter(ScenarioProduct.scenario_id == sc.id)
        .order_by(ScenarioProduct.id.asc())
        .all()
    )
    product_ids = [p.id for p in products]

    # Months for products
    months_rows: List[ScenarioProductMonth] = []
    if product_ids:
        months_rows = (
            db.query(ScenarioProductMonth)
            .filter(ScenarioProductMonth.scenario_product_id.in_(product_ids))
            .order_by(
                ScenarioProductMonth.scenario_product_id.asc(),
                ScenarioProductMonth.year.asc(),
                ScenarioProductMonth.month.asc(),
            )
            .all()
        )

    months_by_prod: Dict[int, List[ProductMonthOut]] = {}
    for r in months_rows:
        months_by_prod.setdefault(r.scenario_product_id, []).append(
            ProductMonthOut(
                year=int(r.year), month=int(r.month), quantity=float(r.quantity or 0.0)
            )
        )

    products_out: List[ProductWithMonthsOut] = []
    for p in products:
        products_out.append(
            ProductWithMonthsOut(
                id=p.id,
                name=p.name,
                price=float(p.price or 0.0),
                unit_cogs=float(p.unit_cogs or 0.0),
                is_active=bool(p.is_active),
                months=months_by_prod.get(p.id, []),
            )
        )

    # Overheads
    overheads = (
        db.query(ScenarioOverhead)
        .filter(ScenarioOverhead.scenario_id == sc.id)
        .order_by(ScenarioOverhead.id.asc())
        .all()
    )
    overheads_out = [
        OverheadOut(id=h.id, name=h.name, type=h.type, amount=float(h.amount or 0.0))
        for h in overheads
    ]

    return ScenarioDetailOut(
        id=sc.id,
        business_case_id=sc.business_case_id,
        name=sc.name,
        months=sc.months,
        start_date=sc.start_date,
        products=products_out,
        overheads=overheads_out,
    )

@scenarios_router.post(
    "/{scenario_id}/products",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create Product under Scenario",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def add_product_to_scenario(
    scenario_id: int,
    body: ProductCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    sc = _ensure_scenario_in_tenant(db, current.tenant_id, scenario_id)

    prod = ScenarioProduct(
        scenario_id=sc.id,
        name=body.name,
        price=body.price,
        unit_cogs=body.unit_cogs,
        is_active=True,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)

    return {
        "id": prod.id,
        "scenario_id": prod.scenario_id,
        "name": prod.name,
        "price": float(prod.price or 0),
        "unit_cogs": float(prod.unit_cogs or 0),
        "is_active": prod.is_active,
    }

@scenarios_router.patch(
    "/products/{product_id}",
    response_model=Dict[str, Any],
    summary="Update Scenario Product (partial)",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def update_product(
    product_id: int,
    body: ProductUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    prod = _ensure_product_in_tenant(db, current.tenant_id, product_id)
    data = body.model_dump(exclude_unset=True)

    for k, v in data.items():
        setattr(prod, k, v)

    db.commit()
    db.refresh(prod)

    return {
        "id": prod.id,
        "scenario_id": prod.scenario_id,
        "name": prod.name,
        "price": float(prod.price or 0),
        "unit_cogs": float(prod.unit_cogs or 0),
        "is_active": prod.is_active,
    }

@scenarios_router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Scenario Product",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    prod = _ensure_product_in_tenant(db, current.tenant_id, product_id)
    db.delete(prod)
    db.commit()
    return None

@scenarios_router.put(
    "/products/{product_id}/months",
    response_model=Dict[str, Any],
    summary="Bulk upsert monthly quantities for a product",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def upsert_product_months(
    product_id: int,
    items: List[MonthQty],
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    prod = _ensure_product_in_tenant(db, current.tenant_id, product_id)

    stmt = text(
        """
        INSERT INTO scenario_product_months (scenario_product_id, year, month, quantity)
        VALUES (:pid, :year, :month, :quantity)
        ON CONFLICT(scenario_product_id, year, month)
        DO UPDATE SET quantity = excluded.quantity
        """
    )

    payload = [
        {"pid": prod.id, "year": it.year, "month": it.month, "quantity": it.quantity}
        for it in items
    ]
    if payload:
        db.execute(stmt, payload)
    db.commit()

    return {"updated": len(payload), "product_id": prod.id}

# ---- Overheads CRUD ----

@scenarios_router.post(
    "/{scenario_id}/overheads",
    response_model=OverheadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Overhead under Scenario",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def create_overhead(
    scenario_id: int,
    body: OverheadCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    sc = _ensure_scenario_in_tenant(db, current.tenant_id, scenario_id)

    ovh = ScenarioOverhead(
        scenario_id=sc.id,
        name=body.name,
        type=body.type,
        amount=body.amount,
    )
    db.add(ovh)
    db.commit()
    db.refresh(ovh)

    return OverheadOut(
        id=ovh.id, name=ovh.name, type=ovh.type, amount=float(ovh.amount or 0)
    )

@scenarios_router.patch(
    "/overheads/{overhead_id}",
    response_model=OverheadOut,
    summary="Update Overhead (partial)",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def update_overhead(
    overhead_id: int,
    body: OverheadUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    ovh = _ensure_overhead_in_tenant(db, current.tenant_id, overhead_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(ovh, k, v)

    db.commit()
    db.refresh(ovh)
    return OverheadOut(
        id=ovh.id, name=ovh.name, type=ovh.type, amount=float(ovh.amount or 0)
    )

@scenarios_router.delete(
    "/overheads/{overhead_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Overhead",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def delete_overhead(
    overhead_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    ovh = _ensure_overhead_in_tenant(db, current.tenant_id, overhead_id)
    db.delete(ovh)
    db.commit()
    return None

# ---- Compute (P&L) ----

@scenarios_router.post(
    "/{scenario_id}/compute",
    response_model=Dict[str, Any],
    summary="Compute monthly P&L for a scenario (Revenue, COGS, Overheads, Services OPEX, Depreciation)",
    dependencies=[Depends(require_permissions(["cases:read"]))],
)
def compute_scenario_pl(
    scenario_id: int,
    _: PLParams = None,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    sc = _ensure_scenario_in_tenant(db, current.tenant_id, scenario_id)

    # ---- Overheads (fixed + % revenue)
    overheads = (
        db.query(ScenarioOverhead)
        .filter(ScenarioOverhead.scenario_id == sc.id)
        .all()
    )
    fixed_sum = sum(float(h.amount or 0) for h in overheads if h.type == "fixed")
    pct_sum = sum(float(h.amount or 0) for h in overheads if h.type == "%_revenue")

    # ---- Revenue & COGS (by month)
    rows = (
        db.query(
            ScenarioProductMonth.year.label("y"),
            ScenarioProductMonth.month.label("m"),
            func.sum(ScenarioProduct.price * ScenarioProductMonth.quantity).label(
                "revenue"
            ),
            func.sum(ScenarioProduct.unit_cogs * ScenarioProductMonth.quantity).label(
                "cogs"
            ),
        )
        .join(
            ScenarioProduct,
            ScenarioProduct.id == ScenarioProductMonth.scenario_product_id,
        )
        .join(Scenario, Scenario.id == ScenarioProduct.scenario_id)
        .filter(Scenario.id == sc.id)
        .group_by(ScenarioProductMonth.year, ScenarioProductMonth.month)
        .all()
    )
    rev_cogs: Dict[Tuple[int, int], Tuple[float, float]] = {}
    for r in rows:
        rev_cogs[(int(r.y), int(r.m))] = (float(r.revenue or 0), float(r.cogs or 0))

    # ---- Services (OPEX) monthly expense
    # P&L için giderler: monthly veya annual_prepaid fark etmeksizin aylık ayrıştırılır.
    # one_time → sadece başlangıç ayına P&L gideri olarak yazılır.
    def next_ym(y: int, m: int) -> Tuple[int, int]:
        return (y + 1, 1) if m == 12 else (y, m + 1)

    timeline: List[Tuple[int, int]] = []
    ty, tm = sc.start_date.year, sc.start_date.month
    for _i in range(sc.months):
        timeline.append((ty, tm))
        ty, tm = next_ym(ty, tm)
    timeline_set = set(timeline)

    services: List[ScenarioService] = (
        db.query(ScenarioService)
        .filter(ScenarioService.scenario_id == sc.id, ScenarioService.is_active.is_(True))
        .all()
    )
    services_by_ym: Dict[Tuple[int, int], float] = {}

    for s in services:
        start_y, start_m = int(s.start_year), int(s.start_month)
        # bitiş: duration_months öncelikli, yoksa end_y/m, hiçbiri yoksa 1 ay (one_time ise zaten tek ay)
        if s.duration_months and s.duration_months > 0:
            total_months = int(s.duration_months)
            ey, em = start_y, start_m
            for _ in range(total_months - 1):
                ey, em = next_ym(ey, em)
        elif s.end_year and s.end_month:
            ey, em = int(s.end_year), int(s.end_month)
            # güvenlik: eğer end < start ise tek ay
            if (ey < start_y) or (ey == start_y and em < start_m):
                ey, em = start_y, start_m
        else:
            # default: one_time ise bir ay, değilse senaryo süresi kadar (başlangıçtan itibaren)
            if s.payment_term == "one_time":
                ey, em = start_y, start_m
            else:
                # senaryonun bitiş ayı
                ey, em = timeline[-1]

        # baz tutar
        base = float(s.unit_cost or 0.0) * float(s.quantity or 0.0)

        # aylara yaz
        y, m = start_y, start_m
        idx = 0
        while True:
            if (y, m) in timeline_set:
                # escalation: yıllıksa başlangıç yıl dönümlerinde artış
                if (s.escalation_freq or "none") == "annual":
                    # kaç yıl geçti (ay bazlı floor)
                    years_passed = max(0, ((y - start_y) * 12 + (m - start_m)) // 12)
                    factor = (1.0 + float(s.escalation_pct or 0.0)) ** years_passed
                else:
                    factor = 1.0

                # P&L'de vergi dahil/haric
                expense = base * factor
                if bool(s.expense_includes_tax) and float(s.tax_rate or 0) > 0:
                    expense = expense / (1.0 + float(s.tax_rate))

                if s.payment_term == "one_time":
                    # tek ay
                    services_by_ym[(y, m)] = services_by_ym.get((y, m), 0.0) + expense
                else:
                    # aylık ayrıştırma
                    services_by_ym[(y, m)] = services_by_ym.get((y, m), 0.0) + expense

            # durma koşulu
            if y == ey and m == em:
                break
            y, m = next_ym(y, m)
            idx += 1
            if idx > 2000:  # güvenlik
                break

    # ---- CAPEX → Monthly Depreciation (straight-line)
    capex_rows = db.execute(
        text(
            """
            SELECT
              year, month, amount,
              COALESCE(service_start_year, year) AS ssy,
              COALESCE(service_start_month, month) AS ssm,
              COALESCE(useful_life_months, 0) AS life,
              COALESCE(salvage_value, 0) AS salvage,
              COALESCE(depr_method, 'straight_line') AS method,
              COALESCE(is_active, 1) AS active,
              per_unit_cost, quantity, COALESCE(contingency_pct, 0) AS contingency_pct,
              disposal_year, disposal_month,
              partial_month_policy
            FROM scenario_capex
            WHERE scenario_id = :sid
            """
        ),
        {"sid": sc.id},
    ).mappings().all()

    depr_by_ym: Dict[Tuple[int, int], float] = {}

    for r in capex_rows:
        if int(r["active"]) == 0:
            continue

        life = int(r["life"] or 0)
        if life <= 0:
            continue

        # effective amount
        puc = r.get("per_unit_cost")
        qty = r.get("quantity")
        cntg = float(r.get("contingency_pct") or 0.0)
        if puc is not None and qty is not None:
            effective_amount = float(puc or 0.0) * float(qty or 0.0)
            effective_amount = effective_amount * (1.0 + cntg / 100.0)
        else:
            effective_amount = float(r["amount"] or 0.0)

        salvage = float(r["salvage"] or 0.0)
        base = max(effective_amount - salvage, 0.0)
        if base <= 0:
            continue

        method = (r.get("method") or "straight_line").lower()
        monthly = base / life  # şimdilik straight-line

        y0 = int(r["ssy"])
        m0 = int(r["ssm"])

        dpy = r.get("disposal_year")
        dpm = r.get("disposal_month")
        has_disposal = dpy is not None and dpm is not None

        y, m = y0, m0
        for _k in range(life):
            if has_disposal and (y > dpy or (y == dpy and m >= dpm)):
                break
            if (y, m) in timeline_set:
                depr_by_ym[(y, m)] = depr_by_ym.get((y, m), 0.0) + monthly
            y, m = next_ym(y, m)

    # ---- Build monthly PL
    months_out: List[Dict[str, Any]] = []
    y = sc.start_date.year
    m = sc.start_date.month
    for _i in range(sc.months):
        key = (y, m)
        revenue, cogs = rev_cogs.get(key, (0.0, 0.0))
        gross_margin = revenue - cogs
        overhead_var = revenue * (pct_sum / 100.0)
        overhead_total = fixed_sum + overhead_var

        services_expense = services_by_ym.get(key, 0.0)
        depreciation = depr_by_ym.get(key, 0.0)

        ebit = gross_margin - overhead_total - services_expense - depreciation

        months_out.append(
            {
                "year": y,
                "month": m,
                "revenue": round(revenue, 4),
                "cogs": round(cogs, 4),
                "gross_margin": round(gross_margin, 4),
                "overhead_fixed": round(fixed_sum, 4),
                "overhead_var_pct": pct_sum,
                "overhead_var_amount": round(overhead_var, 4),
                "overhead_total": round(overhead_total, 4),
                "services_expense": round(services_expense, 4),  # <-- NEW
                "depreciation": round(depreciation, 4),
                "depr": round(depreciation, 4),                  # alias
                "ebit": round(ebit, 4),
                "net_income": round(ebit, 4),
            }
        )

        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

    totals = {
        "revenue": round(sum(x["revenue"] for x in months_out), 4),
        "cogs": round(sum(x["cogs"] for x in months_out), 4),
        "gross_margin": round(sum(x["gross_margin"] for x in months_out), 4),
        "overhead_fixed_total": round(fixed_sum * len(months_out), 4),
        "overhead_var_total": round(sum(x["overhead_var_amount"] for x in months_out), 4),
        "overhead_total": round(sum(x["overhead_total"] for x in months_out), 4),
        "services_expense_total": round(sum(x["services_expense"] for x in months_out), 4),  # NEW
        "depreciation_total": round(sum(x["depreciation"] for x in months_out), 4),
        "depr_total": round(sum(x["depreciation"] for x in months_out), 4),
        "ebit": round(sum(x["ebit"] for x in months_out), 4),
        "net_income": round(sum(x["net_income"] for x in months_out), 4),
    }

    return {
        "scenario": {
            "id": sc.id,
            "business_case_id": sc.business_case_id,
            "name": sc.name,
            "months": sc.months,
            "start_date": sc.start_date,
            "overheads": {
                "fixed_sum": round(fixed_sum, 4),
                "pct_sum": pct_sum,
            },
        },
        "months": months_out,
        "totals": totals,
    }

# Register scenarios sub-router under main
router.include_router(scenarios_router)
