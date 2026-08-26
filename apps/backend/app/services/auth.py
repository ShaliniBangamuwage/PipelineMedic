from datetime import datetime, timedelta, timezone
import hashlib, secrets
import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Organization, OrganizationMember, OrganizationRole, RefreshToken, User

ALGORITHM="HS256"
def hash_password(password:str)->str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(password:str, hashed:str)->bool: return bcrypt.checkpw(password.encode(), hashed.encode())
def access_token(user_id:str)->str: return jwt.encode({"sub":user_id,"type":"access","exp":datetime.now(timezone.utc)+timedelta(minutes=settings.access_token_minutes)},settings.jwt_secret,algorithm=ALGORITHM)
def issue_refresh(db:Session,user_id:str)->str:
    raw=secrets.token_urlsafe(48); db.add(RefreshToken(user_id=user_id,token_hash=hashlib.sha256(raw.encode()).hexdigest(),expires_at=datetime.now(timezone.utc)+timedelta(days=settings.refresh_token_days))); return raw
def consume_refresh(db:Session,raw:str)->str|None:
    item=db.scalar(select(RefreshToken).where(RefreshToken.token_hash==hashlib.sha256(raw.encode()).hexdigest()))
    expires_at=item.expires_at.replace(tzinfo=timezone.utc) if item and item.expires_at.tzinfo is None else item.expires_at if item else None
    if not item or item.revoked_at or expires_at<datetime.now(timezone.utc): return None
    item.revoked_at=datetime.now(timezone.utc); return item.user_id
def organization_slug(name:str)->str: return "-".join(name.lower().split())
def create_account(db:Session,email:str,password:str,organization:str):
    if db.scalar(select(User).where(User.email==email.lower())): return None
    user=User(email=email.lower(),password_hash=hash_password(password)); org=Organization(name=organization,slug=organization_slug(organization)); db.add_all([user,org]); db.flush(); db.add(OrganizationMember(user_id=user.id,organization_id=org.id,role=OrganizationRole.OWNER.value)); return user
