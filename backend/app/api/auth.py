# backend/app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..models import Tenant, User, Role
from .deps import get_db
from ..core.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    tenant_name: str
    tenant_slug: str
    admin_email: EmailStr
    admin_password: str


class LoginIn(BaseModel):
    tenant_slug: str
    email: EmailStr
    password: str


@router.post("/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    # slug mevcut mu?
    if db.query(Tenant).filter(Tenant.slug == body.tenant_slug).first():
        raise HTTPException(status_code=400, detail="Tenant slug already exists")

    try:
        # tenant
        tenant = Tenant(name=body.tenant_name, slug=body.tenant_slug)
        db.add(tenant)
        db.flush()  # tenant.id lazım

        # rol
        admin_role = Role(tenant_id=tenant.id, name="admin", permissions="*")
        db.add(admin_role)

        # kullanıcı
        user = User(
            tenant_id=tenant.id,
            email=body.admin_email.lower(),
            password_hash=hash_password(body.admin_password),
            role_name="admin",
        )
        db.add(user)
        db.flush()  # 🔴 user.id kesinleşsin

        # token üretimi (id artık kesin var)
        token = create_access_token(subject=str(user.id), tenant_id=tenant.id, role_name="admin")
        db.commit()

        return {"access_token": token, "token_type": "bearer"}

    except IntegrityError:
        db.rollback()
        # Örn. aynı email tekrar girildiyse
        raise HTTPException(status_code=409, detail="Signup violates a DB constraint")


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.slug == body.tenant_slug).first()
    if not tenant:
        raise HTTPException(status_code=400, detail="Tenant not found")

    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.email == body.email.lower())
        .first()
    )
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=str(user.id), tenant_id=tenant.id, role_name=user.role_name)
    return {"access_token": token, "token_type": "bearer"}
