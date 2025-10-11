# C:/Dev/AryaIntel_CRM/backend/app/api/opex_api.py
# FastAPI Router: OPEX (headers, lines, kv, allocations) + monthly allocation summary
# - Uses sqlite3 directly against C:/Dev/AryaIntel_CRM/app.db to avoid ORM drift for new tables
# - Idempotent defensive DDL (safe if already migrated)
# - Basis-aware allocation (percent | revenue | volume | gross_margin)
# - Per-month service allocation summary for Services Pricing

from __future__ import annotations
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Body, UploadFile, File, status

DB_PATH = r"C:/Dev/AryaIntel_CRM/app.db"

router = APIRouter(prefix="/api", tags=["opex"])

# ------------------------------ Utilities ------------------------------

def get_conn() -> sqlite3.Connection:
    db = Path(DB_PATH)
    if not db.exists():
        raise HTTPException(500, f"DB not found at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}

def ensure_schema(conn: sqlite3.Connection) -> None:
    # Defensive: ensure tables from migrations exist (no-op if already there)
    ddl = [
        # scenario_opex
        """
        CREATE TABLE IF NOT EXISTS scenario_opex (
            id              INTEGER PRIMARY KEY,
            scenario_id     INTEGER NOT NULL,
            name            TEXT NOT NULL,
            category        TEXT,
            currency        TEXT,
            allocation_mode TEXT NOT NULL DEFAULT 'none',
            periodicity     TEXT NOT NULL DEFAULT 'monthly',
            start_year      INTEGER,
            start_month     INTEGER,
            end_year        INTEGER,
            end_month       INTEGER,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_scenario_opex_scenario ON scenario_opex (scenario_id);",

        # scenario_opex_month
        """
        CREATE TABLE IF NOT EXISTS scenario_opex_month (
            id       INTEGER PRIMARY KEY,
            opex_id  INTEGER NOT NULL,
            year     INTEGER NOT NULL,
            month    INTEGER NOT NULL,
            amount   NUMERIC NOT NULL DEFAULT 0,
            UNIQUE (opex_id, year, month)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_opex_month_opex ON scenario_opex_month (opex_id);",

        # scenario_opex_alloc (+ basis)
        """
        CREATE TABLE IF NOT EXISTS scenario_opex_alloc (
            id         INTEGER PRIMARY KEY,
            opex_id    INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            weight_pct NUMERIC NOT NULL,
            basis      TEXT,
            UNIQUE (opex_id, service_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_opex_alloc_opex ON scenario_opex_alloc (opex_id);",
        "CREATE INDEX IF NOT EXISTS idx_opex_alloc_service ON scenario_opex_alloc (service_id);",
        "CREATE INDEX IF NOT EXISTS idx_opex_alloc_basis ON scenario_opex_alloc (basis);",

        # scenario_opex_line
        """
        CREATE TABLE IF NOT EXISTS scenario_opex_line (
            id               INTEGER PRIMARY KEY,
            opex_id          INTEGER NOT NULL,
            line_no          INTEGER,
            type             TEXT,
            detail           TEXT,
            vendor           TEXT,
            unit             TEXT,
            qty_per_month    NUMERIC,
            unit_rate        NUMERIC,
            currency         TEXT,
            fixed_monthly    NUMERIC,
            valid_from_year  INTEGER,
            valid_from_month INTEGER,
            valid_to_year    INTEGER,
            valid_to_month   INTEGER,
            notes            TEXT,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_opex_line_opex ON scenario_opex_line (opex_id);",
        "CREATE INDEX IF NOT EXISTS idx_opex_line_type ON scenario_opex_line (type);",
        "CREATE INDEX IF NOT EXISTS idx_opex_line_detail ON scenario_opex_line (detail);",

        # scenario_opex_line_kv
        """
        CREATE TABLE IF NOT EXISTS scenario_opex_line_kv (
            id      INTEGER PRIMARY KEY,
            line_id INTEGER NOT NULL,
            key     TEXT NOT NULL,
            value   TEXT,
            UNIQUE (line_id, key)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_opex_line_kv_line ON scenario_opex_line_kv (line_id);",
        "CREATE INDEX IF NOT EXISTS idx_opex_line_kv_key ON scenario_opex_line_kv (key);",
    ]
    cur = conn.cursor()
    for stmt in ddl:
        cur.execute(stmt)
    conn.commit()

def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

# ------------------------------ OPEX: headers ------------------------------

@router.get("/scenarios/{scenario_id}/opex")
def list_opex(scenario_id: int):
    with get_conn() as conn:
        ensure_schema(conn)
        cur = conn.execute(
            "SELECT * FROM scenario_opex WHERE scenario_id = ? ORDER BY id DESC",
            (scenario_id,),
        )
        return [row_to_dict(r) for r in cur.fetchall()]

@router.post("/scenarios/{scenario_id}/opex", status_code=status.HTTP_201_CREATED)
def create_opex(scenario_id: int, payload: Dict[str, Any] = Body(...)):
    allowed = {
        "name","category","currency","allocation_mode","periodicity",
        "start_year","start_month","end_year","end_month","notes"
    }
    cols = ["scenario_id"] + [c for c in allowed if c in payload]
    vals = [scenario_id] + [payload.get(c) for c in cols[1:]]
    qs = ",".join(cols)
    ps = ",".join("?" for _ in cols)
    with get_conn() as conn:
        ensure_schema(conn)
        cur = conn.execute(f"INSERT INTO scenario_opex ({qs}) VALUES ({ps})", vals)
        oid = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM scenario_opex WHERE id=?", (oid,)).fetchone()
        return row_to_dict(row)

@router.put("/opex/{opex_id}")
def update_opex(opex_id: int, payload: Dict[str, Any] = Body(...)):
    allowed = {
        "name","category","currency","allocation_mode","periodicity",
        "start_year","start_month","end_year","end_month","notes"
    }
    sets = []
    vals = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k}=?")
            vals.append(payload[k])
    if not sets:
        raise HTTPException(400, "No updatable fields")
    sets.append("updated_at=?")
    vals.append(now_iso())
    vals.append(opex_id)
    with get_conn() as conn:
        ensure_schema(conn)
        conn.execute(f"UPDATE scenario_opex SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
        row = conn.execute("SELECT * FROM scenario_opex WHERE id=?", (opex_id,)).fetchone()
        if not row:
            raise HTTPException(404, "OPEX not found")
        return row_to_dict(row)

@router.delete("/opex/{opex_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opex(opex_id: int):
    with get_conn() as conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM scenario_opex WHERE id=?", (opex_id,))
        conn.execute("DELETE FROM scenario_opex_month WHERE opex_id=?", (opex_id,))
        conn.execute("DELETE FROM scenario_opex_alloc WHERE opex_id=?", (opex_id,))
        # delete dependent lines & kv
        cur = conn.execute("SELECT id FROM scenario_opex_line WHERE opex_id=?", (opex_id,))
        line_ids = [r[0] for r in cur.fetchall()]
        if line_ids:
            conn.executemany("DELETE FROM scenario_opex_line_kv WHERE line_id=?", [(i,) for i in line_ids])
            conn.execute("DELETE FROM scenario_opex_line WHERE opex_id=?", (opex_id,))
        conn.commit()
        return

# ------------------------------ OPEX: months ------------------------------

@router.put("/opex/{opex_id}/months")
def upsert_opex_months(opex_id: int, months: List[Dict[str, Any]] = Body(...)):
    """
    Body: [{year, month, amount}, ...]
    """
    with get_conn() as conn:
        ensure_schema(conn)
        for m in months:
            y = int(m["year"]); mm = int(m["month"]); amt = float(m.get("amount", 0) or 0)
            conn.execute("""
                INSERT INTO scenario_opex_month (opex_id, year, month, amount)
                VALUES (?,?,?,?)
                ON CONFLICT(opex_id,year,month) DO UPDATE SET amount=excluded.amount
            """, (opex_id, y, mm, amt))
        conn.commit()
        cur = conn.execute("SELECT * FROM scenario_opex_month WHERE opex_id=? ORDER BY year, month", (opex_id,))
        return [row_to_dict(r) for r in cur.fetchall()]

# ------------------------------ OPEX: lines & kv ------------------------------

@router.get("/opex/{opex_id}/lines")
def list_opex_lines(opex_id: int):
    with get_conn() as conn:
        ensure_schema(conn)
        cur = conn.execute("SELECT * FROM scenario_opex_line WHERE opex_id=? ORDER BY COALESCE(line_no, id)", (opex_id,))
        rows = [row_to_dict(r) for r in cur.fetchall()]
        # attach kv
        for r in rows:
            kv = conn.execute("SELECT key, value FROM scenario_opex_line_kv WHERE line_id=?", (r["id"],)).fetchall()
            r["kv"] = {x["key"]: x["value"] for x in kv}
        return rows

@router.post("/opex/{opex_id}/lines", status_code=status.HTTP_201_CREATED)
def create_opex_line(opex_id: int, payload: Dict[str, Any] = Body(...)):
    allowed = {
        "line_no","type","detail","vendor","unit","qty_per_month","unit_rate",
        "currency","fixed_monthly","valid_from_year","valid_from_month","valid_to_year","valid_to_month","notes"
    }
    cols = ["opex_id"] + [c for c in allowed if c in payload]
    vals = [opex_id] + [payload.get(c) for c in cols[1:]]
    qs = ",".join(cols); ps = ",".join("?" for _ in cols)
    kv = payload.get("kv") or {}

    with get_conn() as conn:
        ensure_schema(conn)
        cur = conn.execute(f"INSERT INTO scenario_opex_line ({qs}) VALUES ({ps})", vals)
        line_id = cur.lastrowid
        # kv
        for k, v in kv.items():
            conn.execute("""
                INSERT INTO scenario_opex_line_kv (line_id, key, value)
                VALUES (?,?,?)
                ON CONFLICT(line_id, key) DO UPDATE SET value=excluded.value
            """, (line_id, str(k), None if v is None else str(v)))
        conn.commit()
        row = conn.execute("SELECT * FROM scenario_opex_line WHERE id=?", (line_id,)).fetchone()
        data = row_to_dict(row)
        data["kv"] = kv
        return data

@router.put("/opex/lines/{line_id}")
def update_opex_line(line_id: int, payload: Dict[str, Any] = Body(...)):
    allowed = {
        "line_no","type","detail","vendor","unit","qty_per_month","unit_rate",
        "currency","fixed_monthly","valid_from_year","valid_from_month","valid_to_year","valid_to_month","notes"
    }
    sets = []; vals: List[Any] = []
    for k in allowed:
        if k in payload:
            sets.append(f"{k}=?"); vals.append(payload[k])
    if sets:
        sets.append("updated_at=?"); vals.append(now_iso())
    vals.append(line_id)

    kv = payload.get("kv")

    with get_conn() as conn:
        ensure_schema(conn)
        if sets:
            conn.execute(f"UPDATE scenario_opex_line SET {', '.join(sets)} WHERE id=?", vals)
        if isinstance(kv, dict):
            # upsert each
            for k, v in kv.items():
                conn.execute("""
                    INSERT INTO scenario_opex_line_kv (line_id, key, value)
                    VALUES (?,?,?)
                    ON CONFLICT(line_id, key) DO UPDATE SET value=excluded.value
                """, (line_id, str(k), None if v is None else str(v)))
        conn.commit()
        row = conn.execute("SELECT * FROM scenario_opex_line WHERE id=?", (line_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Line not found")
        data = row_to_dict(row)
        kv_pairs = conn.execute("SELECT key, value FROM scenario_opex_line_kv WHERE line_id=?", (line_id,)).fetchall()
        data["kv"] = {x["key"]: x["value"] for x in kv_pairs}
        return data

@router.delete("/opex/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opex_line(line_id: int):
    with get_conn() as conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM scenario_opex_line_kv WHERE line_id=?", (line_id,))
        conn.execute("DELETE FROM scenario_opex_line WHERE id=?", (line_id,))
        conn.commit()
        return

# ------------------------------ OPEX: allocations ------------------------------

@router.get("/opex/{opex_id}/allocations")
def list_allocations(opex_id: int):
    with get_conn() as conn:
        ensure_schema(conn)
        cur = conn.execute("SELECT * FROM scenario_opex_alloc WHERE opex_id=? ORDER BY service_id", (opex_id,))
        return [row_to_dict(r) for r in cur.fetchall()]

@router.put("/opex/{opex_id}/allocations")
def upsert_allocations(opex_id: int, allocations: List[Dict[str, Any]] = Body(...)):
    """
    Body: [{service_id, weight_pct, basis}]  -- 'basis' in {'percent','revenue','volume','gross_margin'}
    """
    with get_conn() as conn:
        ensure_schema(conn)
        for a in allocations:
            sid = int(a["service_id"])
            pct = float(a.get("weight_pct", 0) or 0)
            basis = (a.get("basis") or "percent").lower()
            if basis not in ("percent","revenue","volume","gross_margin"):
                raise HTTPException(400, f"Invalid basis: {basis}")
            conn.execute("""
                INSERT INTO scenario_opex_alloc (opex_id, service_id, weight_pct, basis)
                VALUES (?,?,?,?)
                ON CONFLICT(opex_id, service_id) DO UPDATE
                SET weight_pct=excluded.weight_pct, basis=excluded.basis
            """, (opex_id, sid, pct, basis))
        conn.commit()
        cur = conn.execute("SELECT * FROM scenario_opex_alloc WHERE opex_id=? ORDER BY service_id", (opex_id,))
        return [row_to_dict(r) for r in cur.fetchall()]

@router.delete("/opex/allocations/{alloc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation(alloc_id: int):
    with get_conn() as conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM scenario_opex_alloc WHERE id=?", (alloc_id,))
        conn.commit()
        return

# ------------------------------ Allocation math ------------------------------

def month_opex_total(conn: sqlite3.Connection, opex_id: int, year: int, month: int) -> float:
    row = conn.execute("""
        SELECT amount FROM scenario_opex_month
        WHERE opex_id=? AND year=? AND month=?
    """, (opex_id, year, month)).fetchone()
    return float(row["amount"]) if row else 0.0

def service_metrics(conn: sqlite3.Connection, scenario_id: int, year: int, month: int) -> Dict[int, Dict[str, float]]:
    """
    Attempts to read per-service metrics for a given month.
    Expected tables (best effort; zeros if missing):
      - scenario_service_month (service_id, year, month, revenue, volume, gross_margin)
    """
    metrics: Dict[int, Dict[str, float]] = {}
    # Check if table exists
    tbl_exists = conn.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='scenario_service_month'
    """).fetchone()
    if not tbl_exists:
        return metrics

    cur = conn.execute("""
        SELECT ssm.service_id, ssm.revenue, ssm.volume, ssm.gross_margin
        FROM scenario_service_month ssm
        JOIN scenario_services ss ON ss.id = ssm.service_id
        WHERE ss.scenario_id = ? AND ssm.year = ? AND ssm.month = ?
    """, (scenario_id, year, month))
    for r in cur.fetchall():
        metrics[int(r["service_id"])] = {
            "revenue": float(r["revenue"] or 0),
            "volume": float(r["volume"] or 0),
            "gross_margin": float(r["gross_margin"] or 0),
        }
    return metrics

def allocate_amount(total: float, basis: str, allocs: List[sqlite3.Row], metrics: Dict[int, Dict[str, float]]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    if total <= 0 or not allocs:
        return out
    basis = (basis or "percent").lower()

    if basis == "percent":
        # Use each row's weight_pct; normalize if not summing 100
        s = sum(float(a["weight_pct"] or 0) for a in allocs)
        if s <= 0:
            return out
        for a in allocs:
            sid = int(a["service_id"])
            pct = float(a["weight_pct"] or 0) / s
            out[sid] = total * pct
        return out

    # Driver-based: revenue | volume | gross_margin
    key = basis
    weights: Dict[int, float] = {}
    for a in allocs:
        sid = int(a["service_id"])
        m = metrics.get(sid) or {}
        w = float(m.get(key, 0) or 0)
        weights[sid] = w
    s = sum(weights.values())
    if s <= 0:
        # fallback: equal split
        n = len(weights) or 1
        eq = total / n
        return {sid: eq for sid in weights.keys()}
    for sid, w in weights.items():
        out[sid] = total * (w / s)
    return out

@router.get("/scenarios/{scenario_id}/opex/allocated-summary")
def allocated_opex_summary(
    scenario_id: int,
    year: int = Query(..., ge=1900, le=3000),
    month: int = Query(..., ge=1, le=12),
):
    """
    Returns per-service Allocated OPEX for the given month by:
      1) Reading each OPEX's monthly amount
      2) Reading allocations (basis per line)
      3) Reading service metrics (for driver-based basis)
      4) Summing amounts per service
    Response:
      {
        "year": 2025, "month": 10,
        "services": [
          {"service_id": 101, "allocated_opex": 1234.56},
          ...
        ]
      }
    """
    with get_conn() as conn:
        ensure_schema(conn)
        # fetch services under scenario to constrain results
        svc_rows = []
        svc_tbl = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table' AND name='scenario_services'
        """).fetchone()
        if svc_tbl:
            svc_rows = conn.execute("SELECT id FROM scenario_services WHERE scenario_id=?", (scenario_id,)).fetchall()
        service_ids = set(int(r["id"]) for r in svc_rows) if svc_rows else set()

        # get opex headers
        opex_rows = conn.execute("SELECT * FROM scenario_opex WHERE scenario_id=?", (scenario_id,)).fetchall()
        metrics = service_metrics(conn, scenario_id, year, month)

        per_service: Dict[int, float] = {sid: 0.0 for sid in service_ids} if service_ids else {}

        for ox in opex_rows:
            opex_id = int(ox["id"])
            total = month_opex_total(conn, opex_id, year, month)
            if total <= 0:
                continue
            allocs = conn.execute("SELECT * FROM scenario_opex_alloc WHERE opex_id=?", (opex_id,)).fetchall()
            if not allocs:
                # if no allocations, skip or drop into 'unallocated'? We skip to avoid distorting GM.
                continue
            # prefer per-allocation basis if set; otherwise header's allocation_mode
            # when basis missing -> assume 'percent'
            # allow mixed-basis rows (each alloc row carries its own basis)
            # compute allocations row-wise and sum
            # group allocs by basis
            by_basis: Dict[str, List[sqlite3.Row]] = {}
            for a in allocs:
                b = (a["basis"] or "percent").lower()
                by_basis.setdefault(b, []).append(a)
            # Split total proportionally across bases (equal split across basis groups)
            # Rationale: If user intentionally mixed bases, we split total equally per basis group,
            # then allocate within each group. If only one basis, it gets 100%.
            groups = list(by_basis.items())
            part = total / len(groups)
            for b, rows in groups:
                dist = allocate_amount(part, b, rows, metrics)
                for sid, amt in dist.items():
                    per_service[sid] = per_service.get(sid, 0.0) + amt

        services_list = [{"service_id": sid, "allocated_opex": round(amt, 2)} for sid, amt in sorted(per_service.items())]
        return {"year": year, "month": month, "services": services_list}
