# Path: backend/app/api/cost_books_api.py
from __future__ import annotations

import os
from datetime import date
from typing import List, Optional, Generator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, ConfigDict
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import and_, or_, select, update, create_engine, desc
from sqlalchemy.exc import IntegrityError

# Fallback default (if APP_DB_PATH is not set)
from .deps import get_db as _default_get_db

# ──────────────────────────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/cost-books", tags=["Cost Books"])
# NEW: product-scoped router to satisfy frontend calls like /api/products/:id/best-cost
router_products = APIRouter(prefix="/api/products", tags=["Products (Cost Lookup)"])

# =========================================================
# DB SESSION — align with Products API (APP_DB_PATH)
# =========================================================
_APP_DB_PATH = os.getenv("APP_DB_PATH")  # e.g., C:/Dev/AryaIntel_CRM/app.db
if _APP_DB_PATH:
    _DB_URL = f"sqlite:///{_APP_DB_PATH}"
    _engine = create_engine(_DB_URL, connect_args={"check_same_thread": False}, future=True)
    _SessionLocalOverride = sessionmaker(bind=_engine, autocommit=False, autoflush=False, future=True)
else:
    _DB_URL = None
    _engine = None
    _SessionLocalOverride = None

def _get_db() -> Generator[Session, None, None]:
    if _SessionLocalOverride is not None:
        db = _SessionLocalOverride()
        try:
            yield db
        finally:
            db.close()
    else:
        # Falls back to project’s standard dependency
        yield from _default_get_db()

def _orm_db_path_hint() -> str:
    try:
        return _engine.url.database if _engine is not None else "default-DB (settings)"
    except Exception:
        return "unknown"

# -----------------------
# Schemas
# -----------------------
class CostBookIn(BaseModel):
    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    currency: str = Field(..., min_length=3, max_length=3)
    is_active: bool | int = True
    is_default: bool | int = False

    @field_validator("code")
    @classmethod
    def _code_trim(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("code is required")
        return v

    @field_validator("currency")
    @classmethod
    def _currency_3(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("currency must be a 3-letter code (e.g., USD)")
        return v

    @field_validator("is_active", "is_default", mode="before")
    @classmethod
    def _normalize_bools(cls, v):
        if isinstance(v, bool): return v
        if v in (0, 1): return bool(v)
        if isinstance(v, str): return v.strip().lower() in {"1", "true", "yes"}
        return bool(v)

class CostBookOut(CostBookIn):
    id: int
    model_config = ConfigDict(from_attributes=True)

class CostBookEntryIn(BaseModel):
    product_id: int
    unit_cost: float
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    # Table has no is_active; keep & ignore for BC
    is_active: bool | int = True
    cost_term_id: Optional[int] = None
    cost_term: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("is_active", mode="before")
    @classmethod
    def _normalize_bool(cls, v):
        if isinstance(v, bool): return v
        if v in (0, 1): return bool(v)
        if isinstance(v, str): return v.strip().lower() in {"1", "true", "yes"}
        return bool(v)

class CostBookEntryOut(BaseModel):
    id: int
    cost_book_id: int
    product_id: int
    unit_cost: float
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    cost_term_id: Optional[int] = None
    cost_term: Optional[str] = None
    notes: Optional[str] = None
    # UI helpers
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    currency: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# NEW: response for /api/products/{id}/best-cost
class BestCostOut(BaseModel):
    product_id: int
    cost_book_id: int
    cost_book_entry_id: int
    unit_cost: float
    currency: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    cost_term: Optional[str] = None
    cost_term_id: Optional[int] = None
    cost_term_code: Optional[str] = None

# -----------------------
# Lazy models
# -----------------------
def _models():
    from app.models import CostBook, CostBookEntry, Product, PriceTerm  # type: ignore
    return CostBook, CostBookEntry, Product, PriceTerm

# -----------------------
# Helpers
# -----------------------
def _ensure_single_default(db: Session, this_id: Optional[int]) -> None:
    if not this_id: return
    CostBook, *_ = _models()
    db.execute(update(CostBook).where(CostBook.id != this_id).values(is_default=False))

def _book_or_404(db: Session, book_id: int):
    CostBook, *_ = _models()
    b = db.get(CostBook, book_id)
    if not b:
        raise HTTPException(status_code=404, detail="Cost Book not found")
    return b

def _entry_or_404(db: Session, entry_id: int):
    _, CostBookEntry, *_ = _models()
    e = db.get(CostBookEntry, entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Cost Book Entry not found")
    return e

def _resolve_term_code(db: Session, cost_term_id: Optional[int], fallback_text: Optional[str]) -> Optional[str]:
    if not cost_term_id:
        return (fallback_text or None)
    *_, PriceTerm = _models()
    pt = db.get(PriceTerm, cost_term_id)
    return pt.code if pt else (fallback_text or None)

def _with_product_labels_and_currency(
    db: Session,
    rows: list,
    book_currency: Optional[str] = None,
) -> List[CostBookEntryOut]:
    if not rows:
        return []
    _, CostBookEntry, Product, PriceTerm = _models()

    prod_ids = list({r.product_id for r in rows if r.product_id})
    term_ids = list({r.cost_term_id for r in rows if r.cost_term_id})

    prod_map = {}
    if prod_ids:
        for pid, code, name in db.execute(
            select(Product.id, Product.code, Product.name).where(Product.id.in_(prod_ids))
        ):
            prod_map[pid] = (code, name)

    term_map = {}
    if term_ids:
        for tid, code in db.execute(
            select(PriceTerm.id, PriceTerm.code).where(PriceTerm.id.in_(term_ids))
        ):
            term_map[tid] = code

    out: List[CostBookEntryOut] = []
    for r in rows:
        p_code = p_name = None
        if r.product_id in prod_map:
            p_code, p_name = prod_map[r.product_id]
        cost_term = term_map.get(r.cost_term_id) if r.cost_term_id else (r.cost_term or None)

        out.append(
            CostBookEntryOut(
                id=r.id,
                cost_book_id=r.cost_book_id,
                product_id=r.product_id,
                unit_cost=float(r.unit_cost or 0),
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                cost_term_id=r.cost_term_id,
                cost_term=cost_term,
                notes=r.notes,
                product_code=p_code,
                product_name=p_name,
                currency=book_currency,
            )
        )
    return out

# NEW: best-cost selector used by /api/products/{id}/best-cost
def _select_best_cost(db: Session, product_id: int, on: Optional[date]) -> Optional[BestCostOut]:
    """
    Choose the effective cost for a product.
    Priority: active books, default book first, then latest valid_from.
    Currency comes from the CostBook (entries don't have a currency column).
    """
    CostBook, CostBookEntry, _, PriceTerm = _models()

    q = (
        select(
            CostBookEntry.id.label("entry_id"),
            CostBookEntry.product_id,
            CostBookEntry.cost_book_id,
            CostBookEntry.unit_cost,
            CostBook.currency.label("book_currency"),
            CostBookEntry.valid_from,
            CostBookEntry.valid_to,
            CostBookEntry.cost_term_id,
            PriceTerm.code.label("term_code"),
            PriceTerm.name.label("term_name"),
            CostBook.is_default,
        )
        .join(CostBook, CostBook.id == CostBookEntry.cost_book_id)
        .outerjoin(PriceTerm, PriceTerm.id == CostBookEntry.cost_term_id)
        .where(
            CostBookEntry.product_id == product_id,
            CostBook.is_active == True,  # noqa: E712
        )
    )

    if on:
        q = q.where(
            and_(
                or_(CostBookEntry.valid_from == None, CostBookEntry.valid_from <= on),  # noqa: E711
                or_(CostBookEntry.valid_to == None, on <= CostBookEntry.valid_to),      # noqa: E711
            )
        )

    q = q.order_by(
        desc(CostBook.is_default),
        desc(CostBookEntry.valid_from),
        desc(CostBookEntry.id),
    )

    row = db.execute(q).first()
    if not row:
        return None

    r = row._mapping
    return BestCostOut(
        product_id=product_id,
        cost_book_id=r["cost_book_id"],
        cost_book_entry_id=r["entry_id"],
        unit_cost=float(r["unit_cost"] or 0),
        currency=r.get("book_currency"),
        valid_from=r.get("valid_from"),
        valid_to=r.get("valid_to"),
        cost_term=r.get("term_name"),
        cost_term_id=r.get("cost_term_id"),
        cost_term_code=r.get("term_code"),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Books CRUD
# ──────────────────────────────────────────────────────────────────────────────
@router.get("", response_model=List[CostBookOut])
def list_cost_books(
    db: Session = Depends(_get_db),
    q: Optional[str] = Query(default=None, description="Search by code or name"),
    is_active: Optional[bool] = Query(default=None),
    is_default: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    CostBook, *_ = _models()
    stmt = select(CostBook)
    if q:
        from sqlalchemy import func
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(func.lower(CostBook.code).like(like), func.lower(CostBook.name).like(like))
        )
    if is_active is not None:
        stmt = stmt.where(CostBook.is_active == is_active)
    if is_default is not None:
        stmt = stmt.where(CostBook.is_default == is_default)
    stmt = stmt.order_by(
        CostBook.is_default.desc(), CostBook.is_active.desc(), CostBook.code.asc()
    ).limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return [CostBookOut.model_validate(b) for b in rows]

@router.post("", response_model=CostBookOut, status_code=status.HTTP_201_CREATED)
def create_cost_book(payload: CostBookIn, db: Session = Depends(_get_db)):
    CostBook, *_ = _models()
    b = CostBook(
        code=payload.code.strip(),
        name=payload.name.strip(),
        currency=payload.currency.strip().upper(),
        is_active=bool(payload.is_active),
        is_default=bool(payload.is_default),
    )
    db.add(b)
    db.flush()
    if b.is_default:
        _ensure_single_default(db, b.id)
    db.commit()
    db.refresh(b)
    return CostBookOut.model_validate(b)

@router.get("/{book_id}", response_model=CostBookOut)
def get_cost_book(book_id: int, db: Session = Depends(_get_db)):
    b = _book_or_404(db, book_id)
    return CostBookOut.model_validate(b)

@router.put("/{book_id}", response_model=CostBookOut)
def update_cost_book(book_id: int, payload: CostBookIn, db: Session = Depends(_get_db)):
    b = _book_or_404(db, book_id)
    b.code = payload.code.strip()
    b.name = payload.name.strip()
    b.currency = payload.currency.strip().upper()
    b.is_active = bool(payload.is_active)
    b.is_default = bool(payload.is_default)
    db.add(b)
    db.flush()
    if b.is_default:
        _ensure_single_default(db, b.id)
    db.commit()
    db.refresh(b)
    return CostBookOut.model_validate(b)

@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_book(book_id: int, db: Session = Depends(_get_db)):
    b = _book_or_404(db, book_id)
    db.delete(b)
    db.commit()
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Entries (nested) CRUD
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/{book_id}/entries", response_model=List[CostBookEntryOut])
def list_cost_book_entries(
    book_id: int,
    db: Session = Depends(_get_db),
    product_id: Optional[int] = Query(default=None),
    active_only: bool = Query(default=False, description="Ignored (no is_active column on entries)"),
    valid_on: Optional[date] = Query(default=None, description="Filter by date window"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    CostBook, CostBookEntry, *_ = _models()
    b = _book_or_404(db, book_id)

    stmt = select(CostBookEntry).where(CostBookEntry.cost_book_id == book_id)
    if product_id:
        stmt = stmt.where(CostBookEntry.product_id == product_id)
    if valid_on:
        stmt = stmt.where(
            and_(
                or_(CostBookEntry.valid_from == None, CostBookEntry.valid_from <= valid_on),  # noqa: E711
                or_(CostBookEntry.valid_to == None, CostBookEntry.valid_to >= valid_on),      # noqa: E711
            )
        )
    stmt = stmt.order_by(
        CostBookEntry.product_id.asc(),
        CostBookEntry.valid_from.asc().nullsfirst(),
        CostBookEntry.valid_to.asc().nullslast(),
        CostBookEntry.id.asc(),
    ).limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return _with_product_labels_and_currency(db, rows, book_currency=b.currency)

@router.post("/{book_id}/entries", response_model=CostBookEntryOut, status_code=status.HTTP_201_CREATED)
def create_cost_book_entry(book_id: int, payload: CostBookEntryIn, db: Session = Depends(_get_db)):
    """
    Insert-first, then map FK errors:
    - Guarantees we don’t reject valid products due to cross-DB lookups.
    - If FK fails, we return 400 with a helpful hint of which DB file this endpoint is using.
    """
    CostBook, CostBookEntry, *_ = _models()
    b = _book_or_404(db, book_id)

    term_code = _resolve_term_code(db, payload.cost_term_id, payload.cost_term)

    e = CostBookEntry(
        cost_book_id=book_id,
        product_id=int(payload.product_id),
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        unit_cost=payload.unit_cost,
        cost_term_id=payload.cost_term_id,
        cost_term=term_code,
        notes=payload.notes,
    )
    try:
        db.add(e)
        db.commit()
        db.refresh(e)
    except IntegrityError as ex:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Invalid product_id or cost_term_id (ORM DB: {_orm_db_path_hint()})",
        ) from ex

    return _with_product_labels_and_currency(db, [e], book_currency=b.currency)[0]

@router.put("/{book_id}/entries/{entry_id}", response_model=CostBookEntryOut)
def update_cost_book_entry(book_id: int, entry_id: int, payload: CostBookEntryIn, db: Session = Depends(_get_db)):
    CostBook, CostBookEntry, *_ = _models()
    b = _book_or_404(db, book_id)
    e = _entry_or_404(db, entry_id)
    if e.cost_book_id != book_id:
        raise HTTPException(status_code=400, detail="Entry does not belong to this book")

    term_code = _resolve_term_code(db, payload.cost_term_id, payload.cost_term)

    e.product_id = int(payload.product_id)
    e.unit_cost = payload.unit_cost
    e.valid_from = payload.valid_from
    e.valid_to = payload.valid_to
    e.cost_term_id = payload.cost_term_id
    e.cost_term = term_code
    e.notes = payload.notes

    try:
        db.add(e)
        db.commit()
        db.refresh(e)
    except IntegrityError as ex:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Invalid product_id or cost_term_id (ORM DB: {_orm_db_path_hint()})",
        ) from ex

    return _with_product_labels_and_currency(db, [e], book_currency=b.currency)[0]

@router.delete("/{book_id}/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_book_entry(book_id: int, entry_id: int, db: Session = Depends(_get_db)):
    _ = _book_or_404(db, book_id)
    e = _entry_or_404(db, entry_id)
    if e.cost_book_id != book_id:
        raise HTTPException(status_code=400, detail="Entry does not belong to this book")
    db.delete(e)
    db.commit()
    return None

# ──────────────────────────────────────────────────────────────────────────────
# NEW: Product-scoped "best cost" endpoint to match the frontend
# ──────────────────────────────────────────────────────────────────────────────
@router_products.get("/{product_id}/best-cost", response_model=BestCostOut)
def best_cost_for_product(
    product_id: int,
    on: Optional[date] = Query(default=None, description="Evaluate cost valid on this date (YYYY-MM-DD)"),
    db: Session = Depends(_get_db),
):
    """
    Mirrors /api/products/{id}/best-price, but for Cost Books.
    Returns 404 if no active/default cost applies (frontend already handles 404s gracefully).
    """
    result = _select_best_cost(db, product_id=product_id, on=on)
    if not result:
        raise HTTPException(status_code=404, detail="No cost found for product")
    return result
