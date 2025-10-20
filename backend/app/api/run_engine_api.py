# Path: backend/app/api/run_engine_api.py
from __future__ import annotations

from typing import List, Dict, Optional, Any, Tuple
from datetime import date
import json
import re
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

# Project deps (absolute import to avoid relative-import issues in Swagger schema build)
from app.api.deps import get_db  # type: ignore

router = APIRouter(prefix="/api", tags=["engine"])

class CategoryCode(str, Enum):
    AN = "AN"
    EM = "EM"
    IE = "IE"
    Services = "Services"

class EngineCategory(BaseModel):
    code: CategoryCode
    enabled: bool = True

class EngineOptions(BaseModel):
    rise_and_fall: Optional[bool] = None  # None = auto (locked by policy if present)
    fx_apply: bool = True
    tax_apply: bool = True
    rebates_apply: bool = True
    twc_apply: bool = True

class RunEngineRequest(BaseModel):
    categories: List[EngineCategory]
    options: EngineOptions = Field(default_factory=EngineOptions)
    persist: bool = False              # persist to engine_facts_monthly
    include_facts: bool = False        # preview için üretilen serileri de döndür

class EngineLocks(BaseModel):
    rise_and_fall: bool  # true means locked ON (cannot be turned off)

class SheetPayload(BaseModel):
    name: str            # ör: "oA.Finance-AN.Revenue" veya "oQ.Finance-AN.GP"
    months: List[str]    # ["YYYY-MM", ...]
    values: List[float]  # aynı uzunlukta

class RunEngineResult(BaseModel):
    scenario_id: int
    generated: List[SheetPayload]
    locks: EngineLocks
    notes: Optional[str] = None
    persisted: bool = False
    persisted_rows: int = 0
    run_id: Optional[int] = None


# --------------------- Yardımcılar ---------------------

def _fetch_scenario(db: Session, scenario_id: int):
    row = db.execute(text("""
        SELECT id, months, start_date
        FROM scenarios
        WHERE id = :sid
    """), {"sid": scenario_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Scenario not found")
    y, m, d = map(int, str(row["start_date"]).split("-"))
    return {"id": int(row["id"]), "months": int(row["months"]), "start_date": date(y, m, d)}

def _ym_series(start: date, count: int) -> List[str]:
    out = []
    y, m = start.year, start.month
    for _ in range(count):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out

def _has_rise_fall_policy(db: Session, scenario_id: int, selected_categories: Optional[List[str]] = None) -> bool:
    cats = []
    for c in (selected_categories or []):
        if not c:
            continue
        cats.append(str(c).strip().lower())
    tokens = ["all"] + cats if cats else ["all", "an", "em", "ie", "services", "capex"]
    ph = ", ".join(f":s{i}" for i in range(len(tokens)))
    params = {"sid": scenario_id, **{f"s{i}": tok for i, tok in enumerate(tokens)}}
    row = db.execute(text(f"""
        SELECT 1
        FROM scenario_escalation_policies
        WHERE scenario_id = :sid
          AND COALESCE(is_active,1) = 1
          AND lower(scope) IN ({ph})
        LIMIT 1
    """), params).first()
    return bool(row)

def _apply_dso_to_cash(accrual: List[float], dso_days: Optional[int]) -> List[float]:
    if not dso_days or dso_days <= 0:
        return accrual[:]
    lag = max(0, round(dso_days / 30))
    out = [0.0] * len(accrual)
    for i, v in enumerate(accrual):
        j = i + lag
        if j < len(out):
            out[j] += v
    return out


# --------------------- Data fetchers ---------------------

def _schedule_from_boq(db: Session, scenario_id: int, section: str, months: int, start: date) -> Tuple[List[float], List[float]]:
    """Returns (revenue_accrual, cogs_accrual) series from BOQ (qty*price, qty*unit_cogs)."""
    rev = [0.0] * months
    cogs = [0.0] * months
    rows = db.execute(text("""
        SELECT quantity, unit_price, unit_cogs, frequency, start_year, start_month, months as row_months
        FROM scenario_boq_items
        WHERE scenario_id = :sid AND (section = :section OR :section = 'ALL')
          AND (is_active = 1)
    """), {"sid": scenario_id, "section": section}).mappings().all()
    for r in rows:
        qty = float(r["quantity"] or 0.0)
        price = float(r["unit_price"] or 0.0)
        ucogs = float(r["unit_cogs"] or 0.0)
        rev_total = qty * price
        cogs_total = qty * ucogs
        freq = (r["frequency"] or "monthly").lower()
        sy = int(r["start_year"]) if r["start_year"] is not None else start.year
        sm = int(r["start_month"]) if r["start_month"] is not None else start.month
        rm = int(r["row_months"]) if r["row_months"] is not None else months
        offset = (sy - start.year) * 12 + (sm - start.month)
        if offset < 0: offset = 0
        if offset >= months: continue
        if freq == "once":
            rev[offset] += rev_total
            cogs[offset] += cogs_total
        elif freq == "monthly":
            span = min(months - offset, max(1, rm))
            for i in range(span):
                rev[offset + i] += rev_total
                cogs[offset + i] += cogs_total
        else:
            span = min(months - offset, max(1, rm))
            per_rev = rev_total / span if span > 0 else 0.0
            per_cogs = cogs_total / span if span > 0 else 0.0
            for i in range(span):
                rev[offset + i] += per_rev
                cogs[offset + i] += per_cogs
    return rev, cogs


def _schedule_services_expense_raw(db: Session, scenario_id: int, months: int, start: date) -> Tuple[List[float], List[Optional[str]]]:
    sched = [0.0] * months
    cur_series: List[Optional[str]] = [None] * months
    rows = db.execute(text("""
        SELECT quantity, unit_cost, currency, start_year, start_month, duration_months
        FROM scenario_services
        WHERE scenario_id = :sid AND is_active = 1
    """), {"sid": scenario_id}).mappings().all()
    for r in rows:
        qty = float(r["quantity"] or 0.0)
        unit_cost = float(r["unit_cost"] or 0.0)
        currency = r["currency"]
        total = qty * unit_cost
        sy = int(r["start_year"]) if r["start_year"] is not None else start.year
        sm = int(r["start_month"]) if r["start_month"] is not None else start.month
        dur = int(r["duration_months"]) if r["duration_months"] is not None else months
        offset = (sy - start.year) * 12 + (sm - start.month)
        if offset < 0: offset = 0
        span = min(months - offset, max(1, dur))
        for i in range(span):
            idx = offset + i
            sched[idx] += total
            cur_series[idx] = currency or cur_series[idx]
    return sched, cur_series


def _fx_rate_for_month(db: Session, scenario_id: int, currency: str, y: int, m: int) -> Optional[float]:
    row = db.execute(text("""
        SELECT rate_to_base
        FROM scenario_fx_rates
        WHERE scenario_id = :sid AND currency = :cur
          AND (start_year IS NULL OR (start_year*100 + start_month) <= (:y*100 + :m))
          AND (end_year   IS NULL OR (end_year*100   + end_month)   >= (:y*100 + :m))
        ORDER BY COALESCE(start_year, 0) DESC, COALESCE(start_month, 0) DESC
        LIMIT 1
    """), {"sid": scenario_id, "cur": currency, "y": y, "m": m}).mappings().first()
    return float(row["rate_to_base"]) if row and row["rate_to_base"] is not None else None


def _apply_fx_on_services(db: Session, scenario_id: int, start: date, series: List[float], currencies: List[Optional[str]]) -> List[float]:
    out = series[:]
    for i, (val, cur) in enumerate(zip(series, currencies)):
        if not cur or not val:
            continue
        y = start.year + (start.month - 1 + i) // 12
        m = (start.month - 1 + i) % 12 + 1
        rate = _fx_rate_for_month(db, scenario_id, cur, y, m)
        if rate:  # convert to base
            out[i] = val * rate
    return out


# --------------------- Rise & Fall ---------------------

def _load_index_series(db: Session, code: str) -> Dict[Tuple[int,int], float]:
    pts = db.execute(text("""
        SELECT p.year, p.month, p.value
        FROM index_series s
        JOIN index_points p ON p.series_id = s.id
        WHERE s.code = :code
    """), {"code": code}).mappings().all()
    d: Dict[Tuple[int,int], float] = {}
    for r in pts:
        y = int(r["year"]); m = int(r["month"]); v = r["value"]
        if v is not None:
            d[(y, m)] = float(v)
    return d

def _build_rf_multiplier(db: Session, scenario_id: int, start: date, months: int, category: CategoryCode) -> List[float]:
    mult = [1.0] * months
    rows = db.execute(text("""
        SELECT scope, method, fixed_pct, index_code, base_year, base_month, step_per_month, freq, is_active
        FROM scenario_escalation_policies
        WHERE scenario_id = :sid
    """), {"sid": scenario_id}).mappings().all()
    if not rows:
        return mult
    for r in rows:
        scope = (r["scope"] or "ALL").upper()
        if scope not in ("ALL","AN","EM","IE","SERVICES"):
            continue
        if scope != "ALL" and (
            (scope == "SERVICES" and category != CategoryCode.Services) or
            (scope != "SERVICES" and scope != category.value)
        ):
            continue
        method = (r.get("method") or "fixed").lower()
        base_y = int(r.get("base_year") or start.year)
        base_m = int(r.get("base_month") or start.month)
        step_per_month = int(r.get("step_per_month") or 1)
        if method == "fixed":
            annual_pct = float(r.get("fixed_pct") or 0.0) / 100.0
            monthly_rate = annual_pct / 12.0
            f = 1.0
            for i in range(months):
                mult[i] *= f
                if ((i+1) % step_per_month) == 0:
                    f *= (1.0 + monthly_rate)
        elif method == "index":
            code = r.get("index_code")
            if not code:
                continue
            series = _load_index_series(db, code)
            base_val = series.get((base_y, base_m))
            if not base_val or base_val == 0:
                continue
            for i in range(months):
                y = start.year + (start.month - 1 + i) // 12
                m = (start.month - 1 + i) % 12 + 1
                cur = series.get((y, m))
                if cur:
                    mult[i] *= (cur / base_val)
    return mult


# --------------------- Rebates ---------------------

def _load_rebates(db: Session, scenario_id: int) -> Dict[str, Any]:
    head = db.execute(text("""
        SELECT id, scope, kind, basis, pay_month_lag
        FROM scenario_rebates
        WHERE scenario_id = :sid
    """), {"sid": scenario_id}).mappings().all()
    tiers = db.execute(text("""
        SELECT rebate_id, min_value, max_value, percent
        FROM scenario_rebate_tiers
        ORDER BY rebate_id, COALESCE(sort_order, 0), COALESCE(min_value, 0)
    """)).mappings().all()
    lumps = db.execute(text("""
        SELECT rebate_id, year, month, amount
        FROM scenario_rebate_lumps
    """)).mappings().all()
    tiers_map: Dict[int, List[Dict[str, Any]]] = {}
    for t in tiers:
        rid = int(t["rebate_id"])
        tiers_map.setdefault(rid, []).append({"min": float(t["min_value"] or 0), "max": float(t["max_value"] or 1e18), "pct": float(t["percent"] or 0)})
    lumps_map: Dict[int, List[Dict[str, Any]]] = {}
    for l in lumps:
        rid = int(l["rebate_id"])
        lumps_map.setdefault(rid, []).append({"y": int(l["year"]), "m": int(l["month"]), "amt": float(l["amount"] or 0)})
    return {"head": head, "tiers": tiers_map, "lumps": lumps_map}

def _apply_rebates(accrual_rev: List[float], start: date, months: int, rb: Dict[str, Any]) -> Tuple[List[float], List[float]]:
    accrual_net = accrual_rev[:]
    cash_out = [0.0] * months
    for h in rb["head"]:
        basis = (h["basis"] or "revenue").lower()
        if basis != "revenue":
            continue
        kind = (h["kind"] or "percent").lower()
        lag = int(h["pay_month_lag"] or 0)
        rid = int(h["id"])
        if kind in ("percent", "tier_percent"):
            for i, v in enumerate(accrual_rev):
                pct = 0.0
                if kind == "tier_percent":
                    tiers = rb["tiers"].get(rid)
                    if tiers:
                        for t in tiers:
                            if t["min"] <= v < t["max"]:
                                pct = t["pct"]
                                break
                if pct:
                    rebate_val = v * (pct / 100.0)
                    accrual_net[i] -= rebate_val
                    j = i + lag
                    if 0 <= j < months:
                        cash_out[j] -= rebate_val
        elif kind == "lump_sum":
            lumps = rb["lumps"].get(rid)
            if lumps:
                for L in lumps:
                    idx = (L["y"] - start.year) * 12 + (L["m"] - start.month)
                    if 0 <= idx < months:
                        accrual_net[idx] -= L["amt"]
                        j = idx + lag
                        if 0 <= j < months:
                            cash_out[j] -= L["amt"]
    return accrual_net, cash_out


# --------------------- Vergi (services) ---------------------

def _apply_tax_on_services(db: Session, scenario_id: int, start: date, base_series: List[float]) -> List[float]:
    rows = db.execute(text("""
        SELECT rate_pct, is_inclusive, start_year, start_month, end_year, end_month, applies_to
        FROM scenario_tax_rules
        WHERE scenario_id = :sid
    """), {"sid": scenario_id}).mappings().all()
    if not rows:
        return base_series
    add = [0.0] * len(base_series)
    for i in range(len(base_series)):
        y = start.year + (start.month - 1 + i) // 12
        m = (start.month - 1 + i) % 12 + 1
        for r in rows:
            applies_to = (r.get("applies_to") or "").lower()
            if applies_to and applies_to != "services":
                continue
            sy = r.get("start_year"); sm = r.get("start_month"); ey = r.get("end_year"); em = r.get("end_month")
            if sy and sm and (y*100+m) < (sy*100+sm): continue
            if ey and em and (y*100+m) > (ey*100+em): continue
            if int(r.get("is_inclusive") or 0) == 1:
                continue
            rate = float(r.get("rate_pct") or 0.0) / 100.0
            add[i] += base_series[i] * rate
    return [base_series[i] + add[i] for i in range(len(base_series))]


# --------------------- Persist yardımcıları ---------------------

_SERIES_SUFFIX_MAP = {
    ".REVENUE": "revenue",
    ".COGS": "cogs",
    ".GP": "gp",
}

_SUFFIX_RE = re.compile(r"\.(REVENUE|COGS|GP)$", flags=re.IGNORECASE)

def _split_name_to_sheet_and_series(name: str) -> Tuple[str, Optional[str]]:
    """
    'oA.Finance-AN.Revenue'  -> ('oA.Finance-AN', 'revenue')
    'oQ.Finance-AN.COGS'     -> ('oQ.Finance-AN', 'cogs')
    'c.Sales-AN'             -> ('c.Sales-AN', None)     # persist etmemeyi tercih edebiliriz
    """
    m = _SUFFIX_RE.search(name)
    if not m:
        return name, None
    suffix = m.group(0).upper()
    series = _SERIES_SUFFIX_MAP.get(suffix, None)
    sheet = name[: -len(suffix)]
    return sheet, series

def _parse_category_from_name(name: str) -> str:
    """Extract category token after first '-' and before optional '.'"""
    if "-" not in name:
        return "ALL"
    tail = name.split("-", 1)[1]
    return tail.split(".", 1)[0]

def _ensure_schema(db: Session) -> None:
    """
    Tabloları ve gerekli indexleri (series dahil) güvenceye alır.
    Eski unique index varsa kalsın; yeni index (series dahil) eklenir.
    """
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_sheets (
            code TEXT PRIMARY KEY,
            name TEXT,
            sort_order INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_categories (
            code TEXT PRIMARY KEY,
            name TEXT,
            sort_order INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS engine_runs (
            id INTEGER PRIMARY KEY,
            scenario_id INTEGER,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            options_json TEXT
        )
    """))
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
        )
    """))
    # series sütunu yoksa ekle
    cols = db.execute(text("PRAGMA table_info('engine_facts_monthly')")).fetchall()
    colnames = { (c[1] if isinstance(c, (list, tuple)) else c["name"]) for c in cols }
    if "series" not in { str(n) for n in colnames }:
        db.execute(text("ALTER TABLE engine_facts_monthly ADD COLUMN series TEXT"))

    # yeni unique index
    db.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_efm_run_sheet_cat_yyyymm_series
        ON engine_facts_monthly(run_id, sheet_code, category_code, yyyymm, series)
    """))

    # küçük seed
    for i, s in enumerate(("c.Sales", "oA.Finance", "oQ.Finance")):
        db.execute(text("""
            INSERT INTO engine_sheets (code, name, sort_order)
            SELECT :c, :n, :o
            WHERE NOT EXISTS (SELECT 1 FROM engine_sheets WHERE code=:c)
        """), {"c": s, "n": s, "o": i})
    for i, c in enumerate(("AN","EM","IE","Services","Spare1","Spare2")):
        db.execute(text("""
            INSERT INTO engine_categories (code, name, sort_order)
            SELECT :c, :n, :o
            WHERE NOT EXISTS (SELECT 1 FROM engine_categories WHERE code=:c)
        """), {"c": c, "n": c, "o": i})

def _persist_results(db: Session, scenario_id: int, req: RunEngineRequest, generated: List[SheetPayload]) -> Tuple[int, Optional[int]]:
    """
    Insert a run row and facts; returns (rows_inserted, run_id).
    Artık persist ederken 'sheet_code' = 'oA.Finance-AN' / 'oQ.Finance-AN' ve
    'series' = revenue|cogs|gp olacak.
    """
    _ensure_schema(db)

    # Insert run
    opts = {"options": req.options.dict(), "categories": [c.dict() for c in req.categories]}
    db.execute(text("""
        INSERT INTO engine_runs (scenario_id, options_json)
        VALUES (:sid, :opts)
    """), {"sid": scenario_id, "opts": json.dumps(opts)})
    run_id = db.execute(text("SELECT id FROM engine_runs ORDER BY id DESC LIMIT 1")).scalar()

    inserted = 0

    for s in generated:
        # sheet/series ayrıştır
        base_sheet, series = _split_name_to_sheet_and_series(s.name)
        if series is None:
            # c.Sales-* gibi serileri DB'ye yazmıyoruz (isteğe göre yazılabilir)
            continue

        category_code = _parse_category_from_name(base_sheet)
        months = s.months
        vals = s.values

        for i in range(len(vals)):
            ym = months[i]  # "YYYY-MM"
            y, m = ym.split("-")
            yyyymm = int(y) * 100 + int(m)
            db.execute(text("""
                INSERT INTO engine_facts_monthly
                    (run_id, scenario_id, sheet_code, category_code, yyyymm, series, value)
                VALUES
                    (:rid, :sid, :sheet, :cat, :yyyymm, :series, :val)
                ON CONFLICT(run_id, sheet_code, category_code, yyyymm, series)
                DO UPDATE SET value = excluded.value
            """), {
                "rid": run_id,
                "sid": scenario_id,
                "sheet": base_sheet,
                "cat": category_code,
                "yyyymm": yyyymm,
                "series": series,
                "val": float(vals[i]),
            })
            inserted += 1

    # Close run
    db.execute(text("UPDATE engine_runs SET finished_at = CURRENT_TIMESTAMP WHERE id = :rid"), {"rid": run_id})

    # Eski dönemde kalmış '...COGS' / '...GP' sheet adları varsa temizlemek istersen:
    db.execute(text("""
        DELETE FROM engine_facts_monthly
        WHERE sheet_code IN ('oA.Finance-AN.COGS','oA.Finance-AN.GP',
                             'oQ.Finance-AN.COGS','oQ.Finance-AN.GP')
          AND run_id = :rid
    """), {"rid": run_id})

    return inserted, int(run_id) if run_id is not None else None


# --------------------- Endpoint ---------------------

@router.post("/scenarios/{scenario_id}/run-engine", response_model=RunEngineResult)
def run_engine(
    scenario_id: int = Path(..., ge=1),
    req: RunEngineRequest = ...,
    db: Session = Depends(get_db),
):
    sc = _fetch_scenario(db, scenario_id)
    months = sc["months"]
    months_axis = _ym_series(sc["start_date"], months)

    enabled_codes = [c.code for c in req.categories if c.enabled]

    # R&F lock (scope-aware)
    locks = EngineLocks(rise_and_fall=_has_rise_fall_policy(db, scenario_id, [e.value for e in enabled_codes]))

    # TWC (DSO)
    twc = db.execute(text("""
        SELECT dso_days FROM scenario_twc WHERE scenario_id = :sid LIMIT 1
    """), {"sid": scenario_id}).mappings().first()
    dso_days = int(twc["dso_days"]) if twc and twc["dso_days"] is not None else 0

    generated: List[SheetPayload] = []

    for code in enabled_codes:
        if code in (CategoryCode.AN, CategoryCode.EM, CategoryCode.IE):
            rev, cogs = _schedule_from_boq(db, scenario_id, code.value, months, sc["start_date"])

            # Rise & Fall (if enabled or locked)
            if req.options.rise_and_fall or locks.rise_and_fall:
                rf_mult = _build_rf_multiplier(db, scenario_id, sc["start_date"], months, code)
                rev = [rev[i] * rf_mult[i] for i in range(months)]
                cogs = [cogs[i] * rf_mult[i] for i in range(months)]

            # Rebates (only on revenue accrual)
            if req.options.rebates_apply:
                rev_net, rebates_cash = _apply_rebates(rev, sc["start_date"], months, _load_rebates(db, scenario_id))
            else:
                rev_net, rebates_cash = rev[:], [0.0] * months

            gp = [rev_net[i] - cogs[i] for i in range(months)]
            cash_in = _apply_dso_to_cash(rev_net, dso_days if req.options.twc_apply else 0)

            def R(lst): return [round(x, 2) for x in lst]

            # c.Sales (legacy index / görünüm)
            generated.append(SheetPayload(name=f"c.Sales-{code.value}", months=months_axis, values=R(rev_net)))

            # oA – accrual facts split
            oa_prefix = f"oA.Finance-{code.value}"
            oq_prefix = f"oQ.Finance-{code.value}"
            part = [
                SheetPayload(name=f"{oa_prefix}.Revenue", months=months_axis, values=R(rev_net)),
                SheetPayload(name=f"{oa_prefix}.COGS",    months=months_axis, values=R(cogs)),
                SheetPayload(name=f"{oa_prefix}.GP",      months=months_axis, values=R(gp)),
            ]
            generated.extend(part)

            # oQ – cash timing (GP = cash_in - cogs)
            generated.append(SheetPayload(name=f"{oq_prefix}.Revenue", months=months_axis, values=R(cash_in)))
            generated.append(SheetPayload(name=f"{oq_prefix}.COGS",    months=months_axis, values=R(cogs)))
            generated.append(SheetPayload(name=f"{oq_prefix}.GP",      months=months_axis, values=R([cash_in[i]-cogs[i] for i in range(months)])))

        elif code == CategoryCode.Services:
            expense_raw, svc_curs = _schedule_services_expense_raw(db, scenario_id, months, sc["start_date"])

            expense = expense_raw[:]
            if req.options.fx_apply:
                expense = _apply_fx_on_services(db, scenario_id, sc["start_date"], expense, svc_curs)

            if req.options.rise_and_fall or locks.rise_and_fall:
                rf_mult = _build_rf_multiplier(db, scenario_id, sc["start_date"], months, code)
                expense = [expense[i] * rf_mult[i] for i in range(months)]

            if req.options.tax_apply:
                expense = _apply_tax_on_services(db, scenario_id, sc["start_date"], expense)

            zeros = [0.0] * months
            def R(lst): return [round(x, 2) for x in lst]

            # legacy görünüm
            generated.append(SheetPayload(name="c.Sales-Services", months=months_axis, values=R(zeros)))

            # accrual & cash (Revenue=0, COGS=expense, GP=-expense)
            oa_prefix = "oA.Finance-Services"
            oq_prefix = "oQ.Finance-Services"
            generated.append(SheetPayload(name=f"{oa_prefix}.Revenue", months=months_axis, values=R(zeros)))
            generated.append(SheetPayload(name=f"{oa_prefix}.COGS",    months=months_axis, values=R([-x for x in expense])))
            generated.append(SheetPayload(name=f"{oa_prefix}.GP",      months=months_axis, values=R([-x for x in expense])))

            generated.append(SheetPayload(name=f"{oq_prefix}.Revenue", months=months_axis, values=R(zeros)))
            generated.append(SheetPayload(name=f"{oq_prefix}.COGS",    months=months_axis, values=R([-x for x in expense])))
            generated.append(SheetPayload(name=f"{oq_prefix}.GP",      months=months_axis, values=R([-x for x in expense])))

    persisted_rows = 0
    run_id: Optional[int] = None
    if req.persist and generated:
        try:
            persisted_rows, run_id = _persist_results(db, scenario_id, req, generated)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Persist failed: {e}")

    return RunEngineResult(
        scenario_id=sc["id"],
        generated=generated,
        locks=locks,
        notes=("Rise & Fall is locked ON due to existing policy." if locks.rise_and_fall else None),
        persisted=bool(req.persist and persisted_rows > 0),
        persisted_rows=int(persisted_rows),
        run_id=run_id,
    )
