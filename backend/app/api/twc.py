# backend/app/api/twc.py
from __future__ import annotations
from typing import Dict, List, Optional, Iterable, Tuple
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..models import (
    Scenario,
    ScenarioOverhead,
    ScenarioProduct,
    ScenarioProductMonth,
    ScenarioBOQItem,
    ScenarioTWC,  # dso/dpo/dio burada
)
from .deps import get_db, get_current_user

router = APIRouter(
    prefix="/scenarios",
    tags=["twc"],
)

# ======================================================
# TWC Assumption Anahtarları (legacy - scenario_overheads.name)
# ======================================================
# DSO/DPO/DIO scenario_twc tablosunda. Ek parametreler overheads'te tutulur.
TWC_KEYS = {
    # core günler (legacy anahtar isimleri – geriye uyumluluk için tutulur)
    "twc_dso_days",
    "twc_dpo_days",
    "twc_dio_days",
    # ek parametreler
    "twc_freight_pct_of_sales",
    "twc_safety_stock_pct_cogs",
    "twc_other_wc_fixed",
}

# scenario_twc alan eşlemesi (UI alan adı -> tablo kolonu)
MAP_TWC_COL = {
    "twc_dso_days": "dso_days",
    "twc_dpo_days": "dpo_days",
    "twc_dio_days": "inventory_days",
}


# =========================
# Schemas
# =========================
class TWCIn(BaseModel):
    # Günler
    twc_dso_days: Optional[Decimal] = Field(45, ge=0, description="DSO: Alacakların ortalama tahsil gün sayısı")
    twc_dpo_days: Optional[Decimal] = Field(30, ge=0, description="DPO: Borçların ortalama ödeme gün sayısı")
    twc_dio_days: Optional[Decimal] = Field(20, ge=0, description="DIO: Stokların ortalama gün sayısı")

    # Opsiyonel oranlar (0-100)
    twc_freight_pct_of_sales: Optional[Decimal] = Field(0, ge=0, le=100)
    twc_safety_stock_pct_cogs: Optional[Decimal] = Field(0, ge=0, le=100)

    # Sabit ek işletme sermayesi
    twc_other_wc_fixed: Optional[Decimal] = Field(0, ge=0)

    @validator("*", pre=True)
    def _none_to_decimal(cls, v):
        if v is None:
            return v
        return Decimal(str(v))


class TWCOut(TWCIn):
    scenario_id: int

    class Config:
        orm_mode = True


class TWCBucket(BaseModel):
    year: int
    month: int
    revenue: Decimal
    cogs: Decimal
    freight: Decimal
    ar: Decimal   # Accounts Receivable
    ap: Decimal   # Accounts Payable
    inv: Decimal  # Inventory
    nwc: Decimal  # Net Working Capital (= AR + INV - AP)


class TWCPreview(BaseModel):
    scenario_id: int
    assumptions: TWCOut
    monthly: List[TWCBucket]
    totals: Dict[str, Decimal]


# =========================
# Internal helpers
# =========================
def _ensure_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _load_overhead_twcs(db: Session, scenario_id: int) -> Dict[str, Decimal]:
    """scenario_overheads tablosundan TWC anahtarlarını oku (fixed)."""
    stmt = (
        select(ScenarioOverhead)
        .where(ScenarioOverhead.scenario_id == scenario_id)
        .where(ScenarioOverhead.type == "fixed")
        .where(ScenarioOverhead.name.in_(list(TWC_KEYS)))
    )
    rows = db.execute(stmt).scalars().all()
    out: Dict[str, Decimal] = {}
    for r in rows:
        if r.name in TWC_KEYS:
            try:
                out[r.name] = Decimal(str(r.amount))
            except Exception:
                pass
    return out


def _upsert_overhead_fixed(db: Session, scenario_id: int, key: str, value: Optional[Decimal]) -> None:
    """ScenarioOverhead'te (fixed) tek satır upsert et (yalnız ek parametreler için)."""
    if value is None:
        return
    row = db.execute(
        select(ScenarioOverhead)
        .where(ScenarioOverhead.scenario_id == scenario_id)
        .where(ScenarioOverhead.type == "fixed")
        .where(ScenarioOverhead.name == key)
    ).scalar_one_or_none()
    if row is None:
        row = ScenarioOverhead(
            scenario_id=scenario_id,
            name=key,
            type="fixed",
            amount=value,
        )
        db.add(row)
    else:
        row.amount = value
        db.add(row)


def _iter_months(db: Session, scenario_id: int) -> Iterable[Tuple[int, int]]:
    """Ürün aylıkları üzerinden (yıl, ay) kombinasyonlarını sırayla döndür."""
    stmt = (
        select(ScenarioProductMonth.year, ScenarioProductMonth.month)
        .join(ScenarioProduct, ScenarioProductMonth.scenario_product_id == ScenarioProduct.id)
        .where(ScenarioProduct.scenario_id == scenario_id)
        .group_by(ScenarioProductMonth.year, ScenarioProductMonth.month)
        .order_by(ScenarioProductMonth.year.asc(), ScenarioProductMonth.month.asc())
    )
    return db.execute(stmt).all()


def _monthly_revenue_cogs(db: Session, scenario_id: int) -> Dict[tuple, Dict[str, Decimal]]:
    """
    Aylık bazda revenue ve cogs hesapla:
      revenue = sum(qty * price)
      cogs    = sum(qty * unit_cogs)
    """
    stmt = (
        select(
            ScenarioProductMonth.year,
            ScenarioProductMonth.month,
            func.sum((ScenarioProductMonth.quantity or 0) * (ScenarioProduct.price or 0)).label("rev"),
            func.sum((ScenarioProductMonth.quantity or 0) * (ScenarioProduct.unit_cogs or 0)).label("cogs"),
        )
        .join(ScenarioProduct, ScenarioProductMonth.scenario_product_id == ScenarioProduct.id)
        .where(ScenarioProduct.scenario_id == scenario_id)
        .group_by(ScenarioProductMonth.year, ScenarioProductMonth.month)
    )
    rows = db.execute(stmt).all()
    out: Dict[tuple, Dict[str, Decimal]] = {}
    for y, m, rev, cgs in rows:
        out[(y, m)] = {
            "rev": Decimal(str(rev or 0)),
            "cogs": Decimal(str(cgs or 0)),
        }
    return out


def _monthly_freight_from_boq(db: Session, scenario_id: int) -> Dict[tuple, Decimal]:
    """
    BOQ üzerinden 'freight' kalemlerini ay bazında kabaca dağıtır.
    """
    stmt = select(ScenarioBOQItem).where(ScenarioBOQItem.scenario_id == scenario_id)
    rows = db.execute(stmt).scalars().all()
    agg: Dict[tuple, Decimal] = {}

    for r in rows:
        if (r.category or "") != "freight":
            continue
        price = Decimal(str(r.unit_price or 0))
        qty   = Decimal(str(r.quantity or 0))
        total = price * qty
        freq = (r.frequency or "once").lower()

        if freq == "once":
            if r.start_year and r.start_month:
                key = (int(r.start_year), int(r.start_month))
                agg[key] = agg.get(key, Decimal("0")) + total
        elif freq == "monthly":
            if r.start_year and r.start_month and r.months:
                month_cnt = int(r.months or 0)
                per = (total / Decimal(month_cnt)) if month_cnt > 0 else Decimal("0")
                y, m = int(r.start_year), int(r.start_month)
                for _ in range(month_cnt):
                    key = (y, m)
                    agg[key] = agg.get(key, Decimal("0")) + per
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
        else:
            # diğer frekanslar şu an yok sayılıyor
            pass

    return agg


# ---- scenario_twc helpers ----
def _get_scenario_twc(db: Session, scenario_id: int) -> Optional[ScenarioTWC]:
    stmt = select(ScenarioTWC).where(ScenarioTWC.scenario_id == scenario_id)
    return db.execute(stmt).scalars().first()


def _ensure_scenario_twc(db: Session, scenario_id: int) -> ScenarioTWC:
    """Yoksa overhead değerlerinden migrate ederek scenario_twc kaydı oluşturur."""
    row = _get_scenario_twc(db, scenario_id)
    if row:
        return row

    # overhead defaults
    oh = _load_overhead_twcs(db, scenario_id)
    dso = Decimal(str(oh.get("twc_dso_days", 45)))
    dpo = Decimal(str(oh.get("twc_dpo_days", 30)))
    dio = Decimal(str(oh.get("twc_dio_days", 20)))

    row = ScenarioTWC(
        scenario_id=scenario_id,
        dso_days=int(dso),
        dpo_days=int(dpo),
        inventory_days=int(dio),
        notes="Auto-created from overhead TWC keys",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# =========================
# Routes
# =========================
@router.get(
    "/{scenario_id}/twc",
    response_model=TWCOut,
    summary="Get TWC assumptions (dso/dpo/dio from scenario_twc; extras from overheads)",
)
def get_twc(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)

    # scenario_twc (core günler)
    twc_row = _ensure_scenario_twc(db, scenario_id)

    # overheads (ek parametreler)
    existing = _load_overhead_twcs(db, scenario_id)

    merged: Dict[str, Decimal] = {}
    defaults = TWCIn().dict()

    # core (tablodan)
    merged["twc_dso_days"] = Decimal(str(twc_row.dso_days if twc_row.dso_days is not None else defaults["twc_dso_days"]))
    merged["twc_dpo_days"] = Decimal(str(twc_row.dpo_days if twc_row.dpo_days is not None else defaults["twc_dpo_days"]))
    merged["twc_dio_days"] = Decimal(str(twc_row.inventory_days if twc_row.inventory_days is not None else defaults["twc_dio_days"]))

    # extras (overheads)
    for k in ("twc_freight_pct_of_sales", "twc_safety_stock_pct_cogs", "twc_other_wc_fixed"):
        merged[k] = Decimal(str(existing.get(k, defaults.get(k, 0) or 0)))

    return TWCOut(scenario_id=sc.id, **merged)


@router.put(
    "/{scenario_id}/twc",
    response_model=TWCOut,
    summary="Upsert TWC assumptions (core to scenario_twc; extras to overheads)",
)
def upsert_twc(
    payload: TWCIn,
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)

    # 1) Core günler → scenario_twc
    row = _get_scenario_twc(db, scenario_id)
    if row is None:
        row = ScenarioTWC(scenario_id=scenario_id)

    data = payload.dict()
    if data.get("twc_dso_days") is not None:
        row.dso_days = int(Decimal(str(data["twc_dso_days"])))
    if data.get("twc_dpo_days") is not None:
        row.dpo_days = int(Decimal(str(data["twc_dpo_days"])))
    if data.get("twc_dio_days") is not None:
        row.inventory_days = int(Decimal(str(data["twc_dio_days"])))

    db.add(row)

    # 2) Ek parametreler → overheads (legacy devam)
    for k in ("twc_freight_pct_of_sales", "twc_safety_stock_pct_cogs", "twc_other_wc_fixed"):
        _upsert_overhead_fixed(db, scenario_id, k, data.get(k))

    db.commit()

    # response
    return get_twc(scenario_id, db, _user)


@router.post(
    "/{scenario_id}/twc/preview",
    response_model=TWCPreview,
    summary="Preview monthly Net Working Capital using current assumptions",
)
def preview_twc(
    scenario_id: int = Path(..., ge=1),
    use_boq_freight: bool = Query(True, description="BOQ 'freight' kalemlerini aylara dağıt ve ek navlun kabul et"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)

    # Assumptions
    twc_rows = get_twc(scenario_id, db, _user)  # reuse birleşik görünüm
    asum: Dict[str, Decimal] = {k: Decimal(str(v)) for k, v in twc_rows.dict().items() if k in TWC_KEYS}

    dso = asum.get("twc_dso_days", Decimal("45"))
    dpo = asum.get("twc_dpo_days", Decimal("30"))
    dio = asum.get("twc_dio_days", Decimal("20"))
    freight_pct = (asum.get("twc_freight_pct_of_sales", Decimal("0")) or Decimal("0")) / Decimal("100")
    safety_pct  = (asum.get("twc_safety_stock_pct_cogs", Decimal("0")) or Decimal("0")) / Decimal("100")
    other_fixed = asum.get("twc_other_wc_fixed", Decimal("0")) or Decimal("0")

    # Aylık gelir/COGS
    rc = _monthly_revenue_cogs(db, scenario_id)
    freight_boq = _monthly_freight_from_boq(db, scenario_id) if use_boq_freight else {}

    buckets: List[TWCBucket] = []
    totals = {
        "revenue": Decimal("0"),
        "cogs": Decimal("0"),
        "freight": Decimal("0"),
        "ar": Decimal("0"),
        "ap": Decimal("0"),
        "inv": Decimal("0"),
        "nwc": Decimal("0"),
    }

    months = sorted(rc.keys())
    for (y, m) in months:
        revenue = rc[(y, m)]["rev"]
        cogs    = rc[(y, m)]["cogs"]

        freight_from_sales = (revenue * freight_pct)
        freight_from_boq   = freight_boq.get((y, m), Decimal("0"))
        freight = freight_from_sales + freight_from_boq

        # Basit 30-gün yaklaşımı
        ar = (revenue * (dso / Decimal("30"))) if revenue > 0 else Decimal("0")
        ap = (cogs * (dpo / Decimal("30"))) if cogs > 0 else Decimal("0")
        inv = (cogs * (dio / Decimal("30"))) if cogs > 0 else Decimal("0")
        inv = inv + (cogs * safety_pct)

        nwc = ar + inv - ap

        totals["revenue"] += revenue
        totals["cogs"]    += cogs
        totals["freight"] += freight
        totals["ar"]      += ar
        totals["ap"]      += ap
        totals["inv"]     += inv
        totals["nwc"]     += nwc

        buckets.append(TWCBucket(
            year=y, month=m,
            revenue=revenue,
            cogs=cogs,
            freight=freight,
            ar=ar, ap=ap, inv=inv, nwc=nwc
        ))

    totals["nwc"] += other_fixed

    return TWCPreview(
        scenario_id=sc.id,
        assumptions=TWCOut(scenario_id=sc.id, **{**asum}),
        monthly=buckets,
        totals=totals,
    )
