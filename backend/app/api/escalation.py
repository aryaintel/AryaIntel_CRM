from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

# Opsiyonel DB dependency (geleceğe hazır)
try:
    from sqlalchemy.orm import Session
    from ..core.db import get_db  # projenizde mevcutsa
except Exception:  # pragma: no cover
    Session = object  # type: ignore
    def get_db():     # type: ignore
        return None

router = APIRouter(tags=["Escalation-Resolve"])

class EscalationResolveItem(BaseModel):
    name: str
    scope: str
    method: str
    effective_pct: float
    source: Optional[str] = None
    matched_policy_id: Optional[int] = None

class EscalationResolveResponse(BaseModel):
    year: int
    month: int
    items: List[EscalationResolveItem] = []

@router.get(
    "/scenarios/{scenario_id}/escalation/resolve",
    response_model=EscalationResolveResponse,
)
def resolve_escalation(
    scenario_id: int,
    year: int = Query(..., ge=1900, le=2300),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """
    Önizleme: yıl/ay için efektif artışları döndürür.
    MVP: boş döner. Model/kurallar eklendiğinde hesaplama eklenecek.
    """
    return EscalationResolveResponse(year=year, month=month, items=[])
