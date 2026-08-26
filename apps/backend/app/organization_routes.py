from datetime import datetime, timedelta, timezone
import hashlib, re, secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.authz import current_user, organization_context, require_role
from app.core.config import settings
from app.db import get_db
from app.models import Invitation, Organization, OrganizationMember, OrganizationRole, User
from app.schemas import InvitationCreate, MemberUpdate, OrganizationCreate, OrganizationUpdate

router=APIRouter(prefix="/api")
roles={role.value for role in OrganizationRole}
def org_out(org): return {"id":org.id,"name":org.name,"slug":org.slug}
def slugify(name): return re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", name.lower()))
def require_auth(context):
    if not context[0]: raise HTTPException(401,"Authentication required")
    return context

@router.get("/organizations")
def list_orgs(user=Depends(current_user),db:Session=Depends(get_db)):
    if not user: raise HTTPException(401,"Authentication required")
    ids=select(OrganizationMember.organization_id).where(OrganizationMember.user_id==user.id)
    return {"items":[org_out(x) for x in db.scalars(select(Organization).where(Organization.id.in_(ids))).all()]}

@router.post("/organizations")
def create_org(payload:OrganizationCreate,user=Depends(current_user),db:Session=Depends(get_db)):
    if not user: raise HTTPException(401,"Authentication required")
    slug=slugify(payload.name)
    if db.scalar(select(Organization).where(Organization.slug==slug)): raise HTTPException(409,"Organization already exists")
    org=Organization(name=payload.name,slug=slug);db.add(org);db.flush();db.add(OrganizationMember(organization_id=org.id,user_id=user.id,role=OrganizationRole.OWNER.value));db.commit();return org_out(org)

@router.get("/organizations/{organization_id}")
def get_org(organization_id:str,context=Depends(organization_context),db:Session=Depends(get_db)):
    user,_,_=require_auth(context); member=db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==organization_id,OrganizationMember.user_id==user.id))
    org=db.get(Organization,organization_id) if member else None
    if not org: raise HTTPException(404,"Organization not found")
    return org_out(org)

@router.patch("/organizations/{organization_id}")
def update_org(organization_id:str,payload:OrganizationUpdate,context=Depends(require_role(OrganizationRole.ADMIN.value)),db:Session=Depends(get_db)):
    _,selected,_=context
    if selected!=organization_id: raise HTTPException(404,"Organization not found")
    org=db.get(Organization,organization_id);org.name=payload.name;org.slug=slugify(payload.name);db.commit();return org_out(org)

@router.delete("/organizations/{organization_id}")
def delete_org(organization_id:str,context=Depends(require_role(OrganizationRole.OWNER.value)),db:Session=Depends(get_db)):
    _,selected,_=context
    if selected!=organization_id: raise HTTPException(404,"Organization not found")
    org=db.get(Organization,organization_id);db.delete(org);db.commit();return {"deleted":True}

@router.get("/organizations/{organization_id}/members")
def members(organization_id:str,context=Depends(require_role(OrganizationRole.VIEWER.value)),db:Session=Depends(get_db)):
    _,selected,_=context
    if selected!=organization_id: raise HTTPException(404,"Organization not found")
    rows=db.execute(select(OrganizationMember,User).join(User,User.id==OrganizationMember.user_id).where(OrganizationMember.organization_id==organization_id)).all()
    return {"items":[{"id":m.id,"userId":u.id,"email":u.email,"role":m.role} for m,u in rows]}

@router.patch("/organizations/{organization_id}/members/{member_id}")
def update_member(organization_id:str,member_id:str,payload:MemberUpdate,context=Depends(require_role(OrganizationRole.ADMIN.value)),db:Session=Depends(get_db)):
    _,selected,actor_role=context
    if selected!=organization_id or payload.role not in roles or (payload.role==OrganizationRole.OWNER.value and actor_role!=OrganizationRole.OWNER.value): raise HTTPException(403,"Insufficient organization permissions")
    member=db.scalar(select(OrganizationMember).where(OrganizationMember.id==member_id,OrganizationMember.organization_id==organization_id))
    if not member: raise HTTPException(404,"Member not found")
    if member.role==OrganizationRole.OWNER.value and actor_role!=OrganizationRole.OWNER.value: raise HTTPException(403,"Only an owner may change an owner")
    if member.role==OrganizationRole.OWNER.value and payload.role!=member.role and not db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==organization_id,OrganizationMember.role==OrganizationRole.OWNER.value,OrganizationMember.id!=member.id)): raise HTTPException(400,"Organization must retain an owner")
    member.role=payload.role;db.commit();return {"id":member.id,"role":member.role}

@router.delete("/organizations/{organization_id}/members/{member_id}")
def remove_member(organization_id:str,member_id:str,context=Depends(require_role(OrganizationRole.ADMIN.value)),db:Session=Depends(get_db)):
    _,selected,actor_role=context
    if selected!=organization_id: raise HTTPException(404,"Organization not found")
    member=db.scalar(select(OrganizationMember).where(OrganizationMember.id==member_id,OrganizationMember.organization_id==organization_id))
    if not member: raise HTTPException(404,"Member not found")
    if member.role==OrganizationRole.OWNER.value and actor_role!=OrganizationRole.OWNER.value: raise HTTPException(403,"Only an owner may remove an owner")
    if member.role==OrganizationRole.OWNER.value and not db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==organization_id,OrganizationMember.role==OrganizationRole.OWNER.value,OrganizationMember.id!=member.id)): raise HTTPException(400,"Organization must retain an owner")
    db.delete(member);db.commit();return {"removed":True}

@router.post("/organizations/{organization_id}/invitations")
def invite(organization_id:str,payload:InvitationCreate,context=Depends(require_role(OrganizationRole.ADMIN.value)),db:Session=Depends(get_db)):
    user,selected,actor_role=context
    if selected!=organization_id or payload.role not in roles or (payload.role==OrganizationRole.OWNER.value and actor_role!=OrganizationRole.OWNER.value): raise HTTPException(403,"Insufficient organization permissions")
    email=payload.email.lower();existing_member=db.scalar(select(OrganizationMember).join(User).where(OrganizationMember.organization_id==organization_id,User.email==email))
    if existing_member or db.scalar(select(Invitation).where(Invitation.organization_id==organization_id,Invitation.email==email,Invitation.accepted_at.is_(None),Invitation.revoked_at.is_(None),Invitation.expires_at>datetime.now(timezone.utc))): raise HTTPException(409,"An active invitation already exists")
    raw=secrets.token_urlsafe(32); invitation=Invitation(organization_id=organization_id,email=email,role=payload.role,token_hash=hashlib.sha256(raw.encode()).hexdigest(),invited_by_user_id=user.id,expires_at=datetime.now(timezone.utc)+timedelta(days=7));db.add(invitation);db.commit();result={"id":invitation.id,"email":email,"role":payload.role,"expiresAt":invitation.expires_at.isoformat()}
    if settings.expose_invitation_urls and settings.app_env!="production": result["invitationUrl"]="/invitations/"+raw
    return result

@router.get("/organizations/{organization_id}/invitations")
def invitations(organization_id:str,context=Depends(require_role(OrganizationRole.ADMIN.value)),db:Session=Depends(get_db)):
    if context[1]!=organization_id: raise HTTPException(404,"Organization not found")
    return {"items":[{"id":x.id,"email":x.email,"role":x.role,"createdAt":x.created_at.isoformat(),"expiresAt":x.expires_at.isoformat(),"invitedByUserId":x.invited_by_user_id,"accepted":bool(x.accepted_at),"revoked":bool(x.revoked_at)} for x in db.scalars(select(Invitation).where(Invitation.organization_id==organization_id)).all()]}

@router.post("/invitations/{token}/accept")
def accept(token:str,user=Depends(current_user),db:Session=Depends(get_db)):
    if not user: raise HTTPException(401,"Authentication required")
    invitation=db.scalar(select(Invitation).where(Invitation.token_hash==hashlib.sha256(token.encode()).hexdigest()))
    if not invitation or invitation.accepted_at or invitation.revoked_at or invitation.expires_at<datetime.now(timezone.utc): raise HTTPException(400,"Invitation is invalid or expired")
    if user.email!=invitation.email: raise HTTPException(403,"Invitation email does not match current user")
    if not db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==invitation.organization_id,OrganizationMember.user_id==user.id)): db.add(OrganizationMember(organization_id=invitation.organization_id,user_id=user.id,role=invitation.role))
    invitation.accepted_at=datetime.now(timezone.utc);db.commit();return {"organizationId":invitation.organization_id,"accepted":True}

@router.delete("/organizations/{organization_id}/invitations/{invitation_id}")
def revoke(organization_id:str,invitation_id:str,context=Depends(require_role(OrganizationRole.ADMIN.value)),db:Session=Depends(get_db)):
    if context[1]!=organization_id: raise HTTPException(404,"Organization not found")
    item=db.scalar(select(Invitation).where(Invitation.id==invitation_id,Invitation.organization_id==organization_id));
    if not item: raise HTTPException(404,"Invitation not found")
    if item.accepted_at or item.revoked_at: raise HTTPException(400,"Invitation is no longer active")
    item.revoked_at=datetime.now(timezone.utc);db.commit();return {"revoked":True}