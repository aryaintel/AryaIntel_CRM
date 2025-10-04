from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from .deps import get_db, get_current_user
from ..models import (
    Scenario,
    ScenarioBOQItem,
    ScenarioOverhead,   # TWC assumptions live here
    ScenarioCapex,
    ScenarioService,
)

router = APIRouter(
    prefix="/scenarios",
    tags=["workflow"],
)

# -------------------------- Helpers & order --------------------------

# Readiness stages (Index & Escalation are ungated, so not part of flags)
STAGES = [
    "boq",
    "twc",
    # (index, escalation) are ungated – user can go anytime
    "capex",
    "fx",
    "tax",
    "services",
    "rebates",
    "rise_fall",
    "summary",  # aka PL
]
STAGE_TO_FLAG = {
    "boq": "boq_ready",
    "twc": "twc_ready",
    "capex": "capex_ready",
    "fx": "fx_ready",
    "tax": "tax_ready",
    "services": "services_ready",
    "rebates": "rebates_ready",
    "rise_fall": "rise_fall_ready",
    "summary": "summary_ready",
}

# legacy workflow_state → cumulative readiness
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
            (ScenarioService.is_active.is_(True)) | (ScenarioService.is_active.is_(None)),
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
        v = getattr(obj, name)
        return bool(v) if v is not None else default
    except Exception:
        return default


def _try_set_flag(obj: Scenario, name: str, value: bool) -> None:
    """Set attribute if present (old schemas may miss columns)."""
    try:
        setattr(obj, name, value)
    except Exception:
        pass


def _derive_from_state(state: str) -> Dict[str, bool]:
    """Backward compatible derivation from legacy workflow_state."""
    s = state or "draft"
    idx = STATE_IDX.get(s, 0)
    return {
        "boq_ready": idx >= STATE_IDX["twc_ready"],
        "twc_ready": idx >= STATE_IDX["capex_ready"],
        "capex_ready": idx >= STATE_IDX["fx_ready"],
        "fx_ready": idx >= STATE_IDX["tax_ready"],
        "tax_ready": idx >= STATE_IDX["services_ready"],
        "services_ready": idx >= STATE_IDX["ready"],
        # not tracked in legacy:
        "rebates_ready": False,
        "rise_fall_ready": False,
        "summary_ready": idx >= STATE_IDX["ready"],
    }


def _flags_from_model(sc: Scenario) -> Dict[str, bool]:
    state = getattr(sc, "workflow_state", "draft") or "draft"
    derived = _derive_from_state(state)
    flags = {
        "boq_ready":       _coalesce_bool(sc, "is_boq_ready",       derived["boq_ready"]),
        "twc_ready":       _coalesce_bool(sc, "is_twc_ready",       derived["twc_ready"]),
        "capex_ready":     _coalesce_bool(sc, "is_capex_ready",     derived["capex_ready"]),
        "fx_ready":        _coalesce_bool(sc, "is_fx_ready",        derived["fx_ready"]),
        "tax_ready":       _coalesce_bool(sc, "is_tax_ready",       derived["tax_ready"]),
        "services_ready":  _coalesce_bool(sc, "is_services_ready",  derived["services_ready"]),
        "rebates_ready":   _coalesce_bool(sc, "is_rebates_ready",   derived["rebates_ready"]),
        "rise_fall_ready": _coalesce_bool(sc, "is_rise_fall_ready", derived["rise_fall_ready"]),
        "summary_ready":   _coalesce_bool(sc, "is_summary_ready",   derived["summary_ready"]),
    }
    return flags


def _status_payload(sc: Scenario, flags: Dict[str, bool]) -> Dict[str, Any]:
    # first incomplete stage → current_stage
    current = None
    for stage in STAGES:
        if not flags[STAGE_TO_FLAG[stage]]:
            current = stage
            break
    if not current:
        current = "summary"

    i = STAGES.index(current)
    next_stage = STAGES[i + 1] if i + 1 < len(STAGES) else None

    return {
        **flags,
        "current_stage": current,
        "next_stage": next_stage,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HTTPException(status_code=422, detail=message)


def _persist_stage(db: Session, sc: Scenario, stage: str) -> Dict[str, bool]:
    """Mark stage as ready; sync legacy workflow_state best-effort."""
    flag_name = f"is_{STAGE_TO_FLAG[stage]}"
    _try_set_flag(sc, flag_name, True)

    ws_map = {
        "twc": "twc_ready",
        "capex": "capex_ready",
        "fx": "fx_ready",
        "tax": "tax_ready",
        "services": "services_ready",
        "summary": "ready",
    }
    if stage in ws_map:
        sc.workflow_state = ws_map[stage]

    db.add(sc)
    db.commit()
    db.refresh(sc)
    return _flags_from_model(sc)

# -------------------------- Routes --------------------------

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
    flags = _flags_from_model(sc)
    return _status_payload(sc, flags)


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
    flags = _flags_from_model(sc)

    _require(flags["boq_ready"], "BOQ must be marked ready first.")
    cnt = _counts(db, scenario_id)
    _require(cnt["boq_active"] > 0, "At least one active BOQ item is required.")

    flags = _persist_stage(db, sc, "twc")
    return _status_payload(sc, flags)


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
    flags = _flags_from_model(sc)

    _require(flags["twc_ready"], "TWC must be marked ready first.")
    cnt = _counts(db, scenario_id)
    _require(cnt["capex_active"] > 0, "At least one CAPEX item is required.")

    flags = _persist_stage(db, sc, "capex")
    return _status_payload(sc, flags)


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
    flags = _flags_from_model(sc)
    _require(flags["capex_ready"], "CAPEX must be marked ready first.")

    flags = _persist_stage(db, sc, "fx")
    return _status_payload(sc, flags)


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
    flags = _flags_from_model(sc)
    _require(flags["fx_ready"], "FX must be marked ready first.")

    flags = _persist_stage(db, sc, "tax")
    return _status_payload(sc, flags)


@router.post(
    "/{scenario_id}/workflow/mark-services-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark SERVICES as ready (requires TAX ready & at least one active service) and move forward",
)
def mark_services_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    flags = _flags_from_model(sc)
    _require(flags["tax_ready"], "TAX must be marked ready first.")
    cnt = _counts(db, scenario_id)
    _require(cnt["services_active"] > 0, "At least one active service item is required.")

    flags = _persist_stage(db, sc, "services")
    return _status_payload(sc, flags)


@router.post(
    "/{scenario_id}/workflow/mark-rebates-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark REBATES as ready (requires BOQ ready).",
)
def mark_rebates_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    flags = _flags_from_model(sc)
    _require(flags["boq_ready"], "BOQ must be marked ready first.")

    _try_set_flag(sc, "is_rebates_ready", True)
    db.add(sc); db.commit(); db.refresh(sc)

    flags = _flags_from_model(sc)
    return _status_payload(sc, flags)


@router.post(
    "/{scenario_id}/workflow/mark-rise-fall-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark RISE & FALL as ready (requires BOQ ready).",
)
def mark_rise_fall_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    flags = _flags_from_model(sc)
    _require(flags["boq_ready"], "BOQ must be marked ready first.")

    _try_set_flag(sc, "is_rise_fall_ready", True)
    db.add(sc); db.commit(); db.refresh(sc)

    flags = _flags_from_model(sc)
    return _status_payload(sc, flags)


@router.post(
    "/{scenario_id}/workflow/mark-summary-ready",
    status_code=status.HTTP_200_OK,
    summary="Mark SUMMARY (PL) as ready (requires SERVICES ready).",
)
def mark_summary_ready(
    scenario_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _user = Depends(get_current_user),
):
    sc = _get_scenario(db, scenario_id)
    flags = _flags_from_model(sc)
    _require(flags["services_ready"], "SERVICES must be marked ready first.")

    _try_set_flag(sc, "is_summary_ready", True)
    sc.workflow_state = "ready"   # legacy compatibility
    db.add(sc); db.commit(); db.refresh(sc)

    flags = _flags_from_model(sc)
    return _status_payload(sc, flags)


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

    for name in (
        "is_boq_ready", "is_twc_ready", "is_capex_ready", "is_fx_ready",
        "is_tax_ready", "is_services_ready", "is_rebates_ready",
        "is_rise_fall_ready", "is_summary_ready"
    ):
        _try_set_flag(sc, name, False)

    sc.workflow_state = "draft"
    db.add(sc); db.commit(); db.refresh(sc)

    flags = _flags_from_model(sc)
    return _status_payload(sc, flags)
