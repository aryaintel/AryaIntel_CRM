from typing import List, Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, confloat
from sqlalchemy.orm import Session

from ..models import Scenario, BusinessCase, Opportunity, ScenarioOverhead
from .deps import get_db, get_current_user, CurrentUser, require_permissions

router = APIRouter(prefix="/business-cases", tags=["business-cases"])

# ---------------------------
# Pydantic Schemas
# ---------------------------

class OverheadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["fixed", "%_revenue"]
    amount: confloat(ge=0) = 0.0  # % ise 0..100 beklenir (iş kuralı kontrolü aşağıda)


class OverheadUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[Literal["fixed", "%_revenue"]] = None
    amount: Optional[confloat(ge=0)] = None


class OverheadOut(BaseModel):
    id: int
    scenario_id: int
    name: str
    type: str
    amount: float

    class Config:
        from_attributes = True


# ---------------------------
# Helpers
# ---------------------------

def _ensure_scenario_in_tenant(db: Session, tenant_id: int, scenario_id: int) -> Scenario:
    sc = (
        db.query(Scenario)
        .join(BusinessCase, Scenario.business_case_id == BusinessCase.id)
        .join(Opportunity, BusinessCase.opportunity_id == Opportunity.id)
        .filter(Scenario.id == scenario_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


def _ensure_overhead_in_tenant(db: Session, tenant_id: int, overhead_id: int) -> ScenarioOverhead:
    oh = (
        db.query(ScenarioOverhead)
        .join(Scenario, ScenarioOverhead.scenario_id == Scenario.id)
        .join(BusinessCase, Scenario.business_case_id == BusinessCase.id)
        .join(Opportunity, BusinessCase.opportunity_id == Opportunity.id)
        .filter(ScenarioOverhead.id == overhead_id, Opportunity.tenant_id == tenant_id)
        .first()
    )
    if not oh:
        raise HTTPException(status_code=404, detail="Overhead not found")
    return oh


def _serialize_overhead(oh: ScenarioOverhead) -> Dict[str, Any]:
    return {
        "id": oh.id,
        "scenario_id": oh.scenario_id,
        "name": oh.name,
        "type": oh.type,
        "amount": float(oh.amount or 0),
    }


# ---------------------------
# Endpoints
# ---------------------------

@router.get(
    "/scenarios/{scenario_id}/overheads",
    response_model=List[OverheadOut],
    summary="List Overheads for a Scenario",
    dependencies=[Depends(require_permissions(["cases:read"]))],
)
def list_overheads(
    scenario_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _ = _ensure_scenario_in_tenant(db, current.tenant_id, scenario_id)
    rows = (
        db.query(ScenarioOverhead)
        .filter(ScenarioOverhead.scenario_id == scenario_id)
        .order_by(ScenarioOverhead.id.asc())
        .all()
    )
    return [OverheadOut.model_validate(_serialize_overhead(r)) for r in rows]


@router.post(
    "/scenarios/{scenario_id}/overheads",
    response_model=OverheadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Overhead for a Scenario",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def create_overhead(
    scenario_id: int,
    body: OverheadCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _ = _ensure_scenario_in_tenant(db, current.tenant_id, scenario_id)

    # İş kuralı: yüzde türünde 0..100 bekleriz
    if body.type == "%_revenue" and not (0 <= body.amount <= 100):
        raise HTTPException(status_code=422, detail="Percentage overhead amount must be between 0 and 100")

    oh = ScenarioOverhead(
        scenario_id=scenario_id,
        name=body.name,
        type=body.type,
        amount=body.amount,
    )
    db.add(oh)
    db.commit()
    db.refresh(oh)
    return OverheadOut.model_validate(_serialize_overhead(oh))


@router.patch(
    "/overheads/{overhead_id}",
    response_model=OverheadOut,
    summary="Update Overhead (partial)",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def update_overhead(
    overhead_id: int,
    body: OverheadUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    oh = _ensure_overhead_in_tenant(db, current.tenant_id, overhead_id)

    data = body.model_dump(exclude_unset=True)
    if "type" in data and data["type"] not in ("fixed", "%_revenue"):
        raise HTTPException(status_code=422, detail="type must be 'fixed' or '%_revenue'")
    if data.get("type", oh.type) == "%_revenue" and "amount" in data:
        if not (0 <= float(data["amount"]) <= 100):
            raise HTTPException(status_code=422, detail="Percentage overhead amount must be between 0 and 100")

    for k, v in data.items():
        setattr(oh, k, v)

    db.commit()
    db.refresh(oh)
    return OverheadOut.model_validate(_serialize_overhead(oh))


@router.delete(
    "/overheads/{overhead_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Overhead",
    dependencies=[Depends(require_permissions(["cases:write"]))],
)
def delete_overhead(
    overhead_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    oh = _ensure_overhead_in_tenant(db, current.tenant_id, overhead_id)
    db.delete(oh)
    db.commit()
    return None
