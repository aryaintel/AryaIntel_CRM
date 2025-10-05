# backend/app/api/products_api.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
from pathlib import Path
import os
import sqlite3
from datetime import date

from fastapi import APIRouter, HTTPException, Query

# ---------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------
def _resolve_db_path() -> Path:
    env = os.getenv("APP_DB_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p

    here = Path(__file__).resolve()
    candidates: List[Path] = [
        here.parents[3] / "app.db",  # repo root
        here.parents[2] / "app.db",  # backend/
        here.parents[1] / "app.db",  # backend/app/
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


DB_PATH = _resolve_db_path()
router = APIRouter(prefix="/api", tags=["products"])


def cx() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    _ensure_schema(con)
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


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _ensure_schema(con: sqlite3.Connection) -> None:
    # --- product_families ----------------------------------------------------
    if not _table_exists(con, "product_families"):
        con.execute(
            """
            CREATE TABLE product_families (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )

    # --- products ------------------------------------------------------------
    if not _table_exists(con, "products"):
        con.execute(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                uom TEXT,
                currency TEXT,
                base_price REAL,
                tax_rate_pct REAL,
                barcode_gtin TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                metadata TEXT,
                deleted_at TEXT,
                product_family_id INTEGER,
                FOREIGN KEY(product_family_id) REFERENCES product_families(id) ON DELETE SET NULL
            )
            """
        )
    else:
        if not _column_exists(con, "products", "product_family_id"):
            con.execute("ALTER TABLE products ADD COLUMN product_family_id INTEGER")
        if not _column_exists(con, "products", "deleted_at"):
            con.execute("ALTER TABLE products ADD COLUMN deleted_at TEXT")
        if not _column_exists(con, "products", "is_active"):
            con.execute("ALTER TABLE products ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    # --- price_books ---------------------------------------------------------
    if not _table_exists(con, "price_books"):
        con.execute(
            """
            CREATE TABLE price_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                currency TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                valid_from TEXT,
                valid_to TEXT
            )
            """
        )

    # --- price_book_entries --------------------------------------------------
    if not _table_exists(con, "price_book_entries"):
        con.execute(
            """
            CREATE TABLE price_book_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                price_book_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                currency TEXT,
                valid_from TEXT, -- inclusive
                valid_to TEXT,   -- inclusive (NULL=open-ended)
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(price_book_id) REFERENCES price_books(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )
            """
        )
        # UNIQUE without expressions (max compatibility)
        con.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_pbe_book_prod_window
            ON price_book_entries (price_book_id, product_id, valid_from, valid_to)
            """
        )

    con.commit()


# ---------------------------------------------------------------------
# PRODUCT FAMILIES (CRUD)
# ---------------------------------------------------------------------
@router.get("/product-families")
@router.get("/product-families/")
def list_product_families(active: Optional[bool] = None) -> Dict[str, Any]:
    with cx() as con:
        sql = "SELECT * FROM product_families"
        params: List[Any] = []
        if active is not None:
            sql += " WHERE is_active = ?"
            params.append(1 if active else 0)
        sql += " ORDER BY is_active DESC, name ASC"
        rows = con.execute(sql, params).fetchall()
        return {"items": [_row_to_dict(r) for r in rows]}


@router.post("/product-families")
@router.post("/product-families/")
def create_product_family(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Field required: name")
    with cx() as con:
        try:
            cur = con.execute(
                "INSERT INTO product_families (name, description, is_active) VALUES (?,?,?)",
                (name, payload.get("description"), 1 if payload.get("is_active", True) else 0),
            )
            con.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"Integrity error: {e}")


@router.put("/product-families/{fid}")
@router.put("/product-families/{fid}/")
def update_product_family(fid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = ["name", "description", "is_active"]
    sets: List[str] = []
    params: List[Any] = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k} = ?")
            params.append(1 if payload.get(k) else 0 if k == "is_active" else payload.get(k))
    if not sets:
        return {"updated": 0}
    with cx() as con:
        if not con.execute("SELECT 1 FROM product_families WHERE id = ?", (fid,)).fetchone():
            raise HTTPException(404, "Product family not found")
        params.append(fid)
        con.execute(f"UPDATE product_families SET {', '.join(sets)} WHERE id = ?", params)
        con.commit()
        return {"updated": 1}


@router.delete("/product-families/{fid}")
@router.delete("/product-families/{fid}/")
def delete_product_family(fid: int) -> Dict[str, Any]:
    with cx() as con:
        in_use = con.execute(
            "SELECT 1 FROM products WHERE product_family_id = ? AND IFNULL(deleted_at,'') = ''",
            (fid,),
        ).fetchone()
        if in_use:
            raise HTTPException(400, "Cannot delete family: still referenced by products")
        con.execute("DELETE FROM product_families WHERE id = ?", (fid,))
        con.commit()
        return {"deleted": True}


# ---------------------------------------------------------------------
# PRODUCTS
# ---------------------------------------------------------------------
@router.get("/products")
@router.get("/products/")
def list_products(
    q: Optional[str] = Query(None, description="FTS or LIKE search on code/name/description"),
    active: Optional[bool] = Query(None),
    family_id: Optional[int] = Query(None, description="Filter by product_family_id"),
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
            if family_id is not None:
                sql += "AND IFNULL(p.product_family_id, 0) = ? "
                params.append(family_id)
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
            if family_id is not None:
                cnt_sql += "AND IFNULL(p.product_family_id, 0) = ? "
                cnt_params.append(family_id)
            total = con.execute(cnt_sql, cnt_params).fetchone()["c"]
        else:
            sql = "SELECT * FROM products WHERE deleted_at IS NULL "
            if q:
                like = f"%{q}%"
                sql += "AND (code LIKE ? OR name LIKE ? OR IFNULL(description,'') LIKE ?) "
                params += [like, like, like]
            if active is not None:
                sql += "AND is_active = ? "
                params.append(1 if active else 0)
            if family_id is not None:
                sql += "AND IFNULL(product_family_id, 0) = ? "
                params.append(family_id)
            sql += "ORDER BY id DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            rows = con.execute(sql, params).fetchall()

            cnt_sql = "SELECT COUNT(*) AS c FROM products WHERE deleted_at IS NULL "
            cnt_params: List[Any] = []
            if q:
                like = f"%{q}%"
                cnt_sql += "AND (code LIKE ? OR name LIKE ? OR IFNULL(description,'') LIKE ?) "
                cnt_params += [like, like, like]
            if active is not None:
                cnt_sql += "AND is_active = ? "
                cnt_params.append(1 if active else 0)
            if family_id is not None:
                cnt_sql += "AND IFNULL(product_family_id, 0) = ? "
                cnt_params.append(family_id)
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
    for k in ["code", "name"]:
        if not payload.get(k):
            raise HTTPException(422, f"Field required: {k}")

    cols = [
        "code", "name", "description", "uom", "currency", "base_price",
        "tax_rate_pct", "barcode_gtin", "is_active", "metadata", "product_family_id",
    ]
    values = [payload.get(c) if c != "is_active" else (1 if payload.get(c, True) else 0) for c in cols]

    with cx() as con:
        try:
            cur = con.execute(
                f"INSERT INTO products ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})",
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
        "code","name","description","uom","currency","base_price",
        "tax_rate_pct","barcode_gtin","is_active","metadata","product_family_id",
    ]
    sets: List[str] = []
    params: List[Any] = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k} = ?")
            params.append(1 if payload.get(k) else 0 if k == "is_active" else payload.get(k))
    if not sets:
        return {"updated": 0}

    with cx() as con:
        if not con.execute("SELECT 1 FROM products WHERE id = ? AND deleted_at IS NULL", (pid,)).fetchone():
            raise HTTPException(404, "Product not found")
        params.append(pid)
        con.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL", params)
        con.commit()
        return {"updated": 1}


@router.delete("/products/{pid}")
@router.delete("/products/{pid}/")
def delete_product(pid: int, hard: bool = Query(False, description="true=hard delete")) -> Dict[str, Any]:
    with cx() as con:
        if hard:
            con.execute("DELETE FROM products WHERE id = ?", (pid,))
        else:
            con.execute(
                "UPDATE products SET deleted_at = datetime('now') WHERE id = ? AND deleted_at IS NULL",
                (pid,),
            )
        con.commit()
        return {"deleted": True}


# ---------------------------------------------------------------------
# PRICE BOOKS (CRUD + list)
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


@router.post("/price-books")
@router.post("/price-books/")
def create_price_book(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Field required: name")
    with cx() as con:
        try:
            cur = con.execute(
                """
                INSERT INTO price_books (name, currency, is_active, is_default, valid_from, valid_to)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    name,
                    payload.get("currency"),
                    1 if payload.get("is_active", True) else 0,
                    1 if payload.get("is_default", False) else 0,
                    payload.get("valid_from"),
                    payload.get("valid_to"),
                ),
            )
            if payload.get("is_default"):
                con.execute("UPDATE price_books SET is_default = 0 WHERE id <> ?", (cur.lastrowid,))
            con.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"Integrity error: {e}")


@router.put("/price-books/{book_id}")
@router.put("/price-books/{book_id}/")
def update_price_book(book_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = ["name", "currency", "is_active", "is_default", "valid_from", "valid_to"]
    sets: List[str] = []
    params: List[Any] = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k} = ?")
            params.append(1 if payload.get(k) else 0 if k in ("is_active","is_default") else payload.get(k))
    if not sets:
        return {"updated": 0}
    with cx() as con:
        if not con.execute("SELECT 1 FROM price_books WHERE id = ?", (book_id,)).fetchone():
            raise HTTPException(404, "Price book not found")
        params.append(book_id)
        con.execute(f"UPDATE price_books SET {', '.join(sets)} WHERE id = ?", params)
        if payload.get("is_default"):
            con.execute("UPDATE price_books SET is_default = 0 WHERE id <> ?", (book_id,))
        con.commit()
        return {"updated": 1}


@router.delete("/price-books/{book_id}")
@router.delete("/price-books/{book_id}/")
def delete_price_book(book_id: int) -> Dict[str, Any]:
    with cx() as con:
        in_use = con.execute(
            "SELECT 1 FROM price_book_entries WHERE price_book_id = ?",
            (book_id,),
        ).fetchone()
        if in_use:
            raise HTTPException(400, "Cannot delete price book: entries exist")
        con.execute("DELETE FROM price_books WHERE id = ?", (book_id,))
        con.commit()
        return {"deleted": True}


# -------------------- Price Book Entries --------------------
@router.get("/price-books/{book_id}/entries")
@router.get("/price-books/{book_id}/entries/")
def list_price_book_entries(book_id: int, product_id: Optional[int] = None) -> Dict[str, Any]:
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


@router.post("/price-books/{book_id}/entries")
@router.post("/price-books/{book_id}/entries/")
def create_price_book_entry(book_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    product_id = payload.get("product_id")
    unit_price = payload.get("unit_price")
    if not product_id or unit_price is None:
        raise HTTPException(422, "Fields required: product_id, unit_price")

    with cx() as con:
        if not con.execute("SELECT 1 FROM price_books WHERE id = ?", (book_id,)).fetchone():
            raise HTTPException(404, "Price book not found")
        if not con.execute(
            "SELECT 1 FROM products WHERE id = ? AND IFNULL(deleted_at,'') = ''",
            (product_id,),
        ).fetchone():
            raise HTTPException(404, "Product not found")

        try:
            cur = con.execute(
                """
                INSERT INTO price_book_entries
                (price_book_id, product_id, unit_price, currency, valid_from, valid_to, is_active)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    book_id,
                    product_id,
                    float(unit_price),
                    payload.get("currency"),
                    payload.get("valid_from"),
                    payload.get("valid_to"),
                    1 if payload.get("is_active", True) else 0,
                ),
            )
            con.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"Integrity error: {e}")


@router.put("/price-books/{book_id}/entries/{entry_id}")
@router.put("/price-books/{book_id}/entries/{entry_id}/")
def update_price_book_entry(book_id: int, entry_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = ["unit_price", "currency", "valid_from", "valid_to", "is_active", "product_id"]
    sets: List[str] = []
    params: List[Any] = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k} = ?")
            if k == "unit_price":
                params.append(float(payload.get(k)))
            elif k == "is_active":
                params.append(1 if payload.get(k) else 0)
            else:
                params.append(payload.get(k))
    if not sets:
        return {"updated": 0}
    with cx() as con:
        exists = con.execute(
            "SELECT 1 FROM price_book_entries WHERE id = ? AND price_book_id = ?",
            (entry_id, book_id),
        ).fetchone()
        if not exists:
            raise HTTPException(404, "Entry not found")
        params.append(entry_id)
        con.execute(f"UPDATE price_book_entries SET {', '.join(sets)} WHERE id = ?", params)
        con.commit()
        return {"updated": 1}


@router.delete("/price-books/{book_id}/entries/{entry_id}")
@router.delete("/price-books/{book_id}/entries/{entry_id}/")
def delete_price_book_entry(book_id: int, entry_id: int) -> Dict[str, Any]:
    with cx() as con:
        con.execute(
            "DELETE FROM price_book_entries WHERE id = ? AND price_book_id = ?",
            (entry_id, book_id),
        )
        con.commit()
        return {"deleted": True}


# ---------------------------------------------------------------------
# BEST PRICE RESOLVER
# ---------------------------------------------------------------------
def _parse_on_date(on: Optional[str]) -> str:
    if not on:
        return date.today().isoformat()
    try:
        y, m, d = [int(x) for x in on.split("-")]
        return date(y, m, d).isoformat()
    except Exception:
        raise HTTPException(422, "Invalid 'on' date. Expected YYYY-MM-DD")


@router.get("/products/{pid}/best-price")
@router.get("/products/{pid}/best-price/")
def best_price_for_product(
    pid: int,
    price_book_id: Optional[int] = Query(None, description="Preferred Price Book"),
    on: Optional[str] = Query(None, description="ISO date, default today"),
) -> Dict[str, Any]:
    on_date = _parse_on_date(on)
    with cx() as con:
        prod = con.execute(
            "SELECT id FROM products WHERE id = ? AND IFNULL(deleted_at,'') = ''",
            (pid,),
        ).fetchone()
        if not prod:
            raise HTTPException(404, "Product not found")

        # Determine price book preference
        book_id = price_book_id
        if book_id is None:
            row = con.execute(
                "SELECT id FROM price_books WHERE is_active = 1 AND is_default = 1 LIMIT 1"
            ).fetchone()
            if row:
                book_id = row["id"]

        def _pick(book_opt: Optional[int]) -> Optional[sqlite3.Row]:
            if book_opt is not None:
                row = con.execute(
                    """
                    SELECT *
                    FROM price_book_entries
                    WHERE price_book_id = ?
                      AND product_id = ?
                      AND is_active = 1
                      AND (valid_from IS NULL OR date(valid_from) <= date(?))
                      AND (valid_to   IS NULL OR date(valid_to)   >= date(?))
                    ORDER BY date(IFNULL(valid_from,'0001-01-01')) DESC, id DESC
                    LIMIT 1
                    """,
                    (book_opt, pid, on_date, on_date),
                ).fetchone()
                if row:
                    return row
            return con.execute(
                """
                SELECT e.*
                FROM price_book_entries e
                JOIN price_books b ON b.id = e.price_book_id
                WHERE e.product_id = ?
                  AND e.is_active = 1
                  AND b.is_active = 1
                  AND (e.valid_from IS NULL OR date(e.valid_from) <= date(?))
                  AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(?))
                ORDER BY b.is_default DESC,
                         date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                         e.id DESC
                LIMIT 1
                """,
                (pid, on_date, on_date),
            ).fetchone()

        entry = _pick(book_id)
        if not entry:
            entry = con.execute(
                """
                SELECT e.*
                FROM price_book_entries e
                JOIN price_books b ON b.id = e.price_book_id
                WHERE e.product_id = ?
                  AND e.is_active = 1
                  AND b.is_active = 1
                ORDER BY b.is_default DESC,
                         date(IFNULL(e.valid_from,'0001-01-01')) DESC,
                         e.id DESC
                LIMIT 1
                """,
                (pid,),
            ).fetchone()

        if not entry:
            raise HTTPException(404, "No active price found for product")

        return {
            "product_id": pid,
            "price_book_id": entry["price_book_id"],
            "price_book_entry_id": entry["id"],
            "unit_price": entry["unit_price"],
            "currency": entry["currency"],
            "valid_from": entry["valid_from"],
            "valid_to": entry["valid_to"],
        }
