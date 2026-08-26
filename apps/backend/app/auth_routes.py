from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
import jwt
import time
from app.core.config import settings
from app.db import get_db
from app.models import OrganizationMember, User
from app.services.auth import access_token, consume_refresh, create_account, issue_refresh, verify_password

router=APIRouter(prefix="/api/auth")
_login_attempts: dict[str,list[float]]={}
def check_rate_limit(key:str):
    now=time.monotonic(); attempts=[value for value in _login_attempts.get(key,[]) if now-value<60]
    if len(attempts)>=5: raise HTTPException(429,"Too many login attempts. Try again shortly.")
    attempts.append(now); _login_attempts[key]=attempts
class Register(BaseModel): email: EmailStr; password: str=Field(min_length=12); organization: str=Field(min_length=2,max_length=120)
class Login(BaseModel): email: EmailStr; password: str
class Refresh(BaseModel): refresh_token: str

def tokens(response:Response,db:Session,user:User):
    refresh=issue_refresh(db,user.id); db.commit(); response.set_cookie("refresh_token",refresh,httponly=True,secure=settings.app_env=="production",samesite="lax",max_age=settings.refresh_token_days*86400); return {"access_token":access_token(user.id),"token_type":"bearer"}
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
