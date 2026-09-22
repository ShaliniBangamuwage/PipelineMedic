from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib.parse import urlencode
import hashlib
import hmac
import jwt
import httpx
import secrets
import time
from app.core.config import settings
from app.db import get_db
from app.models import OAuthLoginState, Organization, OrganizationMember, OrganizationRole, User
from app.services.auth import access_token, consume_refresh, create_account, hash_password, issue_refresh, organization_slug, verify_password

router=APIRouter(prefix="/api/auth")
_login_attempts: dict[str,list[float]]={}
def check_rate_limit(key:str):
    now=time.monotonic(); attempts=[value for value in _login_attempts.get(key,[]) if now-value<60]
    if len(attempts)>=5: raise HTTPException(429,"Too many login attempts. Try again shortly.")
    attempts.append(now); _login_attempts[key]=attempts
class Register(BaseModel): email: EmailStr; password: str=Field(min_length=12); organization: str=Field(min_length=2,max_length=120)
class Login(BaseModel): email: EmailStr; password: str
class Refresh(BaseModel): refresh_token: str

OAUTH_STATE_COOKIE = "github_oauth_state"

def _frontend_base() -> str:
    return (settings.frontend_url or "http://localhost").split(",", 1)[0].strip().rstrip("/")


def _session_cookie_options() -> dict[str, object]:
    if settings.is_production:
        return {"secure": True, "samesite": "none", "httponly": True}
    return {"secure": False, "samesite": "lax", "httponly": True}


def _oauth_error(code: str) -> RedirectResponse:
    return RedirectResponse(f"{_frontend_base()}/login?{urlencode({'github_error': code})}", status_code=303)

def _github_configured() -> bool:
    return bool(settings.github_oauth_client_id and settings.github_oauth_client_secret and settings.github_oauth_callback_url)

def _github_exchange(code: str, code_verifier: str) -> str:
    response = httpx.post(
        "https://github.com/login/oauth/access_token",
        data={"client_id": settings.github_oauth_client_id, "client_secret": settings.github_oauth_client_secret,
              "code": code, "redirect_uri": settings.github_oauth_callback_url, "code_verifier": code_verifier},
        headers={"Accept": "application/json"}, timeout=15.0,
    )
    if response.status_code >= 400:
        raise ValueError("GitHub token exchange failed")
    token = response.json().get("access_token")
    if not token:
        raise ValueError("GitHub token exchange failed")
    return token


def _github_verified_email(profile: dict, email_records: object | None) -> str | None:
    records: list[dict[str, object]] = []
    if isinstance(email_records, list):
        for item in email_records:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip().lower()
            if not email or not item.get("verified"):
                continue
            records.append({"email": email, "primary": bool(item.get("primary"))})
    if records:
        primary = next((item["email"] for item in records if item["primary"]), None)
        return str(primary or records[0]["email"]) if primary or records[0] else None
    profile_email = str(profile.get("email") or "").strip().lower()
    return profile_email if profile_email and "@" in profile_email else None


def _github_identity(token: str) -> tuple[str, str, str]:
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
    response = httpx.get("https://api.github.com/user", headers=headers, timeout=15.0)
    if response.status_code >= 400:
        raise ValueError("Unable to verify GitHub account")
    profile = response.json()
    emails_response = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=15.0)
    email_records = []
    if emails_response.status_code < 400:
        try:
            payload = emails_response.json()
            if isinstance(payload, list):
                email_records = payload
        except ValueError:
            email_records = []
    email = _github_verified_email(profile, email_records)
    if not profile.get("id") or not profile.get("login") or not email:
        raise ValueError("GitHub account has no verified email. Please verify an email address in GitHub and retry.")
    return str(profile["id"]), str(profile["login"]), str(email).lower()

def _github_user(db: Session, github_id: str, login: str, email: str) -> User:
    user = db.scalar(select(User).where(User.github_user_id == github_id))
    if user:
        user.github_login = login
        return user
    user = db.scalar(select(User).where(User.email == email))
    if user:
        if user.github_user_id and user.github_user_id != github_id:
            raise ValueError("This email is already linked to another GitHub account")
        user.github_user_id = github_id
        user.github_login = login
        return user
    user = User(email=email, password_hash=hash_password(secrets.token_urlsafe(32)), github_user_id=github_id, github_login=login)
    db.add(user)
    db.flush()
    name = f"{login}'s Workspace"
    slug = organization_slug(name)
    if db.scalar(select(Organization).where(Organization.slug == slug)):
        slug = f"{slug}-{user.id[:8]}"
    org = Organization(name=name, slug=slug)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(user_id=user.id, organization_id=org.id, role=OrganizationRole.OWNER.value))
    return user

def tokens(response:Response,db:Session,user:User):
    refresh=issue_refresh(db,user.id); db.commit();
    cookie_options = _session_cookie_options()
    response.set_cookie("refresh_token", refresh, max_age=settings.refresh_token_days*86400, **cookie_options)
    return {"access_token": access_token(user.id), "token_type": "bearer"}
@router.post("/register")
def register(payload:Register,response:Response,db:Session=Depends(get_db)):
    user=create_account(db,payload.email,payload.password,payload.organization)
    if not user: raise HTTPException(400,"Unable to create account")
    return tokens(response,db,user)
@router.post("/login")
def login(payload:Login,response:Response,db:Session=Depends(get_db)):
    check_rate_limit(payload.email.lower())
    user=db.scalar(select(User).where(User.email==payload.email.lower()))
    if not user or not verify_password(payload.password,user.password_hash): raise HTTPException(401,"Invalid email or password")
    return tokens(response,db,user)
@router.post("/refresh")
def refresh(request:Request,response:Response,payload:Refresh|None=None,db:Session=Depends(get_db)):
    user_id=consume_refresh(db,(payload.refresh_token if payload else None) or request.cookies.get("refresh_token", ""))
    if not user_id: raise HTTPException(401,"Invalid refresh token")
    user=db.get(User,user_id); return tokens(response,db,user)
@router.post("/logout")
def logout(request:Request,response:Response,db:Session=Depends(get_db)):
    raw=request.cookies.get("refresh_token")
    if raw: consume_refresh(db,raw); db.commit()
    response.delete_cookie("refresh_token"); return {"ok":True}

@router.get("/github")
def github_start(db: Session = Depends(get_db)):
    if not _github_configured():
        raise HTTPException(503, "GitHub authentication is not configured")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.add(OAuthLoginState(state_hash=hashlib.sha256(state.encode()).hexdigest(), code_verifier=verifier,
                           expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.github_oauth_state_ttl_seconds)))
    db.commit()
    params = {"client_id": settings.github_oauth_client_id, "redirect_uri": settings.github_oauth_callback_url,
              "scope": "read:user user:email", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    response = RedirectResponse("https://github.com/login/oauth/authorize?" + urlencode(params), status_code=307)
    cookie_options = _session_cookie_options()
    response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=settings.github_oauth_state_ttl_seconds, **cookie_options)
    return response

@router.get("/github/callback")
def github_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                   request: Request = None, db: Session = Depends(get_db)):
    if error:
        return _oauth_error("GitHub authorization was cancelled.")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE) if request else None
    if not code or not state:
        raise HTTPException(400, "Invalid GitHub authentication state")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    record = db.scalar(select(OAuthLoginState).where(OAuthLoginState.state_hash == state_hash))
    if cookie_state is not None and not hmac.compare_digest(state, cookie_state):
        raise HTTPException(400, "Invalid GitHub authentication state")
    expires_at = record.expires_at.replace(tzinfo=timezone.utc) if record and record.expires_at.tzinfo is None else record.expires_at if record else None
    if not record or record.used_at or not expires_at or expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired GitHub authentication state")
    record.used_at = datetime.now(timezone.utc)
    db.commit()
    try:
        token = _github_exchange(code, record.code_verifier)
        github_id, login, email = _github_identity(token)
        user = _github_user(db, github_id, login, email)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _oauth_error(str(exc))
    response = RedirectResponse(f"{_frontend_base()}/overview", status_code=303)
    tokens(response, db, user)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response
@router.get("/me")
def me(request:Request,db:Session=Depends(get_db)):
    value=request.headers.get("authorization","")
    try:
        claims=jwt.decode(value.removeprefix("Bearer "),settings.jwt_secret,algorithms=["HS256"])
        if claims.get("type")!="access": raise jwt.InvalidTokenError
        user_id=claims["sub"]
    except jwt.PyJWTError: raise HTTPException(401,"Authentication required")
    user=db.get(User,user_id)
    if not user: raise HTTPException(401,"Authentication required")
    memberships=db.scalars(select(OrganizationMember).where(OrganizationMember.user_id==user.id)).all()
    return {"id":user.id,"email":user.email,"organizations":[{"id":m.organization_id,"role":m.role} for m in memberships]}
