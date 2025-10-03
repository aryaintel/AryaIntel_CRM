from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import Scenario, ScenarioTaxRule
from .deps import get_db, get_current_user

router = APIRouter(prefix="/scenarios", tags=["tax"])

# ---------------------------
# Helpers
# ---------------------------
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc

def _ym(year: int, month: int) -> Tuple[int, int]:
    y, m = int(year), int(month)
    if not (1 <= m <= 12):
        raise HTTPException(status_code=400, detail="Month must be in 1..12")
    return y, m

def _cmp(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return (a[0] - b[0]) or (a[1] - b[1])

def _overlaps(
    s1: Tuple[int, int],
    e1: Optional[Tuple[int, int]],
    s2: Tuple[int, int],
    e2: Optional[Tuple[int, int]],
) -> bool:
    # overlap yoksa e1 < s2 veya e2 < s1
    def lt(x: Tuple[int, int], y: Tuple[int, int]) -> bool:
        return _cmp(x, y) < 0
    if e1 is not None and lt(e1, s2):
        return False
    if e2 is not None and lt(e2, s1):
        return False
    return True

# ---------------------------
# Schemas
# ---------------------------
Scope = Literal["revenue", "services", "capex", "profit", "all"]
TaxType = Literal["vat", "withholding", "corp", "custom"]

class TaxIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Örn: KDV 20%")
    tax_type: TaxType = "custom"
    applies_to: Scope = "all"
    rate_pct: Decimal = Field(..., ge=0)

    start_year: int = Field(..., ge=1900, le=3000)
    start_month: int = Field(..., ge=1, le=12)
    end_year: Optional[int] = Field(None, ge=1900, le=3000)
    end_month: Optional[int] = Field(None, ge=1, le=12)

    is_inclusive: bool = False
    notes: Optional[str] = None
    is_active: bool = True

    @validator("rate_pct", pre=True)
    def _dec(cls, v):
        return Decimal(str(v)) if v is not None else Decimal("0")

class TaxOut(TaxIn):
    id: int
    scenario_id: int

    class Config:
        orm_mode = True
        # JSON encode sırasında Decimal'i güvenle serileştir
        json_encoders = {Decimal: lambda v: float(v)}

class TaxBulkIn(BaseModel):
    items: List[TaxIn]

class TaxResolveOut(BaseModel):
    items: List[TaxOut]

    class Config:
        orm_mode = True
        json_encoders = {Decimal: lambda v: float(v)}

# ---------------------------
# Internal overlap check
# ---------------------------
def _any_overlap(
    db: Session,
    scenario_id: int,
    name: str,
    applies_to: Scope,
    start: Tuple[int, int],
    end: Optional[Tuple[int, int]],
    exclude_id: Optional[int] = None,
) -> bool:
    stmt = select(ScenarioTaxRule).where(
        ScenarioTaxRule.scenario_id == scenario_id,
        ScenarioTaxRule.name == name,
        ScenarioTaxRule.applies_to == applies_to,
    )
    if exclude_id:
        stmt = stmt.where(ScenarioTaxRule.id != exclude_id)

    rows = db.execute(stmt).scalars().all()
    for r in rows:
        s2 = (int(r.start_year), int(r.start_month))
        e2 = (int(r.end_year), int(r.end_month)) if (r.end_year and r.end_month) else None
        if _overlaps(start, end, s2, e2):
            return True
    return False

# ---------------------------
# Routes
# ---------------------------
@router.get(
    "/{scenario_id}/tax",
    response_model=List[TaxOut],
    summary="List scenario tax rules (filterable)",
)
def list_tax_rules(
    scenario_id: int = Path(..., ge=1),
    name: Optional[str] = Query(None, description="contains filter"),
    applies_to: Optional[Scope] = Query(None),
    tax_type: Optional[TaxType] = Query(None),
    active_only: bool = Query(False),
    year_from: Optional[int] = Query(None, ge=1900, le=3000),
    month_from: Optional[int] = Query(None, ge=1, le=12),
    year_to: Optional[int] = Query(None, ge=1900, le=3000),
    month_to: Optional[int] = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    stmt = select(ScenarioTaxRule).where(ScenarioTaxRule.scenario_id == scenario_id)

    if name:
        stmt = stmt.where(ScenarioTaxRule.name.like(f"%{name}%"))
    if applies_to:
        stmt = stmt.where(ScenarioTaxRule.applies_to == applies_to)
    if tax_type:
        stmt = stmt.where(ScenarioTaxRule.tax_type == tax_type)
    if active_only:
        stmt = stmt.where(ScenarioTaxRule.is_active.is_(True))

    if year_from is not None and month_from is not None:
        y, m = year_from, month_from
        stmt = stmt.where(
            or_(
                ScenarioTaxRule.end_year.is_(None),
                ScenarioTaxRule.end_year > y,
                and_(ScenarioTaxRule.end_year == y, ScenarioTaxRule.end_month >= m),
            )
        )
    if year_to is not None and month_to is not None:
        y, m = year_to, month_to
        stmt = stmt.where(
            or_(
                ScenarioTaxRule.start_year < y,
                and_(ScenarioTaxRule.start_year == y, ScenarioTaxRule.start_month <= m),
            )
        )

    stmt = stmt.order_by(
        ScenarioTaxRule.start_year.asc(),
        ScenarioTaxRule.start_month.asc(),
        ScenarioTaxRule.id.asc(),
    )
    return db.execute(stmt).scalars().all()

@router.options(
    "/{scenario_id}/tax/resolve",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
def cors_preflight_resolve(scenario_id: int):
    return None


@router.post(
    "/{scenario_id}/tax",
    response_model=TaxOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scenario tax rule",
)
def create_tax_rule(
    payload: TaxIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    if (payload.end_year is None) ^ (payload.end_month is None):
        raise HTTPException(status_code=400, detail="end_year and end_month must be both null or both provided")

    s = _ym(payload.start_year, payload.start_month)
    e = _ym(payload.end_year, payload.end_month) if payload.end_year and payload.end_month else None
    if e is not None and _cmp(e, s) < 0:
        raise HTTPException(status_code=400, detail="End (Y/M) must be >= Start (Y/M)")

    if _any_overlap(db, scenario_id, payload.name, payload.applies_to, s, e, None):
        raise HTTPException(status_code=409, detail="Overlapping period for the same (name, applies_to)")

    row = ScenarioTaxRule(
        scenario_id=scenario_id,
        name=payload.name,
        tax_type=payload.tax_type,
        applies_to=payload.applies_to,
        rate_pct=payload.rate_pct,
        start_year=payload.start_year,
        start_month=payload.start_month,
        end_year=payload.end_year,
        end_month=payload.end_month,
        is_inclusive=payload.is_inclusive,
        notes=payload.notes,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put(
    "/{scenario_id}/tax/{tax_id}",
    response_model=TaxOut,
    summary="Update a scenario tax rule",
)
def update_tax_rule(
    payload: TaxIn,
    scenario_id: int = Path(..., ge=1),
    tax_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioTaxRule, tax_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="Tax rule not found")

    if (payload.end_year is None) ^ (payload.end_month is None):
        raise HTTPException(status_code=400, detail="end_year and end_month must be both null or both provided")

    s = _ym(payload.start_year, payload.start_month)
    e = _ym(payload.end_year, payload.end_month) if payload.end_year and payload.end_month else None
    if e is not None and _cmp(e, s) < 0:
        raise HTTPException(status_code=400, detail="End (Y/M) must be >= Start (Y/M)")

    if _any_overlap(db, scenario_id, payload.name, payload.applies_to, s, e, exclude_id=row.id):
        raise HTTPException(status_code=409, detail="Overlapping period for the same (name, applies_to)")

    row.name = payload.name
    row.tax_type = payload.tax_type
    row.applies_to = payload.applies_to
    row.rate_pct = payload.rate_pct
    row.start_year = payload.start_year
    row.start_month = payload.start_month
    row.end_year = payload.end_year
    row.end_month = payload.end_month
    row.is_inclusive = payload.is_inclusive
    row.notes = payload.notes
    row.is_active = payload.is_active

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{scenario_id}/tax/{tax_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scenario tax rule",
)
def delete_tax_rule(
    scenario_id: int = Path(..., ge=1),
    tax_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioTaxRule, tax_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="Tax rule not found")
    db.delete(row)
    db.commit()
    return None


@router.post(
    "/{scenario_id}/tax/bulk",
    response_model=List[TaxOut],
    summary="Bulk insert tax rules (append-only)",
)
def bulk_insert_tax_rules(
    payload: TaxBulkIn,
    scenario_id: int = Path(..., ge=1),
    strict_overlap_check: bool = Query(True),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    to_add: List[ScenarioTaxRule] = []
    for it in payload.items:
        if (it.end_year is None) ^ (it.end_month is None):
            raise HTTPException(status_code=400, detail="end_year and end_month must be both null or both provided")

        s = _ym(it.start_year, it.start_month)
        e = _ym(it.end_year, it.end_month) if it.end_year and it.end_month else None
        if e is not None and _cmp(e, s) < 0:
            raise HTTPException(status_code=400, detail="End (Y/M) must be >= Start (Y/M)")

        if _any_overlap(db, scenario_id, it.name, it.applies_to, s, e, None):
            if strict_overlap_check:
                raise HTTPException(status_code=409, detail=f"Overlapping period for {(it.name, it.applies_to)}")
            else:
                continue

        # payload içi çakışma
        clash = False
        for r in to_add:
            if r.name == it.name and r.applies_to == it.applies_to:
                s2 = (int(r.start_year), int(r.start_month))
                e2 = (int(r.end_year), int(r.end_month)) if (r.end_year and r.end_month) else None
                if _overlaps(s, e, s2, e2):
                    if strict_overlap_check:
                        raise HTTPException(status_code=409, detail=f"Overlapping period within payload for {(it.name, it.applies_to)}")
                    clash = True
                    break
        if clash:
            continue

        to_add.append(
            ScenarioTaxRule(
                scenario_id=scenario_id,
                name=it.name,
                tax_type=it.tax_type,
                applies_to=it.applies_to,
                rate_pct=it.rate_pct,
                start_year=it.start_year,
                start_month=it.start_month,
                end_year=it.end_year,
                end_month=it.end_month,
                is_inclusive=it.is_inclusive,
                notes=it.notes,
                is_active=it.is_active,
            )
        )

    if not to_add:
        return []
    db.add_all(to_add)
    db.commit()
    for r in to_add:
        db.refresh(r)
    return to_add


@router.get(
    "/{scenario_id}/tax/resolve",
    response_model=TaxResolveOut,
    summary="Resolve tax for a given scope on a given year/month",
)
def resolve_tax(
    scenario_id: int = Path(..., ge=1),
    year: int = Query(..., ge=1900, le=3000),
    month: int = Query(..., ge=1, le=12),
    applies_to: Scope = Query("all"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    stmt = (
        select(ScenarioTaxRule)
        .where(ScenarioTaxRule.scenario_id == scenario_id)
        .where(ScenarioTaxRule.is_active.is_(True))
        .where(ScenarioTaxRule.applies_to.in_([applies_to, "all"]))
        .where(
            and_(
                or_(
                    ScenarioTaxRule.start_year < year,
                    and_(ScenarioTaxRule.start_year == year, ScenarioTaxRule.start_month <= month),
                ),
                or_(
                    ScenarioTaxRule.end_year.is_(None),
                    ScenarioTaxRule.end_year > year,
                    and_(ScenarioTaxRule.end_year == year, ScenarioTaxRule.end_month >= month),
                ),
            )
        )
        .order_by(
            ScenarioTaxRule.start_year.desc(),
            ScenarioTaxRule.start_month.desc(),
            ScenarioTaxRule.id.desc(),
        )
    )
    rows = db.execute(stmt).scalars().all()

    # ORM -> Pydantic (eksik/legacy kayıtlara karşı güvenli)
    items: List[TaxOut] = []
    for r in rows:
        try:
            items.append(TaxOut.from_orm(r))
        except Exception:
            # Legacy / eksik alanlara karşı defaultlarla doldur
            items.append(
                TaxOut(
                    id=int(r.id),
                    scenario_id=int(r.scenario_id),
                    name=r.name or "",
                    tax_type=(r.tax_type or "custom"),
                    applies_to=(r.applies_to or "all"),
                    rate_pct=Decimal(str(r.rate_pct or 0)),
                    start_year=int(r.start_year or year),
                    start_month=int(r.start_month or month),
                    end_year=(int(r.end_year) if r.end_year is not None else None),
                    end_month=(int(r.end_month) if r.end_month is not None else None),
                    is_inclusive=bool(r.is_inclusive),
                    notes=r.notes,
                    is_active=bool(r.is_active),
                )
            )

    return TaxResolveOut(items=items)
