from pathlib import Path
from typing import Optional, List
from datetime import datetime
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, condecimal, validator

router = APIRouter(prefix="/api/index-series", tags=["index-series"])
DB_PATH = Path(__file__).resolve().parents[2] / "app.db"

# =========================
# DB helpers & schema guard
# =========================
def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx

def _ensure_exists(cx: sqlite3.Connection, table: str, id_: int):
    if cx.execute(f"SELECT 1 FROM {table} WHERE id=?", (id_,)).fetchone() is None:
        raise HTTPException(404, f"{table} not found")

def _parse_ym(s: str) -> tuple[int, int]:
    try:
        y, m = s.split("-")
        y = int(y); m = int(m)
        if m < 1 or m > 12:
            raise ValueError
        return y, m
    except Exception:
        raise HTTPException(400, "invalid ym, expected 'YYYY-MM'")

def _col_exists(cx: sqlite3.Connection, table: str, col: str) -> bool:
    rows = cx.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)

def _ensure_schema():
    with _db() as cx:
        # base tables
        cx.execute("""
            CREATE TABLE IF NOT EXISTS index_series (
              id INTEGER PRIMARY KEY,
              code TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              unit TEXT,
              -- optional/extended fields follow (added via schema guard below)
              country TEXT,
              currency TEXT,
              source TEXT,
              fetch_adapter TEXT,
              fetch_config TEXT,
              is_active INTEGER DEFAULT 1,
              description TEXT,
              created_at TEXT,
              updated_at TEXT
            )
        """)
        cx.execute("""
            CREATE TABLE IF NOT EXISTS index_points (
              id INTEGER PRIMARY KEY,
              series_id INTEGER NOT NULL REFERENCES index_series(id) ON DELETE CASCADE,
              year INTEGER NOT NULL,
              month INTEGER NOT NULL,
              value REAL NOT NULL,
              source_ref TEXT,
              updated_at TEXT,
              UNIQUE(series_id, year, month)
            )
        """)

        # in case an older DB exists, make sure the new columns are present
        # index_series columns to ensure
        for col_def in [
            ("country", "TEXT"),
            ("currency", "TEXT"),
            ("source", "TEXT"),
            ("fetch_adapter", "TEXT"),
            ("fetch_config", "TEXT"),
            ("is_active", "INTEGER DEFAULT 1"),
            ("description", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ]:
            if not _col_exists(cx, "index_series", col_def[0]):
                cx.execute(f"ALTER TABLE index_series ADD COLUMN {col_def[0]} {col_def[1]}")

        # index_points columns to ensure
        for col_def in [
            ("source_ref", "TEXT"),
            ("updated_at", "TEXT"),
        ]:
            if not _col_exists(cx, "index_points", col_def[0]):
                cx.execute(f"ALTER TABLE index_points ADD COLUMN {col_def[0]} {col_def[1]}")

# run guard at import
_ensure_schema()

# =========================
# Schemas
# =========================
class IndexSeriesCreate(BaseModel):
    code: str
    name: str
    unit: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    source: Optional[str] = None          # tuik | fred | manual ...
    fetch_adapter: Optional[str] = None   # reserved for future
    fetch_config: Optional[str] = None
    is_active: bool = True
    description: Optional[str] = None

class IndexSeriesUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    unit: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    source: Optional[str] = None
    fetch_adapter: Optional[str] = None
    fetch_config: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None

class IndexPointIn(BaseModel):
    year: int
    month: int
    value: condecimal(max_digits=18, decimal_places=6)
    source_ref: Optional[str] = None

    @validator("year")
    def _year_ok(cls, v):
        if v < 1900 or v > 2100:
            raise ValueError("year out of range")
        return v

    @validator("month")
    def _month_ok(cls, v):
        if v < 1 or v > 12:
            raise ValueError("month must be 1..12")
        return v

class BulkUpsertRequest(BaseModel):
    points: List[IndexPointIn]

class SingleUpsertRequest(BaseModel):
    ym: str
    value: condecimal(max_digits=18, decimal_places=6)
    source_ref: Optional[str] = None

# =========================
# Routes: Series
# =========================
@router.post("", status_code=201)
def create_series(payload: IndexSeriesCreate):
    with _db() as cx:
        # unique code
        dup = cx.execute("SELECT 1 FROM index_series WHERE code=?", (payload.code,)).fetchone()
        if dup:
            raise HTTPException(409, "index_series code already exists")

        now = datetime.utcnow().isoformat(timespec="seconds")
        cur = cx.execute(
            """
            INSERT INTO index_series
              (code, name, unit, country, currency, source,
               fetch_adapter, fetch_config, is_active, description,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?, ?,?, ?,?)
            """,
            (
                payload.code, payload.name, payload.unit, payload.country, payload.currency, payload.source,
                payload.fetch_adapter, payload.fetch_config, 1 if payload.is_active else 0, payload.description,
                now, now
            )
        )
        sid = cur.lastrowid
        row = cx.execute("SELECT * FROM index_series WHERE id=?", (sid,)).fetchone()
        return dict(row)

@router.get("")
def list_series(
    q: Optional[str] = None,
    source: Optional[str] = None,
    country: Optional[str] = None,
    currency: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    sql = "SELECT * FROM index_series WHERE 1=1"
    args: list = []
    if q:
        sql += " AND (code LIKE ? OR name LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if source:
        sql += " AND source = ?"; args.append(source)
    if country:
        sql += " AND country = ?"; args.append(country)
    if currency:
        sql += " AND currency = ?"; args.append(currency)
    if is_active is not None:
        sql += " AND is_active = ?"; args.append(1 if is_active else 0)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"; args += [limit, offset]

    with _db() as cx:
        items = [dict(r) for r in cx.execute(sql, args).fetchall()]
        # If you want an exact total, compute separately; this lightweight approach mirrors prior code
        return {"items": items, "count": len(items), "limit": limit, "offset": offset}

@router.get("/{sid}")
def get_series(sid: int):
    with _db() as cx:
        s = cx.execute("SELECT * FROM index_series WHERE id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "index_series not found")
        return dict(s)

@router.put("/{sid}")
def update_series(sid: int, payload: IndexSeriesUpdate):
    with _db() as cx:
        _ensure_exists(cx, "index_series", sid)
        fields = []; vals: list = []
        mapping = {
            "code": payload.code,
            "name": payload.name,
            "unit": payload.unit,
            "country": payload.country,
            "currency": payload.currency,
            "source": payload.source,
            "fetch_adapter": payload.fetch_adapter,
            "fetch_config": payload.fetch_config,
            "is_active": (None if payload.is_active is None else (1 if payload.is_active else 0)),
            "description": payload.description,
        }
        for col, val in mapping.items():
            if val is not None:
                fields.append(f"{col}=?"); vals.append(val)
        if fields:
            fields.append("updated_at=?"); vals.append(datetime.utcnow().isoformat(timespec="seconds"))
            vals.append(sid)
            cx.execute(f"UPDATE index_series SET {', '.join(fields)} WHERE id=?", vals)
        row = cx.execute("SELECT * FROM index_series WHERE id=?", (sid,)).fetchone()
        return dict(row)

# =========================
# Routes: Points
# =========================
@router.get("/{sid}/points")
def list_points(
    sid: int,
    date_from: Optional[str] = Query(None, description="YYYY-MM"),
    date_to: Optional[str] = Query(None, description="YYYY-MM (inclusive)"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    with _db() as cx:
        _ensure_exists(cx, "index_series", sid)
        sql = "SELECT year, month, value, source_ref FROM index_points WHERE series_id=?"
        args: list = [sid]

        if date_from:
            fy, fm = _parse_ym(date_from)
            sql += " AND (year > ? OR (year = ? AND month >= ?))"
            args += [fy, fy, fm]
        if date_to:
            ty, tm = _parse_ym(date_to)
            sql += " AND (year < ? OR (year = ? AND month <= ?))"
            args += [ty, ty, tm]

        sql += " ORDER BY year, month LIMIT ? OFFSET ?"
        args += [limit, offset]
        rows = [dict(r) for r in cx.execute(sql, args).fetchall()]
        # enrich with ym to help FE
        items = [{"ym": f"{r['year']}-{str(r['month']).zfill(2)}", "value": r["value"], "source_ref": r["source_ref"]} for r in rows]
        return {"items": items, "count": len(items), "limit": limit, "offset": offset}

@router.post("/{sid}/points:bulk-upsert")
def bulk_upsert_points(sid: int, payload: BulkUpsertRequest):
    if not payload.points:
        raise HTTPException(400, "points cannot be empty")

    with _db() as cx:
        _ensure_exists(cx, "index_series", sid)
        q = """
        INSERT INTO index_points(series_id, year, month, value, source_ref, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(series_id, year, month) DO UPDATE SET
            value=excluded.value,
            source_ref=excluded.source_ref,
            updated_at=excluded.updated_at
        """
        now = datetime.utcnow().isoformat(timespec="seconds")
        for p in payload.points:
            cx.execute(q, (sid, p.year, p.month, float(p.value), p.source_ref, now))
        cx.commit()

    return {"series_id": sid, "upserted": len(payload.points)}

@router.post("/{sid}/points:upsert")
def upsert_point(sid: int, payload: SingleUpsertRequest):
    with _db() as cx:
        _ensure_exists(cx, "index_series", sid)
        y, m = _parse_ym(payload.ym)
        q = """
        INSERT INTO index_points(series_id, year, month, value, source_ref, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(series_id, year, month) DO UPDATE SET
            value=excluded.value,
            source_ref=excluded.source_ref,
            updated_at=excluded.updated_at
        """
        now = datetime.utcnow().isoformat(timespec="seconds")
        cx.execute(q, (sid, y, m, float(payload.value), payload.source_ref, now))
        cx.commit()
    return {"series_id": sid, "ym": payload.ym, "value": float(payload.value)}

@router.delete("/{sid}/points")
def delete_point(sid: int, ym: str = Query(..., description="YYYY-MM")):
    with _db() as cx:
        _ensure_exists(cx, "index_series", sid)
        y, m = _parse_ym(ym)
        cur = cx.execute("DELETE FROM index_points WHERE series_id=? AND year=? AND month=?", (sid, y, m))
        return {"series_id": sid, "deleted": cur.rowcount}
