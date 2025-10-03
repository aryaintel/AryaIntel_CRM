# backend/app/api/scenario_fx.py
from __future__ import annotations

from typing import List, Optional, Tuple
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, func

from ..models import Scenario, ScenarioFXRate
from .deps import get_db, get_current_user  # mevcut projedeki auth/db bağımlılıkları

router = APIRouter(
    prefix="/scenarios",
    tags=["fx"],
)

# =========================
# Helpers
# =========================
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _ym_tuple(year: int, month: int) -> Tuple[int, int]:
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="Month must be in 1..12")
    return (int(year), int(month))


def _cmp_ym(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """a < b: -1, a == b: 0, a > b: 1"""
    return (a[0] - b[0]) or (a[1] - b[1])


def _range_overlaps(
    s1: Tuple[int, int],
    e1: Optional[Tuple[int, int]],  # None => open-ended
    s2: Tuple[int, int],
    e2: Optional[Tuple[int, int]],
) -> bool:
    """[s1, e1] ile [s2, e2] kesişiyor mu? (ay kapalı aralık, e=None sonsuz)"""
    # e1 yoksa +inf, e2 yoksa +inf
    # overlap yok olması için: e1 < s2 veya e2 < s1 olmalı
    def lt(x: Tuple[int, int], y: Tuple[int, int]) -> bool:
        return _cmp_ym(x, y) < 0

    def le(x: Tuple[int, int], y: Tuple[int, int]) -> bool:
        c = _cmp_ym(x, y)
        return c <= 0

    # e1 < s2 ?
    if e1 is not None and lt(e1, s2):
        return False
    # e2 < s1 ?
    if e2 is not None and lt(e2, s1):
        return False
    return True  # aksi halde kesişir


def _any_overlap_for_currency(
    db: Session,
    scenario_id: int,
    currency: str,
    start: Tuple[int, int],
    end: Optional[Tuple[int, int]],
    exclude_id: Optional[int] = None,
) -> bool:
    """Aynı currency için mevcut kayıtlarla dönem çakışması var mı?"""
    q = (
        select(ScenarioFXRate)
        .where(ScenarioFXRate.scenario_id == scenario_id)
        .where(func.upper(ScenarioFXRate.currency) == currency.upper())
    )
    if exclude_id:
        q = q.where(ScenarioFXRate.id != exclude_id)

    rows = db.execute(q).scalars().all()
    for r in rows:
        s2 = (int(r.start_year), int(r.start_month))
        e2 = None
        if r.end_year and r.end_month:
            e2 = (int(r.end_year), int(r.end_month))
        if _range_overlaps(start, end, s2, e2):
            return True
    return False


def _resolve_rate(
    db: Session, scenario_id: int, currency: str, at: Tuple[int, int]
) -> Optional[ScenarioFXRate]:
    """
    Verilen (year, month) için geçerli olan oranı bul.
    Kriter:
      - start <= at <= end (end yoksa open)
      - birden fazla eşleşme varsa start tarihi en büyük olanı (en yakın geçmiş) seç.
    """
    y, m = at
    q = (
        select(ScenarioFXRate)
        .where(ScenarioFXRate.scenario_id == scenario_id)
        .where(func.upper(ScenarioFXRate.currency) == currency.upper())
        .where(
            and_(
                # start <= at
                or_(
                    ScenarioFXRate.start_year < y,
                    and_(
                        ScenarioFXRate.start_year == y,
                        ScenarioFXRate.start_month <= m,
                    ),
                ),
                # (end is null) or (at <= end)
                or_(
                    and_(
                        ScenarioFXRate.end_year.is_(None),
                        ScenarioFXRate.end_month.is_(None),
                    ),
                    or_(
                        ScenarioFXRate.end_year > y,
                        and_(
                            ScenarioFXRate.end_year == y,
                            ScenarioFXRate.end_month >= m,
                        ),
                    ),
                ),
            )
        )
        .order_by(ScenarioFXRate.start_year.desc(), ScenarioFXRate.start_month.desc())
        .limit(1)
    )
    return db.execute(q).scalars().first()


# =========================
# Schemas
# =========================
class FXIn(BaseModel):
    currency: str = Field(..., min_length=3, max_length=3, description="ISO-4217, e.g. USD")
    rate_to_base: Decimal = Field(..., gt=0, description="FX rate to scenario base")
    start_year: int = Field(..., ge=1900, le=3000)
    start_month: int = Field(..., ge=1, le=12)
    end_year: Optional[int] = Field(None, ge=1900, le=3000)
    end_month: Optional[int] = Field(None, ge=1, le=12)
    source: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None
    is_active: Optional[bool] = True

    @validator("currency")
    def _cur_upper(cls, v: str) -> str:
        return v.upper()

    @validator("*", pre=True)
    def _coerce_decimal(cls, v):
        if isinstance(v, (int, float, str)):
            try:
                return Decimal(str(v))
            except Exception:
                return v
        return v

    @validator("end_year", "end_month")
    def _end_pair(cls, v, values):
        # İkisi de None olabilir (open-ended) ya da ikisi birlikte dolu olmalı
        ey = v if isinstance(v, int) else values.get("end_year")
        em = values.get("end_month") if "end_month" in values else None
        # validasyon pydantic sırasına bağlı olabileceği için asıl mantığı route'da da koruyacağız
        return v


class FXOut(BaseModel):
    id: int
    scenario_id: int
    currency: str
    rate_to_base: Decimal
    start_year: int
    start_month: int
    end_year: Optional[int]
    end_month: Optional[int]
    source: Optional[str]
    notes: Optional[str]
    is_active: bool

    class Config:
        orm_mode = True


class FXBulkIn(BaseModel):
    items: List[FXIn]


class FXResolveOut(BaseModel):
    scenario_id: int
    currency: str
    year: int
    month: int
    rate_to_base: Optional[Decimal] = None
    found: bool = False
    source_id: Optional[int] = None


# =========================
# Routes
# =========================
@router.get(
    "/{scenario_id}/fx",
    response_model=List[FXOut],
    summary="List scenario FX rates (filterable)",
)
def list_fx_rates(
    scenario_id: int = Path(..., ge=1),
    currency: Optional[str] = Query(None, min_length=3, max_length=3),
    active_only: bool = Query(False, description="Only active rows"),
    year_from: Optional[int] = Query(None, ge=1900, le=3000),
    month_from: Optional[int] = Query(None, ge=1, le=12),
    year_to: Optional[int] = Query(None, ge=1900, le=3000),
    month_to: Optional[int] = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    stmt = select(ScenarioFXRate).where(ScenarioFXRate.scenario_id == scenario_id)

    if currency:
        stmt = stmt.where(func.upper(ScenarioFXRate.currency) == currency.upper())
    if active_only:
        stmt = stmt.where(ScenarioFXRate.is_active.is_(True))

    # basit dönem filtresi: start >= from veya end <= to gibi geniş filtreler
    if year_from and month_from:
        y, m = year_from, month_from
        # kayıt başlangıcı seçili tarihten sonra başlayanlar veya
        # bitişi seçili tarihten sonra olanlar → kaba kapsama
        stmt = stmt.where(
            or_(
                or_(
                    ScenarioFXRate.start_year > y,
                    and_(
                        ScenarioFXRate.start_year == y,
                        ScenarioFXRate.start_month >= m,
                    ),
                ),
                # open-ended de dahil
                and_(
                    ScenarioFXRate.end_year.is_(None),
                    ScenarioFXRate.end_month.is_(None),
                ),
                or_(
                    ScenarioFXRate.end_year > y,
                    and_(
                        ScenarioFXRate.end_year == y,
                        ScenarioFXRate.end_month >= m,
                    ),
                ),
            )
        )
    if year_to and month_to:
        y, m = year_to, month_to
        stmt = stmt.where(
            or_(
                or_(
                    ScenarioFXRate.start_year < y,
                    and_(
                        ScenarioFXRate.start_year == y,
                        ScenarioFXRate.start_month <= m,
                    ),
                ),
                # open-ended de dahil (üst sınırı aşmadığı varsayılan kaba filtre)
                and_(
                    ScenarioFXRate.end_year.is_(None),
                    ScenarioFXRate.end_month.is_(None),
                ),
                or_(
                    ScenarioFXRate.end_year < y,
                    and_(
                        ScenarioFXRate.end_year == y,
                        ScenarioFXRate.end_month <= m,
                    ),
                ),
            )
        )

    stmt = stmt.order_by(
        ScenarioFXRate.currency.asc(),
        ScenarioFXRate.start_year.asc(),
        ScenarioFXRate.start_month.asc(),
        ScenarioFXRate.id.asc(),
    )
    rows = db.execute(stmt).scalars().all()
    return rows


@router.post(
    "/{scenario_id}/fx",
    response_model=FXOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scenario FX rate",
)
def create_fx_rate(
    payload: FXIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    # end_year ve end_month eşleşmesi kontrolü
    if (payload.end_year is None) ^ (payload.end_month is None):
        raise HTTPException(status_code=400, detail="end_year and end_month must be both null or both provided")

    s = _ym_tuple(int(payload.start_year), int(payload.start_month))
    e = None
    if payload.end_year is not None and payload.end_month is not None:
        e = _ym_tuple(int(payload.end_year), int(payload.end_month))
        if _cmp_ym(e, s) < 0:
            raise HTTPException(status_code=400, detail="End (year,month) must be >= Start (year,month)")

    # Overlap kontrolü
    if _any_overlap_for_currency(db, scenario_id, payload.currency, s, e, exclude_id=None):
        raise HTTPException(status_code=409, detail="Overlapping FX period exists for the same currency")

    row = ScenarioFXRate(
        scenario_id=scenario_id,
        currency=payload.currency.upper(),
        rate_to_base=Decimal(str(payload.rate_to_base)),
        start_year=int(payload.start_year),
        start_month=int(payload.start_month),
        end_year=(int(payload.end_year) if payload.end_year is not None else None),
        end_month=(int(payload.end_month) if payload.end_month is not None else None),
        source=payload.source,
        notes=payload.notes,
        is_active=bool(payload.is_active if payload.is_active is not None else True),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put(
    "/{scenario_id}/fx/{fx_id}",
    response_model=FXOut,
    summary="Update a scenario FX rate",
)
def update_fx_rate(
    payload: FXIn,
    scenario_id: int = Path(..., ge=1),
    fx_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioFXRate, fx_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="FX rate not found")

    # end_year/month beraber olmalı
    if (payload.end_year is None) ^ (payload.end_month is None):
        raise HTTPException(status_code=400, detail="end_year and end_month must be both null or both provided")

    s = _ym_tuple(int(payload.start_year), int(payload.start_month))
    e = None
    if payload.end_year is not None and payload.end_month is not None:
        e = _ym_tuple(int(payload.end_year), int(payload.end_month))
        if _cmp_ym(e, s) < 0:
            raise HTTPException(status_code=400, detail="End (year,month) must be >= Start (year,month)")

    # Overlap kontrolü (kendi kaydını hariç tut)
    if _any_overlap_for_currency(db, scenario_id, payload.currency, s, e, exclude_id=row.id):
        raise HTTPException(status_code=409, detail="Overlapping FX period exists for the same currency")

    row.currency = payload.currency.upper()
    row.rate_to_base = Decimal(str(payload.rate_to_base))
    row.start_year = int(payload.start_year)
    row.start_month = int(payload.start_month)
    row.end_year = (int(payload.end_year) if payload.end_year is not None else None)
    row.end_month = (int(payload.end_month) if payload.end_month is not None else None)
    row.source = payload.source
    row.notes = payload.notes
    row.is_active = bool(payload.is_active if payload.is_active is not None else True)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/{scenario_id}/fx/{fx_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scenario FX rate",
)
def delete_fx_rate(
    scenario_id: int = Path(..., ge=1),
    fx_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioFXRate, fx_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="FX rate not found")
    db.delete(row)
    db.commit()
    return None


@router.post(
    "/{scenario_id}/fx/bulk",
    response_model=List[FXOut],
    summary="Bulk insert scenario FX rates (append-only)",
)
def bulk_insert_fx_rates(
    payload: FXBulkIn,
    scenario_id: int = Path(..., ge=1),
    strict_overlap_check: bool = Query(True, description="Fail all on first overlap if True"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)

    to_add: List[ScenarioFXRate] = []
    for item in payload.items:
        if (item.end_year is None) ^ (item.end_month is None):
            raise HTTPException(status_code=400, detail="end_year and end_month must be both null or both provided")

        s = _ym_tuple(int(item.start_year), int(item.start_month))
        e = None
        if item.end_year is not None and item.end_month is not None:
            e = _ym_tuple(int(item.end_year), int(item.end_month))
            if _cmp_ym(e, s) < 0:
                raise HTTPException(status_code=400, detail="End (year,month) must be >= Start (year,month)")

        # Overlap kontrolü: veritabanı + lokal buffer
        if _any_overlap_for_currency(db, scenario_id, item.currency, s, e, exclude_id=None):
            if strict_overlap_check:
                raise HTTPException(
                    status_code=409,
                    detail=f"Overlapping FX period exists for {item.currency}",
                )
            else:
                # strict değilse bu kalemi atla
                continue

        # buffer içi çakışma kontrolü (aynı payload içinde tekrar olmasın)
        for r in to_add:
            if r.currency.upper() == item.currency.upper():
                s2 = (int(r.start_year), int(r.start_month))
                e2 = None
                if r.end_year and r.end_month:
                    e2 = (int(r.end_year), int(r.end_month))
                if _range_overlaps(s, e, s2, e2):
                    if strict_overlap_check:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Overlapping FX period within payload for {item.currency}",
                        )
                    else:
                        # atla
                        s = None  # type: ignore
                        break
        if s is None:
            continue

        to_add.append(
            ScenarioFXRate(
                scenario_id=scenario_id,
                currency=item.currency.upper(),
                rate_to_base=Decimal(str(item.rate_to_base)),
                start_year=int(item.start_year),
                start_month=int(item.start_month),
                end_year=(int(item.end_year) if item.end_year is not None else None),
                end_month=(int(item.end_month) if item.end_month is not None else None),
                source=item.source,
                notes=item.notes,
                is_active=bool(item.is_active if item.is_active is not None else True),
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
    "/{scenario_id}/fx/resolve",
    response_model=FXResolveOut,
    summary="Resolve FX rate for a given (currency, year, month)",
)
def resolve_fx_rate(
    scenario_id: int = Path(..., ge=1),
    currency: str = Query(..., min_length=3, max_length=3),
    year: int = Query(..., ge=1900, le=3000),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    _ensure_scenario(db, scenario_id)
    cur = currency.upper()
    at = _ym_tuple(year, month)

    row = _resolve_rate(db, scenario_id, cur, at)
    if not row:
        return FXResolveOut(
            scenario_id=scenario_id,
            currency=cur,
            year=year,
            month=month,
            rate_to_base=None,
            found=False,
            source_id=None,
        )
    return FXResolveOut(
        scenario_id=scenario_id,
        currency=cur,
        year=year,
        month=month,
        rate_to_base=row.rate_to_base,  # type: ignore
        found=True,
        source_id=row.id,
    )
