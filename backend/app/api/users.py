# backend/app/api/users.py

from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..models import User
from .deps import get_db, get_current_user, CurrentUser, require_permissions
from ..core.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

DEFAULT_ROLE = "member"  # ← None gelirse kullanılacak güvenli değer


# ---------------------------
# Pydantic Schemas
# ---------------------------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    role_name: Optional[str] = None
    is_active: Optional[bool] = True


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    role_name: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    tenant_id: int
    email: EmailStr
    role_name: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # Pydantic v2


def serialize_user(u: User) -> Dict[str, Any]:
    return {
        "id": getattr(u, "id", None),
        "tenant_id": getattr(u, "tenant_id", None),
        "email": getattr(u, "email", None),
        "role_name": getattr(u, "role_name", None),
        "is_active": getattr(u, "is_active", None),
        "created_at": getattr(u, "created_at", None),
    }


class PageMeta(BaseModel):
    total: int
    page: int
    size: int
    pages: int


class UsersListOut(BaseModel):
    meta: PageMeta
    items: List[UserOut]


# ---------------------------
# Endpoints
# ---------------------------

@router.get(
    "/",
    response_model=UsersListOut,
    summary="List Users",
    dependencies=[Depends(require_permissions(["users:read"]))],
)
def list_users(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search in email/role"),
):
    q = db.query(User).filter(User.tenant_id == current.tenant_id)

    if search:
        like = f"%{search.lower()}%"
        q = q.filter(
            or_(
                User.email.ilike(like),
                func.coalesce(User.role_name, "").ilike(like),
            )
        )

    total = q.count()
    rows = (
        q.order_by(User.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    pages = (total + size - 1) // size if size else 1

    return UsersListOut(
        meta=PageMeta(total=total, page=page, size=size, pages=pages),
        items=[UserOut.model_validate(serialize_user(u)) for u in rows],
    )


# ... üst kısım aynı ...

@router.post(
    "/",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create User",
    dependencies=[Depends(require_permissions(["users:create"]))],
)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    exists = (
        db.query(User)
        .filter(User.tenant_id == current.tenant_id, User.email == body.email.lower())
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Email already exists")

    role_name = body.role_name or DEFAULT_ROLE

    user_kwargs = dict(
        tenant_id=current.tenant_id,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role_name=role_name,
    )

    # 🔧 SADECE modelde böyle bir kolon varsa is_active'i set et
    if body.is_active is not None and hasattr(User, "is_active"):
        user_kwargs["is_active"] = bool(body.is_active)

    user = User(**user_kwargs)

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserOut.model_validate(serialize_user(user))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="User violates a DB constraint") from e
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Database error while creating user") from e


@router.get(
    "/{user_id}",
    response_model=UserOut,
    summary="Get User",
    dependencies=[Depends(require_permissions(["users:read"]))],
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == current.tenant_id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(serialize_user(user))


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="Update User (partial)",
    dependencies=[Depends(require_permissions(["users:write"]))],
)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == current.tenant_id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Email değişirse benzersizlik kontrolü
    if body.email and body.email.lower() != getattr(user, "email", None):
        exists = (
            db.query(User)
            .filter(User.tenant_id == current.tenant_id, User.email == body.email.lower())
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="Email already exists")

    if body.email is not None:
        user.email = body.email.lower()
    if body.role_name is not None:
        # None gelirse default kullan
        user.role_name = body.role_name or DEFAULT_ROLE
    if body.is_active is not None and hasattr(user, "is_active"):
        user.is_active = bool(body.is_active)
    if body.password:
        user.password_hash = hash_password(body.password)

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserOut.model_validate(serialize_user(user))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="User violates a DB constraint") from e
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Database error while updating user") from e


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete User",
    dependencies=[Depends(require_permissions(["users:write"]))],
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == current.tenant_id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    # 204 No Content
