
from __future__ import annotations

from typing import Optional, List, Dict, Any, Tuple
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

    # --- reference: price_terms ---------------------------------------------
    #  (id, code unique, name, is_active)
    if not _table_exists(con, "price_terms"):
        con.execute(
            """
            CREATE TABLE price_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        # Basit tohumlar (gerekirse)
        con.executemany(
            "INSERT OR IGNORE INTO price_terms (code, name, is_active) VALUES (?,?,1)",
            [
                ("bulk_with_freight", "Bulk with Freight"),
                ("bulk_ex_freight",  "Bulk ex Freight"),
                ("freight",          "Freight Only"),
            ],
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
                price_term TEXT,
                price_term_id INTEGER NULL,
                FOREIGN KEY(price_book_id) REFERENCES price_books(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY(price_term_id) REFERENCES price_terms(id) ON DELETE SET NULL
            )
            """
        )
        con.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_pbe_book_prod_window
            ON price_book_entries (price_book_id, product_id, valid_from, valid_to)
            """
        )
    else:
        # migration-safe: add price_term TEXT if missing (geri uyum)
        if not _column_exists(con, "price_book_entries", "price_term"):
            con.execute("ALTER TABLE price_book_entries ADD COLUMN price_term TEXT")
        # yeni referans id kolonu
        if not _column_exists(con, "price_book_entries", "price_term_id"):
            con.execute("ALTER TABLE price_book_entries ADD COLUMN price_term_id INTEGER NULL")

    # --- engine categories + map (ensure) -----------------------------------
    _ensure_engine_category_schema(con)

    con.commit()


# --------------------------- Cleaning helpers ---------------------------
def _clean_name(v: Any) -> str:
    return (str(v or "")).strip()

def _clean_desc(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None

def _to_db_bool(v: Any) -> int:
    return 1 if bool(v) else 0


# --------------------------- Price Term helper --------------------------
def _resolve_price_term_id(con: sqlite3.Connection, payload: Dict[str, Any]) -> Optional[int]:
    """
    Öncelik: price_term_id (doğrudan).
    Alternatif: price_term (code) -> id.
    Yoksa: None (kolon NULL olabilir).
    """
    if payload is None:
        return None
    if "price_term_id" in payload and payload["price_term_id"] is not None:
        return int(payload["price_term_id"])
    code = (payload.get("price_term") or "").strip()
    if code:
        r = con.execute("SELECT id FROM price_terms WHERE lower(code)=lower(?)", (code,)).fetchone()
        if not r:
            raise HTTPException(422, f"unknown price_term code: {code}")
        return int(r["id"])
    return None


# --------------------------- Engine Category helpers --------------------
ENGINE_CATEGORY_SEED: Tuple[Tuple[str,str,int], ...] = (
    ("AN", "Ammonium Nitrate", 10),
    ("EM", "Emulsion", 20),
    ("IE", "Initiating Explosives", 30),
    ("Services", "Services", 40),
)

def _ensure_engine_category_schema(con: sqlite3.Connection) -> None:
    # engine_categories
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS engine_categories (
            code TEXT PRIMARY KEY,
            name TEXT,
            sort_order INTEGER
        )
        """
    )
    # seed
    for code, name, sort_order in ENGINE_CATEGORY_SEED:
        con.execute(
            """
            INSERT OR IGNORE INTO engine_categories (code, name, sort_order)
            VALUES (?,?,?)
            """,
            (code, name, sort_order),
        )
    # engine_category_map
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS engine_category_map (
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL,
            ref_id INTEGER NOT NULL,
            category_code TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ecm_scope_ref
        ON engine_category_map (scope, ref_id)
        """
    )

def _engine_code_exists(con: sqlite3.Connection, code: str) -> bool:
    if not code or not isinstance(code, str):
        return False
    row = con.execute("SELECT 1 FROM engine_categories WHERE code = ?", (code,)).fetchone()
    return bool(row)

def _upsert_engine_category_map(con: sqlite3.Connection, scope: str, ref_id: int, category_code: Optional[str]) -> None:
    """
    - If category_code is a non-empty string: validate against engine_categories and upsert row (set is_active=1).
    - If category_code is None or empty string: delete any existing row (clear mapping).
    """
    if category_code is None or str(category_code).strip() == "":
        con.execute("DELETE FROM engine_category_map WHERE scope = ? AND ref_id = ?", (scope, ref_id))
        return
    code = str(category_code).strip()
    if not _engine_code_exists(con, code):
        raise HTTPException(422, f"Invalid engine category code: {code}")
    con.execute(
        """
        INSERT INTO engine_category_map (scope, ref_id, category_code, is_active, note, created_at, updated_at)
        VALUES (?, ?, ?, 1, NULL, datetime('now'), datetime('now'))
        ON CONFLICT(scope, ref_id) DO UPDATE SET
          category_code = excluded.category_code,
          is_active = 1,
          updated_at = datetime('now')
        """,
        (scope, ref_id, code),
    )

def _resolve_family_category(con: sqlite3.Connection, family_id: Optional[int]) -> Optional[str]:
    if not family_id:
        return None
    r = con.execute(
        """
        SELECT category_code
        FROM engine_category_map
        WHERE scope = 'product_family' AND ref_id = ? AND is_active = 1
        LIMIT 1
        """,
        (family_id,),
    ).fetchone()
    return r["category_code"] if r else None

def _resolve_product_category(con: sqlite3.Connection, product_id: int, family_id: Optional[int]) -> Optional[str]:
    # product override first
    r = con.execute(
        """
        SELECT category_code
        FROM engine_category_map
        WHERE scope = 'product' AND ref_id = ? AND is_active = 1
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if r:
        return r["category_code"]
    # else family default
    return _resolve_family_category(con, family_id)


# ---------------------------------------------------------------------
# PRODUCT FAMILIES (CRUD)
# ---------------------------------------------------------------------
@router.get("/product-families")
@router.get("/product-families/")
def list_product_families(active: Optional[bool] = None) -> Dict[str, Any]:
    with cx() as con:
        sql = """
        SELECT pf.*,
               (
                 SELECT ecm.category_code
                 FROM engine_category_map ecm
                 WHERE ecm.scope='product_family' AND ecm.ref_id=pf.id AND ecm.is_active=1
                 LIMIT 1
               ) AS family_category_code
        FROM product_families pf
        """
        params: List[Any] = []
        where = []
        if active is not None:
            where.append("pf.is_active = ?")
            params.append(1 if active else 0)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY pf.is_active DESC, pf.name ASC"
        rows = con.execute(sql, params).fetchall()
        return {"items": [_row_to_dict(r) for r in rows]}


@router.post("/product-families")
@router.post("/product-families/")
def create_product_family(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _clean_name(payload.get("name"))
    if not name:
        raise HTTPException(422, "Field required: name")
    with cx() as con:
        try:
            cur = con.execute(
                "INSERT INTO product_families (name, description, is_active) VALUES (?,?,?)",
                (name, _clean_desc(payload.get("description")), _to_db_bool(payload.get("is_active", True))),
            )
            # Optional category_code upsert
            if "category_code" in payload:
                _upsert_engine_category_map(con, "product_family", int(cur.lastrowid), payload.get("category_code"))
            con.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"Integrity error: {e}")


@router.put("/product-families/{fid}")
@router.put("/product-families/{fid}/")
def update_product_family(fid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    sets: List[str] = []
    params: List[Any] = []

    if "name" in payload:
        name = _clean_name(payload.get("name"))
        if not name:
            raise HTTPException(422, "Field required: name")
        sets.append("name = ?")
        params.append(name)

    if "description" in payload:
        sets.append("description = ?")
        params.append(_clean_desc(payload.get("description")))

    if "is_active" in payload:
        sets.append("is_active = ?")
        params.append(_to_db_bool(payload.get("is_active")))

    with cx() as con:
        if not con.execute("SELECT 1 FROM product_families WHERE id = ?", (fid,)).fetchone():
            raise HTTPException(404, "Product family not found")

        updated = 0
        if sets:
            params.append(fid)
            con.execute(f"UPDATE product_families SET {', '.join(sets)} WHERE id = ?", params)
            updated = 1

        # Optional category_code upsert/clear when key present
        if "category_code" in payload:
            _upsert_engine_category_map(con, "product_family", fid, payload.get("category_code"))
            updated = 1 if updated == 0 else updated

        con.commit()
        return {"updated": updated}


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
        # also clear mapping if any
        con.execute("DELETE FROM engine_category_map WHERE scope='product_family' AND ref_id=?", (fid,))
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
                "SELECT p.*, "
                "  (SELECT category_code FROM engine_category_map e "
                "   WHERE e.scope='product' AND e.ref_id=p.id AND e.is_active=1 LIMIT 1) AS product_category_code, "
                "  (SELECT category_code FROM engine_category_map e2 "
                "   WHERE e2.scope='product_family' AND e2.ref_id=IFNULL(p.product_family_id,-1) AND e2.is_active=1 LIMIT 1) AS family_category_code "
                "FROM products_fts f "
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
            sql = (
                "SELECT p.*, "
                "  (SELECT category_code FROM engine_category_map e "
                "   WHERE e.scope='product' AND e.ref_id=p.id AND e.is_active=1 LIMIT 1) AS product_category_code, "
                "  (SELECT category_code FROM engine_category_map e2 "
                "   WHERE e2.scope='product_family' AND e2.ref_id=IFNULL(p.product_family_id,-1) AND e2.is_active=1 LIMIT 1) AS family_category_code "
                "FROM products p WHERE p.deleted_at IS NULL "
            )
            if q:
                like = f"%{q}%"
                sql += "AND (p.code LIKE ? OR p.name LIKE ? OR IFNULL(p.description,'') LIKE ?) "
                params += [like, like, like]
            if active is not None:
                sql += "AND p.is_active = ? "
                params.append(1 if active else 0)
            if family_id is not None:
                sql += "AND IFNULL(p.product_family_id, 0) = ? "
                params.append(family_id)
            sql += "ORDER BY p.id DESC LIMIT ? OFFSET ?"
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

        items = []
        for r in rows:
            d = _row_to_dict(r)
            # resolved category: product override -> family default
            resolved = d.get("product_category_code") or d.get("family_category_code")
            d["category_code"] = resolved
            items.append(d)
        return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/products/{pid}")
@router.get("/products/{pid}/")
def get_product(pid: int) -> Dict[str, Any]:
    with cx() as con:
        r = con.execute(
            """
            SELECT p.*,
                   (SELECT category_code FROM engine_category_map e
                    WHERE e.scope='product' AND e.ref_id=p.id AND e.is_active=1 LIMIT 1) AS product_category_code,
                   (SELECT category_code FROM engine_category_map e2
                    WHERE e2.scope='product_family' AND e2.ref_id=IFNULL(p.product_family_id,-1) AND e2.is_active=1 LIMIT 1) AS family_category_code
            FROM products p
            WHERE p.id = ? AND p.deleted_at IS NULL
            """,
            (pid,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "Product not found")
        d = _row_to_dict(r)
        d["category_code"] = d.get("product_category_code") or d.get("family_category_code")
        return d


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
    values = []
    for c in cols:
        if c == "is_active":
            values.append(_to_db_bool(payload.get(c, True)))
        elif c == "name":
            nm = _clean_name(payload.get(c))
            if not nm:
                raise HTTPException(422, "Field required: name")
            values.append(nm)
        elif c == "description":
            values.append(_clean_desc(payload.get(c)))
        else:
            values.append(payload.get(c))

    with cx() as con:
        try:
            cur = con.execute(
                f"INSERT INTO products ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})",
                values,
            )
            # Optional category_code upsert for product override
            if "category_code" in payload:
                _upsert_engine_category_map(con, "product", int(cur.lastrowid), payload.get("category_code"))
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
        if k not in payload:
            continue
        if k == "is_active":
            sets.append("is_active = ?")
            params.append(_to_db_bool(payload.get(k)))
        elif k == "name":
            nm = _clean_name(payload.get(k))
            if not nm:
                raise HTTPException(422, "Field required: name")
            sets.append("name = ?")
            params.append(nm)
        elif k == "description":
            sets.append("description = ?")
            params.append(_clean_desc(payload.get(k)))
        else:
            sets.append(f"{k} = ?")
            params.append(payload.get(k))

    with cx() as con:
        if not con.execute("SELECT 1 FROM products WHERE id = ? AND deleted_at IS NULL", (pid,)).fetchone():
            raise HTTPException(404, "Product not found")

        updated = 0
        if sets:
            params.append(pid)
            con.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL", params)
            updated = 1

        # Optional category_code upsert/clear when key present
        if "category_code" in payload:
            _upsert_engine_category_map(con, "product", pid, payload.get("category_code"))
            updated = 1 if updated == 0 else updated

        con.commit()
        return {"updated": updated}


@router.delete("/products/{pid}")
@router.delete("/products/{pid}/")
def delete_product(pid: int, hard: bool = Query(False, description="true=hard delete")) -> Dict[str, Any]:
    with cx() as con:
        # clear product mapping regardless of soft/hard
        con.execute("DELETE FROM engine_category_map WHERE scope='product' AND ref_id=?", (pid,))
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
    name = _clean_name(payload.get("name"))
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
                    _to_db_bool(payload.get("is_active", True)),
                    _to_db_bool(payload.get("is_default", False)),
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
        if k not in payload:
            continue
        if k in ("is_active", "is_default"):
            sets.append(f"{k} = ?")
            params.append(_to_db_bool(payload.get(k)))
        elif k == "name":
            nm = _clean_name(payload.get(k))
            if not nm:
                raise HTTPException(422, "Field required: name")
            sets.append("name = ?")
            params.append(nm)
        else:
            sets.append(f"{k} = ?")
            params.append(payload.get(k))

    if not sets:
        return {"updated": 0}

    with cx() as con:
        if not con.execute("SELECT 1 FROM price_books WHERE id = ?", (book_id,)).fetchone():
            raise HTTPException(404, "Price book not found")
        params.append(book_id)
        con.execute(f"UPDATE price_books SET {', '.join(sets)} WHERE id = ?", params)
        if "is_default" in payload and payload.get("is_default"):
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
        SELECT e.*,
               p.code AS product_code,
               p.name AS product_name,
               pt.id   AS price_term_id,
               pt.code AS price_term
        FROM price_book_entries e
        JOIN products p ON p.id = e.product_id
        LEFT JOIN price_terms pt ON pt.id = e.price_term_id
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

        price_term_id = _resolve_price_term_id(con, payload)

        try:
            cur = con.execute(
                """
                INSERT INTO price_book_entries
                (price_book_id, product_id, unit_price, currency, valid_from, valid_to, is_active, price_term, price_term_id)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    book_id,
                    product_id,
                    float(unit_price),
                    payload.get("currency"),
                    payload.get("valid_from"),
                    payload.get("valid_to"),
                    _to_db_bool(payload.get("is_active", True)),
                    payload.get("price_term"),  # back-compat (TEXT)
                    price_term_id,
                ),
            )
            con.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"Integrity error: {e}")


@router.put("/price-books/{book_id}/entries/{entry_id}")
@router.put("/price-books/{book_id}/entries/{entry_id}/")
def update_price_book_entry(book_id: int, entry_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = ["unit_price", "currency", "valid_from", "valid_to", "is_active", "product_id", "price_term", "price_term_id"]
    sets: List[str] = []
    params: List[Any] = []

    with cx() as con:
        # Resolve price_term_id from code if needed (prefer explicit id)
        if "price_term_id" in payload or "price_term" in payload:
            resolved = _resolve_price_term_id(con, payload)
            sets.append("price_term_id = ?")
            params.append(resolved)

        for k in allowed:
            if k not in payload:
                continue
            if k in ("price_term_id",):  # already handled above
                continue
            if k == "unit_price":
                sets.append("unit_price = ?")
                params.append(float(payload.get(k)))
            elif k == "is_active":
                sets.append("is_active = ?")
                params.append(_to_db_bool(payload.get(k)))
            else:
                sets.append(f"{k} = ?")
                params.append(payload.get(k))

        if not sets:
            return {"updated": 0}

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
                    SELECT e.*,
                           pt.id   AS price_term_id,
                           pt.code AS price_term
                    FROM price_book_entries e
                    LEFT JOIN price_terms pt ON pt.id = e.price_term_id
                    WHERE e.price_book_id = ?
                      AND e.product_id = ?
                      AND e.is_active = 1
                      AND (e.valid_from IS NULL OR date(e.valid_from) <= date(?))
                      AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(?))
                    ORDER BY date(IFNULL(e.valid_from,'0001-01-01')) DESC, e.id DESC
                    LIMIT 1
                    """,
                    (book_opt, pid, on_date, on_date),
                ).fetchone()
                if row:
                    return row
            return con.execute(
                """
                SELECT e.*,
                       pt.id   AS price_term_id,
                       pt.code AS price_term
                FROM price_book_entries e
                JOIN price_books b ON b.id = e.price_book_id
                LEFT JOIN price_terms pt ON pt.id = e.price_term_id
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
                SELECT e.*,
                       pt.id   AS price_term_id,
                       pt.code AS price_term
                FROM price_book_entries e
                JOIN price_books b ON b.id = e.price_book_id
                LEFT JOIN price_terms pt ON pt.id = e.price_term_id
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
            "price_term_id": entry["price_term_id"],
            "price_term": entry["price_term"],  # code
        }
