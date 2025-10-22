from __future__ import annotations

from typing import List, Dict, Optional, Any, Tuple
from datetime import date
import json, re
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db  # Session factory

router = APIRouter(prefix="/api", tags=["engine"])

# --- Models (unchanged) ---
class CategoryCode(str, Enum):
    AN = "AN"; EM = "EM"; IE = "IE"; Services = "Services"

class EngineCategory(BaseModel):
    code: CategoryCode
    enabled: bool = True

class EngineOptions(BaseModel):
    rise_and_fall: Optional[bool] = None
    fx_apply: bool = True
    tax_apply: bool = True
    rebates_apply: bool = True
    twc_apply: bool = True

class RunEngineRequest(BaseModel):
    categories: List[EngineCategory]
    options: EngineOptions = Field(default_factory=EngineOptions)
    persist: bool = False
    include_facts: bool = False

class EngineLocks(BaseModel):
    rise_and_fall: bool

class SheetPayload(BaseModel):
    name: str
    months: List[str]
    values: List[float]

class RunEngineResult(BaseModel):
    scenario_id: int
    generated: List[SheetPayload]
    locks: EngineLocks
    notes: Optional[str] = None
    persisted: bool = False
    persisted_rows: int = 0
    run_id: Optional[int] = None

# --- helpers (same as before) ---
#   _fetch_scenario, _ym_series, _has_rise_fall_policy, _apply_dso_to_cash,
#   _schedule_from_boq, _schedule_services_expense_raw, _fx_rate_for_month,
#   _apply_fx_on_services, _load_index_series, _build_rf_multiplier,
#   _load_rebates, _apply_rebates, _apply_tax_on_services
#   (içerikleri sizdekiyle aynı; burayı kısalttım)

_SERIES_SUFFIX_MAP = {".REVENUE":"revenue",".COGS":"cogs",".GP":"gp"}
_SUFFIX_RE = re.compile(r"\.(REVENUE|COGS|GP)$", re.IGNORECASE)

def _split_name_to_sheet_and_series(name: str) -> Tuple[str, Optional[str]]:
    m = _SUFFIX_RE.search(name); 
    if not m: return name, None
    return name[: -len(m.group(0))], _SERIES_SUFFIX_MAP[m.group(0).upper()]

def _parse_category_from_name(name: str) -> str:
    if "-" not in name: return "ALL"
    return name.split("-", 1)[1].split(".", 1)[0]

def _ensure_schema(db: Session) -> None:
    # tablo + UNIQUE index (series dahil)
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_runs (
            id INTEGER PRIMARY KEY,
            scenario_id INTEGER,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            options_json TEXT
        )"""))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_facts_monthly (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            scenario_id INTEGER,
            sheet_code TEXT NOT NULL,
            category_code TEXT NOT NULL,
            yyyymm INTEGER NOT NULL,
            value NUMERIC(18,6) NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            series TEXT
        )"""))
    # series kolonu yoksa ekle
    cols = db.execute(text("PRAGMA table_info('engine_facts_monthly')")).fetchall()
    if "series" not in { (c._mapping["name"] if hasattr(c,"_mapping") else c[1]) for c in cols }:
        db.execute(text("ALTER TABLE engine_facts_monthly ADD COLUMN series TEXT"))
    db.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_efm_run_sheet_cat_yyyymm_series
        ON engine_facts_monthly(run_id, sheet_code, category_code, yyyymm, series)
    """))

def _persist_results(db: Session, scenario_id: int, req: RunEngineRequest, generated: List[SheetPayload]) -> Tuple[int, int]:
    _ensure_schema(db)
    inserted = 0
    # Tek transaction
    with db.begin():
        db.execute(
            text("INSERT INTO engine_runs (scenario_id, options_json) VALUES (:sid, :opts)"),
            {"sid": scenario_id, "opts": json.dumps({"options": req.options.dict(), "categories":[c.dict() for c in req.categories]})}
        )
        # SQLite güvenlisi: connection scoped id
        rid = db.execute(text("SELECT last_insert_rowid()")).scalar()
        if not rid:
            # fallback
            rid = db.execute(text("SELECT MAX(id) FROM engine_runs WHERE scenario_id=:sid"), {"sid": scenario_id}).scalar()
        run_id = int(rid)

        for s in generated:
            sheet, series = _split_name_to_sheet_and_series(s.name)
            if series is None:    # c.Sales-* legacy görünüm, persist etmiyoruz
                continue
            cat = _parse_category_from_name(sheet)
            for ym, val in zip(s.months, s.values):
                y, m = ym.split("-")
                yyyymm = int(y)*100 + int(m)
                db.execute(text("""
                    INSERT INTO engine_facts_monthly
                      (run_id, scenario_id, sheet_code, category_code, yyyymm, series, value)
                    VALUES
                      (:rid, :sid, :sheet, :cat, :yyyymm, :series, :val)
                    ON CONFLICT(run_id, sheet_code, category_code, yyyymm, series)
                    DO UPDATE SET value = excluded.value
                """), {"rid": run_id, "sid": scenario_id, "sheet": sheet, "cat": cat, "yyyymm": yyyymm, "series": series, "val": float(val)})
                inserted += 1

        db.execute(text("UPDATE engine_runs SET finished_at=CURRENT_TIMESTAMP WHERE id=:rid"), {"rid": run_id})

        # Eski ‘sheet suffix’ kalıntılarını aynı run için temizlemek isterseniz:
        db.execute(text("""
            DELETE FROM engine_facts_monthly
            WHERE run_id=:rid
              AND sheet_code IN ('oA.Finance-AN.COGS','oA.Finance-AN.GP','oQ.Finance-AN.COGS','oQ.Finance-AN.GP')
        """), {"rid": run_id})

    return inserted, run_id

@router.post("/scenarios/{scenario_id}/run-engine", response_model=RunEngineResult)
def run_engine(scenario_id: int = Path(..., ge=1), req: RunEngineRequest = ..., db: Session = Depends(get_db)):
    """
    Engine’i çalıştırır. persist=true ise V2 kontratına yazar: 
    (run_id, scenario_id, sheet_code, category_code, yyyymm, series, value)
    """
    # ... burada sizin mevcut hesaplama bloklarınız (rev/cogs/gp, services vs.)
    # ... 'generated: List[SheetPayload]' üretir (c.Sales-*, oA.*, oQ.*)
    # (Hesaplama kısmını sizdekiyle aynı bıraktım.)

    # ↓ aşağısı aynı kalıp
    persisted_rows = 0
    run_id: Optional[int] = None
    if req.persist and generated:
        try:
            persisted_rows, run_id = _persist_results(db, scenario_id, req, generated)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Persist failed: {e}")

    # R&F kilit bilgisi vb. sizdeki gibi döndürülür
    return RunEngineResult(
        scenario_id=scenario_id,
        generated=generated if req.include_facts else [],
        locks=EngineLocks(rise_and_fall=True),  # örnek; sizdeki hesapla
        notes=("Rise & Fall is locked ON due to existing policy."),
        persisted=bool(req.persist and persisted_rows > 0),
        persisted_rows=int(persisted_rows),
        run_id=run_id,
    )
