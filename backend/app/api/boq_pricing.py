from __future__ import annotations

from pathlib import Path
from decimal import Decimal, getcontext
from datetime import date
import os
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

getcontext().prec = 28

router = APIRouter(prefix="/api/boq", tags=["pricing"])

# ---------------------------------------------------------------------
# DB path (env -> common locations)
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
    # default to repo-root style even if it doesn't exist yet
    return candidates[0]


DB_PATH = _resolve_db_path()


def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _parse_ym(ym: str) -> tuple[int, int]:
    try:
        y, m = ym.split("-")
        y_i, m_i = int(y), int(m)
        if not (1 <= m_i <= 12):
            raise ValueError
        return y_i, m_i
    except Exception:
        raise HTTPException(422, "ym must be 'YYYY-MM'")


def _ym_to_date(ym: str) -> str:
    y, m = _parse_ym(ym)
    return date(y, m, 1).isoformat()


def _index_value(cx: sqlite3.Connection, series_id: int, year: int, month: int) -> Decimal:
    row = cx.execute(
        "SELECT value FROM index_points WHERE series_id=? AND year=? AND month=?",
        (series_id, year, month),
    ).fetchone()
    if not row:
        raise HTTPException(
            409,
            f"Missing index point: series_id={series_id} at {year}-{month:02d}",
        )
    return Decimal(str(row["value"]))


def _formulation_factor(
    cx: sqlite3.Connection, formulation_id: int, year: int, month: int
) -> Decimal:
    comps = cx.execute(
        """
        SELECT index_series_id, weight_pct, base_index_value
        FROM formulation_components
        WHERE formulation_id=?
        """,
        (formulation_id,),
    ).fetchall()
    if not comps:
        raise HTTPException(409, "Formulation has no components")

    factor = Decimal("0")
    for c in comps:
        base = c["base_index_value"]
        if base is None:
            raise HTTPException(409, "base_index_value is NULL (set Base Ref)")
        curr = _index_value(cx, int(c["index_series_id"]), year, month)
        ratio = curr / Decimal(str(base))
        w = Decimal(str(c["weight_pct"])) / Decimal("100")
        factor += w * ratio
    return factor


def _best_price_for_product(
    cx: sqlite3.Connection, product_id: int, on_date: str
) -> sqlite3.Row | None:
    """
    Resolve best active price for product on given date.
    Preference:
      1) default & active price book AND entry period-valid,
      2) any active price book AND entry period-valid,
      3) latest active entry regardless of date window.
    """
    # 1) default price book + period-valid
    row = cx.execute(
        """
        SELECT e.*, b.currency AS book_currency
        FROM price_book_entries e
        JOIN price_books b ON b.id = e.price_book_id
        WHERE e.product_id = ?
          AND e.is_active = 1
          AND b.is_active = 1
          AND b.is_default = 1
          AND (e.valid_from IS NULL OR date(e.valid_from) <= date(?))
          AND (e.valid_to   IS NULL OR date(e.valid_to)   >= date(?))
        ORDER BY date(IFNULL(e.valid_from,'0001-01-01')) DESC, e.id DESC
        LIMIT 1
        """,
        (product_id, on_date, on_date),
    ).fetchone()
    if row:
        return row

    # 2) any active book + period-valid (prefer default if ties)
    row = cx.execute(
        """
        SELECT e.*, b.currency AS book_currency
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
        (product_id, on_date, on_date),
    ).fetchone()
    if row:
        return row

    # 3) latest active entry (ignore date window)
    row = cx.execute(
        """
        SELECT e.*, b.currency AS book_currency
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
        (product_id,),
    ).fetchone()
    return row


def _load_boq(cx: sqlite3.Connection, boq_id: int) -> sqlite3.Row | None:
    return cx.execute(
        """
        SELECT b.*,
               f.base_price     AS formulation_base_price,
               f.base_currency  AS formulation_currency
        FROM scenario_boq_items b
        LEFT JOIN product_formulations f ON f.id = b.formulation_id
        WHERE b.id = ?
        """,
        (boq_id,),
    ).fetchone()


# ---------------------------------------------------------------------
# API: price preview (by BOQ id)
# ---------------------------------------------------------------------
@router.get("/{boq_id}/price-preview")
def boq_price_preview(boq_id: int, ym: str = Query(..., description="YYYY-MM")):
    """
    Price preview logic:
      - If BOQ row has a formulation: price = formulation.base_price * factor(ym)
      - elif product_id exists: price = best PriceBook entry on ym
      - else: fallback to stored unit_price on BOQ
    Returns numbers as strings to keep precision consistent.
    Also returns `price_term` when using a Price Book entry, so FE can auto-fill BOQ's Price Terms.
    """
    y, m = _parse_ym(ym)
    on_date = _ym_to_date(ym)

    with _db() as cx:
        row = _load_boq(cx, boq_id)
        if not row:
            raise HTTPException(404, "boq item not found")

        qty = Decimal(str(row["quantity"] or 1))
        currency = "USD"
        source = "boq_unit_price"
        price_term = None

        # 1) formulation based
        if row["formulation_id"] is not None:
            factor = _formulation_factor(cx, int(row["formulation_id"]), y, m)
            base_price = Decimal(str(row["formulation_base_price"] or 0))
            unit_price = (base_price * factor).quantize(Decimal("0.01"))
            currency = row["formulation_currency"] or "USD"
            line_total = (unit_price * qty).quantize(Decimal("0.01"))
            return {
                "id": row["id"],
                "scenario_id": row["scenario_id"],
                "name": row["item_name"],
                "period": ym,
                "currency": currency,
                "base_price": str(base_price),
                "factor": str(factor),
                "unit_price": str(unit_price),
                "quantity": str(qty),
                "line_total": str(line_total),
                "source": "formulation",
                "price_term": None,
            }

        # 2) price book by product_id
        if row["product_id"] is not None:
            pbe = _best_price_for_product(cx, int(row["product_id"]), on_date)
            if pbe:
                unit_price = Decimal(str(pbe["unit_price"])).quantize(Decimal("0.01"))
                currency = (pbe["currency"] or pbe["book_currency"] or "USD")
                source = "product_price_book"
                # NEW: pass-through price_term if present on the price book entry
                price_term = pbe["price_term"] if "price_term" in pbe.keys() else None
            else:
                unit_price = Decimal(str(row["unit_price"] or 0)).quantize(Decimal("0.01"))
                source = "boq_unit_price"
        else:
            # 3) fallback: stored unit_price
            unit_price = Decimal(str(row["unit_price"] or 0)).quantize(Decimal("0.01"))
            source = "boq_unit_price"

        line_total = (unit_price * qty).quantize(Decimal("0.01"))
        return {
            "id": row["id"],
            "scenario_id": row["scenario_id"],
            "name": row["item_name"],
            "period": ym,
            "currency": currency,
            "unit_price": str(unit_price),
            "quantity": str(qty),
            "line_total": str(line_total),
            "source": source,
            "price_term": price_term,  # NEW
        }


# ---------------------------------------------------------------------
# API: scenario-bounded price preview
# ---------------------------------------------------------------------
@router.get("/scenarios/{scenario_id}/boq/{boq_id}/price-preview")
def scenario_bounded_price_preview(
    scenario_id: int, boq_id: int, ym: str = Query(..., description="YYYY-MM")
):
    """
    Same calculation as /{boq_id}/price-preview but **enforces**
    that the BOQ row belongs to the given scenario_id.
    """
    y, m = _parse_ym(ym)
    on_date = _ym_to_date(ym)

    with _db() as cx:
        row = _load_boq(cx, boq_id)
        if not row:
            raise HTTPException(404, "boq item not found")
        if int(row["scenario_id"]) != int(scenario_id):
            raise HTTPException(404, "boq item not found in this scenario")

        qty = Decimal(str(row["quantity"] or 1))
        currency = "USD"
        source = "boq_unit_price"
        price_term = None

        # formulation
        if row["formulation_id"] is not None:
            factor = _formulation_factor(cx, int(row["formulation_id"]), y, m)
            base_price = Decimal(str(row["formulation_base_price"] or 0))
            unit_price = (base_price * factor).quantize(Decimal("0.01"))
            currency = row["formulation_currency"] or "USD"
            line_total = (unit_price * qty).quantize(Decimal("0.01"))
            return {
                "id": row["id"],
                "scenario_id": row["scenario_id"],
                "name": row["item_name"],
                "period": ym,
                "currency": currency,
                "base_price": str(base_price),
                "factor": str(factor),
                "unit_price": str(unit_price),
                "quantity": str(qty),
                "line_total": str(line_total),
                "source": "formulation",
                "price_term": None,
            }

        # price book
        if row["product_id"] is not None:
            pbe = _best_price_for_product(cx, int(row["product_id"]), on_date)
            if pbe:
                unit_price = Decimal(str(pbe["unit_price"])).quantize(Decimal("0.01"))
                currency = (pbe["currency"] or pbe["book_currency"] or "USD")
                source = "product_price_book"
                price_term = pbe["price_term"] if "price_term" in pbe.keys() else None
            else:
                unit_price = Decimal(str(row["unit_price"] or 0)).quantize(Decimal("0.01"))
                source = "boq_unit_price"
        else:
            unit_price = Decimal(str(row["unit_price"] or 0)).quantize(Decimal("0.01"))
            source = "boq_unit_price"

        line_total = (unit_price * qty).quantize(Decimal("0.01"))
        return {
            "id": row["id"],
            "scenario_id": row["scenario_id"],
            "name": row["item_name"],
            "period": ym,
            "currency": currency,
            "unit_price": str(unit_price),
            "quantity": str(qty),
            "line_total": str(line_total),
            "source": source,
            "price_term": price_term,  # NEW
        }


# ---------------------------------------------------------------------
# LIST ENDPOINTS (Swagger'da görünür)
# ---------------------------------------------------------------------
@router.get("/scenarios", tags=["browse"])
def list_scenarios(
    q: str | None = Query(None, description="Name contains (case-insensitive)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Senaryoların kısa listesi (id, name, months, start_date, flags).
    """
    sql = """
        SELECT id, name, months, start_date,
               is_boq_ready, is_twc_ready, is_capex_ready, is_services_ready
        FROM scenarios
    """
    params: list[object] = []
    if q:
        sql += " WHERE lower(name) LIKE lower(?)"
        params.append(f"%{q}%")
    sql += " ORDER BY id LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with _db() as cx:
        rows = cx.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@router.get("/scenarios/{scenario_id}/boq", tags=["browse"])
def list_boq_items_for_scenario(
    scenario_id: int,
    active: Literal["all", "active", "inactive"] = Query(
        "active", description="Filter by is_active"
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Belirli senaryoya ait BOQ satırlarını listeler.
    """
    base_sql = """
        SELECT id, scenario_id, section, category, item_name, unit,
               quantity, unit_price, unit_cogs, frequency, months,
               start_year, start_month, is_active,
               formulation_id, product_id
        FROM scenario_boq_items
        WHERE scenario_id = ?
    """
    params: list[object] = [scenario_id]
    if active == "active":
        base_sql += " AND is_active = 1"
    elif active == "inactive":
        base_sql += " AND (is_active IS NOT 1)"

    base_sql += " ORDER BY id LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with _db() as cx:
        rows = cx.execute(base_sql, params).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------
# Debug helpers (read-only)
# ---------------------------------------------------------------------
@router.get("/_debug/schema", tags=["debug"])
def debug_schema():
    """Return DB path + minimal table defs useful for troubleshooting."""
    with _db() as cx:
        def table_info(name: str):
            cols = cx.execute(f"PRAGMA table_info({name})").fetchall()
            return [
                dict(
                    cid=c["cid"],
                    name=c["name"],
                    type=c["type"],
                    notnull=c["notnull"],
                    dflt_value=c["dflt_value"],
                    pk=c["pk"],
                )
                for c in cols
            ]

        tables = []
        for t in cx.execute(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        ).fetchall():
            tables.append(
                {"name": t["name"], "create_sql": t["sql"], "columns": table_info(t["name"])}
            )

        # quick presence flags we care about
        def exists(name: str) -> bool:
            return bool(
                cx.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
                ).fetchone()
            )

        presence = {
            "business_case_boq_items": exists("business_case_boq_items"),
            "scenario_boq_items": exists("scenario_boq_items"),
            "bc_boq_items": exists("bc_boq_items"),
            "products": exists("products"),
            "price_books": exists("price_books"),
            "price_book_entries": exists("price_book_entries"),
            "product_formulations": exists("product_formulations"),
            "formulation_components": exists("formulation_components"),
            "index_points": exists("index_points"),
        }

        return {
            "db_path": str(DB_PATH),
            "boq_table_detected": "scenario_boq_items" if presence["scenario_boq_items"] else None,
            "tables": tables,
            "presence": presence,
        }


@router.get("/_debug/count", tags=["debug"])
def debug_count(table: str):
    """
    Verilen tablo için satır sayısını döner. Whitelist uygulanır.
    Ör: /api/boq/_debug/count?table=scenario_boq_items
    """
    allowed = {
        "scenario_boq_items",
        "products",
        "price_books",
        "price_book_entries",
        "product_formulations",
        "formulation_components",
        "index_points",
        "scenarios",
    }
    if table not in allowed:
        raise HTTPException(400, f"table not allowed: {table}")

    try:
        with _db() as cx:
            row = cx.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
            return {"table": table, "count": int(row["cnt"])}
    except sqlite3.OperationalError as e:
        raise HTTPException(409, f"db error: {e}")


@router.get("/_debug/sample", tags=["debug"])
def debug_sample(table: str, limit: int = 10):
    """Dump first N rows from a table (read-only, whitelisted)."""
    allowed = {
        "scenario_boq_items",
        "products",
        "price_books",
        "price_book_entries",
        "product_formulations",
        "formulation_components",
        "index_points",
        "scenarios",
    }
    if table not in allowed:
        raise HTTPException(400, f"table not allowed: {table}")
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")

    with _db() as cx:
        try:
            rows = cx.execute(f"SELECT * FROM {table} LIMIT ?", (limit,)).fetchall()
        except sqlite3.OperationalError as e:
            raise HTTPException(400, f"bad table: {e}")
        return [dict(r) for r in rows]


@router.get("/_debug/boq-locate", tags=["debug"])
def debug_boq_locate(id: int):
    """
    Find which known BOQ table a row id lives in (currently: scenario_boq_items).
    """
    with _db() as cx:
        r = cx.execute("SELECT id, scenario_id FROM scenario_boq_items WHERE id=?", (id,)).fetchone()
        if r:
            return {"found_in": "scenario_boq_items", "id": r["id"], "scenario_id": r["scenario_id"]}
    raise HTTPException(404, f"BOQ id {id} is not found in known tables")
