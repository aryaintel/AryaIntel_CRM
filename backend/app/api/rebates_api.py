from __future__ import annotations

from typing import List, Optional, Any, Dict, Union
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .deps import get_db, get_current_user

router = APIRouter(prefix="/api/scenarios", tags=["rebates"])

# ---------------- Utilities ----------------
NumberLike = Optional[Union[int, float, Decimal]]

def _to_float(x: NumberLike) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    # last resort: try cast from str
    try:
        return float(x)  # type: ignore[arg-type]
    except Exception:
        return None

# --------------- Schema bootstrap (SQLite safe) ---------------
def _pragma(conn: Connection, sql: str):
    return conn.exec_driver_sql(sql)

def _ensure_schema(db: Session) -> None:
    conn = db.connection()

    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS scenario_rebates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            scope TEXT NOT NULL CHECK(scope IN ('all','boq','services','product')),
            kind  TEXT NOT NULL CHECK(kind  IN ('percent','tier_percent','lump_sum')),
            basis TEXT NOT NULL DEFAULT 'revenue',
            product_id INTEGER,
            valid_from_year INTEGER,
            valid_from_month INTEGER CHECK(valid_from_month IS NULL OR (valid_from_month BETWEEN 1 AND 12)),
            valid_to_year INTEGER,
            valid_to_month INTEGER CHECK(valid_to_month IS NULL OR (valid_to_month BETWEEN 1 AND 12)),
            accrual_method TEXT NOT NULL DEFAULT 'monthly' CHECK(accrual_method IN ('monthly','quarterly','annual','on_invoice')),
            pay_month_lag INTEGER DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cols = {row[1] for row in _pragma(conn, "PRAGMA table_info('scenario_rebates')").fetchall()}
    alters = {
        "basis":            "ALTER TABLE scenario_rebates ADD COLUMN basis TEXT NOT NULL DEFAULT 'revenue';",
        "product_id":       "ALTER TABLE scenario_rebates ADD COLUMN product_id INTEGER;",
        "valid_from_year":  "ALTER TABLE scenario_rebates ADD COLUMN valid_from_year INTEGER;",
        "valid_from_month": "ALTER TABLE scenario_rebates ADD COLUMN valid_from_month INTEGER;",
        "valid_to_year":    "ALTER TABLE scenario_rebates ADD COLUMN valid_to_year INTEGER;",
        "valid_to_month":   "ALTER TABLE scenario_rebates ADD COLUMN valid_to_month INTEGER;",
        "accrual_method":   "ALTER TABLE scenario_rebates ADD COLUMN accrual_method TEXT NOT NULL DEFAULT 'monthly';",
        "pay_month_lag":    "ALTER TABLE scenario_rebates ADD COLUMN pay_month_lag INTEGER DEFAULT 0;",
        "is_active":        "ALTER TABLE scenario_rebates ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
        "notes":            "ALTER TABLE scenario_rebates ADD COLUMN notes TEXT;",
        "created_at":       "ALTER TABLE scenario_rebates ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'));",
        "updated_at":       "ALTER TABLE scenario_rebates ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));",
    }
    for col, sql in alters.items():
        if col not in cols:
            conn.exec_driver_sql(sql)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_rebates_scenario ON scenario_rebates(scenario_id);")

    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS scenario_rebate_tiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rebate_id INTEGER NOT NULL,
            min_value NUMERIC NOT NULL DEFAULT 0,
            max_value NUMERIC,
            percent  NUMERIC,
            amount   NUMERIC,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(rebate_id) REFERENCES scenario_rebates(id) ON DELETE CASCADE
        );
    """)
    cols = {row[1] for row in _pragma(conn, "PRAGMA table_info('scenario_rebate_tiers')").fetchall()}
    alters = {
        "min_value":   "ALTER TABLE scenario_rebate_tiers ADD COLUMN min_value NUMERIC NOT NULL DEFAULT 0;",
        "max_value":   "ALTER TABLE scenario_rebate_tiers ADD COLUMN max_value NUMERIC;",
        "percent":     "ALTER TABLE scenario_rebate_tiers ADD COLUMN percent NUMERIC;",
        "amount":      "ALTER TABLE scenario_rebate_tiers ADD COLUMN amount NUMERIC;",
        "description": "ALTER TABLE scenario_rebate_tiers ADD COLUMN description TEXT;",
        "sort_order":  "ALTER TABLE scenario_rebate_tiers ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;",
    }
    for col, sql in alters.items():
        if col not in cols:
            conn.exec_driver_sql(sql)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_rebate_tiers_rebate ON scenario_rebate_tiers(rebate_id);")

    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS scenario_rebate_lumps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rebate_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
            amount NUMERIC NOT NULL,
            description TEXT,
            FOREIGN KEY(rebate_id) REFERENCES scenario_rebates(id) ON DELETE CASCADE
        );
    """)
    cols = {row[1] for row in _pragma(conn, "PRAGMA table_info('scenario_rebate_lumps')").fetchall()}
    alters = {
        "year":        "ALTER TABLE scenario_rebate_lumps ADD COLUMN year INTEGER NOT NULL;",
        "month":       "ALTER TABLE scenario_rebate_lumps ADD COLUMN month INTEGER NOT NULL;",
        "amount":      "ALTER TABLE scenario_rebate_lumps ADD COLUMN amount NUMERIC NOT NULL;",
        "description": "ALTER TABLE scenario_rebate_lumps ADD COLUMN description TEXT;",
    }
    for col, sql in alters.items():
        if col not in cols:
            conn.exec_driver_sql(sql)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_rebate_lumps_rebate ON scenario_rebate_lumps(rebate_id);")

# ---------------- Pydantic models ----------------
class RebateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scope: str = Field("all")                   # all|boq|services|product
    kind: str = Field("percent")                # percent|tier_percent|lump_sum
    basis: str = Field("revenue")               # revenue|gross_margin|volume
    product_id: Optional[int] = None

    valid_from_year: Optional[int] = None
    valid_from_month: Optional[int] = Field(None, ge=1, le=12)
    valid_to_year: Optional[int] = None
    valid_to_month: Optional[int] = Field(None, ge=1, le=12)

    accrual_method: str = Field("monthly")      # monthly|quarterly|annual|on_invoice
    pay_month_lag: Optional[int] = 0

    is_active: bool = True
    notes: Optional[str] = None

    percent_value: Optional[Decimal] = Field(None, description="Only when kind='percent'")
    tiers: Optional[List[Dict[str, Any]]] = None
    lumps: Optional[List[Dict[str, Any]]] = None

    @validator("scope")
    def _scope_ok(cls, v: str) -> str:
        allow = {"all", "boq", "services", "product"}
        if v not in allow:
            raise ValueError(f"scope must be one of {sorted(allow)}")
        return v

    @validator("kind")
    def _kind_ok(cls, v: str) -> str:
        allow = {"percent", "tier_percent", "lump_sum"}
        if v not in allow:
            raise ValueError(f"kind must be one of {sorted(allow)}")
        return v

    @validator("basis")
    def _basis_ok(cls, v: str) -> str:
        allow = {"revenue", "gross_margin", "volume"}
        if v not in allow:
            raise ValueError(f"basis must be one of {sorted(allow)}")
        return v

    @validator("accrual_method")
    def _accrual_ok(cls, v: str) -> str:
        allow = {"monthly", "quarterly", "annual", "on_invoice"}
        if v not in allow:
            raise ValueError(f"accrual_method must be one of {sorted(allow)}")
        return v


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
    notes: Optional[str]

    class Config:
        orm_mode = True


class TierIn(BaseModel):
    min_value: Decimal = 0
    max_value: Optional[Decimal] = None
    percent: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: Optional[int] = 0

class TierOut(TierIn):
    id: int
    rebate_id: int

class LumpIn(BaseModel):
    year: int
    month: int = Field(..., ge=1, le=12)
    amount: Decimal
    description: Optional[str] = None

class LumpOut(LumpIn):
    id: int
    rebate_id: int

# ---------------- Helpers ----------------
def _ensure_scenario(db: Session, scenario_id: int) -> None:
    try:
        row = db.execute(text("SELECT id FROM scenarios WHERE id=:sid"), {"sid": scenario_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Scenario not found")
    except SQLAlchemyError:
        # permissive in dev
        pass

def _ensure_rebate(db: Session, scenario_id: int, rebate_id: int) -> Dict[str, Any]:
    r = db.execute(
        text("SELECT * FROM scenario_rebates WHERE id = :rid AND scenario_id = :sid"),
        {"rid": rebate_id, "sid": scenario_id},
    ).mappings().fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Rebate not found")
    return dict(r)

def _fetch_tiers(db: Session, rid: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text("SELECT id, rebate_id, min_value, max_value, percent, amount, description, sort_order "
             "FROM scenario_rebate_tiers WHERE rebate_id = :rid ORDER BY sort_order, id"),
        {"rid": rid},
    ).mappings().all()
    return [dict(r) for r in rows]

def _fetch_lumps(db: Session, rid: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text("SELECT id, rebate_id, year, month, amount, description "
             "FROM scenario_rebate_lumps WHERE rebate_id = :rid ORDER BY year, month, id"),
        {"rid": rid},
    ).mappings().all()
    return [dict(r) for r in rows]

# ---------------- Endpoints ----------------
@router.get("/{scenario_id}/rebates", response_model=List[RebateOut])
def list_rebates(
    scenario_id: int,
    include_details: bool = Query(False, description="If true, include tiers & lumps"),
    active: Optional[bool] = Query(None, description="Filter by is_active"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_scenario(db, scenario_id)

        where = ["scenario_id = :sid"]
        params: Dict[str, Any] = {"sid": scenario_id}
        if active is not None:
            where.append("is_active = :active")
            params["active"] = 1 if active else 0

        rows = db.execute(
            text(
                "SELECT id, scenario_id, name, scope, kind, basis, product_id, "
                "valid_from_year, valid_from_month, valid_to_year, valid_to_month, "
                "accrual_method, pay_month_lag, is_active, notes "
                f"FROM scenario_rebates WHERE {' AND '.join(where)} "
                "ORDER BY id DESC"
            ),
            params,
        ).mappings().all()

        items = [dict(r) for r in rows]
        if include_details:
            for it in items:
                it["tiers"] = _fetch_tiers(db, it["id"])
                it["lumps"] = _fetch_lumps(db, it["id"])
        return items
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

@router.post("/{scenario_id}/rebates", response_model=RebateOut, status_code=status.HTTP_201_CREATED)
def create_rebate(
    scenario_id: int,
    body: RebateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_scenario(db, scenario_id)

        if body.scope == "product" and not body.product_id:
            raise HTTPException(status_code=400, detail="product_id is required when scope='product'")

        res = db.execute(
            text(
                "INSERT INTO scenario_rebates ("
                "scenario_id, name, scope, kind, basis, product_id, "
                "valid_from_year, valid_from_month, valid_to_year, valid_to_month, "
                "accrual_method, pay_month_lag, is_active, notes, updated_at"
                ") VALUES ("
                ":sid, :name, :scope, :kind, :basis, :product_id, "
                ":vfy, :vfm, :vty, :vtm, "
                ":accrual, :lag, :active, :notes, datetime('now')"
                ")"
            ),
            {
                "sid": scenario_id,
                "name": body.name,
                "scope": body.scope,
                "kind": body.kind,
                "basis": body.basis,
                "product_id": body.product_id,
                "vfy": body.valid_from_year,
                "vfm": body.valid_from_month,
                "vty": body.valid_to_year,
                "vtm": body.valid_to_month,
                "accrual": body.accrual_method,
                "lag": body.pay_month_lag or 0,
                "active": 1 if body.is_active else 0,
                "notes": body.notes,
            },
        )
        rebate_id = res.lastrowid

        # percent shortcut → one tier (convert Decimal to float)
        if body.kind == "percent" and body.percent_value is not None:
            db.execute(
                text(
                    "INSERT INTO scenario_rebate_tiers "
                    "(rebate_id, min_value, max_value, percent, amount, description, sort_order) "
                    "VALUES (:rid, 0, NULL, :pct, NULL, NULL, 0)"
                ),
                {"rid": rebate_id, "pct": _to_float(body.percent_value)},
            )

        # bulk tiers with safe casting
        if body.kind == "tier_percent" and body.tiers:
            for i, t in enumerate(body.tiers):
                db.execute(
                    text(
                        "INSERT INTO scenario_rebate_tiers "
                        "(rebate_id, min_value, max_value, percent, amount, description, sort_order) "
                        "VALUES (:rid, :min, :max, :pct, :amt, :desc, :ord)"
                    ),
                    {
                        "rid": rebate_id,
                        "min": _to_float(t.get("min_value", 0)),
                        "max": _to_float(t.get("max_value")),
                        "pct": _to_float(t.get("percent")),
                        "amt": _to_float(t.get("amount")),
                        "desc": t.get("description"),
                        "ord": t.get("sort_order", i),
                    },
                )

        # bulk lumps with safe casting
        if body.kind == "lump_sum" and body.lumps:
            for l in body.lumps:
                db.execute(
                    text(
                        "INSERT INTO scenario_rebate_lumps "
                        "(rebate_id, year, month, amount, description) "
                        "VALUES (:rid, :y, :m, :amt, :desc)"
                    ),
                    {
                        "rid": rebate_id,
                        "y": int(l.get("year")),
                        "m": int(l.get("month")),
                        "amt": _to_float(l.get("amount")),
                        "desc": l.get("description"),
                    },
                )

        row = db.execute(
            text(
                "SELECT id, scenario_id, name, scope, kind, basis, product_id, "
                "valid_from_year, valid_from_month, valid_to_year, valid_to_month, "
                "accrual_method, pay_month_lag, is_active, notes "
                "FROM scenario_rebates WHERE id=:rid"
            ),
            {"rid": rebate_id},
        ).mappings().fetchone()

        db.commit()
        return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on create_rebate: {e}")

@router.put("/{scenario_id}/rebates/{rebate_id}", response_model=RebateOut)
def update_rebate(
    scenario_id: int,
    rebate_id: int,
    body: RebateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_scenario(db, scenario_id)
        _ensure_rebate(db, scenario_id, rebate_id)

        if body.scope == "product" and not body.product_id:
            raise HTTPException(status_code=400, detail="product_id is required when scope='product'")

        db.execute(
            text(
                "UPDATE scenario_rebates SET "
                "name=:name, scope=:scope, kind=:kind, basis=:basis, product_id=:product_id, "
                "valid_from_year=:vfy, valid_from_month=:vfm, valid_to_year=:vty, valid_to_month=:vtm, "
                "accrual_method=:accrual, pay_month_lag=:lag, is_active=:active, notes=:notes, "
                "updated_at=datetime('now') "
                "WHERE id=:rid AND scenario_id=:sid"
            ),
            {
                "rid": rebate_id,
                "sid": scenario_id,
                "name": body.name,
                "scope": body.scope,
                "kind": body.kind,
                "basis": body.basis,
                "product_id": body.product_id,
                "vfy": body.valid_from_year,
                "vfm": body.valid_from_month,
                "vty": body.valid_to_year,
                "vtm": body.valid_to_month,
                "accrual": body.accrual_method,
                "lag": body.pay_month_lag or 0,
                "active": 1 if body.is_active else 0,
                "notes": body.notes,
            },
        )
        row = db.execute(
            text(
                "SELECT id, scenario_id, name, scope, kind, basis, product_id, "
                "valid_from_year, valid_from_month, valid_to_year, valid_to_month, "
                "accrual_method, pay_month_lag, is_active, notes "
                "FROM scenario_rebates WHERE id=:rid"
            ),
            {"rid": rebate_id},
        ).mappings().fetchone()
        db.commit()
        return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on update_rebate: {e}")

@router.delete("/{scenario_id}/rebates/{rebate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rebate(
    scenario_id: int,
    rebate_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_scenario(db, scenario_id)
        _ensure_rebate(db, scenario_id, rebate_id)
        db.execute(text("DELETE FROM scenario_rebates WHERE id=:rid"), {"rid": rebate_id})
        db.commit()
        return None
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on delete_rebate: {e}")

# ---------- TIERS ----------
@router.get("/{scenario_id}/rebates/{rebate_id}/tiers", response_model=List[TierOut])
def list_tiers(
    scenario_id: int,
    rebate_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        return _fetch_tiers(db, rebate_id)
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"DB error on list_tiers: {e}")

@router.post("/{scenario_id}/rebates/{rebate_id}/tiers", response_model=TierOut, status_code=status.HTTP_201_CREATED)
def create_tier(
    scenario_id: int,
    rebate_id: int,
    body: TierIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        res = db.execute(
            text(
                "INSERT INTO scenario_rebate_tiers "
                "(rebate_id, min_value, max_value, percent, amount, description, sort_order) "
                "VALUES (:rid, :min, :max, :pct, :amt, :desc, :ord)"
            ),
            {
                "rid": rebate_id,
                "min": _to_float(body.min_value),
                "max": _to_float(body.max_value),
                "pct": _to_float(body.percent),
                "amt": _to_float(body.amount),
                "desc": body.description,
                "ord": body.sort_order or 0,
            },
        )
        tid = res.lastrowid
        row = db.execute(
            text("SELECT id, rebate_id, min_value, max_value, percent, amount, description, sort_order "
                 "FROM scenario_rebate_tiers WHERE id=:tid"),
            {"tid": tid},
        ).mappings().fetchone()
        db.commit()
        return dict(row)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on create_tier: {e}")

@router.put("/{scenario_id}/rebates/{rebate_id}/tiers/{tier_id}", response_model=TierOut)
def update_tier(
    scenario_id: int,
    rebate_id: int,
    tier_id: int,
    body: TierIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        res = db.execute(
            text(
                "UPDATE scenario_rebate_tiers SET "
                "min_value=:min, max_value=:max, percent=:pct, amount=:amt, description=:desc, sort_order=:ord "
                "WHERE id=:tid AND rebate_id=:rid"
            ),
            {
                "tid": tier_id,
                "rid": rebate_id,
                "min": _to_float(body.min_value),
                "max": _to_float(body.max_value),
                "pct": _to_float(body.percent),
                "amt": _to_float(body.amount),
                "desc": body.description,
                "ord": body.sort_order or 0,
            },
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Tier not found")
        row = db.execute(
            text("SELECT id, rebate_id, min_value, max_value, percent, amount, description, sort_order "
                 "FROM scenario_rebate_tiers WHERE id=:tid"),
            {"tid": tier_id},
        ).mappings().fetchone()
        db.commit()
        return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on update_tier: {e}")

@router.delete("/{scenario_id}/rebates/{rebate_id}/tiers/{tier_id}")
def delete_tier(
    scenario_id: int,
    rebate_id: int,
    tier_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        res = db.execute(
            text("DELETE FROM scenario_rebate_tiers WHERE id=:tid AND rebate_id=:rid"),
            {"tid": tier_id, "rid": rebate_id},
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Tier not found")
        db.commit()
        return {"deleted": True}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on delete_tier: {e}")

# ---------- LUMPS ----------
@router.get("/{scenario_id}/rebates/{rebate_id}/lumps", response_model=List[LumpOut])
def list_lumps(
    scenario_id: int,
    rebate_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        return _fetch_lumps(db, rebate_id)
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"DB error on list_lumps: {e}")

@router.post("/{scenario_id}/rebates/{rebate_id}/lumps", response_model=LumpOut, status_code=status.HTTP_201_CREATED)
def create_lump(
    scenario_id: int,
    rebate_id: int,
    body: LumpIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        res = db.execute(
            text(
                "INSERT INTO scenario_rebate_lumps (rebate_id, year, month, amount, description) "
                "VALUES (:rid, :y, :m, :amt, :desc)"
            ),
            {"rid": rebate_id, "y": int(body.year), "m": int(body.month), "amt": _to_float(body.amount), "desc": body.description},
        )
        lid = res.lastrowid
        row = db.execute(
            text("SELECT id, rebate_id, year, month, amount, description FROM scenario_rebate_lumps WHERE id=:lid"),
            {"lid": lid},
        ).mappings().fetchone()
        db.commit()
        return dict(row)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on create_lump: {e}")

@router.put("/{scenario_id}/rebates/{rebate_id}/lumps/{lump_id}", response_model=LumpOut)
def update_lump(
    scenario_id: int,
    rebate_id: int,
    lump_id: int,
    body: LumpIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        res = db.execute(
            text(
                "UPDATE scenario_rebate_lumps SET year=:y, month=:m, amount=:amt, description=:desc "
                "WHERE id=:lid AND rebate_id=:rid"
            ),
            {"lid": lump_id, "rid": rebate_id, "y": int(body.year), "m": int(body.month), "amt": _to_float(body.amount), "desc": body.description},
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Lump entry not found")
        row = db.execute(
            text("SELECT id, rebate_id, year, month, amount, description FROM scenario_rebate_lumps WHERE id=:lid"),
            {"lid": lump_id},
        ).mappings().fetchone()
        db.commit()
        return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on update_lump: {e}")

@router.delete("/{scenario_id}/rebates/{rebate_id}/lumps/{lump_id}")
def delete_lump(
    scenario_id: int,
    rebate_id: int,
    lump_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        _ensure_schema(db)
        _ensure_rebate(db, scenario_id, rebate_id)
        res = db.execute(
            text("DELETE FROM scenario_rebate_lumps WHERE id=:lid AND rebate_id=:rid"),
            {"lid": lump_id, "rid": rebate_id},
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Lump entry not found")
        db.commit()
        return {"deleted": True}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error on delete_lump: {e}")
