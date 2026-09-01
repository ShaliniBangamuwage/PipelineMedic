import hashlib
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
import jwt
from app.core.config import settings
from app.db import get_db
from app.models import ApiKey, ApiUsageLog, OrganizationMember, OrganizationRole, User

ROLE_ORDER={OrganizationRole.VIEWER.value:0,OrganizationRole.DEVELOPER.value:1,OrganizationRole.ADMIN.value:2,OrganizationRole.OWNER.value:3}
LOCAL_API_RATE_LIMITS: dict[str, deque[float]] = {}


def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _rate_limit_headers() -> dict[str, str]:
    window_seconds = max(1, settings.api_key_rate_limit_window_seconds)
    limit = max(1, settings.api_key_rate_limit_per_minute)
    return {
        "Retry-After": str(window_seconds),
        "X-RateLimit-Limit": str(limit),
    }


def _raise_rate_limit_exceeded() -> None:
    raise HTTPException(429, "API rate limit exceeded", headers=_rate_limit_headers())


def _redis_api_key_limiter(api_key: ApiKey, limit: int) -> bool:
    if not settings.redis_url:
        return True
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        window = int(time.time() // settings.api_key_rate_limit_window_seconds)
        key_name = f"pipelinemedic:api-rate-limit:{api_key.id}:{window}"
        current = client.incr(key_name)
        if current == 1:
            client.expire(key_name, settings.api_key_rate_limit_window_seconds)
        return current <= limit
    except Exception:
        return True


def _in_memory_api_key_limiter(api_key: ApiKey, limit: int) -> bool:
    bucket = LOCAL_API_RATE_LIMITS.setdefault(api_key.id, deque())
    now = time.monotonic()
    window_seconds = max(1, settings.api_key_rate_limit_window_seconds)
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def _check_api_key_rate_limit(api_key: ApiKey) -> None:
    limit = max(1, settings.api_key_rate_limit_per_minute)
    if not _in_memory_api_key_limiter(api_key, limit):
        _raise_rate_limit_exceeded()
    if settings.redis_url and not _redis_api_key_limiter(api_key, limit):
        _raise_rate_limit_exceeded()


def _record_api_key_usage(db: Session, api_key: ApiKey, request: Request) -> None:
    if getattr(request.state, "_api_key_usage_logged", False):
        return
    request.state._api_key_usage_logged = True
    db.add(ApiUsageLog(
        api_key_id=api_key.id,
        organization_id=api_key.organization_id,
        method=request.method,
        endpoint=request.url.path,
        status_code=200,
    ))
    db.flush()


def _authenticate_api_key(request: Request, db: Session) -> tuple[ApiKey, str, str] | None:
    if hasattr(request.state, "_validated_api_key"):
        api_key = request.state._validated_api_key
        return api_key, request.state._validated_organization_id, api_key.role
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    raw = auth_header.split(" ", 1)[1].strip()
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") == "access":
            return None
    except jwt.PyJWTError:
        pass
    api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == _hash_api_key(raw)))
    if not api_key:
        raise HTTPException(401, "Invalid API key")
    if api_key.revoked_at or (api_key.expires_at and api_key.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)):
        raise HTTPException(401, "API key is revoked or expired")
    organization_id = request.headers.get("x-organization-id") or api_key.organization_id
    if organization_id and organization_id != api_key.organization_id:
        raise HTTPException(403, "API key does not belong to this organization")
    _check_api_key_rate_limit(api_key)
    api_key.last_used_at = datetime.now(timezone.utc)
    request.state._validated_api_key = api_key
    request.state._validated_organization_id = organization_id
    _record_api_key_usage(db, api_key, request)
    db.commit()
    return api_key, organization_id, api_key.role


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not settings.auth_enabled:
        return None
    header=request.headers.get("authorization", "")
    if not header:
        raise HTTPException(401, "Authentication required")
    try:
        payload=jwt.decode(header.removeprefix("Bearer "), settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access": raise ValueError
    except (jwt.PyJWTError, ValueError):
        try:
            api_key_context = _authenticate_api_key(request, db)
        except HTTPException:
            raise
        if api_key_context is not None:
            api_key, _, _ = api_key_context
            if api_key.created_by_user_id:
                user = db.get(User, api_key.created_by_user_id)
                if user:
                    return user
        raise HTTPException(401, "Authentication required")
    user=db.get(User, payload.get("sub"))
    if not user: raise HTTPException(401, "Authentication required")
    return user


def organization_context(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)) -> tuple[User|None,str|None,str|None]:
    if not settings.auth_enabled: return None, None, None
    api_key_context = _authenticate_api_key(request, db)
    if api_key_context is not None:
        _, organization_id, role = api_key_context
        return None, organization_id, role
    organization_id=request.headers.get("x-organization-id")
    if not organization_id:
        raise HTTPException(400, "An organization must be selected")
    if user is None:
        raise HTTPException(401, "Authentication required")
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
