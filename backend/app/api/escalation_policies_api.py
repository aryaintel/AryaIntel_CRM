from pathlib import Path
from typing import Optional, List, Literal
from decimal import Decimal
from datetime import datetime
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Path as FPath
from pydantic import BaseModel, condecimal, validator, root_validator

# ---------------- Base setup ----------------
DB_PATH = Path(__file__).resolve().parents[2] / "app.db"

def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx

def _ensure_exists(cx: sqlite3.Connection, table: str, id_: int):
    row = cx.execute(f"SELECT 1 FROM {table} WHERE id=?", (id_,)).fetchone()
    if not row:
        raise HTTPException(404, f"{table} not found")

def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")

def _has_column(cx: sqlite3.Connection, table: str, col: str) -> bool:
    rows = cx.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"].lower() == col.lower() for r in rows)

# ---------------- Types & Schemas ----------------
Scope = Literal["price", "cost", "both"]
Frequency = Literal["monthly", "quarterly", "annual"]
Compounding = Literal["compound", "simple"]

class PolicyComponentIn(BaseModel):
    index_series_id: int
    weight_pct: condecimal(max_digits=9, decimal_places=4)   # 0..100
    base_index_value: Optional[condecimal(max_digits=18, decimal_places=6)] = None
    note: Optional[str] = None

    @validator("weight_pct")
    def _w_nonneg(cls, v):
        if Decimal(v) < 0:
            raise ValueError("weight_pct must be >= 0")
        return v

class _BasePolicy(BaseModel):
    name: str
    scope: Scope = "both"

    # method: either fixed rate or index-based
    rate_pct: Optional[condecimal(max_digits=9, decimal_places=6)] = None
    index_series_id: Optional[int] = None  # shorthand for single-series
    components: Optional[List[PolicyComponentIn]] = None

    start_year: int
    start_month: int

    cap_pct: Optional[condecimal(max_digits=9, decimal_places=6)] = None
    floor_pct: Optional[condecimal(max_digits=9, decimal_places=6)] = None

    frequency: Frequency = "annual"
    compounding: Compounding = "compound"

    # bazı kurulumlarda yok → PRAGMA ile kontrol edeceğiz
    scenario_id: Optional[int] = None  # NULL → global

    @validator("start_month")
    def _m_ok(cls, v):
        if v < 1 or v > 12:
            raise ValueError("start_month must be 1..12")
        return v

    @root_validator
    def _method_and_weights(cls, values):
        rate = values.get("rate_pct")
        idx_id = values.get("index_series_id")
        comps = values.get("components") or []

        picked = 0
        if rate is not None:
            picked += 1
        if idx_id is not None or comps:
            picked += 1

        if picked == 0:
            raise ValueError("Provide either rate_pct OR index_series_id/components")
        if picked > 1:
            raise ValueError("Use either rate_pct OR index_series_id/components, not both")

        if comps:
            total = sum(Decimal(str(c.weight_pct)) for c in comps)
            if total > Decimal("100"):
                raise ValueError(f"Sum of component weights must be <= 100 (got {total})")
        return values

class EscalationCreate(_BasePolicy):
    pass

class EscalationUpdate(BaseModel):
    name: Optional[str] = None
    scope: Optional[Scope] = None

    rate_pct: Optional[condecimal(max_digits=9, decimal_places=6)] = None
    index_series_id: Optional[int] = None
    components: Optional[List[PolicyComponentIn]] = None  # if given, full replace

    start_year: Optional[int] = None
    start_month: Optional[int] = None

    cap_pct: Optional[condecimal(max_digits=9, decimal_places=6)] = None
    floor_pct: Optional[condecimal(max_digits=9, decimal_places=6)] = None

    frequency: Optional[Frequency] = None
    compounding: Optional[Compounding] = None

    scenario_id: Optional[int] = None

    @root_validator
    def _consistent_method(cls, values):
        # if any method fields provided, keep exclusivity
        keys = {k for k, v in values.items() if v is not None}
        if keys & {"rate_pct", "index_series_id", "components"}:
            rate = values.get("rate_pct")
            idx_id = values.get("index_series_id")
            comps = values.get("components") or []
            picked = 0
            if rate is not None:
                picked += 1
            if idx_id is not None or comps:
                picked += 1
            if picked > 1:
                raise ValueError("Ambiguous: set either rate_pct OR index_series_id/components")

            if comps:
                total = sum(Decimal(str(c.weight_pct)) for c in comps)
                if total > Decimal("100"):
                    raise ValueError(f"Sum of component weights must be <= 100 (got {total})")
        return values

# ---------------- Router: CRUD under scenario ----------------
router = APIRouter(
    prefix="/scenarios/{scenario_id}/escalation-policies",
    tags=["Escalation"],
)

@router.get("")
def list_policies(
    scenario_id: int = FPath(..., gt=0),
    q: Optional[str] = None,
    scope: Optional[Scope] = None,
    frequency: Optional[Frequency] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with _db() as cx:
        _ensure_exists(cx, "scenarios", scenario_id)

        has_scenario_col = _has_column(cx, "escalation_policies", "scenario_id")

        if has_scenario_col:
            sql = """
              SELECT * FROM escalation_policies
              WHERE (scenario_id IS NULL OR scenario_id = ?)
            """
            args: list = [scenario_id]
        else:
            # global tablo: tüm politikalar listelenir (path param sadece guard)
            sql = "SELECT * FROM escalation_policies WHERE 1=1"
            args = []

        if q:
            sql += " AND name LIKE ?"; args.append(f"%{q}%")
        if scope:
            sql += " AND scope=?"; args.append(scope)
        if frequency:
            sql += " AND frequency=?"; args.append(frequency)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"; args += [limit, offset]

        rows = [dict(r) for r in cx.execute(sql, args).fetchall()]
        return {"items": rows, "count": len(rows), "limit": limit, "offset": offset}

@router.post("", status_code=201)
def create_policy(
    payload: EscalationCreate,
    scenario_id: int = FPath(..., gt=0),
):
    with _db() as cx:
        _ensure_exists(cx, "scenarios", scenario_id)

        has_scenario_col = _has_column(cx, "escalation_policies", "scenario_id")
        has_created_col  = _has_column(cx, "escalation_policies", "created_at")
        has_updated_col  = _has_column(cx, "escalation_policies", "updated_at")

        # force path scenario if table supports it
        scen_for_row = (payload.scenario_id if payload.scenario_id is not None else scenario_id) if has_scenario_col else None

        cols = ["name","scope","rate_pct","index_series_id","start_year","start_month",
                "cap_pct","floor_pct","frequency","compounding"]
        vals = [
            payload.name, payload.scope,
            float(payload.rate_pct) if payload.rate_pct is not None else None,
            payload.index_series_id,
            payload.start_year, payload.start_month,
            float(payload.cap_pct) if payload.cap_pct is not None else None,
            float(payload.floor_pct) if payload.floor_pct is not None else None,
            payload.frequency, payload.compounding,
        ]
        if has_scenario_col:
            cols.append("scenario_id"); vals.append(scen_for_row)
        if has_created_col:
            cols.append("created_at"); vals.append(_now())
        if has_updated_col:
            cols.append("updated_at"); vals.append(_now())

        placeholders = ",".join("?" for _ in cols)
        sql = f"INSERT INTO escalation_policies ({', '.join(cols)}) VALUES ({placeholders})"

        try:
            cur = cx.execute(sql, vals)
            pid = cur.lastrowid

            if payload.components:
                for c in payload.components:
                    cx.execute(
                        """
                        INSERT INTO escalation_policy_components
                        (policy_id, index_series_id, weight_pct, base_index_value, note)
                        VALUES (?,?,?,?,?)
                        """,
                        (
                            pid, c.index_series_id, float(c.weight_pct),
                            float(c.base_index_value) if c.base_index_value is not None else None,
                            c.note,
                        )
                    )
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, f"db integrity error: {e}")

        return {"id": pid}

@router.put("/{policy_id}")
def update_policy(
    payload: EscalationUpdate,
    scenario_id: int = FPath(..., gt=0),
    policy_id: int = FPath(..., gt=0),
):
    with _db() as cx:
        _ensure_exists(cx, "scenarios", scenario_id)
        _ensure_exists(cx, "escalation_policies", policy_id)

        has_scenario_col = _has_column(cx, "escalation_policies", "scenario_id")
        has_updated_col  = _has_column(cx, "escalation_policies", "updated_at")

        fields: List[str] = []
        vals: list = []
        mapping = {
            "name": payload.name,
            "scope": payload.scope,
            "rate_pct": (None if payload.rate_pct is None else float(payload.rate_pct)),
            "index_series_id": payload.index_series_id,
            "start_year": payload.start_year,
            "start_month": payload.start_month,
            "cap_pct": (None if payload.cap_pct is None else float(payload.cap_pct)),
            "floor_pct": (None if payload.floor_pct is None else float(payload.floor_pct)),
            "frequency": payload.frequency,
            "compounding": payload.compounding,
        }
        if has_scenario_col:
            mapping["scenario_id"] = payload.scenario_id

        for col, val in mapping.items():
            if val is not None:
                fields.append(f"{col}=?")
                vals.append(val)

        if fields:
            if has_updated_col:
                fields.append("updated_at=?"); vals.append(_now())
            vals.append(policy_id)
            try:
                cx.execute(f"UPDATE escalation_policies SET {', '.join(fields)} WHERE id=?", vals)
            except sqlite3.IntegrityError as e:
                raise HTTPException(409, f"db integrity error: {e}")

        # full replace components if provided (could be empty list)
        if payload.components is not None:
            cx.execute("DELETE FROM escalation_policy_components WHERE policy_id=?", (policy_id,))
            for c in payload.components:
                cx.execute(
                    """
                    INSERT INTO escalation_policy_components
                    (policy_id, index_series_id, weight_pct, base_index_value, note)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        policy_id, c.index_series_id, float(c.weight_pct),
                        float(c.base_index_value) if c.base_index_value is not None else None,
                        c.note,
                    )
                )

        return {"id": policy_id, "updated": True}

@router.delete("/{policy_id}", status_code=204)
def delete_policy(
    scenario_id: int = FPath(..., gt=0),
    policy_id: int = FPath(..., gt=0),
):
    with _db() as cx:
        _ensure_exists(cx, "scenarios", scenario_id)
        _ensure_exists(cx, "escalation_policies", policy_id)

        has_srv_cogs  = _has_column(cx, "scenario_services", "cogs_escalation_policy_id")
        has_boq_cogs  = _has_column(cx, "scenario_boq_items", "cogs_escalation_policy_id")
        has_def_cogs  = _has_column(cx, "scenarios", "default_cogs_escalation_policy_id")

        # usage checks (kolon varsa kontrol edilir)
        ref = cx.execute(
            f"""
            SELECT 1 FROM scenario_services
            WHERE price_escalation_policy_id=?{" OR cogs_escalation_policy_id=?" if has_srv_cogs else ""} LIMIT 1
            """,
            (policy_id, policy_id) if has_srv_cogs else (policy_id,)
        ).fetchone()
        if ref:
            raise HTTPException(409, "policy is in use by scenario_services")

        ref2 = cx.execute(
            f"""
            SELECT 1 FROM scenario_boq_items
            WHERE price_escalation_policy_id=?{" OR cogs_escalation_policy_id=?" if has_boq_cogs else ""} LIMIT 1
            """,
            (policy_id, policy_id) if has_boq_cogs else (policy_id,)
        ).fetchone()
        if ref2:
            raise HTTPException(409, "policy is in use by scenario_boq_items")

        ref3 = cx.execute(
            f"""
            SELECT 1 FROM scenarios
            WHERE default_price_escalation_policy_id=?{" OR default_cogs_escalation_policy_id=?" if has_def_cogs else ""} LIMIT 1
            """,
            (policy_id, policy_id) if has_def_cogs else (policy_id,)
        ).fetchone()
        if ref3:
            raise HTTPException(409, "policy is set as default on scenarios")

        cx.execute("DELETE FROM escalation_policy_components WHERE policy_id=?", (policy_id,))
        cx.execute("DELETE FROM escalation_policies WHERE id=?", (policy_id,))
        return

# ---------------- (Opsiyonel) attach/defaults yardımcı uçları (eski prefix) ----------------
router2 = APIRouter(prefix="/api/escalations", tags=["escalation-policies"])

class AttachEscalationBody(BaseModel):
    policy_id: int
    target: Literal["price", "cogs"] = "price"

@router2.post("/services/{service_id}/attach")
def attach_to_service(service_id: int, body: AttachEscalationBody):
    with _db() as cx:
        _ensure_exists(cx, "scenario_services", service_id)
        _ensure_exists(cx, "escalation_policies", body.policy_id)

        has_srv_cogs = _has_column(cx, "scenario_services", "cogs_escalation_policy_id")

        if body.target == "price" or not has_srv_cogs:
            cx.execute("UPDATE scenario_services SET price_escalation_policy_id=? WHERE id=?",
                       (body.policy_id, service_id))
        else:
            cx.execute("UPDATE scenario_services SET cogs_escalation_policy_id=? WHERE id=?",
                       (body.policy_id, service_id))
        cx.commit()

        row = cx.execute(
            "SELECT id, price_escalation_policy_id FROM scenario_services WHERE id=?",
            (service_id,)
        ).fetchone()
        out = {"service_id": row["id"], "price_policy_id": row["price_escalation_policy_id"]}
        if has_srv_cogs:
            r2 = cx.execute(
                "SELECT cogs_escalation_policy_id FROM scenario_services WHERE id=?", (service_id,)
            ).fetchone()
            out["cogs_policy_id"] = r2["cogs_escalation_policy_id"]
        return out

@router2.post("/boq-items/{item_id}/attach")
def attach_to_boq_item(item_id: int, body: AttachEscalationBody):
    with _db() as cx:
        _ensure_exists(cx, "scenario_boq_items", item_id)
        _ensure_exists(cx, "escalation_policies", body.policy_id)

        has_boq_cogs = _has_column(cx, "scenario_boq_items", "cogs_escalation_policy_id")

        if body.target == "price" or not has_boq_cogs:
            cx.execute("UPDATE scenario_boq_items SET price_escalation_policy_id=? WHERE id=?",
                       (body.policy_id, item_id))
        else:
            cx.execute("UPDATE scenario_boq_items SET cogs_escalation_policy_id=? WHERE id=?",
                       (body.policy_id, item_id))
        cx.commit()

        row = cx.execute(
            "SELECT id, price_escalation_policy_id FROM scenario_boq_items WHERE id=?",
            (item_id,)
        ).fetchone()
        out = {"boq_item_id": row["id"], "price_policy_id": row["price_escalation_policy_id"]}
        if has_boq_cogs:
            r2 = cx.execute(
                "SELECT cogs_escalation_policy_id FROM scenario_boq_items WHERE id=?", (item_id,)
            ).fetchone()
            out["cogs_policy_id"] = r2["cogs_escalation_policy_id"]
        return out

class ScenarioDefaultsBody(BaseModel):
    price_policy_id: Optional[int] = None
    cogs_policy_id: Optional[int] = None

@router2.post("/scenarios/{scenario_id}/set-defaults")
def set_scenario_defaults(scenario_id: int, body: ScenarioDefaultsBody):
    with _db() as cx:
        _ensure_exists(cx, "scenarios", scenario_id)

        has_def_price = _has_column(cx, "scenarios", "default_price_escalation_policy_id")
        has_def_cogs  = _has_column(cx, "scenarios", "default_cogs_escalation_policy_id")

        fields = []
        vals: list = []

        if has_def_price and body.price_policy_id is not None:
            _ensure_exists(cx, "escalation_policies", body.price_policy_id)
            fields.append("default_price_escalation_policy_id=?")
            vals.append(body.price_policy_id)

        if has_def_cogs and body.cogs_policy_id is not None:
            _ensure_exists(cx, "escalation_policies", body.cogs_policy_id)
            fields.append("default_cogs_escalation_policy_id=?")
            vals.append(body.cogs_policy_id)

        if not fields:
            raise HTTPException(400, "no defaults to set")

        vals.append(scenario_id)
        cx.execute(f"UPDATE scenarios SET {', '.join(fields)} WHERE id=?", vals)
        cx.commit()

        s = cx.execute(
            """
            SELECT id,
                   {price_col} as default_price_escalation_policy_id,
                   {cogs_col}  as default_cogs_escalation_policy_id
            FROM scenarios WHERE id=?
            """.format(
                price_col="default_price_escalation_policy_id" if has_def_price else "NULL",
                cogs_col="default_cogs_escalation_policy_id" if has_def_cogs else "NULL",
            ),
            (scenario_id,),
        ).fetchone()

        return {
            "scenario_id": s["id"],
            "default_price_policy_id": s["default_price_escalation_policy_id"],
            "default_cogs_policy_id": s["default_cogs_escalation_policy_id"],
        }
