from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
import jwt
from app.core.config import settings
from app.db import get_db
from app.models import OrganizationMember, OrganizationRole, User

ROLE_ORDER={OrganizationRole.VIEWER.value:0,OrganizationRole.DEVELOPER.value:1,OrganizationRole.ADMIN.value:2,OrganizationRole.OWNER.value:3}

def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not settings.auth_enabled:
        return None
    header=request.headers.get("authorization", "")
    try:
        payload=jwt.decode(header.removeprefix("Bearer "), settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access": raise ValueError
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Authentication required")
    user=db.get(User, payload.get("sub"))
    if not user: raise HTTPException(401, "Authentication required")
    return user

def organization_context(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)) -> tuple[User|None,str|None,str|None]:
    if not settings.auth_enabled: return None, None, None
    organization_id=request.headers.get("x-organization-id")
    if not organization_id: raise HTTPException(400, "An organization must be selected")
    membership=db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==organization_id,OrganizationMember.user_id==user.id))
    if not membership: raise HTTPException(404, "Organization not found")
    return user, organization_id, membership.role

def require_role(minimum: str):
    def dependency(context=Depends(organization_context)):
        user, organization_id, role=context
        if settings.auth_enabled and ROLE_ORDER.get(role or "-", -1) < ROLE_ORDER[minimum]: raise HTTPException(403, "Insufficient organization permissions")
        return context
    return dependency

def ensure_strong_secret():
    if settings.auth_enabled and (len(settings.jwt_secret) < 32 or settings.jwt_secret == "development-only-change-me"):
        raise RuntimeError("JWT_SECRET must be at least 32 characters when AUTH_ENABLED=true")
