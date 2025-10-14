# Pathway: C:/Dev/AryaIntel_CRM/backend/app/api/engine_facts_api.py
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from .deps import get_db  # project dep

router = APIRouter(prefix="/api", tags=["engine"])

class FactRow(BaseModel):
    run_id: Optional[int] = None
    scenario_id: Optional[int] = None
    sheet_code: str
    category_code: str
    yyyymm: int
    value: float

class FactsResponse(BaseModel):
    total: Optional[int] = None
    rows: List[FactRow]

@router.get("/engine/facts", response_model=FactsResponse, summary="Read Engine Facts (rows)")
def read_engine_facts(
    db: Session = Depends(get_db),
    scenario_id: Optional[int] = Query(None, ge=1),
    sheet: Optional[str] = Query(None, description="e.g., c.Sales, oA.Finance, oQ.Finance"),
    category: Optional[str] = Query(None, description="AN, EM, IE, Services"),
    run_id: Optional[int] = Query(None, ge=1),
    yyyymm_from: Optional[int] = Query(None, description="inclusive, e.g., 202501"),
    yyyymm_to: Optional[int] = Query(None, description="inclusive, e.g., 202512"),
    limit: int = Query(2000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
):
    # Ensure table exists (runtime guard; no-op if already created)
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_facts_monthly (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            scenario_id INTEGER,
            sheet_code TEXT NOT NULL,
            category_code TEXT NOT NULL,
            yyyymm INTEGER NOT NULL,
            value NUMERIC(18,6) NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """))

    where = ["1=1"]
    params = {}
    if scenario_id is not None:
        where.append("scenario_id = :sid"); params["sid"] = scenario_id
    if sheet:
        where.append("sheet_code = :sheet"); params["sheet"] = sheet
    if category:
        where.append("category_code = :cat"); params["cat"] = category
    if run_id is not None:
        where.append("run_id = :rid"); params["rid"] = run_id
    if yyyymm_from is not None:
        where.append("yyyymm >= :from"); params["from"] = yyyymm_from
    if yyyymm_to is not None:
        where.append("yyyymm <= :to"); params["to"] = yyyymm_to

    where_sql = " AND ".join(where)
    total = db.execute(text(f"SELECT COUNT(*) FROM engine_facts_monthly WHERE {where_sql}"), params).scalar() or 0

    rows = db.execute(text(f"""
        SELECT run_id, scenario_id, sheet_code, category_code, yyyymm, value
        FROM engine_facts_monthly
        WHERE {where_sql}
        ORDER BY yyyymm, sheet_code, category_code
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": int(limit), "offset": int(offset)}).mappings().all()

    out = [FactRow(
        run_id=r.get("run_id"),
        scenario_id=r.get("scenario_id"),
        sheet_code=r["sheet_code"],
        category_code=r["category_code"],
        yyyymm=int(r["yyyymm"]),
        value=float(r["value"] or 0.0),
    ) for r in rows]

    return FactsResponse(total=int(total), rows=out)
