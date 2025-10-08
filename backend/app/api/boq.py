from typing import List, Optional
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import select, func

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

    # NEW: price term snapshot carried on the BOQ row
    price_term: Optional[str] = Field(None)

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


# --- Price term resolver (SQLAlchemy üzerinden, sadece code döner) ---
from sqlalchemy import text as _text
from sqlalchemy.orm import Session as _Session

def _best_term_code_sa(db: _Session, product_id: int, on_date: str) -> Optional[str]:
    # 1) default book + tarih aralığı
    q1 = db.execute(_text("""
        SELECT pt.code
        FROM price_book_entries e
        JOIN price_books b ON b.id = e.price_book_id
        LEFT JOIN price_terms pt ON pt.id = e.price_term_id
        WHERE e.product_id = :pid
          AND e.is_active = 1
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
          AND e.is_active = 1
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
          AND e.is_active = 1
          AND b.is_active = 1
        ORDER BY b.is_default DESC,
                 date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                 e.id DESC
        LIMIT 1
    """), {"pid": product_id}).scalar()
    return q3


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

    # Eğer price_term verilmemiş ve ürün bağlıysa snapshot'ı otomatik set et
    snap_term = payload.price_term
    if (snap_term is None) and payload.product_id:
        snap_term = _best_term_code_sa(db, int(payload.product_id), date.today().isoformat())

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
        product_id=payload.product_id,   # NEW
        price_term=snap_term,            # snapshot (EXW vb.)
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

    # snapshot kuralı: gönderilen boş ise ve product_id varsa güncel kodu ata
    incoming = payload.dict()
    snap_term = incoming.get("price_term")
    prod_id = incoming.get("product_id") or row.product_id
    if snap_term is None and prod_id:
        snap_term = _best_term_code_sa(db, int(prod_id), date.today().isoformat())
    incoming["price_term"] = snap_term

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
    _ensure_scenario(db, scenario_id)
    new_rows: List[ScenarioBOQItem] = []
    today = date.today().isoformat()
    for item in payload.items:
        snap_term = item.price_term
        if snap_term is None and item.product_id:
            snap_term = _best_term_code_sa(db, int(item.product_id), today)

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
                product_id=item.product_id,     # NEW
                price_term=snap_term,           # NEW snapshot
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


# ------------------------------------------------------------------
# Aşağıdaki ikinci bölüm eski rotaların refactor'ı — senkronize edildi
# ------------------------------------------------------------------
from __future__ import annotations

from typing import List as _List, Optional as _Optional, Tuple
from decimal import Decimal as _Decimal

from fastapi import APIRouter as _APIRouter, Depends as _Depends, HTTPException as _HTTPException, Path as _Path, Query as _Query, status as _status
from pydantic import BaseModel as _BaseModel, Field as _Field, validator as _validator
from sqlalchemy.orm import Session as _Session
from sqlalchemy import text as _text

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
    quantity: _Decimal = _Field(default=0)
    unit_price: _Decimal = _Field(default=0)
    unit_cogs: _Optional[_Decimal] = None
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
    quantity: _Decimal
    unit_price: _Decimal
    unit_cogs: _Optional[_Decimal]
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

@router2.post("/scenarios/{scenario_id}/boq", status_code=_status.HTTP_201_CREATED, response_model=BOQItemOut2)
@router2.post("/business-cases/scenarios/{scenario_id}/boq", status_code=_status.HTTP_201_CREATED, response_model=BOQItemOut2)
def create_boq_item_2(
    scenario_id: int,
    payload: BOQItemIn2,
    db: _Session = _Depends(_get_db),
    user=_Depends(_get_current_user),
):
    _ensure_scenario2(db, scenario_id)
    sy, sm = _ym(payload.start_year, payload.start_month)

    snap_term = payload.price_term
    if snap_term is None and payload.product_id:
        snap_term = _best_term_code_sa(db, int(payload.product_id), date.today().isoformat())

    item = _ScenarioBOQItem(
        scenario_id=scenario_id,
        section=payload.section,
        item_name=payload.item_name,
        unit=payload.unit,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        unit_cogs=payload.unit_cogs,
        frequency=payload.frequency,
        start_year=sy,
        start_month=sm,
        months=payload.months,
        formulation_id=payload.formulation_id,
        price_escalation_policy_id=payload.price_escalation_policy_id,
        product_id=payload.product_id,   # NEW
        price_term=snap_term,            # NEW snapshot
        is_active=payload.is_active,
        notes=payload.notes,
        category=payload.category,
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
    _ensure_scenario2(db, scenario_id)
    item = db.get(_ScenarioBOQItem, item_id)
    if not item or item.scenario_id != scenario_id:
        raise _HTTPException(status_code=404, detail="BOQ item not found")

    sy, sm = _ym(payload.start_year, payload.start_month)

    # snapshot kuralı
    snap_term = payload.price_term
    prod_id = payload.product_id or item.product_id
    if snap_term is None and prod_id:
        snap_term = _best_term_code_sa(db, int(prod_id), date.today().isoformat())

    for k, v in dict(
        section=payload.section,
        item_name=payload.item_name,
        unit=payload.unit,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        unit_cogs=payload.unit_cogs,
        frequency=payload.frequency,
        start_year=sy,
        start_month=sm,
        months=payload.months,
        formulation_id=payload.formulation_id,
        price_escalation_policy_id=payload.price_escalation_policy_id,
        product_id=payload.product_id,     # NEW
        price_term=snap_term,               # NEW
        is_active=payload.is_active,
        notes=payload.notes,
        category=payload.category,
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
