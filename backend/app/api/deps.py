# backend/app/api/deps.py
from typing import List, Set, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..core.config import SessionLocal
from ..models import User, Role
from ..core.security import decode_token

# Swagger'da "Authorize" için tek Bearer alanı
auth_scheme = HTTPBearer(auto_error=True)

# ---------------------------
# DB Session Dependency
# ---------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------------
# Current User DTO
# ---------------------------
class CurrentUser:
    def __init__(self, id: int, tenant_id: int, email: str, role_name: str):
        self.id = id
        self.tenant_id = tenant_id
        self.email = email
        self.role_name = role_name

# ---------------------------
# AuthN: Token → CurrentUser
# ---------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[int] = payload.get("sub")
    tenant_id: Optional[int] = payload.get("tenant")
    role_name_from_token: Optional[str] = payload.get("role")

    if user_id is None or tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        db.query(User)
        .filter(User.id == int(user_id), User.tenant_id == int(tenant_id))
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Token’daki rol yoksa/verilmemişse DB’deki rol adını kullan
    role_name = role_name_from_token or user.role_name or ""

    return CurrentUser(id=user.id, tenant_id=user.tenant_id, email=user.email, role_name=role_name)

# ---------------------------
# AuthZ: Permission Check
# ---------------------------

# Rol bazlı varsayılan izinler (DB'de boş olsa dahi uygulanır)
DEFAULT_ROLE_PERMS = {
    "admin": {"*", "roles:read", "roles:write"},  # admin her şeye sahip
    "member": {
        "accounts:read",
        "contacts:read",
        "deals:read",
        # gerekirse diğer read izinleri
    },
}

def _resolve_permissions(db_perms_raw: Optional[str], role_name: str) -> Set[str]:
    """
    DB'deki virgüllü izinleri parse eder ve DEFAULT_ROLE_PERMS ile birleştirir.
    """
    perms: Set[str] = set()
    if db_perms_raw:
        perms |= {p.strip() for p in db_perms_raw.split(",") if p.strip()}
    perms |= DEFAULT_ROLE_PERMS.get(role_name or "", set())
    return perms

def _perm_allows(perms: Set[str], needed: str) -> bool:
    """
    Genişletilmiş eşleşme:
      - birebir: needed ∈ perms
      - global wildcard: "*" ∈ perms
      - kaynak bazlı wildcard: "resource:*" ∈ perms  ↔  "resource:action" needed
    """
    if needed in perms or "*" in perms:
        return True
    if ":" in needed:
        resource, _ = needed.split(":", 1)
        return f"{resource}:*" in perms
    return False

def require_permissions(required: List[str]):
    """
    Kullanım:
      dependencies=[Depends(require_permissions(["accounts:read"]))]

    Mantık:
      - admin veya '*' → her şeye izin
      - required listesindeki herhangi biri, kullanıcının izinleri tarafından
        karşılanıyorsa (birebir ya da resource:* wildcard) → izin ver
    """
    required_set: Set[str] = set(required)

    def checker(
        current: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        role = (
            db.query(Role)
            .filter(Role.tenant_id == current.tenant_id, Role.name == current.role_name)
            .first()
        )

        role_name = role.name if role else current.role_name
        perms = _resolve_permissions(role.permissions if role else None, role_name)

        if role_name == "admin" or "*" in perms:
            return current

        if any(_perm_allows(perms, r) for r in required_set):
            return current

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    return checker
