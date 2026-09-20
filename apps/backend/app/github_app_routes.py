from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authz import organization_context, require_role
from app.core.config import settings
from app.db import get_db
from app.models import GitHubInstallation, GitHubInstallationState, OrganizationMember, Repository
from app.services.github_app import (
    GitHubAppClient,
    GitHubAppError,
    GitHubAppPermanentError,
    GitHubAppTemporaryError,
    configured,
    install_url,
)

router = APIRouter(prefix="/api/github/app")
logger = logging.getLogger("pipelinemedic.github_app_routes")


class ConnectRepository(BaseModel):
    installation_id: str = Field(min_length=1, max_length=80)
    repository_id: str = Field(min_length=1, max_length=80)


def _frontend_redirect(status: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.frontend_url.split(',', 1)[0].strip().rstrip('/')}/repositories?github_app={status}",
        status_code=303,
    )


def _installation_out(item: GitHubInstallation) -> dict:
    return {
        "id": item.id,
        "installationId": item.github_installation_id,
        "accountId": item.github_account_id,
        "accountLogin": item.github_account_login,
        "accountType": item.github_account_type,
        "repositorySelection": item.repository_selection,
        "active": item.active,
    }


def _repository_out(item: dict, connected_ids: set[str]) -> dict:
    owner = item.get("owner") or {}
    repository_id = str(item.get("id", ""))
    return {
        "id": repository_id,
        "name": item.get("name", ""),
        "fullName": item.get("full_name", ""),
        "owner": owner.get("login", ""),
        "private": bool(item.get("private")),
        "defaultBranch": item.get("default_branch") or "main",
        "htmlUrl": item.get("html_url", ""),
        "installationId": str(item.get("installation_id", "")),
        "alreadyConnected": repository_id in connected_ids,
    }


def _start_installation(db: Session, context) -> str:
    if not configured():
        raise HTTPException(503, "GitHub App is not configured")
    user, organization_id, _ = context
    raw_state = secrets.token_urlsafe(32)
    db.add(GitHubInstallationState(
        state_hash=hashlib.sha256(raw_state.encode()).hexdigest(),
        user_id=user.id,
        organization_id=organization_id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.github_app_state_ttl_seconds),
    ))
    db.commit()
    return install_url(raw_state)


@router.get("/install")
def start_installation(db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    return RedirectResponse(_start_installation(db, context), status_code=307)


@router.post("/install")
def start_installation_api(db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    return {"url": _start_installation(db, context)}


@router.get("/setup")
def complete_installation(
    installation_id: str | None = None,
    setup_action: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    if not installation_id:
        raise HTTPException(400, "Invalid GitHub App installation state")
    existing = db.scalar(select(GitHubInstallation).where(GitHubInstallation.github_installation_id == str(installation_id)))
    if not state:
        if setup_action != "update" or not existing:
            raise HTTPException(400, "Invalid GitHub App installation state")
        try:
            installation = GitHubAppClient().installation(installation_id)
        except GitHubAppTemporaryError as exc:
            logger.warning("GitHub App update verification failed: installation_id=%s category=temporary", installation_id)
            raise HTTPException(503, "GitHub App is temporarily unavailable") from exc
        except GitHubAppPermanentError as exc:
            logger.warning("GitHub App update verification failed: installation_id=%s status=%s category=github_rejected", installation_id, exc.status_code)
            raise HTTPException(400, "GitHub App installation could not be verified") from exc
        except GitHubAppError as exc:
            logger.warning("GitHub App update verification failed: installation_id=%s category=configuration", installation_id)
            raise HTTPException(400, "GitHub App installation could not be verified") from exc
        account = installation.get("account") or {}
        existing.github_account_id = str(account.get("id", existing.github_account_id))
        existing.github_account_login = account.get("login", existing.github_account_login)
        existing.github_account_type = account.get("type", existing.github_account_type)
        existing.repository_selection = installation.get("repository_selection", existing.repository_selection)
        existing.active = True
        db.commit()
        logger.info("GitHub App installation refreshed: installation_id=%s organization_id=%s category=update", installation_id, existing.organization_id)
        return _frontend_redirect("connected")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    pending = db.scalar(select(GitHubInstallationState).where(GitHubInstallationState.state_hash == state_hash))
    expires_at = pending.expires_at.replace(tzinfo=timezone.utc) if pending and pending.expires_at.tzinfo is None else pending.expires_at if pending else None
    if not pending or pending.used_at or not expires_at or expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired GitHub App installation state")
    pending.used_at = datetime.now(timezone.utc)
    if setup_action and setup_action not in {"install", "update"}:
        db.commit()
        return _frontend_redirect("cancelled")
    try:
        installation = GitHubAppClient().installation(installation_id)
    except GitHubAppTemporaryError as exc:
        db.rollback()
        raise HTTPException(503, "GitHub App is temporarily unavailable") from exc
    except (GitHubAppError, GitHubAppPermanentError) as exc:
        db.rollback()
        raise HTTPException(400, "GitHub App installation could not be verified") from exc
    account = installation.get("account") or {}
    if existing and existing.organization_id != pending.organization_id:
        db.rollback()
        raise HTTPException(403, "This GitHub App installation belongs to another organization")
    if not existing:
        existing = GitHubInstallation(
            organization_id=pending.organization_id,
            github_installation_id=str(installation_id),
            github_account_id=str(account.get("id", "")),
            github_account_login=account.get("login", ""),
            github_account_type=account.get("type", "User"),
            repository_selection=installation.get("repository_selection", "selected"),
            active=True,
        )
        db.add(existing)
    else:
        existing.github_account_id = str(account.get("id", existing.github_account_id))
        existing.github_account_login = account.get("login", existing.github_account_login)
        existing.github_account_type = account.get("type", existing.github_account_type)
        existing.repository_selection = installation.get("repository_selection", existing.repository_selection)
        existing.active = True
    db.commit()
    return _frontend_redirect("connected")


@router.get("/installations")
def list_installations(db: Session = Depends(get_db), context=Depends(organization_context)):
    organization_id = context[1]
    rows = db.scalars(select(GitHubInstallation).where(GitHubInstallation.organization_id == organization_id, GitHubInstallation.active).order_by(GitHubInstallation.created_at)).all()
    return {"items": [_installation_out(item) for item in rows]}


@router.get("/repositories")
def list_authorized_repositories(page: int = 1, page_size: int = 30, db: Session = Depends(get_db), context=Depends(organization_context)):
    organization_id = context[1]
    rows = db.scalars(select(GitHubInstallation).where(GitHubInstallation.organization_id == organization_id, GitHubInstallation.active).order_by(GitHubInstallation.created_at)).all()
    logger.info("GitHub App repository discovery: organization_id=%s installation_count=%s installation_ids=%s", organization_id, len(rows), [row.github_installation_id for row in rows])
    if not configured():
        return {"items": [], "page": page, "pageSize": page_size, "total": 0, "configured": False}
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    connected_ids = {str(value) for value in db.scalars(select(Repository.github_repository_id).where(Repository.organization_id == organization_id, Repository.github_repository_id.is_not(None))).all()}
    items = []
    try:
        for installation in rows:
            payload = GitHubAppClient().repositories(installation.github_installation_id, page=page, per_page=page_size)
            logger.info("GitHub App repository response: organization_id=%s installation_id=%s repository_selection=%s repository_count=%s", organization_id, installation.github_installation_id, payload.get("repository_selection"), len(payload.get("repositories", [])))
            for item in payload.get("repositories", []):
                item["installation_id"] = installation.github_installation_id
                items.append(_repository_out(item, connected_ids))
    except GitHubAppTemporaryError as exc:
        raise HTTPException(503, "GitHub App repository access is temporarily unavailable") from exc
    except GitHubAppError as exc:
        raise HTTPException(502, "GitHub App repository access failed") from exc
    logger.info("GitHub App repository discovery complete: organization_id=%s repository_count=%s repository_names=%s", organization_id, len(items), [item["fullName"] for item in items])
    return {"items": items, "page": page, "pageSize": page_size, "total": len(items), "configured": True}


@router.post("/repositories/connect")
def connect_authorized_repository(payload: ConnectRepository, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    organization_id = context[1]
    logger.info("GitHub App repository connect requested: organization_id=%s installation_id=%s repository_id=%s", organization_id, payload.installation_id, payload.repository_id)
    installation = db.scalar(select(GitHubInstallation).where(
        GitHubInstallation.github_installation_id == payload.installation_id,
        GitHubInstallation.organization_id == organization_id,
        GitHubInstallation.active,
    ))
    if not installation:
        raise HTTPException(404, "GitHub App installation not found")
    if not configured():
        raise HTTPException(503, "GitHub App is not configured")
    authorized = None
    try:
        for page in range(1, 21):
            result = GitHubAppClient().repositories(installation.github_installation_id, page=page, per_page=100)
            authorized = next((item for item in result.get("repositories", []) if str(item.get("id")) == payload.repository_id), None)
            if authorized or len(result.get("repositories", [])) < 100:
                break
    except GitHubAppTemporaryError as exc:
        raise HTTPException(503, "GitHub App repository access is temporarily unavailable") from exc
    except GitHubAppError as exc:
        raise HTTPException(502, "GitHub App repository access failed") from exc
    if not authorized:
        logger.warning("GitHub App repository connect rejected: organization_id=%s installation_id=%s repository_id=%s category=not_authorized", organization_id, payload.installation_id, payload.repository_id)
        raise HTTPException(403, "Repository is not authorized by this GitHub App installation")
    owner = (authorized.get("owner") or {}).get("login", "")
    name = authorized.get("name", "")
    item = db.scalar(select(Repository).where(
        Repository.organization_id == organization_id,
        func.lower(Repository.owner) == owner.lower(),
        func.lower(Repository.name) == name.lower(),
    ))
    if not item:
        item = Repository(organization_id=organization_id, owner=owner, name=name)
        db.add(item)
    item.default_branch = authorized.get("default_branch") or item.default_branch or "main"
    item.github_repository_id = payload.repository_id
    item.github_installation_id = installation.id
    item.credential_source = "GITHUB_APP"
    item.active = True
    db.commit()
    logger.info("GitHub App repository connected: organization_id=%s installation_id=%s repository=%s/%s", organization_id, payload.installation_id, owner, name)
    return {"id": item.id, "owner": item.owner, "name": item.name, "fullName": f"{item.owner}/{item.name}", "credentialSource": item.credential_source, "active": item.active}
