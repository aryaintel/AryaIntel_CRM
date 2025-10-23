# relative path: backend/app/api/engine_facts_api.py
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Optional, Tuple
import sqlite3, os

router = APIRouter(prefix="/api/engine", tags=["engine"])

# --- DB path resolution (PROJECT STANDARD ONLY) ------------------------------
# Project standard (single source of truth): backend/app.db
def _db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))          # .../backend/app/api
    app_dir = os.path.abspath(os.path.join(here, ".."))        # .../backend/app
    std = os.path.abspath(os.path.join(app_dir, "..", "app.db"))  # .../backend/app.db
    # No fallback. Enforce single path to avoid writer/reader split.
    if not os.path.exists(std):
        raise HTTPException(status_code=500, detail=f"DB not found at {std}")
    return std

def _rows_to_dict(rows) -> List[Dict]:
    out: List[Dict] = []
    for r in rows:
        item = {
            "run_id": int(r["run_id"]),
            "scenario_id": int(r["scenario_id"]),
            "sheet_code": r["sheet_code"],
            "category_code": r["category_code"],
            "yyyymm": int(r["yyyymm"]),
            "value": float(r["value"]),
        }
        item["series"] = r["series"] if "series" in r.keys() else None
        out.append(item)
    return out

def _resolve_latest_run_id(
    conn: sqlite3.Connection,
    scenario_id: int,
    category: Optional[str],
    sheet: Optional[str],
) -> Optional[int]:
    """Find newest run_id by relaxing scope if needed."""
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
    sheet: Optional[str] = Query(None, description="Exact sheet code (e.g., oA.Finance-AN)"),
    sheet_code: Optional[str] = Query(None, description="Alias of 'sheet'"),
    category: Optional[str] = Query(None, description="Category code (e.g., AN) — optional redundancy"),
    category_code: Optional[str] = Query(None, description="Alias of 'category'"),
    series: Optional[str] = Query(None, description="Series name(s) (e.g., revenue or 'revenue,cogs')"),
    run_id: Optional[int] = Query(None, description="Specific run id; if omitted and latest=true, latest run is used"),
    latest: bool = Query(False, description="If true and run_id not provided, pick MAX(run_id) for the filter scope"),
    yyyymm_from: Optional[int] = Query(None, description="Lower bound for yyyymm (inclusive)"),
    yyyymm_to: Optional[int] = Query(None, description="Upper bound for yyyymm (inclusive)"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """Return engine facts (V2 contract)."""
    # Unify aliases
    if sheet is None and sheet_code is not None:
        sheet = sheet_code
    if category is None and category_code is not None:
        category = category_code

    db_path = _db_path()  # will raise 500 if not exists
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        effective_run_id = run_id
        if effective_run_id is None and latest:
            effective_run_id = _resolve_latest_run_id(conn, scenario_id, category, sheet)
            if effective_run_id is None:
                raise HTTPException(status_code=404, detail="No data found to resolve latest run")

        # WHERE
        wh = ["scenario_id=?"]
        args: List = [scenario_id]
        if sheet:
            wh.append("sheet_code=?")
            args.append(sheet)
        if category:
            wh.append("category_code=?")
            args.append(category)

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

        sql = f"""
            SELECT run_id, scenario_id, sheet_code, category_code, yyyymm, value, series
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

# ----------------------------- DEBUG HELPERS ---------------------------------
@router.get("/facts/debug/where-am-i")
def facts_where_am_i(scenario_id: int = 1, run_id: Optional[int] = None):
    """Show which DB the READER uses and quick counts for latest and a given run."""
    db_path = _db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        latest_run = conn.execute(
            "SELECT MAX(run_id) AS rid FROM engine_facts_monthly WHERE scenario_id=?", (scenario_id,)
        ).fetchone()["rid"]
        count_latest = None
        if latest_run is not None:
            count_latest = conn.execute(
                "SELECT COUNT(*) AS c FROM engine_facts_monthly WHERE scenario_id=? AND run_id=?",
                (scenario_id, latest_run),
            ).fetchone()["c"]
        count_given = None
        if run_id is not None:
            count_given = conn.execute(
                "SELECT COUNT(*) AS c FROM engine_facts_monthly WHERE scenario_id=? AND run_id=?",
                (scenario_id, run_id),
            ).fetchone()["c"]
        return {
            "db_url": os.path.abspath(db_path),
            "scenario_id": scenario_id,
            "latest_run": latest_run,
            "rows_for_latest": count_latest,
            "rows_for_run_id": {"run_id": run_id, "count": count_given},
        }
    finally:
        conn.close()

@router.get("/facts/debug/table-sanity")
def facts_table_sanity(scenario_id: int = 1):
    """If both tables exist, show counts for the latest run in each (helps spot table mismatch)."""
    db_path = _db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        out = {"db_url": os.path.abspath(db_path), "tables": tables}
        for t in ["engine_facts_monthly", "engine_facts"]:
            if t in tables:
                rid = conn.execute(
                    f"SELECT MAX(run_id) AS rid FROM {t} WHERE scenario_id=?", (scenario_id,)
                ).fetchone()["rid"]
                cnt = None
                if rid is not None:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) AS c FROM {t} WHERE scenario_id=? AND run_id=?",
                        (scenario_id, rid),
                    ).fetchone()["c"]
                out[t] = {"latest_run": rid, "rows_for_latest": cnt}
        return out
    finally:
        conn.close()
