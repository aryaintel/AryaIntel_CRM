from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Optional
import sqlite3, os

router = APIRouter(prefix="/api/engine", tags=["engine"])

def _db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.abspath(os.path.join(here, ".."))
    db_path = os.path.join(app_dir, "app.db")
    if not os.path.exists(db_path):
        db_path = os.path.abspath(os.path.join(app_dir, "..", "app.db"))
    return db_path

def _rows_to_dict(rows) -> List[Dict]:
    return [
        {
            "run_id": int(r["run_id"]),
            "scenario_id": int(r["scenario_id"]),
            "sheet_code": r["sheet_code"],
            "category_code": r["category_code"],
            "yyyymm": int(r["yyyymm"]),
            "value": float(r["value"]),
        }
        for r in rows
    ]

def _resolve_latest_run_id(conn: sqlite3.Connection, scenario_id: int, category: Optional[str], sheet: Optional[str]) -> Optional[int]:
    sql = ["SELECT MAX(run_id) AS rid FROM engine_facts_monthly WHERE scenario_id=?"]
    args = [scenario_id]
    if category:
        sql.append("AND category_code=?")
        args.append(category)
    if sheet:
        sql.append("AND sheet_code=?")
        args.append(sheet)
    row = conn.execute(" ".join(sql), args).fetchone()
    return int(row["rid"]) if row and row["rid"] is not None else None

@router.get("/facts")
def get_engine_facts(
    scenario_id: int = Query(..., description="Scenario ID"),
    sheet: Optional[str] = Query(None, description="Exact sheet code (e.g., oA.Finance-AN.Revenue)"),
    category: Optional[str] = Query(None, description="Category code (e.g., AN) — optional redundancy"),
    run_id: Optional[int] = Query(None, description="Specific run id; if omitted and latest=true, latest run is used"),
    latest: bool = Query(False, description="If true and run_id not provided, pick MAX(run_id) for the filter scope"),
    yyyymm_from: Optional[int] = Query(None, description="Lower bound for yyyymm (inclusive)"),
    yyyymm_to: Optional[int] = Query(None, description="Upper bound for yyyymm (inclusive)"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
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
                raise HTTPException(status_code=404, detail="No data found to resolve latest run")

        wh = ["scenario_id=?"]
        args: List = [scenario_id]
        if sheet:
            wh.append("sheet_code=?"); args.append(sheet)
        if category:
            wh.append("category_code=?"); args.append(category)
        if effective_run_id is not None:
            wh.append("run_id=?"); args.append(effective_run_id)
        if yyyymm_from is not None:
            wh.append("yyyymm>=?"); args.append(yyyymm_from)
        if yyyymm_to is not None:
            wh.append("yyyymm<=?"); args.append(yyyymm_to)

        sql = f"""
            SELECT run_id, scenario_id, sheet_code, category_code, yyyymm, value
            FROM engine_facts_monthly
            WHERE {' AND '.join(wh)}
            ORDER BY sheet_code, yyyymm
            LIMIT ? OFFSET ?
        """
        args.extend([limit, offset])
        rows = conn.execute(sql, args).fetchall()
        return {
            "scenario_id": scenario_id,
            "sheet": sheet,
            "category": category,
            "run_id": effective_run_id,
            "count": len(rows),
            "rows": _rows_to_dict(rows),
        }
    finally:
        conn.close()
