from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .deps import get_db, get_current_user, CurrentUser, require_permissions
from ..models import Role

router = APIRouter(prefix="/roles", tags=["roles"])

# ---------- Schemas ----------
class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1)
    permissions: Optional[str] = None  # "accounts:read,accounts:write"

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    permissions: Optional[str] = None

class RoleOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    permissions: Optional[str] = None

    class Config:
        from_attributes = True  # pydantic v2

# ---------- Endpoints ----------
@router.get(
    "/",
    response_model=List[RoleOut],
    dependencies=[Depends(require_permissions(["roles:read"]))],
)
def list_roles(
    q: Optional[str] = Query(None, description="Search by role name"),
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    qs = db.query(Role).filter(Role.tenant_id == current.tenant_id)
    if q:
        like = f"%{q}%"
        qs = qs.filter(Role.name.ilike(like))
    return qs.order_by(Role.name.asc()).all()

@router.post(
    "/",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(["roles:write"]))],
)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    role = Role(
        tenant_id=current.tenant_id,
        name=body.name.strip(),
        permissions=(body.permissions or "").strip() or None,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role

@router.patch(
    "/{role_id}",
    response_model=RoleOut,
    dependencies=[Depends(require_permissions(["roles:write"]))],
)
def update_role(
    role_id: int,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    role = (
        db.query(Role)
        .filter(Role.id == role_id, Role.tenant_id == current.tenant_id)
        .first()
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        role.name = data["name"].strip()
    if "permissions" in data:
        perms = data["permissions"]
        role.permissions = (perms or "").strip() or None

    db.commit()
    db.refresh(role)
    return role

@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permissions(["roles:write"]))],
)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    role = (
        db.query(Role)
        .filter(Role.id == role_id, Role.tenant_id == current.tenant_id)
        .first()
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    db.delete(role)
    db.commit()
    return None
