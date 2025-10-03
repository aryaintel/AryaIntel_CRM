# backend/app/api/deals.py

from typing import Optional, List
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import asc

from .deps import get_db, get_current_user, CurrentUser, require_permissions
from ..models import Account, Pipeline, Stage, Opportunity

router = APIRouter(prefix="/deals", tags=["deals"])


# ---------------------------
# Pydantic Şemalar
# ---------------------------

class DealCreate(BaseModel):
    account_id: int = Field(..., description="Deal must belong to an account")
    name: str
    amount: Optional[int] = None
    currency: Optional[str] = None
    expected_close_date: Optional[date] = None
    source: Optional[str] = None
    stage_id: Optional[int] = None  # verilmezse default pipeline'ın ilk stage'i atanır


class DealUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    expected_close_date: Optional[date] = None
    source: Optional[str] = None
    stage_id: Optional[int] = None
    # Not: owner_id / account_id update ile değiştirilmiyor (tasarım gereği)


class MoveStage(BaseModel):
    stage_id: int


class DealOut(BaseModel):
    id: int
    tenant_id: int
    account_id: int
    account_name: Optional[str] = None
    owner_id: int
    owner_email: Optional[str] = None
    name: str
    amount: Optional[int] = None
    currency: Optional[str] = None
    stage_id: int
    expected_close_date: Optional[date] = None
    source: Optional[str] = None

    # yeni alanlar
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Stages lookup için çıkış şeması ---
class StageOut(BaseModel):
    id: int
    no: int
    name: str

    class Config:
        from_attributes = True


# ---------------------------
# Yardımcılar
# ---------------------------

def ensure_default_pipeline(db: Session, tenant_id: int) -> Pipeline:
    """
    Tenant için 'Sales' isimli default pipeline yoksa oluşturur
    ve temel aşamaları ekler (hard-coded):
      0: Idea
      1: Business Case
      2: Negotiation
      3: Win / Lost
    """
    p = db.query(Pipeline).filter_by(tenant_id=tenant_id, name="Sales").first()
    if not p:
        p = Pipeline(tenant_id=tenant_id, name="Sales")
        db.add(p)
        db.flush()  # p.id gerekli

        defaults = [
            ("Idea",          0, 5),
            ("Business Case", 1, 25),
            ("Negotiation",   2, 60),
            ("Win / Lost",    3, 100),
        ]
        for n, order_idx, prob in defaults:
            db.add(
                Stage(
                    tenant_id=tenant_id,
                    pipeline_id=p.id,
                    name=n,
                    order_index=order_idx,
                    win_probability=prob,
                )
            )
        db.commit()
    return p


def resolve_stage_id(db: Session, tenant_id: int, stage_id: Optional[int]) -> int:
    """
    Verilen stage_id geçerliyse onu doğrular; verilmemişse
    default pipeline'ın ilk aşamasını döndürür.
    """
    if stage_id:
        st = (
            db.query(Stage)
            .join(Pipeline, Pipeline.id == Stage.pipeline_id)
            .filter(Stage.id == stage_id, Pipeline.tenant_id == tenant_id)
            .first()
        )
        if not st:
            raise HTTPException(status_code=400, detail="Invalid stage_id")
        return st.id

    p = ensure_default_pipeline(db, tenant_id)
    st = (
        db.query(Stage)
        .filter_by(pipeline_id=p.id)
        .order_by(asc(Stage.order_index))
        .first()
    )
    if not st:
        raise HTTPException(status_code=500, detail="No stages found for default pipeline")
    return st.id


def _ensure_account_in_tenant(db: Session, tenant_id: int, account_id: int) -> Account:
    acc = (
        db.query(Account)
        .filter(Account.id == account_id, Account.tenant_id == tenant_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return acc


def _guard_admin_or_owner(opp: Opportunity, current: CurrentUser):
    if current.role_name == "admin":
        return
    if opp.owner_id == current.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin or owner can modify this deal")


def _serialize(opp: Opportunity) -> DealOut:
    return DealOut.model_validate({
        "id": opp.id,
        "tenant_id": opp.tenant_id,
        "account_id": opp.account_id,
        "account_name": getattr(getattr(opp, "account", None), "name", None),
        "owner_id": opp.owner_id,
        "owner_email": getattr(getattr(opp, "owner", None), "email", None),
        "name": opp.name,
        "amount": opp.amount,
        "currency": opp.currency,
        "stage_id": opp.stage_id,
        "expected_close_date": opp.expected_close_date,
        "source": opp.source,
        # yeni eklenen alanlar
        "created_at": opp.created_at,
        "updated_at": opp.updated_at,
    })


# ---------------------------
# Endpoints
# ---------------------------

@router.get(
    "/",
    summary="List Deals",
    dependencies=[Depends(require_permissions(["deals:read"]))],
)
def list_deals(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: Optional[str] = None,
    stage_id: Optional[int] = None,
    account_id: Optional[int] = None,
):
    qs = (
        db.query(Opportunity)
        .options(joinedload(Opportunity.account), joinedload(Opportunity.owner))
        .filter(Opportunity.tenant_id == current.tenant_id)
    )
    if q:
        qs = qs.filter(Opportunity.name.ilike(f"%{q}%"))
    if stage_id:
        qs = qs.filter(Opportunity.stage_id == stage_id)
    if account_id:
        qs = qs.filter(Opportunity.account_id == account_id)

    total = qs.count()
    rows: List[Opportunity] = (
        qs.order_by(Opportunity.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [_serialize(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get(
    "/stages",
    summary="List available stages for default Sales pipeline",
    response_model=List[StageOut],
    dependencies=[Depends(require_permissions(["deals:read"]))],
)
def list_stages(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    p = ensure_default_pipeline(db, current.tenant_id)
    rows = (
        db.query(Stage)
        .filter(Stage.pipeline_id == p.id)
        .order_by(asc(Stage.order_index))
        .all()
    )
    return [StageOut(id=s.id, no=s.order_index, name=s.name) for s in rows]


@router.post(
    "/",
    summary="Create Deal",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(["deals:write"]))],
)
def create_deal(
    body: DealCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _ensure_account_in_tenant(db, current.tenant_id, body.account_id)
    st_id = resolve_stage_id(db, current.tenant_id, body.stage_id)

    opp = Opportunity(
        tenant_id=current.tenant_id,
        account_id=body.account_id,
        owner_id=current.id,  # current user owner
        name=body.name,
        amount=body.amount,
        currency=body.currency or "USD",
        stage_id=st_id,
        expected_close_date=body.expected_close_date,
        source=body.source,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return _serialize(opp)


@router.get(
    "/{deal_id}",
    summary="Get Deal",
    dependencies=[Depends(require_permissions(["deals:read"]))],
)
def get_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    d = (
        db.query(Opportunity)
        .options(joinedload(Opportunity.account), joinedload(Opportunity.owner))
        .filter(Opportunity.id == deal_id, Opportunity.tenant_id == current.tenant_id)
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")
    return _serialize(d)


@router.patch(
    "/{deal_id}",
    summary="Update Deal",
    dependencies=[Depends(require_permissions(["deals:write"]))],
)
def update_deal(
    deal_id: int,
    body: DealUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    d = (
        db.query(Opportunity)
        .filter(Opportunity.id == deal_id, Opportunity.tenant_id == current.tenant_id)
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")

    _guard_admin_or_owner(d, current)

    data = body.model_dump(exclude_unset=True)
    if "stage_id" in data:
        data["stage_id"] = resolve_stage_id(db, current.tenant_id, data["stage_id"])

    # account_id/owner_id client'tan değiştirilemez – varsa ignore et
    for blocked in ("account_id", "owner_id"):
        if blocked in data:
            data.pop(blocked, None)

    for k, v in data.items():
        setattr(d, k, v)

    db.commit()
    db.refresh(d)
    return _serialize(d)


@router.post(
    "/{deal_id}/move_stage",
    summary="Move Deal to another stage",
    dependencies=[Depends(require_permissions(["deals:write"]))],
)
def move_stage(
    deal_id: int,
    body: MoveStage,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    d = (
        db.query(Opportunity)
        .filter(Opportunity.id == deal_id, Opportunity.tenant_id == current.tenant_id)
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")

    _guard_admin_or_owner(d, current)

    d.stage_id = resolve_stage_id(db, current.tenant_id, body.stage_id)
    db.commit()
    db.refresh(d)
    return _serialize(d)


@router.delete(
    "/{deal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Deal",
    dependencies=[Depends(require_permissions(["deals:write"]))],
)
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    d = (
        db.query(Opportunity)
        .filter(Opportunity.id == deal_id, Opportunity.tenant_id == current.tenant_id)
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")

    _guard_admin_or_owner(d, current)

    db.delete(d)
    db.commit()
    # 204 No Content
