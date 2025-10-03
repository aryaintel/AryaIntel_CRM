# backend/app/api/workflow.py
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from .deps import get_db, get_current_user
from ..models import (
    Scenario,
    ScenarioBOQItem,
    ScenarioOverhead,   # TWC varsayımları burada tutuluyor
    ScenarioCapex,
    ScenarioService,
)

router = APIRouter(
    prefix="/scenarios",
    tags=["workflow"],
)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

# Aşama sırası (ileri/geri uyumlu)
STATE_ORDER = [
    "draft",
    "boq_ready",
    "twc_ready",
    "capex_ready",
    "fx_ready",
    "tax_ready",
    "services_ready",
    "ready",
]
STATE_IDX = {s: i for i, s in enumerate(STATE_ORDER)}


def _get_scenario(db: Session, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _counts(db: Session, scenario_id: int) -> Dict[str, int]:
    boq_active = db.execute(
        select(func.count(ScenarioBOQItem.id)).where(
            ScenarioBOQItem.scenario_id == scenario_id,
            ScenarioBOQItem.is_active.is_(True),
        )
    ).scalar_one() or 0

    twc_rows = db.execute(
        select(func.count(ScenarioOverhead.id)).where(
            ScenarioOverhead.scenario_id == scenario_id
        )
    ).scalar_one() or 0

    capex_active = db.execute(
        select(func.count(ScenarioCapex.id)).where(
            ScenarioCapex.scenario_id == scenario_id,
            (ScenarioCapex.is_active.is_(True)) | (ScenarioCapex.is_active.is_(None)),
        )
    ).scalar_one() or 0

    services_active = db.execute(
        select(func.count(ScenarioService.id)).where(
            ScenarioService.scenario_id == scenario_id,
            ScenarioService.is_active.is_(True),
        )
    ).scalar_one() or 0

    return {
        "boq_active": int(boq_active),
        "twc_rows": int(twc_rows),
        "capex_active": int(capex_active),
        "services_active": int(services_active),
    }


def _coalesce_bool(obj: Scenario, name: str, default: bool = False) -> bool:
    try:
        return bool(getattr(obj, name))
    except Exception:
        return default


def _try_set_flag(obj: Scenario, name: str, value: bool) -> None:
    """Modelde alan yoksa sessizce geç (eski şema ihtimali)."""
    try:
        setattr(obj, name, value)
    except Exception:
        pass


def _derive_flags_from_state(state: str) -> Dict[str, bool]:
    """State değerinden kümülatif bayrakları türetir (geriye dönük uyum)."""
    s = state or "draft"
    idx = STATE_IDX.get(s, 0)
    return {
        "is_boq_ready": idx >= STATE_IDX["twc_ready"],
        "is_twc_ready": idx >= STATE_IDX["capex_ready"],
        "is_capex_ready": idx >= STATE_IDX["fx_ready"],
        "is_fx_ready": idx >= STATE_IDX["tax_ready"],
        "is_tax_ready": idx >= STATE_IDX["services_ready"],
        "is_services_ready": idx >= STATE_IDX["ready"],
    }


def _status_payload(sc: Scenario, c: Dict[str, int]) -> Dict[str, Any]:
    workflow_state = getattr(sc, "workflow_state", "draft") or "draft"
    derived = _derive_flags_from_state(workflow_state)

    is_boq_ready      = _coalesce_bool(sc, "is_boq_ready")      or derived["is_boq_ready"]
    is_twc_ready      = _coalesce_bool(sc, "is_twc_ready")      or derived["is_twc_ready"]
    is_capex_ready    = _coalesce_bool(sc, "is_capex_ready")    or derived["is_capex_ready"]
    is_fx_ready       = _coalesce_bool(sc, "is_fx_ready")       or derived["is_fx_ready"]
    is_tax_ready      = _coalesce_bool(sc, "is_tax_ready")      or derived["is_tax_ready"]
    is_services_ready = _coalesce_bool(sc, "is_services_ready") or derived["is_services_ready"]

    # Sıraya göre bir sonraki adım
    if not is_boq_ready:
        next_step = "boq"
    elif not is_twc_ready:
        next_step = "twc"
    elif not is_capex_ready:
        next_step = "capex"
    elif not is_fx_ready:
        next_step = "fx"
    elif not is_tax_ready:
        next_step = "tax"
    elif not is_services_ready:
        next_step = "services"
    else:
        next_step = "ready"

    return {
        "scenario_id": sc.id,
        "state": workflow_state,
        "flags": {
            "is_boq_ready": is_boq_ready,
            "is_twc_ready": is_twc_ready,
            "is_capex_ready": is_capex_ready,
            "is_fx_ready": is_fx_ready,
            "is_tax_ready": is_tax_ready,
            "is_services_ready": is_services_ready,
        },
        "counts": c,
        "next_step": next_step,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HTTPException(status_code=400, detail=message)

# -------------------------------------------------------------------
# GET /workflow  → durum
# -------------------------------------------------------------------
@router.get(
    "/{scenario_id}/workflow",
    summary="Get workflow status of a scenario",
)
def get_workflow_status(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    cnt = _counts(db, scenario_id)
    return _status_payload(sc, cnt)

# -------------------------------------------------------------------
# POST /workflow/mark-twc-ready (BOQ → TWC)
# -------------------------------------------------------------------
@router.post(
    "/{scenario_id}/workflow/mark-twc-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark TWC as ready (requires BOQ ready & active items) and move forward",
)
def mark_twc_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    cnt = _counts(db, scenario_id)

    _require(_coalesce_bool(sc, "is_boq_ready", False), "BOQ must be marked ready first.")
    _require(cnt["boq_active"] > 0, "At least one active BOQ item is required.")

    _try_set_flag(sc, "is_twc_ready", True)
    sc.workflow_state = "twc_ready"
    db.add(sc); db.commit(); db.refresh(sc)

    return _status_payload(sc, _counts(db, scenario_id))

# -------------------------------------------------------------------
# POST /workflow/mark-capex-ready (TWC → CAPEX)
# -------------------------------------------------------------------
@router.post(
    "/{scenario_id}/workflow/mark-capex-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark CAPEX as ready (requires TWC ready & at least one CAPEX item) and move forward",
)
def mark_capex_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    cnt = _counts(db, scenario_id)

    _require(_coalesce_bool(sc, "is_twc_ready", False), "TWC must be marked ready first.")
    _require(cnt["capex_active"] > 0, "At least one CAPEX item is required.")

    _try_set_flag(sc, "is_capex_ready", True)
    sc.workflow_state = "capex_ready"
    db.add(sc); db.commit(); db.refresh(sc)

    return _status_payload(sc, _counts(db, scenario_id))

# -------------------------------------------------------------------
# POST /workflow/mark-fx-ready (CAPEX → FX)
# -------------------------------------------------------------------
@router.post(
    "/{scenario_id}/workflow/mark-fx-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark FX as ready (requires CAPEX ready) and move to TAX",
)
def mark_fx_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)

    _require(_coalesce_bool(sc, "is_capex_ready", False), "CAPEX must be marked ready first.")

    _try_set_flag(sc, "is_fx_ready", True)        # kolon varsa işaretle
    sc.workflow_state = "fx_ready"
    db.add(sc); db.commit(); db.refresh(sc)

    return _status_payload(sc, _counts(db, scenario_id))

# -------------------------------------------------------------------
# POST /workflow/mark-tax-ready (FX → TAX)
# -------------------------------------------------------------------
@router.post(
    "/{scenario_id}/workflow/mark-tax-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark TAX as ready (requires FX ready) and move to SERVICES",
)
def mark_tax_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)

    state = getattr(sc, "workflow_state", "draft") or "draft"
    _require(STATE_IDX.get(state, 0) >= STATE_IDX["fx_ready"], "FX must be marked ready first.")

    _try_set_flag(sc, "is_tax_ready", True)       # kolon varsa işaretle
    sc.workflow_state = "tax_ready"
    db.add(sc); db.commit(); db.refresh(sc)

    return _status_payload(sc, _counts(db, scenario_id))

# -------------------------------------------------------------------
# POST /workflow/mark-services-ready (TAX → SERVICES → READY)
# -------------------------------------------------------------------
@router.post(
    "/{scenario_id}/workflow/mark-services-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark SERVICES as ready (requires TAX ready & at least one active service) and move to READY",
)
def mark_services_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    cnt = _counts(db, scenario_id)

    state = getattr(sc, "workflow_state", "draft") or "draft"
    _require(STATE_IDX.get(state, 0) >= STATE_IDX["tax_ready"], "TAX must be marked ready first.")
    _require(cnt["services_active"] > 0, "At least one active service item is required.")

    _try_set_flag(sc, "is_services_ready", True)
    sc.workflow_state = "ready"
    db.add(sc); db.commit(); db.refresh(sc)

    return _status_payload(sc, _counts(db, scenario_id))

# -------------------------------------------------------------------
# POST /workflow/reset  → draft
# -------------------------------------------------------------------
@router.post(
    "/{scenario_id}/workflow/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset workflow back to draft (flags cleared)",
)
def reset_workflow(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)

    for flag in ("is_boq_ready", "is_twc_ready", "is_capex_ready", "is_fx_ready", "is_tax_ready", "is_services_ready"):
        _try_set_flag(sc, flag, False)
    sc.workflow_state = "draft"

    db.add(sc); db.commit(); db.refresh(sc)

    return _status_payload(sc, _counts(db, scenario_id))
