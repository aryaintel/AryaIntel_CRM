# backend/app/api/leads.py

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from .deps import get_db, get_current_user, CurrentUser, require_permissions
from ..models import Lead, Account, Opportunity, Contact  # ← Contact eklendi
from .deals import resolve_stage_id  # stage çözümleme

router = APIRouter(prefix="/leads", tags=["leads"])

# ---------------------------
# Pydantic Schemas
# ---------------------------

class LeadCreate(BaseModel):
    name: str
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None   # New | Working | Nurturing | Unqualified | Converted
    source: Optional[str] = None
    rating: Optional[str] = None   # Hot | Warm | Cold
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    rating: Optional[str] = None
    notes: Optional[str] = None


class LeadOut(BaseModel):
    id: int
    tenant_id: int
    owner_id: int
    owner_email: Optional[str] = None

    name: str
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None

    status: Optional[str] = None
    source: Optional[str] = None
    rating: Optional[str] = None
    notes: Optional[str] = None

    converted_contact_id: Optional[int] = None          # ← eklendi
    converted_account_id: Optional[int] = None
    converted_opportunity_id: Optional[int] = None
    converted_at: Optional[datetime] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConvertLeadIn(BaseModel):
    # "Contact only" modu:
    create_contact_only: bool = False

    # Hesap seçimi/oluşturma:
    account_id: Optional[int] = None
    create_account: bool = True

    # Opportunity (yalnızca account yolunda anlamlı)
    create_opportunity: bool = True
    opportunity_name: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    stage_id: Optional[int] = None  # if None -> first stage of default pipeline


class ConvertLeadOut(BaseModel):
    lead_id: int
    contact_id: Optional[int] = None                  # ← eklendi
    account_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    status: str


# ---------------------------
# Helpers
# ---------------------------

def _guard_admin_or_owner(lead: Lead, current: CurrentUser):
    if current.role_name == "admin":
        return
    if lead.owner_id == current.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only admin or lead owner can modify this lead",
    )


def _serialize(lead: Lead) -> LeadOut:
    return LeadOut.model_validate(
        {
            "id": lead.id,
            "tenant_id": lead.tenant_id,
            "owner_id": lead.owner_id,
            "owner_email": getattr(getattr(lead, "owner", None), "email", None),

            "name": lead.name,
            "company": lead.company,
            "email": lead.email,
            "phone": lead.phone,
            "title": lead.title,

            "status": lead.status,
            "source": lead.source,
            "rating": getattr(lead, "rating", None),
            "notes": lead.notes,

            "converted_contact_id": getattr(lead, "converted_contact_id", None),   # ← eklendi
            "converted_account_id": getattr(lead, "converted_account_id", None),
            "converted_opportunity_id": getattr(lead, "converted_opportunity_id", None),
            "converted_at": getattr(lead, "converted_at", None),

            "created_at": lead.created_at,
            "updated_at": lead.updated_at,
        }
    )


# ---------------------------
# Endpoints
# ---------------------------

@router.get(
    "/",
    summary="List Leads",
    dependencies=[Depends(require_permissions(["leads:read"]))],
)
def list_leads(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    q: Optional[str] = None,
    status_f: Optional[str] = Query(None, alias="status"),
    owner_id: Optional[int] = None,
):
    qs = (
        db.query(Lead)
        .options(joinedload(Lead.owner))
        .filter(Lead.tenant_id == current.tenant_id)
    )
    if q:
        like = f"%{q}%"
        qs = qs.filter(Lead.name.ilike(like))
    if status_f:
        qs = qs.filter(Lead.status == status_f)
    if owner_id:
        qs = qs.filter(Lead.owner_id == owner_id)

    total = qs.count()
    rows: List[Lead] = (
        qs.order_by(Lead.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = [_serialize(r) for r in rows]

    # Accounts endpointi ile aynı meta formatı
    pages = (total + size - 1) // size if size else 1
    meta = {
        "page": page,
        "size": size,
        "total": total,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }
    return {"items": items, "meta": meta}


@router.post(
    "/",
    summary="Create Lead",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(["leads:write"]))],
)
def create_lead(
    body: LeadCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    lead = Lead(
        tenant_id=current.tenant_id,
        owner_id=current.id,
        name=body.name,
        company=body.company,
        email=body.email,
        phone=body.phone,
        title=body.title,
        status=body.status or "New",
        source=body.source,
        rating=body.rating,
        notes=body.notes,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return _serialize(lead)


@router.get(
    "/{lead_id}",
    summary="Get Lead",
    dependencies=[Depends(require_permissions(["leads:read"]))],
)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    lead = (
        db.query(Lead)
        .options(joinedload(Lead.owner))
        .filter(Lead.id == lead_id, Lead.tenant_id == current.tenant_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _serialize(lead)


@router.patch(
    "/{lead_id}",
    summary="Update Lead",
    dependencies=[Depends(require_permissions(["leads:write"]))],
)
def update_lead(
    lead_id: int,
    body: LeadUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    lead = (
        db.query(Lead)
        .filter(Lead.id == lead_id, Lead.tenant_id == current.tenant_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    _guard_admin_or_owner(lead, current)

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(lead, k, v)

    db.commit()
    db.refresh(lead)
    return _serialize(lead)


@router.delete(
    "/{lead_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Lead",
    dependencies=[Depends(require_permissions(["leads:write"]))],
)
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    lead = (
        db.query(Lead)
        .filter(Lead.id == lead_id, Lead.tenant_id == current.tenant_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    _guard_admin_or_owner(lead, current)

    db.delete(lead)
    db.commit()
    # 204


@router.post(
    "/{lead_id}/convert",
    summary="Convert Lead → Contact / Account (+ Opportunity opsiyonel)",
    response_model=ConvertLeadOut,
    dependencies=[Depends(require_permissions(["leads:write"]))],
)
def convert_lead(
    lead_id: int,
    body: ConvertLeadIn,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    lead = (
        db.query(Lead)
        .filter(Lead.id == lead_id, Lead.tenant_id == current.tenant_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    _guard_admin_or_owner(lead, current)

    # Already converted?
    if lead.status == "Converted":
        return ConvertLeadOut(
            lead_id=lead.id,
            contact_id=getattr(lead, "converted_contact_id", None),
            account_id=getattr(lead, "converted_account_id", None),
            opportunity_id=getattr(lead, "converted_opportunity_id", None),
            status="already_converted",
        )

    # ---------- CONTACT ONLY PATH ----------
    if body.create_contact_only:
        # 1) Var olan account kullanılabilir; yoksa minimal bireysel account aç
        account_id: Optional[int] = body.account_id
        account: Optional[Account] = None

        if account_id is not None:
            account = (
                db.query(Account)
                .filter(Account.id == account_id, Account.tenant_id == current.tenant_id)
                .first()
            )
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")
        else:
            # Minimal bireysel hesap (FK zorunlu)
            acc_name = lead.company or lead.name or f"Lead {lead.id}"
            account = Account(
                tenant_id=current.tenant_id,
                name=acc_name,
                phone=lead.phone,
                website=None,
                owner_id=current.id,
            )
            db.add(account)
            db.flush()
            account_id = account.id

        # 2) Contact oluştur
        contact = Contact(
            tenant_id=current.tenant_id,
            account_id=account_id,
            owner_id=current.id,
            name=lead.name,
            email=lead.email,
            phone=lead.phone,
            title=lead.title,
            notes=lead.notes,
        )
        db.add(contact)
        db.flush()

        # 3) Lead’i işaretle
        lead.status = "Converted"
        lead.converted_contact_id = contact.id
        lead.converted_account_id = account_id
        lead.converted_opportunity_id = None
        lead.converted_at = datetime.utcnow()

        db.commit()
        db.refresh(lead)

        return ConvertLeadOut(
            lead_id=lead.id,
            contact_id=contact.id,
            account_id=account_id,
            opportunity_id=None,
            status="converted_contact_only",
        )

    # ---------- DEFAULT PATH (Account (+ Opportunity opsiyonel)) ----------
    # --- ACCOUNT ---
    account_id: Optional[int] = body.account_id
    account: Optional[Account] = None

    if account_id is not None:
        account = (
            db.query(Account)
            .filter(Account.id == account_id, Account.tenant_id == current.tenant_id)
            .first()
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
    elif body.create_account:
        acc_name = lead.company or lead.name or f"Lead {lead.id}"
        account = Account(
            tenant_id=current.tenant_id,
            name=acc_name,
            phone=lead.phone,
            website=None,
            owner_id=current.id,
        )
        db.add(account)
        db.flush()
        account_id = account.id

    # --- OPPORTUNITY (optional) ---
    opportunity_id: Optional[int] = None
    if body.create_opportunity and account_id:
        opp_name = body.opportunity_name or (lead.company or lead.name or f"Lead {lead.id}")
        stage_resolved_id = resolve_stage_id(db, current.tenant_id, body.stage_id)

        opp = Opportunity(
            tenant_id=current.tenant_id,
            account_id=account_id,
            owner_id=current.id,
            name=opp_name,
            amount=body.amount,
            currency=body.currency or "USD",
            stage_id=stage_resolved_id,
            expected_close_date=None,
            source=lead.source,
        )
        db.add(opp)
        db.flush()
        opportunity_id = opp.id

    # Lead’i işaretle
    lead.status = "Converted"
    lead.converted_account_id = account_id
    lead.converted_opportunity_id = opportunity_id
    # contact_only olmadığı için converted_contact_id set edilmez
    lead.converted_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    return ConvertLeadOut(
        lead_id=lead.id,
        contact_id=None,
        account_id=account_id,
        opportunity_id=opportunity_id,
        status="converted",
    )
