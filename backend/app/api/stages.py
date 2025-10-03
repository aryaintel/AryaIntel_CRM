# backend/app/api/stages.py
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import asc

from .deps import get_db, get_current_user, CurrentUser, require_permissions
from ..models import Pipeline, Stage

router = APIRouter(prefix="/stages", tags=["stages"])


class StageOut(BaseModel):
    id: int
    name: str
    order_index: int
    pipeline_id: int
    pipeline_name: Optional[str] = None

    class Config:
        from_attributes = True


@router.get(
    "/",
    summary="List stages (optionally by pipeline)",
    response_model=List[StageOut],
    dependencies=[Depends(require_permissions(["deals:read"]))],
)
def list_stages(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
    pipeline_id: Optional[int] = Query(None, ge=1),
):
    q = (
        db.query(Stage, Pipeline.name.label("pipeline_name"))
        .join(Pipeline, Pipeline.id == Stage.pipeline_id)
        .filter(Pipeline.tenant_id == current.tenant_id)
    )
    if pipeline_id:
        q = q.filter(Stage.pipeline_id == pipeline_id)

    rows = q.order_by(asc(Pipeline.name), asc(Stage.order_index)).all()

    out: List[StageOut] = []
    for st, pipeline_name in rows:
        item = StageOut.model_validate(st)
        item.pipeline_name = pipeline_name
        out.append(item)
    return out
