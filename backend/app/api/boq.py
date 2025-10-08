from __future__ import annotations

# ===============================================================
# AryaIntel CRM — BOQ API (with Best-Cost resolver + server autofill)
# - CRUD for scenario BOQ items (legacy + refactor paths kept)
# - Price Term snapshot logic (frozen on product select if absent)
# - NEW: Best-Cost lookup from Cost Books (cost_books / cost_book_entries)
# - NEW: Server-side autofill of unit_cogs if product is selected and cogs is empty
#
# Notes:
# * Cost lookup prefers the single default active cost book, then any active book.
# * Date window: valid_from <= on_date <= valid_to (NULL is open-ended).
# * If price_term code is supplied, we match on cost_term_id/code when possible.
# * FX conversion is attempted via scenario_fx_rates (rate_to_base); if no match, raw cost is used.
# * Endpoints live under "/scenarios/..." (consistent with existing BOQ CRUD).
# ===============================================================

from typing import List, Optional, Tuple, Dict, Any
from decimal import Decimal
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select, func, text as _text

from ..models import Scenario, ScenarioBOQItem
from .deps import get_db, get_current_user  # Current user dependency (token)

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

    # Link to Product
    product_id: Optional[int] = None

    # price term snapshot carried on the BOQ row
    price_term: Optional[str] = Field(None)

    is_active: bool = True
    notes: Optional[str] = None

    category: Optional[str] = Field(None)  # SQLite CHECK validated in DB layer

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
    # NEW
    product_id: Optional[int]
    price_term: Optional[str]
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


def _as_decimal(v: Optional[float | int | str | Decimal]) -> Optional[Decimal]:
    if v is None:
        return None
    return Decimal(str(v))


def _first_day_of(sy: Optional[int], sm: Optional[int], fallback: Optional[str]) -> str:
    if sy and sm:
        return f"{int(sy):04d}-{int(sm):02d}-01"
    return fallback or date.today().isoformat()


# --- Price term resolver (SQLAlchemy üzerinden, sadece code döner) ---
from sqlalchemy.orm import Session as _Session

def _best_term_code_sa(db: _Session, product_id: int, on_date: str) -> Optional[str]:
    # 1) default book + tarih aralığı
    q1 = db.execute(_text("""
        SELECT pt.code
        FROM price_book_entries e
        JOIN price_books b ON b.id = e.price_book_id
        LEFT JOIN price_terms pt ON pt.id = e.price_term_id
        WHERE e.product_id = :pid
          AND b.is_active = 1
          AND b.is_default = 1
          AND (e.valid_from IS NULL OR date(e.valid_from) <= date(:on))
          AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(:on))
        ORDER BY date(IFNULL(e.valid_from,'0001-01-01')) DESC, e.id DESC
        LIMIT 1
    """), {"pid": product_id, "on": on_date}).scalar()
    if q1:
        return q1

    # 2) herhangi aktif book + tarih aralığı (default öne)
    q2 = db.execute(_text("""
        SELECT pt.code
        FROM price_book_entries e
        JOIN price_books b ON b.id = e.price_book_id
        LEFT JOIN price_terms pt ON pt.id = e.price_term_id
        WHERE e.product_id = :pid
          AND b.is_active = 1
          AND (e.valid_from IS NULL OR date(e.valid_from) <= date(:on))
          AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(:on))
        ORDER BY b.is_default DESC,
                 date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                 e.id DESC
        LIMIT 1
    """), {"pid": product_id, "on": on_date}).scalar()
    if q2:
        return q2

    # 3) tarih penceresini yok say: en yeni aktif entry
    q3 = db.execute(_text("""
        SELECT pt.code
        FROM price_book_entries e
        JOIN price_books b ON b.id = e.price_book_id
        LEFT JOIN price_terms pt ON pt.id = e.price_term_id
        WHERE e.product_id = :pid
          AND b.is_active = 1
        ORDER BY b.is_default DESC,
                 date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                 e.id DESC
        LIMIT 1
    """), {"pid": product_id}).scalar()
    return q3


# --- FX resolver (scenario_fx_rates → rate_to_base) ---
def _fx_rate_to_base(db: Session, scenario_id: int, currency: str, on_date: str) -> Optional[float]:
    """Return most recent active FX rate_to_base for (scenario_id, currency) covering on_date."""
    # Convert date → year/month
    try:
        y, m, _ = [int(x) for x in on_date.split("-")]
    except Exception:
        dt = date.today()
        y, m = dt.year, dt.month

    row = db.execute(_text("""
        SELECT rate_to_base
        FROM scenario_fx_rates
        WHERE scenario_id = :sid
          AND currency = :cur
          AND is_active = 1
          AND (start_year IS NULL OR start_year*100 + IFNULL(start_month,1) <= :ym)
          AND (end_year   IS NULL OR end_year*100   + IFNULL(end_month,12)  >= :ym)
        ORDER BY (start_year*100 + IFNULL(start_month,1)) DESC, id DESC
        LIMIT 1
    """), {"sid": scenario_id, "cur": currency, "ym": y*100 + m}).scalar()
    return float(row) if row is not None else None


# --- Best-Cost resolver (cost_books / cost_book_entries) ---
def _best_cost_sa(
    db: Session,
    product_id: int,
    on_date: str,
    price_term_code: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Returns a dict:
      {
        "unit_cost": float,
        "currency": str,
        "book_id": int,
        "book_code": str,
        "entry_id": int,
        "source": str,  # e.g., "cost_book:COST-DEFAULT"
      }
    or None if not found.
    """
    params = {"pid": product_id, "on": on_date}
    term_filter_sql = ""
    if price_term_code:
        term_filter_sql = " AND (pt.code = :ptc OR e.cost_term = :ptc) "
        params["ptc"] = price_term_code

    # 1) default active cost book
    sql1 = f"""
        SELECT e.id AS entry_id,
               b.id AS book_id,
               b.code AS book_code,
               b.currency AS currency,
               e.unit_cost AS unit_cost
        FROM cost_book_entries e
        JOIN cost_books b ON b.id = e.cost_book_id
        LEFT JOIN price_terms pt ON pt.id = e.cost_term_id
        WHERE e.product_id = :pid
          AND b.is_active = 1
          AND b.is_default = 1
          AND (e.valid_from IS NULL OR date(e.valid_from) <= date(:on))
          AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(:on))
          {term_filter_sql}
        ORDER BY date(IFNULL(e.valid_from,'0001-01-01')) DESC, e.id DESC
        LIMIT 1
    """
    row = db.execute(_text(sql1), params).mappings().first()
    if row:
        d = dict(row)
        d["source"] = f"cost_book:{d.get('book_code','')}"
        return d

    # 2) any active cost book (prefer default)
    sql2 = f"""
        SELECT e.id AS entry_id,
               b.id AS book_id,
               b.code AS book_code,
               b.currency AS currency,
               e.unit_cost AS unit_cost
        FROM cost_book_entries e
        JOIN cost_books b ON b.id = e.cost_book_id
        LEFT JOIN price_terms pt ON pt.id = e.cost_term_id
        WHERE e.product_id = :pid
          AND b.is_active = 1
          AND (e.valid_from IS NULL OR date(e.valid_from) <= date(:on))
          AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(:on))
          {term_filter_sql}
        ORDER BY b.is_default DESC,
                 date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                 e.id DESC
        LIMIT 1
    """
    row = db.execute(_text(sql2), params).mappings().first()
    if row:
        d = dict(row)
        d["source"] = f"cost_book:{d.get('book_code','')}"
        return d

    # 3) ignore date window
    sql3 = f"""
        SELECT e.id AS entry_id,
               b.id AS book_id,
               b.code AS book_code,
               b.currency AS currency,
               e.unit_cost AS unit_cost
        FROM cost_book_entries e
        JOIN cost_books b ON b.id = e.cost_book_id
        LEFT JOIN price_terms pt ON pt.id = e.cost_term_id
        WHERE e.product_id = :pid
          AND b.is_active = 1
          {term_filter_sql}
        ORDER BY b.is_default DESC,
                 date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                 e.id DESC
        LIMIT 1
    """
    row = db.execute(_text(sql3), params).mappings().first()
    if row:
        d = dict(row)
        d["source"] = f"cost_book:{d.get('book_code','')}"
        return d

    return None


def _autofill_cogs_if_needed(
    db: Session,
    scenario: Scenario,
    payload: dict,
    price_term_code: Optional[str],
) -> Optional[Decimal]:
    """
    If unit_cogs is None and product_id exists -> use best-cost to return a Decimal.
    Tries FX to scenario base via scenario_fx_rates; if no FX, returns raw cost.
    """
    unit_cogs = payload.get("unit_cogs")
    product_id = payload.get("product_id")
    if unit_cogs is not None or not product_id:
        return _as_decimal(unit_cogs)

    # pick on_date: prefer row start (year/month) → otherwise scenario.start_date → today
    on_date = _first_day_of(payload.get("start_year"), payload.get("start_month"), getattr(scenario, "start_date", None))

    # if price term unknown, try to resolve one (mirrors price snapshot behavior)
    term_code = price_term_code
    if term_code is None:
        term_code = _best_term_code_sa(db, int(product_id), on_date)

    bc = _best_cost_sa(db, int(product_id), on_date, term_code)
    if not bc:
        return None  # keep as None; FE will show manual

    unit_cost = Decimal(str(bc["unit_cost"]))
    cur = bc["currency"]

    # attempt FX to base
    fx = _fx_rate_to_base(db, scenario.id, cur, on_date)
    if fx is not None and fx > 0:
        try:
            return (unit_cost * Decimal(str(fx))).quantize(Decimal("0.0001"))
        except Exception:
            return unit_cost  # fallback raw
    return unit_cost


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

    # price_term snapshot boşsa response'ta güncel code ile doldur
    today = date.today().isoformat()
    for r in rows:
        if r.price_term is None and r.product_id is not None:
            code = _best_term_code_sa(db, int(r.product_id), today)
            if code:
                r.price_term = code

    return rows


@router.get(
    "/{scenario_id}/boq/best-cost",
    summary="Resolve best unit cost for a product on a date (and optional price term)",
)
def best_cost_endpoint(
    scenario_id: int = Path(..., ge=1),
    product_id: int = Query(..., ge=1),
    price_term: Optional[str] = Query(None, description="Price term code (e.g., EXW). If omitted, resolver will pick using price books."),
    on_date: Optional[str] = Query(None, description="YYYY-MM-DD; default uses scenario start date or today"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    sc = _ensure_scenario(db, scenario_id)
    on = on_date or getattr(sc, "start_date", None) or date.today().isoformat()
    # If no price_term provided, reuse our price-term resolver for a good default
    term = price_term or _best_term_code_sa(db, int(product_id), on)
    bc = _best_cost_sa(db, int(product_id), on, term)
    if not bc:
        raise HTTPException(status_code=404, detail="No matching cost entry found")

    # try FX to base so the client can see both
    fx = _fx_rate_to_base(db, scenario_id, bc["currency"], on)
    unit_cost_base = float(bc["unit_cost"]) * fx if fx else None

    return {
        "product_id": product_id,
        "price_term": term,
        "on_date": on,
        "unit_cost": float(bc["unit_cost"]),
        "currency": bc["currency"],
        "unit_cost_base": unit_cost_base,
        "fx_rate_used": fx,
        "source": bc["source"],
        "entry_id": bc["entry_id"],
        "book_id": bc["book_id"],
    }


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
    sc = _ensure_scenario(db, scenario_id)

    # Eğer price_term verilmemiş ve ürün bağlıysa snapshot'ı otomatik set et
    snap_term = payload.price_term
    if (snap_term is None) and payload.product_id:
        snap_term = _best_term_code_sa(db, int(payload.product_id), _first_day_of(payload.start_year, payload.start_month, getattr(sc, "start_date", None)))

    incoming = payload.dict()
    # Server-side autofill of unit_cogs if empty and product is selected
    if incoming.get("unit_cogs") is None and incoming.get("product_id"):
        auto_cogs = _autofill_cogs_if_needed(db, sc, incoming, snap_term)
        if auto_cogs is not None:
            incoming["unit_cogs"] = auto_cogs

    row = ScenarioBOQItem(
        scenario_id=scenario_id,
        section=incoming["section"],
        item_name=incoming["item_name"],
        unit=incoming["unit"],
        quantity=incoming["quantity"],
        unit_price=incoming["unit_price"],
        unit_cogs=incoming.get("unit_cogs"),
        frequency=incoming["frequency"],
        start_year=incoming["start_year"],
        start_month=incoming["start_month"],
        months=incoming["months"],
        product_id=incoming["product_id"],   # NEW
        price_term=snap_term,                # snapshot (EXW vb.)
        is_active=incoming["is_active"],
        notes=incoming["notes"],
        category=incoming["category"],
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
    sc = _ensure_scenario(db, scenario_id)
    row = db.get(ScenarioBOQItem, item_id)
    if not row or row.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="BOQ item not found")

    incoming = payload.dict()
    # snapshot kuralı: gönderilen boş ise ve product_id varsa güncel kodu ata
    snap_term = incoming.get("price_term")
    prod_id = incoming.get("product_id") or row.product_id
    # choose date from incoming start or row's existing or scenario.start_date
    on_date = _first_day_of(incoming.get("start_year") or row.start_year,
                            incoming.get("start_month") or row.start_month,
                            getattr(sc, "start_date", None))

    if snap_term is None and prod_id:
        snap_term = _best_term_code_sa(db, int(prod_id), on_date)
    incoming["price_term"] = snap_term

    # Autofill unit_cogs only if currently missing AND product present
    if incoming.get("unit_cogs") is None and prod_id:
        auto_cogs = _autofill_cogs_if_needed(
            db,
            sc,
            {**incoming, "product_id": prod_id},
            snap_term,
        )
        if auto_cogs is not None:
            incoming["unit_cogs"] = auto_cogs

    for k, v in incoming.items():
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
    sc = _ensure_scenario(db, scenario_id)
    new_rows: List[ScenarioBOQItem] = []
    for item in payload.items:
        on_date = _first_day_of(item.start_year, item.start_month, getattr(sc, "start_date", None))
        snap_term = item.price_term
        if snap_term is None and item.product_id:
            snap_term = _best_term_code_sa(db, int(item.product_id), on_date)

        incoming = item.dict()
        if incoming.get("unit_cogs") is None and incoming.get("product_id"):
            auto_cogs = _autofill_cogs_if_needed(db, sc, incoming, snap_term)
            if auto_cogs is not None:
                incoming["unit_cogs"] = auto_cogs

        new_rows.append(
            ScenarioBOQItem(
                scenario_id=scenario_id,
                section=incoming["section"],
                item_name=incoming["item_name"],
                unit=incoming["unit"],
                quantity=incoming["quantity"],
                unit_price=incoming["unit_price"],
                unit_cogs=incoming.get("unit_cogs"),
                frequency=incoming["frequency"],
                start_year=incoming["start_year"],
                start_month=incoming["start_month"],
                months=incoming["months"],
                product_id=incoming["product_id"],     # NEW
                price_term=snap_term,                   # NEW snapshot
                is_active=incoming["is_active"],
                notes=incoming["notes"],
                category=incoming["category"],
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


# ------------------------------------------------------------------
# Aşağıdaki ikinci bölüm eski rotaların refactor'ı — senkronize edildi
# ------------------------------------------------------------------
from typing import List as _List, Optional as _Optional

from fastapi import APIRouter as _APIRouter, Depends as _Depends, HTTPException as _HTTPException, Path as _Path, Query as _Query, status as _status
from pydantic import BaseModel as _BaseModel, Field as _Field, validator as _validator
from sqlalchemy.orm import Session as _Session

from ..models import Scenario as _Scenario, ScenarioBOQItem as _ScenarioBOQItem
from .deps import get_db as _get_db, get_current_user as _get_current_user

# Router: explicit paths added per endpoint (both legacy and refactor paths)
router2 = _APIRouter(tags=["boq"])

def _ensure_scenario2(db: _Session, scenario_id: int) -> _Scenario:
    sc = db.get(_Scenario, scenario_id)
    if not sc:
        raise _HTTPException(status_code=404, detail="Scenario not found")
    return sc

def _ym(year: _Optional[int], month: _Optional[int]) -> Tuple[_Optional[int], _Optional[int]]:
    if year is None and month is None:
        return None, None
    if year is None or month is None or not (1 <= int(month) <= 12):
        raise _HTTPException(status_code=400, detail="Invalid start year/month")
    return int(year), int(month)

class BOQItemIn2(_BaseModel):
    section: _Optional[str] = None
    item_name: str
    unit: str
    quantity: Decimal = _Field(default=Decimal("0"))
    unit_price: Decimal = _Field(default=Decimal("0"))
    unit_cogs: _Optional[Decimal] = None
    frequency: str = _Field(default="once")  # once|monthly|quarterly|annual
    start_year: _Optional[int] = None
    start_month: _Optional[int] = _Field(default=None, ge=1, le=12)
    months: _Optional[int] = None
    formulation_id: _Optional[int] = None
    price_escalation_policy_id: _Optional[int] = None
    # NEW
    product_id: _Optional[int] = None
    price_term: _Optional[str] = None
    is_active: bool = True
    notes: _Optional[str] = None
    category: _Optional[str] = None  # bulk_with_freight|bulk_ex_freight|freight

    @_validator("frequency")
    def _freq_ok(cls, v: str) -> str:
        allowed = {"once", "monthly", "quarterly", "annual"}
        if v not in allowed:
            raise ValueError(f"frequency must be one of {sorted(allowed)}")
        return v

    @_validator("category")
    def _cat_ok(cls, v: _Optional[str]) -> _Optional[str]:
        if v is None:
            return v
        allowed = {"bulk_with_freight", "bulk_ex_freight", "freight"}
        if v not in allowed:
            raise ValueError(f"category must be one of {sorted(allowed)}")
        return v

class BOQItemOut2(_BaseModel):
    id: int
    scenario_id: int
    section: _Optional[str]
    item_name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    unit_cogs: _Optional[Decimal]
    frequency: str
    start_year: _Optional[int]
    start_month: _Optional[int]
    months: _Optional[int]
    formulation_id: _Optional[int]
    price_escalation_policy_id: _Optional[int]
    # NEW
    product_id: _Optional[int]
    price_term: _Optional[str]
    is_active: bool
    notes: _Optional[str]
    category: _Optional[str]
    class Config:
        orm_mode = True

class ScenarioOut(_BaseModel):
    id: int
    name: str
    months: int
    start_date: str
    is_boq_ready: bool
    is_twc_ready: bool
    is_capex_ready: bool
    is_services_ready: bool
    class Config:
        orm_mode = True

@router2.get("/boq/scenarios", response_model=_List[ScenarioOut])
def list_scenarios(
    q: _Optional[str] = _Query(None, description="Name contains (case-insensitive)"),
    limit: int = _Query(50, ge=1, le=500),
    offset: int = _Query(0, ge=0),
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    qry = db.query(_Scenario)
    if q:
        qry = qry.filter(_Scenario.name.ilike(f"%{q}%"))
    rows = (
        qry.order_by(_Scenario.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows

@router2.get("/scenarios/{scenario_id}/boq", response_model=_List[BOQItemOut2])
@router2.get("/business-cases/scenarios/{scenario_id}/boq", response_model=_List[BOQItemOut2])
def list_boq_items_2(
    scenario_id: int = _Path(..., ge=1),
    active: _Optional[bool] = _Query(None),
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    _ensure_scenario2(db, scenario_id)
    q = db.query(_ScenarioBOQItem).filter(_ScenarioBOQItem.scenario_id == scenario_id)
    if active is not None:
        q = q.filter(_ScenarioBOQItem.is_active == bool(active))
    q = q.order_by(_ScenarioBOQItem.id.desc())
    items = q.all()

    # price_term boşsa response'ta güncel code ile doldur
    today = date.today().isoformat()
    for r in items:
        if r.price_term is None and r.product_id is not None:
            code = _best_term_code_sa(db, int(r.product_id), today)
            if code:
                r.price_term = code

    return items

@router2.get("/scenarios/{scenario_id}/boq/best-cost")
@router2.get("/business-cases/scenarios/{scenario_id}/boq/best-cost")
def best_cost_endpoint_2(
    scenario_id: int,
    product_id: int = _Query(..., ge=1),
    price_term: _Optional[str] = _Query(None),
    on_date: _Optional[str] = _Query(None),
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    sc = _ensure_scenario2(db, scenario_id)
    on = on_date or getattr(sc, "start_date", None) or date.today().isoformat()
    term = price_term or _best_term_code_sa(db, int(product_id), on)
    bc = _best_cost_sa(db, int(product_id), on, term)
    if not bc:
        raise _HTTPException(status_code=404, detail="No matching cost entry found")

    fx = _fx_rate_to_base(db, scenario_id, bc["currency"], on)
    unit_cost_base = float(bc["unit_cost"]) * fx if fx else None
    return {
        "product_id": product_id,
        "price_term": term,
        "on_date": on,
        "unit_cost": float(bc["unit_cost"]),
        "currency": bc["currency"],
        "unit_cost_base": unit_cost_base,
        "fx_rate_used": fx,
        "source": bc["source"],
        "entry_id": bc["entry_id"],
        "book_id": bc["book_id"],
    }

@router2.post("/scenarios/{scenario_id}/boq", status_code=_status.HTTP_201_CREATED, response_model=BOQItemOut2)
@router2.post("/business-cases/scenarios/{scenario_id}/boq", status_code=_status.HTTP_201_CREATED, response_model=BOQItemOut2)
def create_boq_item_2(
    scenario_id: int,
    payload: BOQItemIn2,
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    sc = _ensure_scenario2(db, scenario_id)
    sy, sm = _ym(payload.start_year, payload.start_month)

    on = _first_day_of(sy, sm, getattr(sc, "start_date", None))
    snap_term = payload.price_term
    if snap_term is None and payload.product_id:
        snap_term = _best_term_code_sa(db, int(payload.product_id), on)

    incoming = payload.dict()
    if incoming.get("unit_cogs") is None and incoming.get("product_id"):
        auto_cogs = _autofill_cogs_if_needed(db, sc, {**incoming, "start_year": sy, "start_month": sm}, snap_term)
        if auto_cogs is not None:
            incoming["unit_cogs"] = auto_cogs

    item = _ScenarioBOQItem(
        scenario_id=scenario_id,
        section=incoming["section"],
        item_name=incoming["item_name"],
        unit=incoming["unit"],
        quantity=incoming["quantity"],
        unit_price=incoming["unit_price"],
        unit_cogs=incoming.get("unit_cogs"),
        frequency=incoming["frequency"],
        start_year=sy,
        start_month=sm,
        months=incoming["months"],
        formulation_id=incoming["formulation_id"],
        price_escalation_policy_id=incoming["price_escalation_policy_id"],
        product_id=incoming["product_id"],   # NEW
        price_term=snap_term,                # NEW snapshot
        is_active=incoming["is_active"],
        notes=incoming["notes"],
        category=incoming["category"],
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router2.put("/scenarios/{scenario_id}/boq/{item_id}", response_model=BOQItemOut2)
@router2.put("/business-cases/scenarios/{scenario_id}/boq/{item_id}", response_model=BOQItemOut2)
def update_boq_item_2(
    scenario_id: int,
    item_id: int,
    payload: BOQItemIn2,
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    sc = _ensure_scenario2(db, scenario_id)
    item = db.get(_ScenarioBOQItem, item_id)
    if not item or item.scenario_id != scenario_id:
        raise _HTTPException(status_code=404, detail="BOQ item not found")

    sy, sm = _ym(payload.start_year, payload.start_month)
    on = _first_day_of(sy if sy else item.start_year, sm if sm else item.start_month, getattr(sc, "start_date", None))

    # snapshot kuralı
    snap_term = payload.price_term
    prod_id = payload.product_id or item.product_id
    if snap_term is None and prod_id:
        snap_term = _best_term_code_sa(db, int(prod_id), on)

    incoming = payload.dict()
    if incoming.get("unit_cogs") is None and prod_id:
        auto_cogs = _autofill_cogs_if_needed(
            db,
            sc,
            {**incoming, "product_id": prod_id, "start_year": sy or item.start_year, "start_month": sm or item.start_month},
            snap_term,
        )
        if auto_cogs is not None:
            incoming["unit_cogs"] = auto_cogs

    for k, v in dict(
        section=incoming["section"],
        item_name=incoming["item_name"],
        unit=incoming["unit"],
        quantity=incoming["quantity"],
        unit_price=incoming["unit_price"],
        unit_cogs=incoming.get("unit_cogs"),
        frequency=incoming["frequency"],
        start_year=sy or item.start_year,
        start_month=sm or item.start_month,
        months=incoming["months"],
        formulation_id=incoming["formulation_id"],
        price_escalation_policy_id=incoming["price_escalation_policy_id"],
        product_id=incoming["product_id"],     # NEW
        price_term=snap_term,                   # NEW
        is_active=incoming["is_active"],
        notes=incoming["notes"],
        category=incoming["category"],
    ).items():
        setattr(item, k, v)

    db.commit()
    db.refresh(item)
    return item

@router2.delete("/scenarios/{scenario_id}/boq/{item_id}")
@router2.delete("/business-cases/scenarios/{scenario_id}/boq/{item_id}")
def delete_boq_item_2(
    scenario_id: int,
    item_id: int,
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    _ensure_scenario2(db, scenario_id)
    item = db.get(_ScenarioBOQItem, item_id)
    if not item or item.scenario_id != scenario_id:
        raise _HTTPException(status_code=404, detail="BOQ item not found")
    db.delete(item)
    db.commit()
    return {"deleted": True}

@router2.post("/scenarios/{scenario_id}/boq/mark-ready")
@router2.post("/business-cases/scenarios/{scenario_id}/boq/mark-ready")
def mark_boq_ready_2(
    scenario_id: int,
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    sc = _ensure_scenario2(db, scenario_id)
    if not sc.is_boq_ready:
        sc.is_boq_ready = True
        db.commit()
    return {"ok": True}

@router2.get("/boq/_debug/db")
@router2.get("/business-cases/_debug/db")
def debug_db_info_2(
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    engine = db.get_bind()
    url = str(engine.url)
    try:
        pragma_rows = db.execute(_text("PRAGMA database_list")).fetchall()
        database_list = [dict(row) for row in pragma_rows]
    except Exception:
        database_list = []

    def count(tbl: str):
        try:
            return int(db.execute(_text(f"SELECT COUNT(*) AS c FROM {tbl}")).scalar() or 0)
        except Exception:
            return None

    return {
        "engine_url": url,
        "sqlite_database_list": database_list,
        "counts": {
            "scenarios": count("scenarios"),
            "scenario_boq_items": count("scenario_boq_items"),
            "price_books": count("price_books"),
            "price_book_entries": count("price_book_entries"),
            "cost_books": count("cost_books"),
            "cost_book_entries": count("cost_book_entries"),
        },
    }

@router2.get("/boq/_debug/count")
def debug_count_2(
    table: str = _Query(..., description="Whitelisted table name"),
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    whitelist = {
        "scenarios",
        "scenario_boq_items",
        "price_books",
        "price_book_entries",
        "cost_books",
        "cost_book_entries",
    }
    if table not in whitelist:
        raise _HTTPException(status_code=400, detail=f"table must be one of: {sorted(whitelist)}")
    n = int(db.execute(_text(f"SELECT COUNT(*) AS c FROM {table}")).scalar() or 0)
    return {"table": table, "count": n}

@router2.get("/boq/_debug/sample")
def debug_sample_2(
    table: str = _Query(...),
    limit: int = _Query(10, ge=1, le=100),
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    try:
        rows = db.execute(_text(f"SELECT * FROM {table} LIMIT :lim"), {"lim": limit}).mappings().all()
    except Exception as e:
        raise _HTTPException(status_code=400, detail=f"bad table: {e}")
    return [dict(r) for r in rows]

# Mount second router
from fastapi import APIRouter as _APIRouterAlias
router_alias: _APIRouterAlias = router2
