# backend/app/api/formulation_links_api.py
from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["formulation-links"])
DB_PATH = Path(__file__).resolve().parents[2] / "app.db"

# ---------------- DB helpers ----------------
def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx

def _ensure_exists(cx: sqlite3.Connection, table: str, id_: int):
    row = cx.execute(f"SELECT id FROM {table} WHERE id=?", (id_,)).fetchone()
    if not row:
        raise HTTPException(404, f"{table} not found")

def _get_formulation(cx: sqlite3.Connection, fid: int):
    return cx.execute(
        "SELECT id, code, is_archived FROM product_formulations WHERE id=?",
        (fid,)
    ).fetchone()

# ---------------- Schemas ----------------
class AttachBody(BaseModel):
    formulation_id: int
    allow_archived: bool = False  # arşivli formül bağlamaya izin verilsin mi?

# ---------------- Services ----------------
@router.post("/services/{service_id}/attach-formulation")
def attach_formulation_to_service(service_id: int, body: AttachBody):
    with _db() as cx:
        _ensure_exists(cx, "scenario_services", service_id)
        f = _get_formulation(cx, body.formulation_id)
        if not f:
            raise HTTPException(404, "formulation not found")
        if (f["is_archived"] or 0) == 1 and not body.allow_archived:
            raise HTTPException(409, "cannot attach archived formulation (set allow_archived=true to override)")

        # bağla
        cx.execute(
            "UPDATE scenario_services SET formulation_id=? WHERE id=?",
            (body.formulation_id, service_id)
        )
        cx.commit()

        # dönüş
        svc = cx.execute(
            "SELECT id, service_name, formulation_id FROM scenario_services WHERE id=?",
            (service_id,)
        ).fetchone()
        return {
            "service_id": svc["id"],
            "service_name": svc["service_name"],
            "formulation_id": svc["formulation_id"],
            "formulation_code": f["code"],
        }

@router.post("/services/{service_id}/detach-formulation")
def detach_formulation_from_service(service_id: int):
    with _db() as cx:
        _ensure_exists(cx, "scenario_services", service_id)
        cx.execute("UPDATE scenario_services SET formulation_id=NULL WHERE id=?", (service_id,))
        cx.commit()
        return {"service_id": service_id, "detached": True}

# ---------------- BOQ Items ----------------
@router.post("/boq-items/{item_id}/attach-formulation")
def attach_formulation_to_boq_item(item_id: int, body: AttachBody):
    with _db() as cx:
        _ensure_exists(cx, "scenario_boq_items", item_id)
        f = _get_formulation(cx, body.formulation_id)
        if not f:
            raise HTTPException(404, "formulation not found")
        if (f["is_archived"] or 0) == 1 and not body.allow_archived:
            raise HTTPException(409, "cannot attach archived formulation (set allow_archived=true to override)")

        cx.execute(
            "UPDATE scenario_boq_items SET formulation_id=? WHERE id=?",
            (body.formulation_id, item_id)
        )
        cx.commit()

        item = cx.execute(
            "SELECT id, item_name, formulation_id FROM scenario_boq_items WHERE id=?",
            (item_id,)
        ).fetchone()
        return {
            "boq_item_id": item["id"],
            "item_name": item["item_name"],
            "formulation_id": item["formulation_id"],
            "formulation_code": f["code"],
        }

@router.post("/boq-items/{item_id}/detach-formulation")
def detach_formulation_from_boq_item(item_id: int):
    with _db() as cx:
        _ensure_exists(cx, "scenario_boq_items", item_id)
        cx.execute("UPDATE scenario_boq_items SET formulation_id=NULL WHERE id=?", (item_id,))
        cx.commit()
        return {"boq_item_id": item_id, "detached": True}

# ---------------- Usage report ----------------
@router.get("/formulations/{fid}/usage")
def formulation_usage(fid: int):
    with _db() as cx:
        f = _get_formulation(cx, fid)
        if not f:
            raise HTTPException(404, "formulation not found")

        svc = cx.execute(
            "SELECT id, service_name FROM scenario_services WHERE formulation_id=? LIMIT 50",
            (fid,)
        ).fetchall()
        boq = cx.execute(
            "SELECT id, item_name FROM scenario_boq_items WHERE formulation_id=? LIMIT 50",
            (fid,)
        ).fetchall()

        return {
            "formulation_id": fid,
            "formulation_code": f["code"],
            "is_archived": int(f["is_archived"] or 0),
            "service_count": len(svc),
            "boq_item_count": len(boq),
            "services": [{"id": r["id"], "service_name": r["service_name"]} for r in svc],
            "boq_items": [{"id": r["id"], "item_name": r["item_name"]} for r in boq],
        }
