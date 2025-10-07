# backend/app/api/price_terms.py
from __future__ import annotations

from pathlib import Path
from typing import Optional
import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Body

router = APIRouter(prefix="/api/price-terms", tags=["reference"])

# ---------------------------------------------------------------------
# DB helpers (ENV -> common locations)
# ---------------------------------------------------------------------
def _resolve_db_path() -> Path:
    env = os.getenv("APP_DB_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p

    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "app.db",  # repo root
        here.parents[2] / "app.db",  # backend/
        here.parents[1] / "app.db",  # backend/app/
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]

DB_PATH = _resolve_db_path()

def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx

# ---------------------------------------------------------------------
# One-time schema guard
# ---------------------------------------------------------------------
def _column_exists(cx: sqlite3.Connection, table: str, col: str) -> bool:
    r = cx.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == col for c in r)

def _ensure_schema() -> None:
    with _db() as cx:
        # base table
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS price_terms (
              id          INTEGER PRIMARY KEY,
              code        TEXT NOT NULL UNIQUE,
              name        TEXT NOT NULL,
              description TEXT,
              is_active   INTEGER NOT NULL DEFAULT 1,
              sort_order  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # add missing columns safely (idempotent)
        for col_sql, col_name in [
            ("ALTER TABLE price_terms ADD COLUMN description TEXT", "description"),
            ("ALTER TABLE price_terms ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0", "sort_order"),
            ("ALTER TABLE price_terms ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1", "is_active"),
            # optional future columns:
            # ("ALTER TABLE price_terms ADD COLUMN default_days INTEGER", "default_days"),
            # ("ALTER TABLE price_terms ADD COLUMN notes TEXT", "notes"),
        ]:
            try:
                if not _column_exists(cx, "price_terms", col_name):
                    cx.execute(col_sql)
            except sqlite3.OperationalError:
                # ignore if column already present or SQLite cannot add due to old versions
                pass

        # optional: allow linking from price_book_entries
        try:
            if not _column_exists(cx, "price_book_entries", "price_term_id"):
                cx.execute("ALTER TABLE price_book_entries ADD COLUMN price_term_id INTEGER REFERENCES price_terms(id)")
        except sqlite3.OperationalError:
            pass

# run once at import
_ensure_schema()

def _exists(cx: sqlite3.Connection, table: str, id_: int) -> bool:
    r = cx.execute(f"SELECT 1 FROM {table} WHERE id=?", (id_,)).fetchone()
    return bool(r)

def _unique_code_ok(cx: sqlite3.Connection, code: str, exclude_id: Optional[int] = None) -> bool:
    if exclude_id is None:
        r = cx.execute("SELECT 1 FROM price_terms WHERE lower(code)=lower(?)", (code,)).fetchone()
    else:
        r = cx.execute(
            "SELECT 1 FROM price_terms WHERE lower(code)=lower(?) AND id<>?",
            (code, exclude_id),
        ).fetchone()
    return r is None

# ---------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------
@router.get("", summary="List Price Terms")
def list_terms(
    q: Optional[str] = Query(None, description="Search in code or name (case-insensitive)"),
    active_only: bool = Query(True, description="Return only active rows when true"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sql = """
        SELECT id, code, name, description, is_active, sort_order
          FROM price_terms
    """
    where: list[str] = []
    args: list[object] = []

    if q:
        where.append("(lower(code) LIKE lower(?) OR lower(name) LIKE lower(?))")
        args.extend([f"%{q}%", f"%{q}%"])
    if active_only:
        where.append("is_active = 1")

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY sort_order, id LIMIT ? OFFSET ?"
    args.extend([limit, offset])

    with _db() as cx:
        rows = cx.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

@router.get("/options", summary="List Price Term Options (active only)")
def list_term_options():
    with _db() as cx:
        rows = cx.execute(
            "SELECT id, code, name FROM price_terms WHERE is_active=1 ORDER BY sort_order, id"
        ).fetchall()
        return [dict(r) for r in rows]

@router.get("/{term_id}", summary="Get Price Term")
def get_term(term_id: int):
    with _db() as cx:
        r = cx.execute(
            "SELECT id, code, name, description, is_active, sort_order FROM price_terms WHERE id=?",
            (term_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "price_term not found")
        return dict(r)

@router.get("/by-code/{code}", summary="Get Price Term by code")
def get_term_by_code(code: str):
    with _db() as cx:
        r = cx.execute(
            "SELECT id, code, name, description, is_active, sort_order FROM price_terms WHERE lower(code)=lower(?)",
            (code,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "price_term not found")
        return dict(r)

# ---------------------------------------------------------------------
# Create / Update / Delete
# ---------------------------------------------------------------------
@router.post("", summary="Create Price Term")
def create_term(payload: dict = Body(...)):
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    description = payload.get("description")
    is_active = 1 if bool(payload.get("is_active", True)) else 0
    sort_order = int(payload.get("sort_order") or 0)

    if not code or not name:
        raise HTTPException(422, "code and name are required")

    with _db() as cx:
        if not _unique_code_ok(cx, code):
            raise HTTPException(409, f"code already exists: {code}")

        cur = cx.execute(
            """
            INSERT INTO price_terms (code, name, description, is_active, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (code, name, description, is_active, sort_order),
        )
        cx.commit()
        new_id = cur.lastrowid
        return get_term(new_id)

@router.put("/{term_id}", summary="Update Price Term")
def update_term(term_id: int, payload: dict = Body(...)):
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    description = payload.get("description")
    is_active = 1 if bool(payload.get("is_active", True)) else 0
    sort_order = int(payload.get("sort_order") or 0)

    if not code or not name:
        raise HTTPException(422, "code and name are required")

    with _db() as cx:
        if not _exists(cx, "price_terms", term_id):
            raise HTTPException(404, "price_term not found")

        if not _unique_code_ok(cx, code, exclude_id=term_id):
            raise HTTPException(409, f"code already exists: {code}")

        cx.execute(
            """
            UPDATE price_terms
               SET code=?, name=?, description=?, is_active=?, sort_order=?
             WHERE id=?
            """,
            (code, name, description, is_active, sort_order, term_id),
        )
        cx.commit()
        return get_term(term_id)

@router.delete("/{term_id}", summary="Delete Price Term")
def delete_term(term_id: int, force: bool = Query(False, description="Hard delete even if unused")):
    with _db() as cx:
        if not _exists(cx, "price_terms", term_id):
            raise HTTPException(404, "price_term not found")

        used = cx.execute(
            "SELECT 1 FROM price_book_entries WHERE price_term_id = ? LIMIT 1", (term_id,)
        ).fetchone()
        if used and not force:
            raise HTTPException(
                409,
                "price_term is referenced by price_book_entries; set force=true to attempt hard delete",
            )

        cx.execute("DELETE FROM price_terms WHERE id=?", (term_id,))
        cx.commit()
        return {"ok": True, "deleted_id": term_id}
