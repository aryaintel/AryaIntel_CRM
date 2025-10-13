# Pathway: C:/Dev/AryaIntel_CRM/backend/app/api/services_catalog_api.py
from __future__ import annotations

from typing import List, Optional
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

# Use the project's deps (do not replace)
from .deps import get_db  # type: ignore

router = APIRouter(prefix="/api", tags=["services-catalog"])

# ----------------------------------
# One-time self-heal for missing tables
# ----------------------------------
_SCHEMA_OK = False

def _ensure_schema(db: Session):
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    # Create tables if not present (idempotent)
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS service_families (
            id INTEGER PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_service_families_code ON service_families(code);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_service_families_active ON service_families(is_active);"))

    db.execute(text("""
        CREATE TABLE IF NOT EXISTS services_catalog (
            id INTEGER PRIMARY KEY,
            family_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            uom TEXT,
            default_currency TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (family_id) REFERENCES service_families(id) ON DELETE RESTRICT
        );
    """))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_services_catalog_code ON services_catalog(code);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_services_catalog_family ON services_catalog(family_id);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_services_catalog_active ON services_catalog(is_active);"))
    db.commit()
    _SCHEMA_OK = True

def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

def _row_or_404(result, entity: str):
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{entity} not found")
    return row

# ---------------------------
# Schemas
# ---------------------------
class ServiceFamilyIn(BaseModel):
    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    is_active: bool = True
    sort_order: int = 0

class ServiceFamilyOut(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool
    sort_order: int

class ServiceItemIn(BaseModel):
    family_id: int
    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    uom: Optional[str] = None
    default_currency: Optional[str] = None
    is_active: bool = True
    description: Optional[str] = None

class ServiceItemOut(BaseModel):
    id: int
    family_id: int
    # NEW: family_name to help FE show category quickly and prefill Scenario Services
    family_name: Optional[str] = None
    code: str
    name: str
    uom: Optional[str] = None
    default_currency: Optional[str] = None
    is_active: bool
    description: Optional[str] = None

# ---------------------------
# Families Endpoints
# ---------------------------
@router.get("/service-families", response_model=List[ServiceFamilyOut])
def list_families(db: Session = Depends(get_db)):
    _ensure_schema(db)
    sql = text("""
        SELECT id, code, name, is_active, sort_order
        FROM service_families
        ORDER BY is_active DESC, sort_order ASC, name ASC;
    """)
    rows = db.execute(sql).mappings().all()
    return rows

@router.post("/service-families", response_model=ServiceFamilyOut, status_code=status.HTTP_201_CREATED)
def create_family(payload: ServiceFamilyIn, db: Session = Depends(get_db)):
    _ensure_schema(db)
    now = now_iso()
    try:
        sql = text("""
            INSERT INTO service_families (code, name, is_active, sort_order, created_at, updated_at)
            VALUES (:code, :name, :is_active, :sort_order, :ca, :ua);
        """)
        db.execute(sql, {
            "code": payload.code.strip(),
            "name": payload.name.strip(),
            "is_active": 1 if payload.is_active else 0,
            "sort_order": payload.sort_order or 0,
            "ca": now, "ua": now,
        })
        db.commit()
    except Exception as ex:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create family: {ex}")

    return get_family_by_code(payload.code, db)

def get_family_by_code(code: str, db: Session) -> ServiceFamilyOut:
    sql = text("""
        SELECT id, code, name, is_active, sort_order
        FROM service_families WHERE code = :code;
    """)
    row = db.execute(sql, {"code": code}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Service family not found")
    return row

@router.put("/service-families/{family_id}", response_model=ServiceFamilyOut)
def update_family(
    payload: ServiceFamilyIn,
    family_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    _ensure_schema(db)
    now = now_iso()
    sql = text("""
        UPDATE service_families
           SET code=:code, name=:name, is_active=:is_active, sort_order=:sort_order, updated_at=:ua
         WHERE id=:id;
    """)
    res = db.execute(sql, {
        "id": family_id,
        "code": payload.code.strip(),
        "name": payload.name.strip(),
        "is_active": 1 if payload.is_active else 0,
        "sort_order": payload.sort_order or 0,
        "ua": now,
    })
    if res.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Service family not found")
    db.commit()
    return get_family_by_id(family_id, db)

def get_family_by_id(family_id: int, db: Session) -> ServiceFamilyOut:
    sql = text("""
        SELECT id, code, name, is_active, sort_order
        FROM service_families WHERE id = :id;
    """)
    row = db.execute(sql, {"id": family_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Service family not found")
    return row

@router.patch("/service-families/{family_id}/toggle", response_model=ServiceFamilyOut)
def toggle_family(
    family_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    _ensure_schema(db)
    sql = text("SELECT is_active FROM service_families WHERE id=:id")
    row = db.execute(sql, {"id": family_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Service family not found")
    current = int(row[0]) if row[0] is not None else 0
    newv = 0 if current else 1
    now = now_iso()
    up = text("UPDATE service_families SET is_active=:v, updated_at=:ua WHERE id=:id")
    db.execute(up, {"id": family_id, "v": newv, "ua": now})
    db.commit()
    return get_family_by_id(family_id, db)

# ---------------------------
# Services Endpoints
# ---------------------------
@router.get("/services", response_model=List[ServiceItemOut])
def list_services(
    family_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, min_length=1, description="Search by code or name"),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Returns catalog services with joined family name (family_name) for FE convenience.
    """
    _ensure_schema(db)
    clauses = ["1=1"]
    params = {"limit": limit}
    if family_id is not None:
        clauses.append("s.family_id = :family_id")
        params["family_id"] = family_id
    if q:
        clauses.append("(s.code LIKE :q OR s.name LIKE :q OR f.name LIKE :q)")
        params["q"] = f"%{q}%"
    if is_active is not None:
        clauses.append("s.is_active = :active")
        params["active"] = 1 if is_active else 0

    sql = text(f"""
        SELECT
            s.id,
            s.family_id,
            f.name AS family_name,
            s.code,
            s.name,
            s.uom,
            s.default_currency,
            s.is_active,
            s.description
        FROM services_catalog s
        JOIN service_families f ON f.id = s.family_id
        WHERE {' AND '.join(clauses)}
        ORDER BY s.is_active DESC, f.sort_order ASC, s.name ASC
        LIMIT :limit;
    """)
    rows = db.execute(sql, params).mappings().all()
    return rows

@router.post("/services", response_model=ServiceItemOut, status_code=status.HTTP_201_CREATED)
def create_service(payload: ServiceItemIn, db: Session = Depends(get_db)):
    _ensure_schema(db)
    fam = db.execute(text("SELECT id FROM service_families WHERE id=:id"), {"id": payload.family_id}).first()
    if not fam:
        raise HTTPException(status_code=400, detail="Invalid family_id")
    now = now_iso()
    try:
        sql = text("""
            INSERT INTO services_catalog (family_id, code, name, uom, default_currency, is_active, description, created_at, updated_at)
            VALUES (:family_id, :code, :name, :uom, :cur, :active, :desc, :ca, :ua);
        """)
        db.execute(sql, {
            "family_id": payload.family_id,
            "code": payload.code.strip(),
            "name": payload.name.strip(),
            "uom": (payload.uom or None),
            "cur": (payload.default_currency or None),
            "active": 1 if payload.is_active else 0,
            "desc": (payload.description or None),
            "ca": now, "ua": now,
        })
        db.commit()
    except Exception as ex:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create service: {ex}")
    return get_service_by_code(payload.code, db)

def get_service_by_code(code: str, db: Session) -> ServiceItemOut:
    sql = text("""
        SELECT
            s.id,
            s.family_id,
            f.name AS family_name,
            s.code,
            s.name,
            s.uom,
            s.default_currency,
            s.is_active,
            s.description
        FROM services_catalog s
        JOIN service_families f ON f.id = s.family_id
        WHERE s.code=:code;
    """)
    row = db.execute(sql, {"code": code}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return row

@router.put("/services/{service_id}", response_model=ServiceItemOut)
def update_service(
    payload: ServiceItemIn,
    service_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    _ensure_schema(db)
    fam = db.execute(text("SELECT id FROM service_families WHERE id=:id"), {"id": payload.family_id}).first()
    if not fam:
        raise HTTPException(status_code=400, detail="Invalid family_id")
    now = now_iso()
    sql = text("""
        UPDATE services_catalog
           SET family_id=:family_id, code=:code, name=:name, uom=:uom, default_currency=:cur,
               is_active=:active, description=:desc, updated_at=:ua
         WHERE id=:id;
    """)
    res = db.execute(sql, {
        "id": service_id,
        "family_id": payload.family_id,
        "code": payload.code.strip(),
        "name": payload.name.strip(),
        "uom": (payload.uom or None),
        "cur": (payload.default_currency or None),
        "active": 1 if payload.is_active else 0,
        "desc": (payload.description or None),
        "ua": now,
    })
    if res.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Service not found")
    db.commit()
    return get_service_by_id(service_id, db)

def get_service_by_id(service_id: int, db: Session) -> ServiceItemOut:
    sql = text("""
        SELECT
            s.id,
            s.family_id,
            f.name AS family_name,
            s.code,
            s.name,
            s.uom,
            s.default_currency,
            s.is_active,
            s.description
        FROM services_catalog s
        JOIN service_families f ON f.id = s.family_id
        WHERE s.id=:id;
    """)
    row = db.execute(sql, {"id": service_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return row

@router.patch("/services/{service_id}/toggle", response_model=ServiceItemOut)
def toggle_service(
    service_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    _ensure_schema(db)
    sql = text("SELECT is_active FROM services_catalog WHERE id=:id")
    row = db.execute(sql, {"id": service_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    current = int(row[0]) if row[0] is not None else 0
    newv = 0 if current else 1
    now = now_iso()
    up = text("UPDATE services_catalog SET is_active=:v, updated_at=:ua WHERE id=:id")
    db.execute(up, {"id": service_id, "v": newv, "ua": now})
    db.commit()
    return get_service_by_id(service_id, db)
