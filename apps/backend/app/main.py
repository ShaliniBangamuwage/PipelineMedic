from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.db import Base, engine, get_db, initialize_database
from app.models import ApiKey, ApiUsageLog, FailureAnalysis, GitHubInstallation, IncidentEmbedding, IncidentFeedback, Job, PatchDecision, PatchSuggestion, PRCommentDelivery, Repository, WorkflowRun
from app.services.jobs import enqueue as enqueue_job, out as job_out, publish, retry as retry_job, queue_depth, redis_health
import json
from app.schemas import ApiKeyCreate, ApiKeyOut, ApiKeyUsageItem, FeedbackCreate, RepositoryCreate, RepositoryUpdate, RepositoryVerify, ResolveCreate, WorkflowRunOut
from app.services.ai import analyze_with_fallback
from app.services.analyzer import compute_failure_fingerprint
from app.services.github import GitHubClient, GitHubClientError, GitHubPermanentError, GitHubTemporaryError
from app.services.log_processing import process_log
from app.services.similarity import find_similar
from app.services.embedding import provider_for_database
from app.auth_routes import router as auth_router
from app.github_app_routes import router as github_app_router
from app.organization_routes import router as organization_router
from app.authz import ensure_strong_secret
from app.authz import organization_context, require_role
from app.schemas import PRCommentSettings
from app.services.pr_comments import delivery_out, queue_delivery
from app.services.patch_validation import validate_unified_diff
from app.services.patch_generation import OpenAICompatiblePatchProvider, PatchProviderError, generate_and_validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("pipelinemedic")
app = FastAPI(title="PipelineMedic API", version="1.0.0")
app.add_middleware(CORSMiddleware,
                   allow_origins=settings.frontend_origins,
                   allow_origin_regex=settings.frontend_origin_regex or None,
                   allow_methods=["*"],
                   allow_headers=["*"],
                   allow_credentials=True)
app.include_router(auth_router)
app.include_router(organization_router)
app.include_router(github_app_router)
ensure_strong_secret()
initialize_database(engine)

def _parse_json_list(value):
    if value in (None, "", "null"):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def synchronize_analysis_fingerprint_metadata(db: Session, item: FailureAnalysis, fingerprint: str | None = None):
    if item.organization_id and item.repository_id and not item.fingerprint:
        item.fingerprint = fingerprint or compute_failure_fingerprint(
            item.category or "UNKNOWN",
            item.failed_step or "Workflow execution",
            "UNKNOWN",
            item.root_cause or item.summary or "",
            item.repository_id or "",
            item.summary or "",
        )
    elif fingerprint:
        item.fingerprint = fingerprint
    if not item.fingerprint:
        item.fingerprint = hashlib.sha256((item.category + "|" + (item.failed_step or "") + "|" + (item.summary or "") + "|" + (item.root_cause or "") + "|" + (item.cleaned_log or "")).encode("utf-8")).hexdigest()

    item.first_seen = item.first_seen or item.created_at or datetime.now(timezone.utc)
    item.last_seen = item.last_seen or item.created_at or datetime.now(timezone.utc)
    if item.organization_id and item.repository_id:
        matches = db.scalars(
            select(FailureAnalysis).where(
                FailureAnalysis.organization_id == item.organization_id,
                FailureAnalysis.repository_id == item.repository_id,
                FailureAnalysis.fingerprint == item.fingerprint,
            ).order_by(FailureAnalysis.created_at.asc())
        ).all()
        if matches:
            item.occurrence_count = len(matches) + (0 if any(m.id == item.id for m in matches) else 1)
            item.first_seen = min((match.first_seen or match.created_at for match in matches if match.first_seen or match.created_at), default=item.first_seen)
            item.last_seen = max((match.last_seen or match.created_at for match in matches if match.last_seen or match.created_at), default=item.last_seen)
        else:
            item.occurrence_count = max(item.occurrence_count or 1, 1)
    else:
        item.occurrence_count = max(item.occurrence_count or 1, 1)
    item.status = "RESOLVED" if item.resolved else "OPEN"
    return item


def out(item: FailureAnalysis):
    return {"id": item.id, "summary": item.summary, "rootCause": item.root_cause, "category": item.category,
            "severity": item.severity, "confidence": item.confidence, "source": item.source,
            "workflowName": item.workflow_name, "branch": item.branch, "commitSha": item.commit_sha,
            "failedStep": item.failed_step, "failedCommand": item.failed_command, "cleanedLog": item.cleaned_log,
            "evidence": item.raw_log_excerpt.splitlines() if item.raw_log_excerpt else [],
            "suggestedActions": _parse_json_list(getattr(item, "suggested_actions", None)),
            "fingerprint": item.fingerprint,
            "occurrenceCount": item.occurrence_count or 1,
            "firstSeen": item.first_seen.isoformat() if item.first_seen else None,
            "lastSeen": item.last_seen.isoformat() if item.last_seen else None,
            "status": item.status or ("RESOLVED" if item.resolved else "OPEN"),
            "resolved": item.resolved,
            "resolvedAt": item.resolved_at.isoformat() if item.resolved_at else None,
            "resolvedBy": item.resolved_by,
            "resolutionNote": item.resolution_note,
            "analysisTimeMinutes": float(item.analysis_time_minutes or 0),
            "resolutionTimeMinutes": float(item.resolution_time_minutes or 0), "actualSolution": item.actual_solution,
            "createdAt": item.created_at.isoformat() if item.created_at else None,
            "repository": f"{item.repository.owner}/{item.repository.name}" if item.repository else None}

def workflow_run_out(item: WorkflowRun):
    return {"id": item.id, "repository_id": item.repository_id, "github_run_id": item.github_run_id,
            "github_run_url": item.github_run_url, "workflow_name": item.workflow_name, "branch": item.branch,
            "head_sha": item.head_sha, "status": item.status, "conclusion": item.conclusion,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None}


def repo_out(item: Repository, db: Session):
    count = db.scalar(select(func.count()).where(FailureAnalysis.repository_id == item.id)) or 0
    last = db.scalar(select(func.max(FailureAnalysis.created_at)).where(FailureAnalysis.repository_id == item.id))
    return {"id": item.id, "owner": item.owner, "name": item.name, "fullName": f"{item.owner}/{item.name}",
            "defaultBranch": item.default_branch, "active": item.active, "failureCount": count,
            "lastFailure": last.isoformat() if last else None, "prCommentsEnabled": item.pr_comments_enabled,
            "prCommentMinConfidence": item.pr_comment_min_confidence, "prCommentAllowedBranches": item.pr_comment_allowed_branches,
            "prCommentIncludeSimilarIncident": item.pr_comment_include_similar_incident, "prCommentIncludePatch": item.pr_comment_include_patch,
            "githubTokenConfigured": bool(item.github_token), "webhookSecretConfigured": bool(item.webhook_secret),
            "credentialSource": item.credential_source, "githubAppConnected": item.credential_source == "GITHUB_APP" and bool(item.github_installation_id)}

def repo_setup_out(item: Repository, db: Session, webhook_secret: str | None = None):
    result = repo_out(item, db)
    if webhook_secret:
        result["webhookSecret"] = webhook_secret
        result["webhookSecretShownOnce"] = True
    return result


def resolve_repository_token(repository: Repository | None, db: Session | None = None) -> str:
    if repository and repository.credential_source == "GITHUB_APP":
        if not db or not repository.github_installation_id:
            raise ValueError("GitHub App installation is not configured for this repository")
        installation = db.get(GitHubInstallation, repository.github_installation_id)
        if not installation or not installation.active:
            raise ValueError("GitHub App installation is no longer active")
        from app.services.github_app import GitHubAppError, installation_token
        try:
            return installation_token(installation.github_installation_id)
        except GitHubAppError as exc:
            raise ValueError("GitHub App installation token could not be created") from exc
    if repository and repository.github_token and repository.github_token.strip():
        return repository.github_token.strip()
    raise ValueError("Repository GitHub token is not configured")


def resolve_repository_webhook_secret(repository: Repository | None) -> str:
    if repository and repository.webhook_secret:
        return repository.webhook_secret
    raise ValueError("Repository webhook secret is not configured")


def find_webhook_repository(db: Session, owner: str, name: str, *, installation_id: str | None = None, github_repository_id: str | None = None) -> Repository | None:
    owner_name = (owner or "").strip()
    repo_name = (name or "").strip()
    if not owner_name or not repo_name:
        return None

    matches = db.scalars(
        select(Repository).where(
            func.lower(Repository.owner) == owner_name.lower(),
            func.lower(Repository.name) == repo_name.lower(),
            Repository.active.is_(True),
        )
    ).all()
    if len(matches) == 1:
        return matches[0]

    if github_repository_id:
        exact_matches = [item for item in matches if str(item.github_repository_id or "") == str(github_repository_id)]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            raise HTTPException(409, "Multiple repositories match this webhook identity; repository ownership is ambiguous")

    if installation_id:
        installation_matches = db.scalars(
            select(Repository).join(GitHubInstallation, Repository.github_installation_id == GitHubInstallation.id).where(
                func.lower(Repository.owner) == owner_name.lower(),
                func.lower(Repository.name) == repo_name.lower(),
                Repository.active.is_(True),
                GitHubInstallation.github_installation_id == str(installation_id),
                GitHubInstallation.active.is_(True),
            )
        ).all()
        if len(installation_matches) == 1:
            return installation_matches[0]
        if len(installation_matches) > 1:
            raise HTTPException(409, "Multiple repositories match this webhook installation; repository ownership is ambiguous")

    if matches:
        raise HTTPException(409, "Multiple repositories match this webhook; repository ownership is ambiguous")
    return None

def scoped_repository(repository_id: str, db: Session, context):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    return item


def require_repository_credentials(repository: Repository | None, *, token_name: str = "GitHub token") -> str:
    try:
        token = resolve_repository_token(repository).strip()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return token

@app.get("/api/repositories/{repository_id}/pr-comment-settings")
def get_pr_settings(repository_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = scoped_repository(repository_id, db, context)
    return PRCommentSettings(pr_comments_enabled=item.pr_comments_enabled, pr_comment_min_confidence=item.pr_comment_min_confidence,
                             pr_comment_allowed_branches=item.pr_comment_allowed_branches, pr_comment_include_similar_incident=item.pr_comment_include_similar_incident,
                             pr_comment_include_patch=item.pr_comment_include_patch)

@app.patch("/api/repositories/{repository_id}/pr-comment-settings")
def update_pr_settings(repository_id: str, payload: PRCommentSettings, db: Session = Depends(get_db), context=Depends(require_role("ADMIN"))):
    item = scoped_repository(repository_id, db, context)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    db.commit(); db.refresh(item)
    return get_pr_settings(repository_id, db, context)

@app.get("/api/analyses/{analysis_id}/pr-comment")
def get_pr_comment(analysis_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    analysis = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1]))
    if not analysis: raise HTTPException(404, "Analysis not found")
    item = db.scalar(select(PRCommentDelivery).where(PRCommentDelivery.analysis_id == analysis_id, PRCommentDelivery.organization_id == context[1]))
    return delivery_out(item)

@app.post("/api/analyses/{analysis_id}/pr-comment/retry")
def retry_pr_comment(analysis_id: str, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    item = db.scalar(select(PRCommentDelivery).where(PRCommentDelivery.analysis_id == analysis_id, PRCommentDelivery.organization_id == context[1]))
    if not item: raise HTTPException(404, "PR comment delivery not found")
    if item.status == "DELIVERED": raise HTTPException(400, "PR comment already delivered")
    item.status = "QUEUED"; item.last_error_code = None; item.last_error_message = None; db.commit()
    enqueue_job(db, "PR_COMMENT_DELIVERY", item.organization_id, None, item.id)
    return delivery_out(item)

def patch_out(item: PatchSuggestion):
    return {"id": item.id, "analysisId": item.analysis_id, "status": item.status, "provider": item.provider, "model": item.model,
            "unifiedDiff": item.unified_diff, "explanation": item.explanation, "confidence": item.confidence, "riskLevel": item.risk_level,
            "affectedFiles": json.loads(item.affected_files or "[]"), "validationErrors": json.loads(item.validation_errors or "[]")}

@app.post("/api/analyses/{analysis_id}/generate-patch")
def generate_patch(analysis_id: str, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    analysis = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1]))
    if not analysis: raise HTTPException(404, "Analysis not found")
    existing = db.scalar(select(PatchSuggestion).where(PatchSuggestion.analysis_id == analysis_id, PatchSuggestion.organization_id == context[1], PatchSuggestion.status.in_(["REQUESTED", "GENERATING", "READY"])))
    if existing: return patch_out(existing)
    item = PatchSuggestion(organization_id=context[1], repository_id=analysis.repository_id, analysis_id=analysis_id, provider="pending", model=settings.groq_model, status="REQUESTED", explanation="Awaiting safe patch generation.", risk_level="HIGH")
    if not settings.patch_generation_enabled or not settings.groq_api_key:
        item.status = "FAILED"; item.explanation = "Patch generation is unavailable until an approved provider is configured."
    db.add(item); db.commit(); db.refresh(item)
    if item.status == "REQUESTED": enqueue_job(db, "PATCH_GENERATION", context[1], None, item.id)
    return patch_out(item)

@app.get("/api/analyses/{analysis_id}/patches")
def list_patches(analysis_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    query = select(PatchSuggestion).where(PatchSuggestion.analysis_id == analysis_id)
    if context[1]: query = query.where(PatchSuggestion.organization_id == context[1])
    return {"items": [patch_out(item) for item in db.scalars(query).all()]}

@app.get("/api/patches/{patch_id}")
def get_patch(patch_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(PatchSuggestion).where(PatchSuggestion.id == patch_id, PatchSuggestion.organization_id == context[1])) if context[1] else db.get(PatchSuggestion, patch_id)
    if not item: raise HTTPException(404, "Patch not found")
    return patch_out(item)

@app.patch("/api/patches/{patch_id}/decision")
def decide_patch(patch_id: str, payload: dict, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    item = db.scalar(select(PatchSuggestion).where(PatchSuggestion.id == patch_id, PatchSuggestion.organization_id == context[1]))
    if not item: raise HTTPException(404, "Patch not found")
    if item.status != "READY" or payload.get("decision") not in ("ACCEPTED", "REJECTED"): raise HTTPException(400, "Patch is not ready for this decision")
    db.add(PatchDecision(patch_id=item.id, user_id=context[0].id, decision=payload["decision"], feedback=str(payload.get("feedback", ""))[:500])); db.commit()
    return {"patchId": item.id, "decision": payload["decision"]}

@app.get("/api/patches/{patch_id}/download")
def download_patch(patch_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    from fastapi.responses import PlainTextResponse
    item = db.scalar(select(PatchSuggestion).where(PatchSuggestion.id == patch_id, PatchSuggestion.organization_id == context[1])) if context[1] else db.get(PatchSuggestion, patch_id)
    if not item: raise HTTPException(404, "Patch not found")
    if item.status != "READY": raise HTTPException(409, "Patch is not ready")
    return PlainTextResponse(item.unified_diff, media_type="text/x-diff", headers={"Content-Disposition": "attachment; filename=pipelinemedic.patch"})

@app.get("/api/api-keys")
def list_api_keys(db: Session = Depends(get_db), context=Depends(require_role("ADMIN"))):
    items = db.scalars(select(ApiKey).where(ApiKey.organization_id == context[1]).order_by(ApiKey.created_at.desc())).all()
    return {"items": [{
        "id": item.id,
        "name": item.name,
        "role": item.role,
        "organizationId": item.organization_id,
        "createdAt": item.created_at.isoformat(),
        "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
        "revoked": bool(item.revoked_at),
    } for item in items]}

@app.post("/api/api-keys")
def create_api_key(payload: ApiKeyCreate, db: Session = Depends(get_db), context=Depends(require_role("ADMIN"))):
    raw = secrets.token_urlsafe(32)
    item = ApiKey(
        organization_id=context[1],
        name=payload.name,
        role=payload.role.upper(),
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        created_by_user_id=context[0].id if context[0] else None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days),
    )
    db.add(item); db.commit(); db.refresh(item)
    return {
        "id": item.id,
        "name": item.name,
        "role": item.role,
        "organizationId": item.organization_id,
        "createdAt": item.created_at.isoformat(),
        "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
        "key": raw,
    }

@app.get("/api/api-keys/{api_key_id}/usage")
def api_key_usage(api_key_id: str, db: Session = Depends(get_db), context=Depends(require_role("ADMIN"))):
    item = db.scalar(select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.organization_id == context[1]))
    if not item: raise HTTPException(404, "API key not found")
    rows = db.scalars(select(ApiUsageLog).where(ApiUsageLog.api_key_id == api_key_id).order_by(ApiUsageLog.created_at.desc())).all()
    return {"items": [{
        "id": row.id,
        "method": row.method,
        "endpoint": row.endpoint,
        "statusCode": row.status_code,
        "createdAt": row.created_at.isoformat(),
    } for row in rows]}

@app.delete("/api/api-keys/{api_key_id}")
def delete_api_key(api_key_id: str, db: Session = Depends(get_db), context=Depends(require_role("ADMIN"))):
    item = db.scalar(select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.organization_id == context[1]))
    if not item: raise HTTPException(404, "API key not found")
    item.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": item.id, "revoked": True}

@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "PipelineMedic API", "version": "1.0.0"}
@app.get("/api/health/worker")
def worker_health():
    configured = bool(settings.redis_url)
    connected = redis_health() if configured else None
    return {"status":"ready" if not configured or connected else "degraded", "mode":"redis" if configured else "inline",
            "redisConfigured":configured, "redisConnected":connected, "consumerAvailable":not configured or connected,
            "queueName":settings.redis_queue_name if configured else None, "queueDepth":queue_depth() if configured and connected else None}
@app.get("/api/jobs")
def jobs(db:Session=Depends(get_db),context=Depends(organization_context)):
    query=select(Job).order_by(Job.created_at.desc())
    if context[1]: query=query.where(Job.organization_id==context[1])
    return {"items":[job_out(item) for item in db.scalars(query).all()]}
@app.get("/api/jobs/failed")
def failed_jobs(db:Session=Depends(get_db),context=Depends(organization_context)):
    query=select(Job).where(Job.status == "FAILED_PERMANENT").order_by(Job.updated_at.desc())
    if context[1]: query=query.where(Job.organization_id==context[1])
    return {"items":[job_out(item) for item in db.scalars(query).all()]}
@app.get("/api/jobs/{job_id}")
def job_detail(job_id:str,db:Session=Depends(get_db),context=Depends(organization_context)):
    item=db.scalar(select(Job).where(Job.id==job_id,Job.organization_id==context[1])) if context[1] else db.get(Job,job_id)
    if not item: raise HTTPException(404,"Job not found")
    return job_out(item)
@app.post("/api/jobs/{job_id}/retry")
def retry(job_id:str,db:Session=Depends(get_db),context=Depends(require_role("DEVELOPER"))):
    item=db.scalar(select(Job).where(Job.id==job_id,Job.organization_id==context[1])) if context[1] else db.get(Job,job_id)
    if not item: raise HTTPException(404,"Job not found")
    if item.status not in ("FAILED", "FAILED_PERMANENT"):
        raise HTTPException(400,"Job is not in a retryable failed state")
    item.status = "QUEUED"
    item.attempts = 0
    item.error_message = None
    item.next_retry_at = None
    db.commit();db.refresh(item)
    if settings.redis_url:
        try: publish(item.id)
        except Exception: pass
    return job_out(item)

@app.get("/api/dashboard/queue-status")
def queue_status(db: Session = Depends(get_db), context=Depends(organization_context)):
    query = select(Job.status, func.count(Job.id).label("count")).group_by(Job.status)
    if context[1]: query = query.where(Job.organization_id == context[1])
    rows = db.execute(query).all()
    counts = {status: int(count) for status, count in rows}
    durations = db.execute(
        select(Job.kind, func.avg(func.extract('epoch', Job.updated_at) - func.extract('epoch', Job.created_at)).label("avg_seconds"))
        .where(Job.status == "COMPLETED")
        .group_by(Job.kind)
    ).all()
    avg_processing_seconds = 0.0
    if durations:
        avg_processing_seconds = sum(float(value) for _, value in durations if value is not None) / len([value for _, value in durations if value is not None])
    return {
        "pending": counts.get("QUEUED", 0) + counts.get("RETRYING", 0),
        "running": counts.get("RUNNING", 0),
        "completed": counts.get("COMPLETED", 0),
        "failed": counts.get("FAILED", 0),
        "failedPermanent": counts.get("FAILED_PERMANENT", 0),
        "averageProcessingSeconds": round(avg_processing_seconds, 3),
        "countsByStatus": counts,
    }
@app.post("/api/demo/analyze")
async def demo_analyze(log: str = Form(""), repository: str = Form(""), workflow: str = Form("Manual analysis"),
                       branch: str = Form("main"), commit_sha: str = Form(""), file: UploadFile | None = File(None),
                       db: Session = Depends(get_db), context=Depends(organization_context)):
    if file:
        if file.filename and not file.filename.lower().endswith((".log", ".txt")):
            raise HTTPException(400, "Only .log and .txt files are supported")
        content = await file.read()
        if len(content) > settings.max_log_size_bytes:
            raise HTTPException(413, "Log exceeds the configured size limit")
        log = content.decode("utf-8", errors="replace")
    try:
        processed = process_log(log, settings.max_log_size_bytes, settings.max_ai_log_characters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result, provider = analyze_with_fallback(processed["ai_log"], processed["evidence"])
    repo = None
    if repository:
        if "/" not in repository:
            raise HTTPException(400, "Repository must use owner/name format")
        owner, name = repository.split("/", 1)
        repo = db.scalar(select(Repository).where(Repository.owner == owner, Repository.name == name, Repository.organization_id == context[1])) if context[1] else db.scalar(select(Repository).where(Repository.owner == owner, Repository.name == name))
        if not repo:
            repo = Repository(owner=owner, name=name, organization_id=context[1])
        db.add(repo)
        db.flush()
    item = FailureAnalysis(organization_id=context[1], repository_id=repo.id if repo else None, workflow_name=workflow, branch=branch,
                           commit_sha=commit_sha, source="DEMO", category=result["category"], summary=result["summary"],
                           root_cause=result.get("rootCause", result.get("root_cause", "")),
                           failed_step=result.get("failedStep", "Unknown"), failed_command=result.get("failingCommand", result.get("failing_command")), confidence=result["confidence"],
                           severity=result["severity"], cleaned_log=processed["cleaned_log"],
                           raw_log_excerpt="\n".join(result.get("evidence", [])),
                           suggested_actions=json.dumps(result.get("suggestedActions", result.get("suggested_actions", []))),
                           analysis_time_minutes=1.5, resolution_time_minutes=0.0)
    item.fingerprint = result.get("fingerprint") or compute_failure_fingerprint(
        result.get("category", "UNKNOWN"),
        result.get("failedStep", result.get("failed_step", "Workflow execution")),
        result.get("errorType", "UNKNOWN"),
        result.get("errorMessage", result.get("error_message", "")),
        result.get("failingFile", ""),
        result.get("failingTest", ""),
    )
    db.add(item); db.flush(); synchronize_analysis_fingerprint_metadata(db, item, item.fingerprint); db.commit(); db.refresh(item)
    try:
        from app.services.embedding import DeterministicEmbeddingProvider, content_fingerprint
        fingerprint=content_fingerprint(processed["cleaned_log"])
        if not db.scalar(select(IncidentEmbedding).where(IncidentEmbedding.content_fingerprint==fingerprint, IncidentEmbedding.organization_id==context[1])):
            db.add(IncidentEmbedding(analysis_id=item.id,organization_id=context[1],content_fingerprint=fingerprint,vector_json=json.dumps(DeterministicEmbeddingProvider().embed(processed["cleaned_log"])),provider="deterministic",model="sha256-32",dimensions=32)); db.commit()
    except Exception:
        logger.warning("Embedding persistence unavailable for analysis %s", item.id)
    return {**out(item), "suggestedActions": result.get("suggestedActions", result.get("suggested_actions", [])),
            "analysisProvider": provider, "demoMode": provider == "RULE_BASED"}

@app.get("/api/analyses")
def analyses(page: int = 1, pageSize: int = 20, source: str | None = None, category: str | None = None,
             severity: str | None = None, resolved: bool | None = None, repository: str | None = None,
             branch: str | None = None, workflow_name: str | None = None, start_date: datetime | None = None, end_date: datetime | None = None,
             search: str | None = None, db: Session = Depends(get_db), context=Depends(organization_context)):
    query = select(FailureAnalysis).order_by(FailureAnalysis.created_at.desc())
    if context[1]: query = query.where(FailureAnalysis.organization_id == context[1])
    if source: query = query.where(FailureAnalysis.source == source)
    if category: query = query.where(FailureAnalysis.category == category)
    if severity: query = query.where(FailureAnalysis.severity == severity)
    if resolved is not None: query = query.where(FailureAnalysis.resolved == resolved)
    if repository: query = query.join(Repository).where(func.concat(Repository.owner, "/", Repository.name).contains(repository))
    if branch: query = query.where(FailureAnalysis.branch == branch)
    if workflow_name: query = query.where(FailureAnalysis.workflow_name.contains(workflow_name))
    if start_date: query = query.where(FailureAnalysis.created_at >= start_date)
    if end_date: query = query.where(FailureAnalysis.created_at <= end_date)
    if search: query = query.where(FailureAnalysis.summary.contains(search) | FailureAnalysis.cleaned_log.contains(search))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.offset((page - 1) * pageSize).limit(pageSize)).all()
    return {"items": [out(x) for x in rows], "page": page, "pageSize": pageSize, "total": total}

@app.get("/api/workflow-runs")
def workflow_runs(page: int = 1, pageSize: int = 20, repository_id: str | None = None, status: str | None = None,
                 workflow_name: str | None = None, db: Session = Depends(get_db), context=Depends(organization_context)):
    query = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
    if context[1]: query = query.where(WorkflowRun.organization_id == context[1])
    if repository_id: query = query.where(WorkflowRun.repository_id == repository_id)
    if status: query = query.where(WorkflowRun.status == status)
    if workflow_name: query = query.where(WorkflowRun.workflow_name.contains(workflow_name))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.offset((page - 1) * pageSize).limit(pageSize)).all()
    return {"items": [workflow_run_out(item) for item in rows], "page": page, "pageSize": pageSize, "total": total}


@app.get("/api/workflow-runs/{workflow_run_id}")
def workflow_run_detail(workflow_run_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id, WorkflowRun.organization_id == context[1])) if context[1] else db.get(WorkflowRun, workflow_run_id)
    if not item: raise HTTPException(404, "Workflow run not found")
    return workflow_run_out(item)


@app.get("/api/analyses/{analysis_id}")
def detail(analysis_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1])) if context[1] else db.get(FailureAnalysis, analysis_id)
    if not item: raise HTTPException(404, "Analysis not found")
    result = out(item)
    if item.workflow_run_id:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.github_run_id == item.workflow_run_id, WorkflowRun.organization_id == item.organization_id, WorkflowRun.repository_id == item.repository_id, WorkflowRun.run_attempt == item.run_attempt))
        if run:
            result["githubRunUrl"] = run.github_run_url or None
            result["runAttempt"] = run.run_attempt
    return result

@app.patch("/api/analyses/{analysis_id}/resolve")
def resolve(analysis_id: str, payload: ResolveCreate | None = None, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1])) if context[1] else db.get(FailureAnalysis, analysis_id)
    if not item: raise HTTPException(404, "Analysis not found")
    item.resolved = True
    item.resolved_by = context[0].id if context[0] else None
    item.resolved_at = datetime.now(timezone.utc)
    created_at = item.created_at.replace(tzinfo=timezone.utc) if item.created_at.tzinfo is None else item.created_at
    if item.analysis_time_minutes <= 0:
        item.analysis_time_minutes = max((datetime.now(timezone.utc) - created_at).total_seconds() / 60.0, 0.0)
    item.resolution_time_minutes = max((datetime.now(timezone.utc) - created_at).total_seconds() / 60.0, 0.0)
    if payload:
        item.actual_solution = payload.actual_solution
        item.resolution_note = payload.resolution_note
    db.commit(); db.refresh(item)
    return out(item)

@app.post("/api/analyses/{analysis_id}/feedback")
def feedback(analysis_id: str, payload: FeedbackCreate, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1])) if context[1] else db.get(FailureAnalysis, analysis_id)
    if not item: raise HTTPException(404, "Analysis not found")
    record = IncidentFeedback(organization_id=context[1], analysis_id=analysis_id, accurate=payload.accurate,
                              actual_category=payload.actual_category, actual_solution=payload.actual_solution)
    db.add(record)
    if payload.actual_solution: item.actual_solution = payload.actual_solution
    db.commit()
    return {"id": record.id, "analysisId": analysis_id, "accurate": record.accurate}

@app.get("/api/analyses/{analysis_id}/similar")
def similar(analysis_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1])) if context[1] else db.get(FailureAnalysis, analysis_id)
    if not item: raise HTTPException(404, "Analysis not found")
    matches=provider_for_database(db).search(db,item,organization_id=context[1])
    return {"items": [{"similarity": match["similarity"], "vectorSimilarity": match.get("vector_similarity"), "scoreBreakdown": match.get("score_breakdown", {"keyword":match["similarity"]}), "similarityProvider": provider_for_database(db).__class__.__name__, **out(match["analysis"])} for match in matches]}

@app.get("/api/repositories")
def repositories(db: Session = Depends(get_db), context=Depends(organization_context)):
    query=select(Repository).order_by(Repository.owner, Repository.name)
    if context[1]: query=query.where(Repository.organization_id == context[1])
    return {"items": [repo_out(item, db) for item in db.scalars(query).all()]}

@app.post("/api/repositories")
def create_repository(payload: RepositoryCreate, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    existing_query=select(Repository).where(Repository.owner == payload.owner, Repository.name == payload.name, Repository.organization_id == context[1])
    existing = db.scalar(existing_query)
    if existing: raise HTTPException(409, "Repository already exists")
    supplied_webhook_secret = payload.webhook_secret
    item = Repository(**payload.model_dump(exclude_none=True), organization_id=context[1])
    if not item.github_token:
        item.github_token = payload.github_token.strip() if payload.github_token else None
    if not item.webhook_secret or not item.webhook_secret.strip():
        item.webhook_secret = payload.webhook_secret.strip() if payload.webhook_secret else item.webhook_secret
    db.add(item); db.commit(); db.refresh(item)
    return repo_setup_out(item, db, None if supplied_webhook_secret else item.webhook_secret)

@app.post("/api/repositories/verify")
def verify_repository(payload: RepositoryVerify):
    try:
        metadata = GitHubClient(payload.github_token).repository_metadata(payload.owner, payload.name)
    except GitHubTemporaryError as exc:
        raise HTTPException(503, "GitHub is temporarily unavailable") from exc
    except GitHubPermanentError as exc:
        if exc.status_code == 404:
            raise HTTPException(404, "Repository not found or unavailable to this token") from exc
        if exc.status_code in (401, 403):
            raise HTTPException(403, "Token cannot access this repository") from exc
        raise HTTPException(400, "GitHub rejected the repository verification request") from exc
    return {
        "verified": True,
        "owner": metadata.get("owner", {}).get("login") or payload.owner,
        "name": metadata.get("name") or payload.name,
        "fullName": metadata.get("full_name") or f"{payload.owner}/{payload.name}",
        "defaultBranch": metadata.get("default_branch") or "main",
        "visibility": metadata.get("visibility") or ("private" if metadata.get("private") else "public"),
    }

@app.get("/api/repositories/{repository_id}")
def get_repository(repository_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    return repo_out(item, db)

@app.patch("/api/repositories/{repository_id}")
def update_repository(repository_id: str, payload: RepositoryUpdate, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if key in {"github_token", "webhook_secret"} and value == "":
            continue
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    return repo_out(item, db)

@app.post("/api/repositories/{repository_id}/rotate-webhook-secret")
def rotate_webhook_secret(repository_id: str, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1]))
    if not item: raise HTTPException(404, "Repository not found")
    item.webhook_secret = secrets.token_urlsafe(32)
    db.commit(); db.refresh(item)
    return {"id": item.id, "webhookSecret": item.webhook_secret, "webhookSecretShownOnce": True,
        "message": "Update this secret in your GitHub repository webhook settings."}

@app.delete("/api/repositories/{repository_id}")
def delete_repository(repository_id: str, db: Session = Depends(get_db), context=Depends(require_role("ADMIN"))):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    item.active = False; db.commit()
    return {"id": repository_id, "active": False}

@app.get("/api/dashboard/summary")
def summary(db: Session = Depends(get_db), context=Depends(organization_context)):
    analysis_scope=FailureAnalysis.organization_id == context[1] if context[1] else True
    total = db.scalar(select(func.count()).select_from(FailureAnalysis).where(analysis_scope)) or 0
    resolved_count = db.scalar(select(func.count()).where(FailureAnalysis.resolved, analysis_scope)) or 0
    avg = db.scalar(select(func.avg(FailureAnalysis.confidence)).where(analysis_scope)) or 0
    avg_analysis = db.scalar(select(func.avg(FailureAnalysis.analysis_time_minutes)).where(analysis_scope)) or 0
    avg_resolution = db.scalar(select(func.avg(FailureAnalysis.resolution_time_minutes)).where(analysis_scope)) or 0
    common = db.execute(select(FailureAnalysis.category, func.count()).where(analysis_scope).group_by(FailureAnalysis.category).order_by(func.count().desc())).first()
    repos = db.scalar(select(func.count()).select_from(Repository).where(Repository.active, Repository.organization_id == context[1] if context[1] else True)) or 0
    repository_rows = db.execute(
        select(Repository.owner, Repository.name, func.count(FailureAnalysis.id).label("failures"), func.coalesce(func.avg(FailureAnalysis.confidence), 0.0).label("avg_confidence"))
        .outerjoin(FailureAnalysis, FailureAnalysis.repository_id == Repository.id)
        .where(Repository.organization_id == context[1] if context[1] else True)
        .group_by(Repository.owner, Repository.name)
        .order_by(func.count(FailureAnalysis.id).desc())
    ).all()
    failure_rate_by_repository = [
        {
            "repository": f"{owner}/{name}",
            "failures": failures,
            "failureRate": round((failures / max(total, 1)) * 100, 1),
            "averageConfidence": round(avg_confidence * 100, 1),
        }
        for owner, name, failures, avg_confidence in repository_rows
    ]
    return {"totalFailures": total, "resolvedFailures": resolved_count, "unresolvedFailures": total - resolved_count,
            "resolutionRate": round(resolved_count / total * 100, 1) if total else 0,
            "averageConfidence": round(avg * 100, 1), "mostCommonCategory": common[0] if common else "NONE",
            "averageAnalysisTimeMinutes": round(float(avg_analysis or 0), 2),
            "averageResolutionTimeMinutes": round(float(avg_resolution or 0), 2),
            "failureRateByRepository": failure_rate_by_repository,
            "repositoriesMonitored": repos}


@app.get("/api/dashboard/insights")
def dashboard_insights(db: Session = Depends(get_db), context=Depends(organization_context)):
    scope = FailureAnalysis.organization_id == context[1] if context[1] else True
    avg_resolution = db.scalar(select(func.avg(FailureAnalysis.resolution_time_minutes)).where(scope)) or 0.0
    total = db.scalar(select(func.count()).select_from(FailureAnalysis).where(scope)) or 0
    repeated = db.execute(
        select(FailureAnalysis.summary, FailureAnalysis.branch, FailureAnalysis.category, Repository.owner, Repository.name, func.count(FailureAnalysis.id).label("count"))
        .join(Repository, FailureAnalysis.repository_id == Repository.id, isouter=True)
        .where(scope)
        .group_by(FailureAnalysis.summary, FailureAnalysis.branch, FailureAnalysis.category, Repository.owner, Repository.name)
        .having(func.count(FailureAnalysis.id) > 1)
        .order_by(func.count(FailureAnalysis.id).desc())
    ).all()
    flaky_signals = [
        {
            "summary": summary,
            "branch": branch,
            "category": category,
            "repository": f"{owner}/{name}" if owner and name else "Unassigned",
            "count": count,
        }
        for summary, branch, category, owner, name, count in repeated[:5]
    ]
    notifications = []
    if avg_resolution >= 30:
        notifications.append({
            "level": "warning",
            "title": "MTTR above target",
            "message": f"Average recovery time is {avg_resolution:.1f} minutes, above the target for fast CI turnaround.",
        })
    if flaky_signals:
        notifications.append({
            "level": "info",
            "title": "Recurring failure pattern",
            "message": f"{flaky_signals[0]['summary']} is repeating on {flaky_signals[0]['repository']} and may indicate a flaky workflow.",
        })
    if total > 0:
        unresolved = db.scalar(select(func.count()).where(FailureAnalysis.resolved.is_(False), scope)) or 0
        if unresolved / total > 0.5:
            notifications.append({
                "level": "alert",
                "title": "Unresolved failures rising",
                "message": f"{unresolved} of {total} incidents remain unresolved and need follow-up.",
            })
    if not notifications:
        notifications.append({
            "level": "success",
            "title": "Operationally stable",
            "message": "No active stabilization alerts are detected for the current incident set.",
        })
    return {
        "mttrMinutes": round(float(avg_resolution or 0), 2),
        "flakySignals": flaky_signals,
        "notifications": notifications,
    }


@app.get("/api/dashboard/trends")
def dashboard_trends(start_date: datetime | None = None, end_date: datetime | None = None, db: Session = Depends(get_db), context=Depends(organization_context)):
    scope = FailureAnalysis.organization_id == context[1] if context[1] else True
    if start_date: scope = scope & (FailureAnalysis.created_at >= start_date)
    if end_date: scope = scope & (FailureAnalysis.created_at <= end_date)
    series = db.execute(
        select(func.date(FailureAnalysis.created_at).label("day"), func.count(FailureAnalysis.id).label("count"))
        .where(scope)
        .group_by(func.date(FailureAnalysis.created_at))
        .order_by(func.date(FailureAnalysis.created_at).asc())
    ).all()
    categories = db.execute(
        select(FailureAnalysis.category, func.count(FailureAnalysis.id))
        .where(scope)
        .group_by(FailureAnalysis.category)
        .order_by(func.count(FailureAnalysis.id).desc())
    ).all()
    branches = db.execute(
        select(FailureAnalysis.branch, func.count(FailureAnalysis.id))
        .where(scope)
        .group_by(FailureAnalysis.branch)
        .order_by(func.count(FailureAnalysis.id).desc())
    ).all()
    repository_failures = db.execute(
        select(Repository.owner, Repository.name, func.count(FailureAnalysis.id).label("count"))
        .outerjoin(FailureAnalysis, FailureAnalysis.repository_id == Repository.id)
        .where(Repository.organization_id == context[1] if context[1] else True)
        .group_by(Repository.owner, Repository.name)
        .order_by(func.count(FailureAnalysis.id).desc())
    ).all()
    repeated = db.scalar(select(func.count()).select_from(
        select(FailureAnalysis.summary, FailureAnalysis.branch, FailureAnalysis.repository_id)
        .where(scope)
        .group_by(FailureAnalysis.summary, FailureAnalysis.branch, FailureAnalysis.repository_id)
        .having(func.count(FailureAnalysis.id) > 1)
        .subquery())
    ) or 0
    total = db.scalar(select(func.count()).select_from(FailureAnalysis).where(scope)) or 0
    return {
        "series": [{"date": day, "count": count} for day, count in series],
        "categories": [{"category": category, "count": count} for category, count in categories],
        "branches": [{"branch": branch, "count": count} for branch, count in branches],
        "repositoryFailures": [{"repository": f"{owner}/{name}", "count": count} for owner, name, count in repository_failures],
        "repeatedVsUnique": {"repeated": repeated, "unique": max(total - repeated, 0)},
    }


@app.post("/api/webhooks/github")
async def webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body(); signature = request.headers.get("x-hub-signature-256", "")
    event = request.headers.get("x-github-event", ""); payload = await request.json()
    repository_name = payload.get("repository", {}).get("name", "")
    repository_owner = payload.get("repository", {}).get("owner", {}).get("login", "")
    installation_id = str((payload.get("installation") or {}).get("id") or request.headers.get("x-github-hook-installation-target-id") or "")
    github_repository_id = str((payload.get("repository") or {}).get("id") or "")
    is_app_webhook = bool(installation_id and settings.github_app_webhook_secret)
    if event in {"installation", "installation_repositories"} and settings.github_app_webhook_secret:
        expected = "sha256=" + hmac.new(settings.github_app_webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(401, "Invalid webhook signature")
        installation = db.scalar(select(GitHubInstallation).where(GitHubInstallation.github_installation_id == installation_id))
        if installation:
            if event == "installation" and payload.get("action") in {"deleted", "suspend"}:
                installation.active = False
                db.query(Repository).filter(Repository.github_installation_id == installation.id).update({"active": False})
            elif event == "installation" and payload.get("action") == "unsuspend":
                installation.active = True
            elif event == "installation_repositories":
                removed = {str(item.get("id")) for item in payload.get("repositories_removed", [])}
                added = {str(item.get("id")) for item in payload.get("repositories_added", [])}
                if removed:
                    db.query(Repository).filter(Repository.github_installation_id == installation.id, Repository.github_repository_id.in_(removed)).update({"active": False}, synchronize_session=False)
                if added:
                    db.query(Repository).filter(Repository.github_installation_id == installation.id, Repository.github_repository_id.in_(added)).update({"active": True}, synchronize_session=False)
                installation.repository_selection = payload.get("repository_selection", installation.repository_selection)
            db.commit()
        return {"ok": True, "event": event, "updated": bool(installation)}
    if is_app_webhook:
        repo = db.scalar(
            select(Repository).join(GitHubInstallation, Repository.github_installation_id == GitHubInstallation.id).where(
                GitHubInstallation.github_installation_id == installation_id,
                GitHubInstallation.active,
                Repository.github_repository_id == github_repository_id,
            )
        )
        expected_secret = settings.github_app_webhook_secret
    else:
        repo = find_webhook_repository(db, repository_owner, repository_name, installation_id=installation_id or None, github_repository_id=github_repository_id or None) if repository_owner and repository_name else None
        expected_secret = None
    logger.info(
        "GitHub webhook received: event=%s owner=%s name=%s repository_id=%s webhook_secret_configured=%s webhook_secret_length=%d signature_present=%s signature_length=%d",
        event or "unknown", repository_owner or "<missing>", repository_name or "<missing>",
        repo.id if repo else "<unmatched>", bool(repo and repo.webhook_secret), len(repo.webhook_secret) if repo and repo.webhook_secret else 0,
        bool(signature), len(signature),
    )
    if not repo:
        logger.warning("GitHub webhook repository not recognized: owner=%s name=%s", repository_owner or "<missing>", repository_name or "<missing>")
        raise HTTPException(404, "Repository not recognized for this webhook")
    if not is_app_webhook:
        try:
            expected_secret = resolve_repository_webhook_secret(repo)
        except ValueError as exc:
            logger.warning("GitHub webhook secret is not configured: repository_id=%s", repo.id)
            raise HTTPException(401, str(exc)) from exc
    expected = "sha256=" + hmac.new(expected_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    signature_matches = hmac.compare_digest(expected, signature)
    logger.info(
        "GitHub webhook signature comparison: repository_id=%s event=%s matched=%s",
        repo.id, event or "unknown", signature_matches,
    )
    if not signature_matches:
        logger.warning("GitHub webhook signature rejected: repository_id=%s event=%s", repo.id, event or "unknown")
        raise HTTPException(401, "Invalid webhook signature")
    event = request.headers.get("x-github-event", ""); payload = payload
    if event == "ping": return {"ok": True, "event": "ping"}
    if event == "check_run":
        check_run = payload.get("check_run", {})
        conclusion = check_run.get("conclusion")
        status = check_run.get("status")
        if status != "completed" or conclusion != "failure": return {"ok": True, "ignored": True}
        return {"ok": True, "ignored": True, "event": "check_run"}
    if event == "pull_request":
        action = payload.get("action")
        return {"ok": True, "ignored": True, "event": "pull_request", "action": action}
    if event not in {"workflow_run", "workflow_job"}:
        return {"ok": True, "ignored": True}

    if event == "workflow_job":
        job_payload = payload.get("workflow_job", {})
        repository = payload.get("repository", {})
        if job_payload.get("status") != "completed" or job_payload.get("conclusion") != "failure":
            return {"ok": True, "ignored": True, "event": "workflow_job"}
        run = job_payload
    else:
        run = payload.get("workflow_run", {})
        repository = payload.get("repository", {})
        if run.get("status") != "completed" or run.get("conclusion") != "failure":
            return {"ok": True, "ignored": True}

    owner = repository.get("owner", {}).get("login", ""); name = repository.get("name", "")
    if not owner or not name: return {"ok": True, "ignored": True}
    if not is_app_webhook:
        repo = find_webhook_repository(db, owner, name, installation_id=installation_id or None, github_repository_id=github_repository_id or None)
        if not repo:
            raise HTTPException(404, "Repository not recognized for this webhook")
    run_id = str(run.get("run_id") or run.get("id") or "")
    if not run_id: return {"ok": True, "ignored": True}
    run_attempt = run.get("run_attempt")
    try:
        run_attempt = int(run_attempt) if run_attempt is not None else None
    except (TypeError, ValueError):
        run_attempt = None
    try:
        stmt = (select(WorkflowRun).where(WorkflowRun.repository_id == repo.id, WorkflowRun.github_run_id == run_id, WorkflowRun.run_attempt == run_attempt))
        existing = db.scalar(stmt)
        if existing:
            existing.status = run.get("status", "")
            existing.conclusion = run.get("conclusion", "")
            existing.run_attempt = run_attempt
            existing.raw_payload = json.dumps(payload)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            workflow_run = WorkflowRun(
                organization_id=repo.organization_id,
                repository_id=repo.id,
                github_run_id=run_id,
                run_attempt=run_attempt,
                github_run_url=run.get("html_url") or run.get("run_url", ""),
                workflow_name=run.get("name", ""),
                branch=run.get("head_branch", ""),
                head_sha=run.get("head_sha", ""),
                status=run.get("status", ""),
                conclusion=run.get("conclusion", ""),
                raw_payload=json.dumps(payload)
            )
            db.add(workflow_run)
        db.commit()
    except Exception as err:
        logger.warning("Error persisting workflow run %s: %s", run_id, err)
        db.rollback()
        return {"ok": True, "error": "Failed to persist workflow run"}
    logger.info("GitHub workflow queued: run_id=%s run_attempt=%s repository_id=%s", run_id, run_attempt, repo.id)
    job, created = enqueue_job(db, "ANALYZE_WORKFLOW_RUN", repo.organization_id, request.headers.get("x-github-delivery"), run_id, run_attempt)
    return {"ok": True, "queued": created, "jobId": job.id, "event": event}
