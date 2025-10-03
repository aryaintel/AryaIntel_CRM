# backend/app/api/scenario_rebates.py
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session, sessionmaker, joinedload

from ..core.config import engine
from ..models import ScenarioRebate, ScenarioRebateTier, ScenarioRebateLump

# ------------------------------------------------------------
# DB session
# ------------------------------------------------------------
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(prefix="/scenarios", tags=["rebates"])


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _to_float(x: Optional[float]) -> Optional[float]:
    # Normalizes Decimal/int/str to float; prevents SQLite Decimal binding errors
    if x is None:
        return None
    try:
        return float(x)  # type: ignore[arg-type]
    except Exception:
        return None

def _validate_month(m: Optional[int]) -> Optional[int]:
    if m is None:
        return None
    if not (1 <= int(m) <= 12):
        raise HTTPException(status_code=400, detail="Month must be in 1..12")
    return int(m)


# ------------------------------------------------------------
# Schemas
# ------------------------------------------------------------
class RebateTierIn(BaseModel):
    min_value: float = 0
    max_value: Optional[float] = None
    percent: Optional[float] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    sort_order: int = 0

    @validator("min_value", "max_value", "percent", "amount", pre=True)
    def _nf(cls, v):
        return _to_float(v)

class RebateLumpIn(BaseModel):
    year: int
    month: int
    amount: float
    currency: str = "USD"
    note: Optional[str] = None

    @validator("month")
    def _vm(cls, v):
        return _validate_month(v)

    @validator("amount", pre=True)
    def _fa(cls, v):
        f = _to_float(v)
        if f is None:
            raise ValueError("amount must be numeric")
        return f

class RebateIn(BaseModel):
    name: str
    scope: str = Field("all", regex=r"^(all|boq|services|product)$")
    # Allow 'gross_margin' to match current FE; 'volume' kept for parity map.
    basis: str = Field("revenue", regex=r"^(revenue|gross_margin|volume)$")
    kind: str = Field("percent", regex=r"^(percent|tier_percent|lump_sum)$")

    product_id: Optional[int] = None
    valid_from_year: Optional[int] = None
    valid_from_month: Optional[int] = None
    valid_to_year: Optional[int] = None
    valid_to_month: Optional[int] = None

    accrual_method: str = Field("monthly", regex=r"^(monthly|quarterly|annual|on_invoice)$")
    pay_month_lag: Optional[int] = 0
    is_active: bool = True
    notes: Optional[str] = None

    # details
    percent: Optional[float] = None        # for kind=percent
    tiers: Optional[List[RebateTierIn]] = None
    lumps: Optional[List[RebateLumpIn]] = None

    @validator("valid_from_month", "valid_to_month")
    def _vm(cls, v):
        return _validate_month(v)

    @validator("percent", pre=True)
    def _fp(cls, v):
        return _to_float(v)

class RebateTierOut(BaseModel):
    id: int
    rebate_id: int
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    percent: Optional[float] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    sort_order: int

    class Config:
        from_attributes = True

class RebateLumpOut(BaseModel):
    id: int
    rebate_id: int
    year: int
    month: int
    amount: float
    currency: Optional[str] = None
    note: Optional[str] = None

    class Config:
        from_attributes = True

class RebateOut(BaseModel):
    id: int
    scenario_id: int
    name: str
    scope: str
    kind: str
    basis: str
    product_id: Optional[int]
    valid_from_year: Optional[int]
    valid_from_month: Optional[int]
    valid_to_year: Optional[int]
    valid_to_month: Optional[int]
    accrual_method: str
    pay_month_lag: Optional[int]
    is_active: bool
    notes: Optional[str] = None

    # details for UI
    percent: Optional[float] = None
    tiers: Optional[List[RebateTierOut]] = None
    lumps: Optional[List[RebateLumpOut]] = None

    class Config:
        from_attributes = True


# ------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------
@router.get("/{scenario_id}/rebates", response_model=List[RebateOut])
def list_rebates(
    scenario_id: int,
    include_details: bool = Query(False, description="Include percent/tiers/lumps in response"),
    db: Session = Depends(get_db),
):
    q = (
        db.query(ScenarioRebate)
        .filter(ScenarioRebate.scenario_id == scenario_id)
        .order_by(ScenarioRebate.id.desc())
    )
    if include_details:
        q = q.options(
            joinedload(ScenarioRebate.tiers),
            joinedload(ScenarioRebate.lumps),
        )
    rows: List[ScenarioRebate] = q.all()

    out: List[RebateOut] = []
    for r in rows:
        dto = RebateOut.from_orm(r)
        if include_details:
            # percent: expose as a convenience for kind=percent (taken from the first tier)
            pct: Optional[float] = None
            if r.kind == "percent":
                # Choose first tier by sort_order (fall back to first)
                t = sorted(list(r.tiers or []), key=lambda x: (x.sort_order or 0, x.id))[0] if (r.tiers) else None
                if t and t.percent is not None:
                    pct = _to_float(t.percent)
            dto.percent = pct
            # tiers/lumps
            dto.tiers = [RebateTierOut.from_orm(t) for t in (r.tiers or [])] or None
            dto.lumps = [RebateLumpOut.from_orm(l) for l in (r.lumps or [])] or None
        out.append(dto)
    return out


@router.post("/{scenario_id}/rebates", response_model=RebateOut)
def create_rebate(scenario_id: int, body: RebateIn, db: Session = Depends(get_db)):
    r = ScenarioRebate(
        scenario_id=scenario_id,
        name=body.name.strip(),
        scope=body.scope,
        kind=body.kind,
        basis=body.basis,
        product_id=body.product_id,
        valid_from_year=body.valid_from_year,
        valid_from_month=body.valid_from_month,
        valid_to_year=body.valid_to_year,
        valid_to_month=body.valid_to_month,
        accrual_method=body.accrual_method,
        pay_month_lag=int(body.pay_month_lag or 0),
        is_active=bool(body.is_active),
        notes=body.notes or None,
    )
    db.add(r)
    db.flush()  # get r.id

    # details
    if body.kind == "percent":
        pct = _to_float(body.percent) or 0.0
        db.add(
            ScenarioRebateTier(
                rebate_id=r.id,
                min_value=0.0,
                max_value=None,
                percent=pct,
                amount=None,
                description=None,
                sort_order=0,
            )
        )
    elif body.kind == "tier_percent" and body.tiers:
        for i, t in enumerate(body.tiers):
            db.add(
                ScenarioRebateTier(
                    rebate_id=r.id,
                    min_value=_to_float(t.min_value) or 0.0,
                    max_value=_to_float(t.max_value),
                    percent=_to_float(t.percent),
                    amount=_to_float(t.amount),
                    description=t.description,
                    sort_order=int(t.sort_order if t.sort_order is not None else i),
                )
            )
    elif body.kind == "lump_sum" and body.lumps:
        for l in body.lumps:
            db.add(
                ScenarioRebateLump(
                    rebate_id=r.id,
                    year=int(l.year),
                    month=_validate_month(int(l.month)),
                    amount=_to_float(l.amount) or 0.0,
                    currency=l.currency or "USD",
                    note=l.note,
                )
            )

    db.commit()
    # Return with details so FE can immediately show new row properly
    r = (
        db.query(ScenarioRebate)
        .options(joinedload(ScenarioRebate.tiers), joinedload(ScenarioRebate.lumps))
        .get(r.id)  # type: ignore[arg-type]
    )
    if not r:
        raise HTTPException(status_code=500, detail="Failed to reload created rebate")
    # build dto
    dto = RebateOut.from_orm(r)
    if r.kind == "percent":
        t = sorted(list(r.tiers or []), key=lambda x: (x.sort_order or 0, x.id))[0] if (r.tiers) else None
        dto.percent = _to_float(t.percent) if t else 0.0  # type: ignore[union-attr]
    dto.tiers = [RebateTierOut.from_orm(t) for t in (r.tiers or [])] or None
    dto.lumps = [RebateLumpOut.from_orm(l) for l in (r.lumps or [])] or None
    return dto


@router.put("/{scenario_id}/rebates/{rebate_id}", response_model=RebateOut)
def update_rebate(scenario_id: int, rebate_id: int, body: RebateIn, db: Session = Depends(get_db)):
    r: Optional[ScenarioRebate] = (
        db.query(ScenarioRebate)
        .filter(ScenarioRebate.id == rebate_id, ScenarioRebate.scenario_id == scenario_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Rebate not found")

    # update main fields (exclude detail collections)
    r.name = body.name.strip()
    r.scope = body.scope
    r.kind = body.kind
    r.basis = body.basis
    r.product_id = body.product_id
    r.valid_from_year = body.valid_from_year
    r.valid_from_month = body.valid_from_month
    r.valid_to_year = body.valid_to_year
    r.valid_to_month = body.valid_to_month
    r.accrual_method = body.accrual_method
    r.pay_month_lag = int(body.pay_month_lag or 0)
    r.is_active = bool(body.is_active)
    r.notes = body.notes or None

    # replace details according to kind
    if body.kind in ("percent", "tier_percent"):
        db.query(ScenarioRebateTier).filter(ScenarioRebateTier.rebate_id == r.id).delete()
        if body.kind == "percent":
            pct = _to_float(body.percent) or 0.0
            db.add(
                ScenarioRebateTier(
                    rebate_id=r.id,
                    min_value=0.0,
                    max_value=None,
                    percent=pct,
                    amount=None,
                    description=None,
                    sort_order=0,
                )
            )
        elif body.tiers:
            for i, t in enumerate(body.tiers):
                db.add(
                    ScenarioRebateTier(
                        rebate_id=r.id,
                        min_value=_to_float(t.min_value) or 0.0,
                        max_value=_to_float(t.max_value),
                        percent=_to_float(t.percent),
                        amount=_to_float(t.amount),
                        description=t.description,
                        sort_order=int(t.sort_order if t.sort_order is not None else i),
                    )
                )
        # also clear lumps if switching away from lump_sum
        db.query(ScenarioRebateLump).filter(ScenarioRebateLump.rebate_id == r.id).delete()
    elif body.kind == "lump_sum":
        db.query(ScenarioRebateLump).filter(ScenarioRebateLump.rebate_id == r.id).delete()
        if body.lumps:
            for l in body.lumps:
                db.add(
                    ScenarioRebateLump(
                        rebate_id=r.id,
                        year=int(l.year),
                        month=_validate_month(int(l.month)),
                        amount=_to_float(l.amount) or 0.0,
                        currency=l.currency or "USD",
                        note=l.note,
                    )
                )
        # clear tiers if switching from percent/tier_percent
        db.query(ScenarioRebateTier).filter(ScenarioRebateTier.rebate_id == r.id).delete()

    db.commit()

    # reload with details
    r = (
        db.query(ScenarioRebate)
        .options(joinedload(ScenarioRebate.tiers), joinedload(ScenarioRebate.lumps))
        .get(rebate_id)  # type: ignore[arg-type]
    )
    if not r:
        raise HTTPException(status_code=500, detail="Failed to reload updated rebate")

    dto = RebateOut.from_orm(r)
    if r.kind == "percent":
        t = sorted(list(r.tiers or []), key=lambda x: (x.sort_order or 0, x.id))[0] if (r.tiers) else None
        dto.percent = _to_float(t.percent) if t else 0.0  # type: ignore[union-attr]
    dto.tiers = [RebateTierOut.from_orm(t) for t in (r.tiers or [])] or None
    dto.lumps = [RebateLumpOut.from_orm(l) for l in (r.lumps or [])] or None
    return dto


@router.delete("/{scenario_id}/rebates/{rebate_id}", status_code=204)
def delete_rebate(scenario_id: int, rebate_id: int, db: Session = Depends(get_db)):
    cnt = (
        db.query(ScenarioRebate)
        .filter(ScenarioRebate.id == rebate_id, ScenarioRebate.scenario_id == scenario_id)
        .delete()
    )
    if not cnt:
        raise HTTPException(status_code=404, detail="Rebate not found")
    # cascade delete on tiers/lumps if not configured in DB:
    db.query(ScenarioRebateTier).filter(ScenarioRebateTier.rebate_id == rebate_id).delete()
    db.query(ScenarioRebateLump).filter(ScenarioRebateLump.rebate_id == rebate_id).delete()
    db.commit()
    return None
