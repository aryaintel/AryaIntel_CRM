# backend/app/api/products_api.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
from pathlib import Path
import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query

# ---------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------
def _resolve_db_path() -> Path:
    # 1) Explicit env override, if provided
    env = os.getenv("APP_DB_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p

    here = Path(__file__).resolve()
    candidates: List[Path] = [
        # repo root /app.db  (…/arya-crm-*/app.db)
        here.parents[3] / "app.db",
        # backend root /app.db (…/backend/app.db)
        here.parents[2] / "app.db",
        # app package dir /app.db (legacy; usually NOT present)
        here.parents[1] / "app.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    # fallback to first candidate (do not create deep unexpected paths)
    return candidates[0]


DB_PATH = _resolve_db_path()

router = APIRouter(prefix="/api", tags=["products"])


def cx() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
        ).fetchone()
    )


# ---------------------------------------------------------------------
# PRODUCTS
# ---------------------------------------------------------------------
@router.get("/products")
@router.get("/products/")
def list_products(
    q: Optional[str] = Query(None, description="FTS or LIKE search on code/name/description"),
    active: Optional[bool] = Query(None),
    # FE modal limit=1000 gönderiyor; burada üst sınırı genişlettik.
    limit: int = Query(50, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    with cx() as con:
        params: List[Any] = []

        use_fts = _table_exists(con, "products_fts") and bool(q)

        if use_fts:
            sql = (
                "SELECT p.* FROM products_fts f "
                "JOIN products p ON p.id = f.rowid "
                "WHERE products_fts MATCH ? AND p.deleted_at IS NULL "
            )
            params.append(q)
            if active is not None:
                sql += "AND p.is_active = ? "
                params.append(1 if active else 0)
            sql += "ORDER BY p.id DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            rows = con.execute(sql, params).fetchall()

            cnt_sql = (
                "SELECT COUNT(*) AS c FROM products_fts f "
                "JOIN products p ON p.id = f.rowid "
                "WHERE products_fts MATCH ? AND p.deleted_at IS NULL "
            )
            cnt_params: List[Any] = [q]
            if active is not None:
                cnt_sql += "AND p.is_active = ? "
                cnt_params.append(1 if active else 0)
            total = con.execute(cnt_sql, cnt_params).fetchone()["c"]
        else:
            sql = "SELECT * FROM products WHERE deleted_at IS NULL "
            if q:
                sql += "AND (code LIKE ? OR name LIKE ? OR IFNULL(description,'') LIKE ?) "
                like = f"%{q}%"
                params += [like, like, like]
            if active is not None:
                sql += "AND is_active = ? "
                params.append(1 if active else 0)
            sql += "ORDER BY id DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            rows = con.execute(sql, params).fetchall()

            cnt_sql = "SELECT COUNT(*) AS c FROM products WHERE deleted_at IS NULL "
            cnt_params: List[Any] = []
            if q:
                cnt_sql += "AND (code LIKE ? OR name LIKE ? OR IFNULL(description,'') LIKE ?) "
                like = f"%{q}%"
                cnt_params += [like, like, like]
            if active is not None:
                cnt_sql += "AND is_active = ? "
                cnt_params.append(1 if active else 0)
            total = con.execute(cnt_sql, cnt_params).fetchone()["c"]

        items = [_row_to_dict(r) for r in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/products/{pid}")
@router.get("/products/{pid}/")
def get_product(pid: int) -> Dict[str, Any]:
    with cx() as con:
        r = con.execute(
            "SELECT * FROM products WHERE id = ? AND deleted_at IS NULL", (pid,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "Product not found")
        return _row_to_dict(r)


@router.post("/products")
@router.post("/products/")
def create_product(payload: Dict[str, Any]) -> Dict[str, Any]:
    required = ["code", "name"]
    for k in required:
        if not payload.get(k):
            raise HTTPException(422, f"Field required: {k}")

    cols = [
        "code",
        "name",
        "description",
        "uom",
        "currency",
        "base_price",
        "tax_rate_pct",
        "barcode_gtin",
        "is_active",
        "metadata",
    ]
    values = [payload.get(c) for c in cols]
    with cx() as con:
        try:
            cur = con.execute(
                f"""
                INSERT INTO products
                ({", ".join(cols)})
                VALUES ({", ".join(["?"] * len(cols))})
                """,
                values,
            )
            con.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"Integrity error: {e}")


@router.put("/products/{pid}")
@router.put("/products/{pid}/")
def update_product(pid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = [
        "code",
        "name",
        "description",
        "uom",
        "currency",
        "base_price",
        "tax_rate_pct",
        "barcode_gtin",
        "is_active",
        "metadata",
    ]
    sets: List[str] = []
    params: List[Any] = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k} = ?")
            params.append(payload.get(k))
    if not sets:
        return {"updated": 0}

    with cx() as con:
        exists = con.execute(
            "SELECT 1 FROM products WHERE id = ? AND deleted_at IS NULL", (pid,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, "Product not found")
        params.append(pid)
        con.execute(
            f"UPDATE products SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL",
            params,
        )
        con.commit()
        return {"updated": 1}


@router.delete("/products/{pid}")
@router.delete("/products/{pid}/")
def delete_product(
    pid: int,
    hard: bool = Query(False, description="true=hard delete"),
) -> Dict[str, Any]:
    with cx() as con:
        if hard:
            con.execute("DELETE FROM products WHERE id = ?", (pid,))
        else:
            con.execute(
                "UPDATE products SET deleted_at = datetime('now') "
                "WHERE id = ? AND deleted_at IS NULL",
                (pid,),
            )
        con.commit()
        return {"deleted": True}


# ---------------------------------------------------------------------
# PRICE BOOKS
# ---------------------------------------------------------------------
@router.get("/price-books")
@router.get("/price-books/")
def list_price_books(active: Optional[bool] = None) -> Dict[str, Any]:
    with cx() as con:
        sql = "SELECT * FROM price_books"
        params: List[Any] = []
        if active is not None:
            sql += " WHERE is_active = ?"
            params.append(1 if active else 0)
        sql += " ORDER BY is_default DESC, id DESC"
        rows = con.execute(sql, params).fetchall()
        return {"items": [_row_to_dict(r) for r in rows]}


@router.get("/price-books/{book_id}/entries")
@router.get("/price-books/{book_id}/entries/")
def list_price_book_entries(
    book_id: int, product_id: Optional[int] = None
) -> Dict[str, Any]:
    with cx() as con:
        sql = """
        SELECT e.*, p.code AS product_code, p.name AS product_name
        FROM price_book_entries e
        JOIN products p ON p.id = e.product_id
        WHERE e.price_book_id = ?
        """
        params: List[Any] = [book_id]
        if product_id:
            sql += " AND e.product_id = ?"
            params.append(product_id)
        sql += " ORDER BY e.product_id, e.valid_from"
        rows = con.execute(sql, params).fetchall()
        return {"items": [_row_to_dict(r) for r in rows]}
