from pathlib import Path
from decimal import Decimal, getcontext
from typing import Optional, List
from datetime import datetime
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, condecimal


import os

def _resolve_db_path() -> Path:
    """Resolve app.db path consistently (similar to products_api)."""
    # 1) Explicit env override
    env = os.getenv("APP_DB_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p

    # 2) Nearby common locations
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "app.db",  # repo root
        here.parents[2] / "app.db",  # backend root
        here.parents[1] / "app.db",  # app package dir (legacy)
    ]
    for p in candidates:
        if p.exists():
            return p

    # 3) Fallback to repo root
    return candidates[0]

def _ensure_schema(cx) -> None:
    """Create product_formulations + formulation_components tables if missing."""
    # product_formulations
    cx.executescript("""
    CREATE TABLE IF NOT EXISTS product_formulations (
      id INTEGER PRIMARY KEY,
      product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      code TEXT NOT NULL,
      name TEXT NULL,
      description TEXT NULL,
      base_price NUMERIC(18,6) NULL,
      base_currency TEXT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      version_no INTEGER NOT NULL DEFAULT 1,
      is_archived INTEGER NOT NULL DEFAULT 0,
      archived_at TEXT NULL,
      parent_formulation_id INTEGER NULL,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_product_formulations_prod_code_ver
      ON product_formulations(product_id, code, version_no);
    -- formulation_components
    CREATE TABLE IF NOT EXISTS formulation_components (
      id INTEGER PRIMARY KEY,
      formulation_id INTEGER NOT NULL REFERENCES product_formulations(id) ON DELETE CASCADE,
      index_series_id INTEGER NOT NULL,
      weight_pct NUMERIC(9,6) NOT NULL,
      base_index_value NUMERIC(18,6) NULL,
      note TEXT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_components_formulation ON formulation_components(formulation_id);
    """)

router = APIRouter(prefix="/api/formulations", tags=["formulations"])
DB_PATH = _resolve_db_path()

getcontext().prec = 28


# ---------------- DB helpers ----------------
def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    try:
        _ensure_schema(cx)
    except Exception:
        pass
    return cx


def _ensure_exists(cx: sqlite3.Connection, table: str, id_: int):
    row = cx.execute(f"SELECT id FROM {table} WHERE id=?", (id_,)).fetchone()
    if not row:
        raise HTTPException(404, f"{table} not found")


def _exists(cx: sqlite3.Connection, table: str, id_: int) -> bool:
    return cx.execute(f"SELECT 1 FROM {table} WHERE id=?", (id_,)).fetchone() is not None


def _now() -> str:
    # TEXT kolonları için ISO-8601 (timezone’suz UTC)
    return datetime.utcnow().isoformat(timespec="seconds")


# ---------------- Schemas ----------------
class ComponentIn(BaseModel):
    index_series_id: int
    weight_pct: condecimal(max_digits=9, decimal_places=4)
    base_index_value: Optional[condecimal(max_digits=18, decimal_places=6)] = None
    note: Optional[str] = None


class FormulationCreate(BaseModel):
    product_id: int
    code: str
    name: Optional[str] = None
    base_price: Optional[condecimal(max_digits=18, decimal_places=6)] = None
    base_currency: Optional[str] = "USD"
    components: List[ComponentIn]


class FormulationUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    base_price: Optional[condecimal(max_digits=18, decimal_places=6)] = None
    base_currency: Optional[str] = None
    components: Optional[List[ComponentIn]] = None  # if provided → full replace


class CloneIn(BaseModel):
    # Opsiyonel override alanları
    code: Optional[str] = None
    name: Optional[str] = None
    base_price: Optional[condecimal(max_digits=18, decimal_places=6)] = None
    base_currency: Optional[str] = None


# ---------------- Helpers ----------------
def _normalize_weights(components: List[ComponentIn]) -> List[dict]:
    """
    Gelen weight_pct değerlerini toplam 100 olacak şekilde normalize eder.
    4 ondalığa yuvarlar ve kalan farkı ±0.0001 adımlarla dağıtır.
    """
    vals = [Decimal(str(c.weight_pct)) for c in components]
    total = sum(vals)
    if total <= 0:
        raise HTTPException(400, "sum(weight_pct) must be > 0")

    norm = [(v * Decimal("100")) / total for v in vals]
    rounded = [n.quantize(Decimal("0.0001")) for n in norm]

    residual = Decimal("100") - sum(rounded)
    step = Decimal("0.0001")
    i = 0
    while residual != 0:
        idx = i % len(rounded)
        if residual > 0:
            rounded[idx] += step
            residual -= step
        else:
            rounded[idx] -= step
            residual += step
        i += 1
        if i > 200000:  # emniyet freni
            break

    out: List[dict] = []
    for c, w in zip(components, rounded):
        out.append(
            {
                "index_series_id": c.index_series_id,
                "weight_pct": float(w),
                "base_index_value": float(c.base_index_value) if c.base_index_value is not None else None,
                "note": c.note,
            }
        )
    return out


# ---------------- Routes ----------------
@router.post("", status_code=201)
def create_formulation(payload: FormulationCreate):
    with _db() as cx:
        if cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone():
            _ensure_exists(cx, "products", payload.product_id)

        dupe = cx.execute(
            "SELECT id FROM product_formulations WHERE product_id=? AND code=?",
            (payload.product_id, payload.code),
        ).fetchone()
        if dupe:
            raise HTTPException(409, "formulation code already exists for this product")

        comps = _normalize_weights(payload.components)

        try:
            cur = cx.execute(
                """
                INSERT INTO product_formulations
                (product_id, code, name, base_price, base_currency,
                 is_active, version_no, is_archived, archived_at, parent_formulation_id, created_at, updated_at)
                VALUES (?,?,?,?,?, 1, 1, 0, NULL, NULL, ?, ?)
                """,
                (
                    payload.product_id,
                    payload.code,
                    payload.name,
                    float(payload.base_price) if payload.base_price is not None else None,
                    payload.base_currency,
                    _now(),
                    _now(),
                ),
            )
            fid = cur.lastrowid
            for c in comps:
                cx.execute(
                    """
                    INSERT INTO formulation_components
                    (formulation_id, index_series_id, weight_pct, base_index_value, note)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        fid,
                        c["index_series_id"],
                        float(c["weight_pct"]),
                        float(c["base_index_value"]) if c["base_index_value"] is not None else None,
                        c["note"],
                    ),
                )
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"db integrity error: {e}")

        return {"id": fid}


@router.get("/{fid}")
def get_formulation(fid: int):
    with _db() as cx:
        f = cx.execute("SELECT * FROM product_formulations WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "formulation not found")
        comps = cx.execute(
            """
            SELECT id, index_series_id, weight_pct, base_index_value, note
            FROM formulation_components
            WHERE formulation_id=?
            ORDER BY id
            """,
            (fid,),
        ).fetchall()
        return {"formulation": dict(f), "components": [dict(r) for r in comps]}


@router.get("")
def list_formulations(
    product_id: Optional[int] = None,
    q: Optional[str] = None,
    include_archived: bool = Query(False, description="Arşivdekileri de getir"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    sql = "SELECT * FROM product_formulations WHERE 1=1"
    args: list = []
    if product_id is not None:
        sql += " AND product_id=?"
        args.append(product_id)
    if q:
        sql += " AND (code LIKE ? OR name LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if not include_archived:
        sql += " AND COALESCE(is_archived,0)=0"
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    with _db() as cx:
        rows = [dict(r) for r in cx.execute(sql, args).fetchall()]
        return {"items": rows, "count": len(rows), "limit": limit, "offset": offset}


@router.put("/{fid}")
def update_formulation(fid: int, payload: FormulationUpdate):
    with _db() as cx:
        _ensure_exists(cx, "product_formulations", fid)

        try:
            fields: List[str] = []
            vals: list = []
            for col in ("code", "name", "base_price", "base_currency"):
                val = getattr(payload, col)
                if val is not None:
                    if col == "base_price":
                        val = float(val)
                    fields.append(f"{col}=?")
                    vals.append(val)
            if fields:
                fields.append("updated_at=?")
                vals.append(_now())
                vals.append(fid)
                cx.execute(f"UPDATE product_formulations SET {', '.join(fields)} WHERE id=?", vals)

            if payload.components is not None:
                if not payload.components:
                    raise HTTPException(400, "components must contain at least 1 item")
                missing = [
                    c.index_series_id for c in payload.components if not _exists(cx, "index_series", c.index_series_id)
                ]
                if missing:
                    raise HTTPException(404, f"index_series not found: ids={missing}")

                comps = _normalize_weights(payload.components)
                cx.execute("DELETE FROM formulation_components WHERE formulation_id=?", (fid,))
                for c in comps:
                    cx.execute(
                        """
                        INSERT INTO formulation_components
                        (formulation_id, index_series_id, weight_pct, base_index_value, note)
                        VALUES (?,?,?,?,?)
                        """,
                        (
                            fid,
                            c["index_series_id"],
                            float(c["weight_pct"]),
                            float(c["base_index_value"]) if c["base_index_value"] is not None else None,
                            c["note"],
                        ),
                    )
            return {"id": fid, "updated": True}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"db integrity error: {e}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"update_formulation failed: {e}")


# ---- ARCHIVE / RESTORE ----
@router.post("/{fid}/archive")
def archive_formulation(fid: int):
    with _db() as cx:
        f = cx.execute("SELECT id, is_archived FROM product_formulations WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "formulation not found")
        if (f["is_archived"] or 0) == 1:
            raise HTTPException(409, "already archived")

        cx.execute(
            """
            UPDATE product_formulations
               SET is_archived=1, archived_at=?, is_active=0, updated_at=?
             WHERE id=?
            """,
            (_now(), _now(), fid),
        )
        return {"id": fid, "archived": True}


@router.post("/{fid}/restore")
def restore_formulation(fid: int):
    with _db() as cx:
        f = cx.execute("SELECT id, is_archived FROM product_formulations WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "formulation not found")
        if (f["is_archived"] or 0) == 0:
            raise HTTPException(409, "not archived")

        cx.execute(
            """
            UPDATE product_formulations
               SET is_archived=0, archived_at=NULL, is_active=1, updated_at=?
             WHERE id=?
            """,
            (_now(), fid),
        )
        return {"id": fid, "restored": True}


# ---- CLONE (new version) ----
@router.post("/{fid}/clone", status_code=201)
def clone_formulation(fid: int, body: CloneIn | None = None):
    body = body or CloneIn()
    with _db() as cx:
        src = cx.execute("SELECT * FROM product_formulations WHERE id=?", (fid,)).fetchone()
        if not src:
            raise HTTPException(404, "formulation not found")

        # versiyon numarası
        curr_ver = src["version_no"] or 1
        new_ver = curr_ver + 1

        # kod / isim / fiyat override
        new_code = body.code or f"{src['code']}_v{new_ver}"
        new_name = body.name or src["name"]
        new_price = float(body.base_price) if body.base_price is not None else src["base_price"]
        new_ccy = body.base_currency or src["base_currency"]

        # aynı ürün + kod var mı?
        dupe = cx.execute(
            "SELECT id FROM product_formulations WHERE product_id=? AND code=?",
            (src["product_id"], new_code),
        ).fetchone()
        if dupe:
            raise HTTPException(409, "formulation code already exists for this product")

        cur = cx.execute(
            """
            INSERT INTO product_formulations
            (product_id, code, name, base_price, base_currency,
             is_active, version_no, is_archived, archived_at, parent_formulation_id, created_at, updated_at)
            VALUES (?,?,?,?,?, 1, ?, 0, NULL, ?, ?, ?)
            """,
            (
                src["product_id"],
                new_code,
                new_name,
                new_price,
                new_ccy,
                new_ver,
                src["id"],  # parent_formulation_id
                _now(),
                _now(),
            ),
        )
        new_id = cur.lastrowid

        comps = cx.execute(
            """
            SELECT index_series_id, weight_pct, base_index_value, note
              FROM formulation_components
             WHERE formulation_id=?
            """,
            (fid,),
        ).fetchall()

        for c in comps:
            cx.execute(
                """
                INSERT INTO formulation_components
                (formulation_id, index_series_id, weight_pct, base_index_value, note)
                VALUES (?,?,?,?,?)
                """,
                (
                    new_id,
                    c["index_series_id"],
                    float(c["weight_pct"]),
                    float(c["base_index_value"]) if c["base_index_value"] is not None else None,
                    c["note"],
                ),
            )

        return {"id": new_id, "cloned_from": fid, "version_no": new_ver}


# ---- DELETE DEVRE DIŞI (Seçenek 2) ----
@router.delete("/{fid}", status_code=409)
def delete_formulation(fid: int):
    """Deletion bilinçli olarak devre dışı bırakıldı; her zaman 409 döner."""
    raise HTTPException(409, "Deleting formulations is disabled")
