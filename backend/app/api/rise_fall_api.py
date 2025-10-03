from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple, Dict
import sqlite3
import re

from fastapi import APIRouter, HTTPException, Path as FPath, Body
from pydantic import BaseModel, Field, conint, confloat, root_validator, validator

# ------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------
router = APIRouter(prefix="/business-cases/scenarios", tags=["rise-fall"])

DB_PATH = Path(__file__).resolve().parents[2] / "app.db"

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
_YM_RE = re.compile(r"(?P<y>\d{4})[-/](?P<m>\d{1,2})")

_MONTHS_TR = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
    "oca": 1, "şub": 2, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7,
    "ağu": 8, "agu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
}
_MONTHS_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,
    "september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12
}

def _parse_ym_any(s: str) -> Optional[Tuple[int, int]]:
    if not s:
        return None
    s = str(s).strip()
    m = _YM_RE.search(s)
    if m:
        y = int(m.group("y")); mo = int(m.group("m"))
        if 1 <= mo <= 12: 
            return (y, mo)
    if s.isdigit() and len(s) in (5, 6):
        try:
            val = int(s)
            y, mo = divmod(val, 100)
            if 1 <= mo <= 12: 
                return (int(y), int(mo))
        except Exception:
            pass
    s_low = s.lower()
    year_match = re.search(r"(20\d{2}|19\d{2})", s_low)
    if year_match:
        y = int(year_match.group(0))
        for name_map in (_MONTHS_TR, _MONTHS_EN):
            for nm, mo in name_map.items():
                if nm in s_low:
                    return (y, mo)
    return None

def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _to_int(v):
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None

def _add_months(y: int, m: int, delta: int) -> Tuple[int, int]:
    z = (y * 12 + (m - 1)) + delta
    ny = z // 12
    nm = (z % 12) + 1
    return ny, nm

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def _init_db():
    with _conn() as cx:
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS rise_fall_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id INTEGER NOT NULL,
                scope TEXT NOT NULL,                 -- 'service' | 'boq'
                scope_id INTEGER NOT NULL,
                frequency TEXT NOT NULL,
                compounding TEXT NOT NULL,
                preview_months INTEGER NOT NULL,
                start_year INTEGER NOT NULL,
                start_month INTEGER NOT NULL,
                base_price REAL
            );
        """
        )
        cx.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_rfp_unique
            ON rise_fall_policy (scenario_id, scope, scope_id);
        """
        )
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS rise_fall_component (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                policy_id INTEGER NOT NULL,
                index_series_id INTEGER NOT NULL,
                weight_pct REAL NOT NULL,
                base_ref_year INTEGER NOT NULL,
                base_ref_month INTEGER NOT NULL,
                lag_m INTEGER NOT NULL DEFAULT 0,
                factor REAL NOT NULL DEFAULT 1.0,
                cap_pct REAL,
                floor_pct REAL,
                sort_order INTEGER,
                FOREIGN KEY(policy_id) REFERENCES rise_fall_policy(id) ON DELETE CASCADE
            );
        """
        )

_init_db()

# ------------------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------------------
class RFComponentIn(BaseModel):
    index_series_id: int = Field(..., description="Global index series id")
    weight_pct: confloat(ge=0, le=100) = 100
    base_ref_year: conint(ge=1900, le=3000)
    base_ref_month: conint(ge=1, le=12)
    lag_m: conint(ge=0, le=120) = 0
    factor: confloat(ge=0) = 1.0
    cap_pct: Optional[confloat(ge=0)] = None
    floor_pct: Optional[confloat(ge=0)] = None
    sort_order: Optional[int] = None

    @root_validator(pre=True)
    def _coerce_alt_keys(cls, values):
        if values.get("index_series_id") is None:
            alt = values.get("index_series") or values.get("series_id")
            values["index_series_id"] = _to_int(alt) if alt is not None else None

        if values.get("weight_pct") is None and values.get("weight") is not None:
            values["weight_pct"] = _to_float(values.get("weight"))

        if values.get("lag_m") is None and values.get("lag") is not None:
            values["lag_m"] = _to_int(values.get("lag"))

        if values.get("cap_pct") is None and values.get("cap") is not None:
            values["cap_pct"] = _to_float(values.get("cap"))

        if values.get("floor_pct") is None and values.get("floor") is not None:
            values["floor_pct"] = _to_float(values.get("floor"))

        by = values.get("base_ref_year")
        bm = values.get("base_ref_month")
        if by is None or bm is None:
            alt = values.get("base_ref") or values.get("base_ref_ym") or values.get("base") or values.get("baseRef")
            if isinstance(alt, str):
                ym = _parse_ym_any(alt)
                if ym:
                    values["base_ref_year"], values["base_ref_month"] = ym
            elif isinstance(alt, int):
                y, m = divmod(alt, 100)
                values["base_ref_year"], values["base_ref_month"] = int(y), int(m)
            elif isinstance(alt, (list, tuple)) and len(alt) >= 2:
                values["base_ref_year"], values["base_ref_month"] = int(alt[0]), int(alt[1])

        for k in ("weight_pct", "lag_m", "factor", "cap_pct", "floor_pct", "sort_order"):
            if k in values:
                if k in ("lag_m", "sort_order"):
                    v = _to_int(values[k])
                    if v is not None:
                        values[k] = v
                    else:
                        values.pop(k, None)
                else:
                    v = _to_float(values[k])
                    if v is not None:
                        values[k] = v
                    else:
                        values.pop(k, None)
        return values


class RiseFallPolicyIn(BaseModel):
    frequency: str = Field(..., description="annual | quarterly | monthly")
    compounding: str = Field(..., description="simple | compound")
    preview_months: conint(gt=0, le=240) = 36
    start_year: conint(ge=1900, le=3000)
    start_month: conint(ge=1, le=12)
    base_price: Optional[float] = None
    components: List[RFComponentIn] = Field(default_factory=list)

    @root_validator(pre=True)
    def _coerce_start_fields(cls, values):
        if "preview_months" not in values and "previewMonths" in values:
            pm = _to_int(values.get("previewMonths"))
            if pm:
                values["preview_months"] = pm
        if "base_price" not in values and "basePrice" in values:
            bp = _to_float(values.get("basePrice"))
            if bp is not None:
                values["base_price"] = bp

        sy = values.get("start_year"); sm = values.get("start_month")
        if sy is None or sm is None:
            alt = (values.get("start") or values.get("start_ym") or values.get("start_date")
                   or values.get("startYYYYMM") or values.get("start_yyyymm") or values.get("startYm"))
            if isinstance(alt, str):
                ym = _parse_ym_any(alt)
                if ym:
                    values["start_year"], values["start_month"] = ym
            elif isinstance(alt, int):
                y, m = divmod(alt, 100)
                values["start_year"], values["start_month"] = int(y), int(m)
            elif isinstance(alt, (list, tuple)) and len(alt) >= 2:
                values["start_year"], values["start_month"] = int(alt[0]), int(alt[1])
        return values

    @validator("frequency")
    def _v_freq(cls, v: str) -> str:
        v = v.lower()
        allowed = {"annual", "quarterly", "monthly"}
        if v not in allowed:
            raise ValueError(f"frequency must be one of {sorted(allowed)}")
        return v

    @validator("compounding")
    def _v_cmp(cls, v: str) -> str:
        v = v.lower()
        allowed = {"simple", "compound"}
        if v not in allowed:
            raise ValueError(f"compounding must be one of {sorted(allowed)}")
        return v


class RiseFallPolicyPatch(BaseModel):
    frequency: Optional[str] = None
    compounding: Optional[str] = None
    preview_months: Optional[conint(gt=0, le=240)] = None
    start_year: Optional[conint(ge=1900, le=3000)] = None
    start_month: Optional[conint(ge=1, le=12)] = None
    base_price: Optional[float] = None
    components: Optional[List[RFComponentIn]] = None

    @root_validator(pre=True)
    def _pre(cls, values):
        if "preview_months" not in values and "previewMonths" in values:
            pm = _to_int(values.get("previewMonths"))
            if pm:
                values["preview_months"] = pm
        if "base_price" not in values and "basePrice" in values:
            bp = _to_float(values.get("basePrice"))
            if bp is not None:
                values["base_price"] = bp

        sy = values.get("start_year"); sm = values.get("start_month")
        if (sy is None or sm is None) and any(k in values for k in ("start","start_ym","start_date","startYYYYMM","start_yyyymm","startYm")):
            alt = (values.get("start") or values.get("start_ym") or values.get("start_date")
                   or values.get("startYYYYMM") or values.get("start_yyyymm") or values.get("startYm"))
            if isinstance(alt, str):
                ym = _parse_ym_any(alt)
                if ym:
                    values["start_year"], values["start_month"] = ym
            elif isinstance(alt, int):
                y, m = divmod(alt, 100)
                values["start_year"], values["start_month"] = int(y), int(m)
            elif isinstance(alt, (list, tuple)) and len(alt) >= 2:
                values["start_year"], values["start_month"] = int(alt[0]), int(alt[1])
        return values

    @validator("frequency")
    def _vf(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower()
        if v not in {"annual","quarterly","monthly"}:
            raise ValueError("invalid frequency")
        return v

    @validator("compounding")
    def _vc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower()
        if v not in {"simple","compound"}:
            raise ValueError("invalid compounding")
        return v


class RFComponentOut(RFComponentIn):
    id: int


class RiseFallPolicyOut(BaseModel):
    id: int
    scenario_id: int
    scope: str  # 'service' | 'boq'
    scope_id: int
    frequency: str
    compounding: str
    preview_months: int
    start_year: int
    start_month: int
    base_price: Optional[float]
    components: List[RFComponentOut]

# ---------- Preview payloads ----------
class PreviewIn(BaseModel):
    months: Optional[conint(gt=0, le=240)] = None
    policy: Optional[RiseFallPolicyIn] = None

class ComponentSeriesOut(BaseModel):
    index_series_id: int
    values: List[float]  # normalized to base (after lag & factor, cap/floor applied)

class PreviewOut(BaseModel):
    start_year: int
    start_month: int
    months: int
    composite: List[float]
    price: List[float]
    series: List[ComponentSeriesOut] = []  # for "Visualize Series"

# ------------------------------------------------------------------------------
# Core DB ops
# ------------------------------------------------------------------------------
def _row_to_policy_out(row: sqlite3.Row, comps: List[sqlite3.Row]) -> RiseFallPolicyOut:
    return RiseFallPolicyOut(
        id=row["id"],
        scenario_id=row["scenario_id"],
        scope=row["scope"],
        scope_id=row["scope_id"],
        frequency=row["frequency"],
        compounding=row["compounding"],
        preview_months=row["preview_months"],
        start_year=row["start_year"],
        start_month=row["start_month"],
        base_price=row["base_price"],
        components=[
            RFComponentOut(
                id=c["id"],
                index_series_id=c["index_series_id"],
                weight_pct=c["weight_pct"],
                base_ref_year=c["base_ref_year"],
                base_ref_month=c["base_ref_month"],
                lag_m=c["lag_m"],
                factor=c["factor"],
                cap_pct=c["cap_pct"],
                floor_pct=c["floor_pct"],
                sort_order=c["sort_order"],
            )
            for c in comps
        ],
    )

def _fetch_policy(scope: str, scenario_id: int, scope_id: int):
    with _conn() as cx:
        pol = cx.execute(
            "SELECT * FROM rise_fall_policy WHERE scenario_id=? AND scope=? AND scope_id=?",
            (scenario_id, scope, scope_id),
        ).fetchone()
        if not pol:
            return None, []
        comps = cx.execute(
            "SELECT * FROM rise_fall_component WHERE policy_id=? ORDER BY COALESCE(sort_order,0), id",
            (pol["id"],),
        ).fetchall()
        return pol, comps

def _fetch_policy_rows(scope: str, scenario_id: int) -> List[sqlite3.Row]:
    with _conn() as cx:
        return cx.execute(
            "SELECT * FROM rise_fall_policy WHERE scenario_id=? AND scope=? ORDER BY id",
            (scenario_id, scope),
        ).fetchall()

def _upsert_policy_and_replace_components(
    *, scenario_id: int, scope: str, scope_id: int, payload: RiseFallPolicyIn
) -> RiseFallPolicyOut:
    _init_db()
    with _conn() as cx:
        row = cx.execute(
            "SELECT id FROM rise_fall_policy WHERE scenario_id=? AND scope=? AND scope_id=?",
            (scenario_id, scope, scope_id),
        ).fetchone()

        if row is None:
            cx.execute(
                """
                INSERT INTO rise_fall_policy
                (scenario_id, scope, scope_id, frequency, compounding, preview_months, start_year, start_month, base_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    scenario_id, scope, scope_id,
                    payload.frequency, payload.compounding, int(payload.preview_months),
                    int(payload.start_year), int(payload.start_month),
                    float(payload.base_price) if payload.base_price is not None else None,
                ),
            )
            policy_id = cx.execute("SELECT last_insert_rowid() AS id;").fetchone()["id"]
        else:
            policy_id = row["id"]
            cx.execute(
                """
                UPDATE rise_fall_policy
                SET frequency=?, compounding=?, preview_months=?, start_year=?, start_month=?, base_price=?
                WHERE id=?;
                """,
                (
                    payload.frequency, payload.compounding, int(payload.preview_months),
                    int(payload.start_year), int(payload.start_month),
                    float(payload.base_price) if payload.base_price is not None else None,
                    policy_id,
                ),
            )

        cx.execute("DELETE FROM rise_fall_component WHERE policy_id=?", (policy_id,))
        for i, comp in enumerate(payload.components):
            cx.execute(
                """
                INSERT INTO rise_fall_component
                (policy_id, index_series_id, weight_pct, base_ref_year, base_ref_month, lag_m, factor, cap_pct, floor_pct, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    policy_id,
                    int(comp.index_series_id),
                    float(comp.weight_pct),
                    int(comp.base_ref_year),
                    int(comp.base_ref_month),
                    int(comp.lag_m or 0),
                    float(comp.factor or 1.0),
                    float(comp.cap_pct) if comp.cap_pct is not None else None,
                    float(comp.floor_pct) if comp.floor_pct is not None else None,
                    int(comp.sort_order) if comp.sort_order is not None else i,
                ),
            )

        pol, comps = _fetch_policy(scope, scenario_id, scope_id)
        return _row_to_policy_out(pol, comps)

def _get_policy(*, scenario_id: int, scope: str, scope_id: int) -> RiseFallPolicyOut:
    pol, comps = _fetch_policy(scope, scenario_id, scope_id)
    if pol is None:
        raise HTTPException(status_code=404, detail="Rise & Fall policy not found")
    return _row_to_policy_out(pol, comps)

def _delete_policy(*, scenario_id: int, scope: str, scope_id: int) -> bool:
    with _conn() as cx:
        cur = cx.execute(
            "DELETE FROM rise_fall_policy WHERE scenario_id=? AND scope=? AND scope_id=?",
            (scenario_id, scope, scope_id),
        )
        return cur.rowcount > 0

def _merge_patch_with_existing(
    *, scenario_id: int, scope: str, scope_id: int, body: RiseFallPolicyPatch
) -> RiseFallPolicyIn:
    pol, comps = _fetch_policy(scope, scenario_id, scope_id)
    if pol is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return RiseFallPolicyIn(
        frequency=body.frequency or pol["frequency"],
        compounding=body.compounding or pol["compounding"],
        preview_months=body.preview_months or pol["preview_months"],
        start_year=body.start_year or pol["start_year"],
        start_month=body.start_month or pol["start_month"],
        base_price=pol["base_price"] if body.base_price is None else body.base_price,
        components=body.components if body.components is not None else [
            RFComponentIn(
                index_series_id=c["index_series_id"],
                weight_pct=c["weight_pct"],
                base_ref_year=c["base_ref_year"],
                base_ref_month=c["base_ref_month"],
                lag_m=c["lag_m"],
                factor=c["factor"],
                cap_pct=c["cap_pct"],
                floor_pct=c["floor_pct"],
                sort_order=c["sort_order"],
            )
            for c in comps
        ],
    )

# ---------- Index access ----------
def _get_index_value(series_id: int, year: int, month: int) -> Optional[float]:
    """
    Returns the latest available index value at or before (year, month).
    If no earlier value exists, returns None.
    """
    with _conn() as cx:
        row = cx.execute(
            """
            SELECT value FROM index_points
            WHERE series_id=? AND (year < ? OR (year=? AND month <= ?))
            ORDER BY year DESC, month DESC
            LIMIT 1
            """,
            (series_id, year, year, month),
        ).fetchone()
        return float(row["value"]) if row else None

# ---------- Preview compute ----------
def _preview_from_policy(pol: RiseFallPolicyIn) -> PreviewOut:
    months = int(pol.preview_months)
    start_y, start_m = int(pol.start_year), int(pol.start_month)
    base_price = float(pol.base_price or 0.0)

    # Precompute each component's base (reference) index
    base_vals: List[float] = []
    for c in pol.components:
        base = _get_index_value(int(c.index_series_id), int(c.base_ref_year), int(c.base_ref_month))
        base_vals.append(base if (base and base > 0) else 1.0)

    composite: List[float] = []
    price: List[float] = []
    series_out: List[ComponentSeriesOut] = [ComponentSeriesOut(index_series_id=int(c.index_series_id), values=[]) for c in pol.components]

    for i in range(months):
        y, m = _add_months(start_y, start_m, i)
        total = 0.0

        for idx, c in enumerate(pol.components):
            by = base_vals[idx] or 1.0
            cy, cm = _add_months(y, m, -int(c.lag_m or 0))
            val = _get_index_value(int(c.index_series_id), cy, cm) or by

            # Normalized ratio vs base, apply factor and cap/floor
            ratio = (val / by) if by else 1.0
            ratio *= float(c.factor or 1.0)
            if c.cap_pct is not None:
                ratio = min(ratio, 1.0 + float(c.cap_pct) / 100.0)
            if c.floor_pct is not None:
                ratio = max(ratio, 1.0 - float(c.floor_pct) / 100.0)

            weight = float(c.weight_pct) / 100.0
            total += weight * ratio

            # Keep per-component series for the "Visualize Series" chart
            series_out[idx].values.append(ratio)

        composite.append(total)
        price.append(base_price * total)

    return PreviewOut(
        start_year=start_y,
        start_month=start_m,
        months=months,
        composite=composite,
        price=price,
        series=series_out,
    )

# ------------------------------------------------------------------------------
# SERVICE — PUT / GET / LIST / DELETE / PATCH / PREVIEW
# ------------------------------------------------------------------------------
@router.put(
    "/{scenario_id}/rise-fall/service/{service_id}",
    response_model=RiseFallPolicyOut,
    summary="Upsert Rise & Fall policy for a Service row",
)
def upsert_service_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    service_id: int = FPath(..., ge=1),
    payload: RiseFallPolicyIn = Body(...),
):
    return _upsert_policy_and_replace_components(
        scenario_id=scenario_id, scope="service", scope_id=service_id, payload=payload
    )

@router.get(
    "/{scenario_id}/rise-fall/service/{service_id}",
    response_model=RiseFallPolicyOut,
    summary="Get Rise & Fall policy for a Service row",
)
def get_service_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    service_id: int = FPath(..., ge=1),
):
    return _get_policy(scenario_id=scenario_id, scope="service", scope_id=service_id)

@router.get(
    "/{scenario_id}/rise-fall/service",
    response_model=List[RiseFallPolicyOut],
    summary="List all Service policies in a Scenario",
)
def list_service_rise_fall(
    scenario_id: int = FPath(..., ge=1),
):
    rows = _fetch_policy_rows("service", scenario_id)
    out: List[RiseFallPolicyOut] = []
    with _conn() as cx:
        for r in rows:
            comps = cx.execute(
                "SELECT * FROM rise_fall_component WHERE policy_id=? ORDER BY COALESCE(sort_order,0), id",
                (r["id"],),
            ).fetchall()
            out.append(_row_to_policy_out(r, comps))
    return out

@router.delete(
    "/{scenario_id}/rise-fall/service/{service_id}",
    summary="Delete Rise & Fall policy for a Service row",
)
def delete_service_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    service_id: int = FPath(..., ge=1),
):
    if not _delete_policy(scenario_id=scenario_id, scope="service", scope_id=service_id):
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"status": "deleted"}

@router.patch(
    "/{scenario_id}/rise-fall/service/{service_id}",
    response_model=RiseFallPolicyOut,
    summary="Patch (partial update) Rise & Fall policy for a Service row",
)
def patch_service_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    service_id: int = FPath(..., ge=1),
    patch: RiseFallPolicyPatch = Body(...),
):
    merged = _merge_patch_with_existing(
        scenario_id=scenario_id, scope="service", scope_id=service_id, body=patch
    )
    return _upsert_policy_and_replace_components(
        scenario_id=scenario_id, scope="service", scope_id=service_id, payload=merged
    )

@router.post(
    "/{scenario_id}/rise-fall/service/{service_id}/preview",
    response_model=PreviewOut,
    summary="Preview composite index and price for a Service row",
)
def preview_service_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    service_id: int = FPath(..., ge=1),
    body: Optional[PreviewIn] = Body(None),
):
    body = body or PreviewIn()
    pol_in = body.policy
    if pol_in is None:
        pol, comps = _fetch_policy("service", scenario_id, service_id)
        if pol is None:
            raise HTTPException(status_code=404, detail="Policy not found for preview")
        pol_in = RiseFallPolicyIn(
            frequency=pol["frequency"],
            compounding=pol["compounding"],
            preview_months=body.months or pol["preview_months"],
            start_year=pol["start_year"],
            start_month=pol["start_month"],
            base_price=pol["base_price"],
            components=[
                RFComponentIn(
                    index_series_id=c["index_series_id"],
                    weight_pct=c["weight_pct"],
                    base_ref_year=c["base_ref_year"],
                    base_ref_month=c["base_ref_month"],
                    lag_m=c["lag_m"],
                    factor=c["factor"],
                    cap_pct=c["cap_pct"],
                    floor_pct=c["floor_pct"],
                    sort_order=c["sort_order"],
                )
                for c in comps
            ],
        )
    else:
        if body.months:
            pol_in.preview_months = body.months
    return _preview_from_policy(pol_in)

# ------------------------------------------------------------------------------
# BOQ — PUT / GET / LIST / DELETE / PATCH / PREVIEW
# ------------------------------------------------------------------------------
@router.put(
    "/{scenario_id}/rise-fall/boq/{boq_id}",
    response_model=RiseFallPolicyOut,
    summary="Upsert Rise & Fall policy for a BOQ row",
)
def upsert_boq_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    boq_id: int = FPath(..., ge=1),
    payload: RiseFallPolicyIn = Body(...),
):
    return _upsert_policy_and_replace_components(
        scenario_id=scenario_id, scope="boq", scope_id=boq_id, payload=payload
    )

@router.get(
    "/{scenario_id}/rise-fall/boq/{boq_id}",
    response_model=RiseFallPolicyOut,
    summary="Get Rise & Fall policy for a BOQ row",
)
def get_boq_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    boq_id: int = FPath(..., ge=1),
):
    return _get_policy(scenario_id=scenario_id, scope="boq", scope_id=boq_id)

@router.get(
    "/{scenario_id}/rise-fall/boq",
    response_model=List[RiseFallPolicyOut],
    summary="List all BOQ policies in a Scenario",
)
def list_boq_rise_fall(
    scenario_id: int = FPath(..., ge=1),
):
    rows = _fetch_policy_rows("boq", scenario_id)
    out: List[RiseFallPolicyOut] = []
    with _conn() as cx:
        for r in rows:
            comps = cx.execute(
                "SELECT * FROM rise_fall_component WHERE policy_id=? ORDER BY COALESCE(sort_order,0), id",
                (r["id"],),
            ).fetchall()
            out.append(_row_to_policy_out(r, comps))
    return out

@router.delete(
    "/{scenario_id}/rise-fall/boq/{boq_id}",
    summary="Delete Rise & Fall policy for a BOQ row",
)
def delete_boq_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    boq_id: int = FPath(..., ge=1),
):
    if not _delete_policy(scenario_id=scenario_id, scope="boq", scope_id=boq_id):
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"status": "deleted"}

@router.patch(
    "/{scenario_id}/rise-fall/boq/{boq_id}",
    response_model=RiseFallPolicyOut,
    summary="Patch (partial update) Rise & Fall policy for a BOQ row",
)
def patch_boq_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    boq_id: int = FPath(..., ge=1),
    patch: RiseFallPolicyPatch = Body(...),
):
    merged = _merge_patch_with_existing(
        scenario_id=scenario_id, scope="boq", scope_id=boq_id, body=patch
    )
    return _upsert_policy_and_replace_components(
        scenario_id=scenario_id, scope="boq", scope_id=boq_id, payload=merged
    )

@router.post(
    "/{scenario_id}/rise-fall/boq/{boq_id}/preview",
    response_model=PreviewOut,
    summary="Preview composite index and price for a BOQ row",
)
def preview_boq_rise_fall(
    scenario_id: int = FPath(..., ge=1),
    boq_id: int = FPath(..., ge=1),
    body: Optional[PreviewIn] = Body(None),
):
    body = body or PreviewIn()
    pol_in = body.policy
    if pol_in is None:
        pol, comps = _fetch_policy("boq", scenario_id, boq_id)
        if pol is None:
            raise HTTPException(status_code=404, detail="Policy not found for preview")
        pol_in = RiseFallPolicyIn(
            frequency=pol["frequency"],
            compounding=pol["compounding"],
            preview_months=body.months or pol["preview_months"],
            start_year=pol["start_year"],
            start_month=pol["start_month"],
            base_price=pol["base_price"],
            components=[
                RFComponentIn(
                    index_series_id=c["index_series_id"],
                    weight_pct=c["weight_pct"],
                    base_ref_year=c["base_ref_year"],
                    base_ref_month=c["base_ref_month"],
                    lag_m=c["lag_m"],
                    factor=c["factor"],
                    cap_pct=c["cap_pct"],
                    floor_pct=c["floor_pct"],
                    sort_order=c["sort_order"],
                )
                for c in comps
            ],
        )
    else:
        if body.months:
            pol_in.preview_months = body.months
    return _preview_from_policy(pol_in)
