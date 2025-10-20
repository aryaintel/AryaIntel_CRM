# Path: backend/app/api/engine_facts_api.py
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Optional, Tuple
from typing import List, Dict, Optional
import sqlite3, os

router = APIRouter(prefix="/api/engine", tags=["engine"])

# --- DB path resolution (keeps existing behavior; prefers backend/app.db) ---
def _db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.abspath(os.path.join(here, ".."))
    # Try backend/app/app.db first (legacy), then backend/app.db (project standard)
    db_path = os.path.join(app_dir, "app.db")
    if not os.path.exists(db_path):
        db_path = os.path.abspath(os.path.join(app_dir, "..", "app.db"))
    return db_path

def _rows_to_dict(rows) -> List[Dict]:
    out: List[Dict] = []
    for r in rows:
        # Guarantee keys expected by FE contract; keep extra fields for debugging
        item = {
            "run_id": int(r["run_id"]),
            "scenario_id": int(r["scenario_id"]),
            "sheet_code": r["sheet_code"],
            "category_code": r["category_code"],
            "yyyymm": int(r["yyyymm"]),
            "value": float(r["value"]),
        }
        # 'series' is part of V2 contract; tolerate None if schema is old
        if "series" in r.keys():
            item["series"] = r["series"]
        else:
            item["series"] = None
        out.append(item)
    return out
def _resolve_latest_run_id(
    conn: sqlite3.Connection,
    scenario_id: int,
    category: Optional[str],
    sheet: Optional[str],
) -> Optional[int]:
    """Return the newest run_id for the given filters with graceful fallbacks.

    Historically we only persisted oA.* sheets, while the FE requests c.Sales-* (monthly)
    and then falls back client-side to any family that matches the suffix (AN/Services).
    If we keep the sheet filter during latest-run resolution we end up 404'ing even
    though a persisted run exists for that scenario/category. To avoid that, we try the
    most specific scope first (scenario+category+sheet), then relax the sheet, and
    finally fall back to scenario-only before giving up.
    """

    attempts: List[Tuple[Optional[str], Optional[str]]] = []

    if sheet:
          attempts.append((category, sheet))
    if category:
        attempts.append((category, None))
    attempts.append((None, None))

    seen = set()
    for cat_scope, sheet_scope in attempts:
        key = (cat_scope or "__any__", sheet_scope or "__any__")
        if key in seen:
            continue
        seen.add(key)

        sql = ["SELECT MAX(run_id) AS rid FROM engine_facts_monthly WHERE scenario_id=?"]
        args: List = [scenario_id]
        if cat_scope:
            sql.append("AND category_code=?")
            args.append(cat_scope)
        if sheet_scope:
            sql.append("AND sheet_code=?")
            args.append(sheet_scope)
        row = conn.execute(" ".join(sql), args).fetchone()
        if row and row["rid"] is not None:
            return int(row["rid"])
    return None

@router.get("/facts")
def get_engine_facts(
    scenario_id: int = Query(..., description="Scenario ID"),
    # Accept both 'sheet' and 'sheet_code' for compatibility
    sheet: Optional[str] = Query(None, description="Exact sheet code (e.g., oA.Finance-AN)"),
    sheet_code: Optional[str] = Query(None, description="Alias of 'sheet'"),
    # Accept both 'category' and 'category_code' for compatibility
    category: Optional[str] = Query(None, description="Category code (e.g., AN) — optional redundancy"),
    category_code: Optional[str] = Query(None, description="Alias of 'category'"),
    # Series can be a single value or comma-separated list (e.g., 'revenue,cogs')
    series: Optional[str] = Query(None, description="Series name(s) (e.g., revenue or 'revenue,cogs')"),
    run_id: Optional[int] = Query(None, description="Specific run id; if omitted and latest=true, latest run is used"),
    latest: bool = Query(False, description="If true and run_id not provided, pick MAX(run_id) for the filter scope"),
    yyyymm_from: Optional[int] = Query(None, description="Lower bound for yyyymm (inclusive)"),
    yyyymm_to: Optional[int] = Query(None, description="Upper bound for yyyymm (inclusive)"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """Return engine facts in the unified V2 contract.

    Response shape (stable):
    {
      "scenario_id": number,
      "sheet": string | null,
      "category": string | null,
      "series": string | null,
      "run_id": number | null,
      "count": number,
      "rows": [
        { "yyyymm": 202501, "series": "revenue", "category_code": "AN", "sheet_code": "oA.Finance-AN", "value": 123.45 },
        ...
      ]
    }
    Notes:
    - If latest=true and no persisted run exists for the scenario (after relaxing sheet/category), returns 404.
    """
    # Unify aliases
    if sheet is None and sheet_code is not None:
        sheet = sheet_code
    if category is None and category_code is not None:
        category = category_code

    db_path = _db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=500, detail=f"DB not found at {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        effective_run_id = run_id
        if effective_run_id is None and latest:
            effective_run_id = _resolve_latest_run_id(conn, scenario_id, category, sheet)
            if effective_run_id is None:
                   # Keep 404 behavior only when nothing persisted at scenario level
                raise HTTPException(status_code=404, detail="No data found to resolve latest run")

        # WHERE clauses
        wh = ["scenario_id=?"]
        args: List = [scenario_id]
        if sheet:
          wh.append("sheet_code=?")
          args.append(sheet)
          
        if category:
            wh.append("category_code=?")
            args.append(category)

        # Handle single or comma-separated series values
        if series:
            series_list = [s.strip() for s in series.split(",") if s.strip()]
            if len(series_list) == 1:
                wh.append("series=?")
                args.append(series_list[0])
            elif len(series_list) > 1:
                placeholders = ",".join(["?"] * len(series_list))
                wh.append(f"series IN ({placeholders})")
                args.extend(series_list)
        if effective_run_id is not None:
            wh.append("run_id=?")
            args.append(effective_run_id)
        if yyyymm_from is not None:
            wh.append("yyyymm>=?")
            args.append(yyyymm_from)
        if yyyymm_to is not None:
            wh.append("yyyymm<=?")
            args.append(yyyymm_to)

        sql = f"""                SELECT run_id, scenario_id, sheet_code, category_code, yyyymm, value, series
            FROM engine_facts_monthly
            WHERE {' AND '.join(wh)}
            ORDER BY sheet_code, yyyymm, series
            LIMIT ? OFFSET ?
        """
        args.extend([limit, offset])
        rows = conn.execute(sql, args).fetchall()
        return {
            "scenario_id": scenario_id,
            "sheet": sheet,
            "category": category,
            "series": series,
            "run_id": effective_run_id,
            "count": len(rows),
            "rows": _rows_to_dict(rows),
        }
    finally:
        conn.close()
