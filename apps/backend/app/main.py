from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import hashlib
import hmac
import logging
from app.core.config import settings
from app.db import Base, engine, ensure_legacy_sqlite_schema, get_db
from app.models import FailureAnalysis, IncidentEmbedding, IncidentFeedback, Job, PatchDecision, PatchSuggestion, PRCommentDelivery, Repository
from app.services.jobs import enqueue as enqueue_job, out as job_out, retry as retry_job, queue_depth, redis_health
import json
from app.schemas import FeedbackCreate, RepositoryCreate, RepositoryUpdate, ResolveCreate
from app.services.ai import analyze_with_fallback
from app.services.github import GitHubClient, GitHubClientError
from app.services.log_processing import process_log
from app.services.similarity import find_similar
from app.services.embedding import provider_for_database
from app.auth_routes import router as auth_router
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
app.include_router(auth_router)
app.include_router(organization_router)
ensure_strong_secret()
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_methods=["*"], allow_headers=["*"])
Base.metadata.create_all(engine)
ensure_legacy_sqlite_schema()

def out(item: FailureAnalysis):
    return {"id": item.id, "summary": item.summary, "rootCause": item.root_cause, "category": item.category,
            "severity": item.severity, "confidence": item.confidence, "source": item.source,
            "workflowName": item.workflow_name, "branch": item.branch, "commitSha": item.commit_sha,
            "failedStep": item.failed_step, "cleanedLog": item.cleaned_log,
            "evidence": item.raw_log_excerpt.splitlines() if item.raw_log_excerpt else [],
            "resolved": item.resolved, "actualSolution": item.actual_solution,
            "createdAt": item.created_at.isoformat() if item.created_at else None,
            "repository": f"{item.repository.owner}/{item.repository.name}" if item.repository else None}

def repo_out(item: Repository, db: Session):
    count = db.scalar(select(func.count()).where(FailureAnalysis.repository_id == item.id)) or 0
    last = db.scalar(select(func.max(FailureAnalysis.created_at)).where(FailureAnalysis.repository_id == item.id))
    return {"id": item.id, "owner": item.owner, "name": item.name, "fullName": f"{item.owner}/{item.name}",
            "defaultBranch": item.default_branch, "active": item.active, "failureCount": count,
            "lastFailure": last.isoformat() if last else None, "prCommentsEnabled": item.pr_comments_enabled,
            "prCommentMinConfidence": item.pr_comment_min_confidence, "prCommentAllowedBranches": item.pr_comment_allowed_branches,
            "prCommentIncludeSimilarIncident": item.pr_comment_include_similar_incident, "prCommentIncludePatch": item.pr_comment_include_patch}

def scoped_repository(repository_id: str, db: Session, context):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    return item

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
@app.get("/api/jobs/{job_id}")
def job_detail(job_id:str,db:Session=Depends(get_db),context=Depends(organization_context)):
    item=db.scalar(select(Job).where(Job.id==job_id,Job.organization_id==context[1])) if context[1] else db.get(Job,job_id)
    if not item: raise HTTPException(404,"Job not found")
    return job_out(item)
@app.post("/api/jobs/{job_id}/retry")
def retry(job_id:str,db:Session=Depends(get_db),context=Depends(require_role("DEVELOPER"))):
    item=db.scalar(select(Job).where(Job.id==job_id,Job.organization_id==context[1])) if context[1] else db.get(Job,job_id)
    if not item: raise HTTPException(404,"Job not found")
    if not retry_job(item): raise HTTPException(400,"Job has exhausted its retry limit")
    db.commit();db.refresh(item);return job_out(item)
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
                           failed_step=result.get("failedStep", "Unknown"), confidence=result["confidence"],
                           severity=result["severity"], cleaned_log=processed["cleaned_log"],
                           raw_log_excerpt="\n".join(result.get("evidence", [])))
    db.add(item); db.commit(); db.refresh(item)
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
             search: str | None = None, db: Session = Depends(get_db), context=Depends(organization_context)):
    query = select(FailureAnalysis).order_by(FailureAnalysis.created_at.desc())
    if context[1]: query = query.where(FailureAnalysis.organization_id == context[1])
    if source: query = query.where(FailureAnalysis.source == source)
    if category: query = query.where(FailureAnalysis.category == category)
    if severity: query = query.where(FailureAnalysis.severity == severity)
    if resolved is not None: query = query.where(FailureAnalysis.resolved == resolved)
    if repository: query = query.join(Repository).where((Repository.owner + "/" + Repository.name).contains(repository))
    if search: query = query.where(FailureAnalysis.summary.contains(search) | FailureAnalysis.cleaned_log.contains(search))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.offset((page - 1) * pageSize).limit(pageSize)).all()
    return {"items": [out(x) for x in rows], "page": page, "pageSize": pageSize, "total": total}

@app.get("/api/analyses/{analysis_id}")
def detail(analysis_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1])) if context[1] else db.get(FailureAnalysis, analysis_id)
    if not item: raise HTTPException(404, "Analysis not found")
    return out(item)

@app.patch("/api/analyses/{analysis_id}/resolve")
def resolve(analysis_id: str, payload: ResolveCreate | None = None, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(FailureAnalysis).where(FailureAnalysis.id == analysis_id, FailureAnalysis.organization_id == context[1])) if context[1] else db.get(FailureAnalysis, analysis_id)
    if not item: raise HTTPException(404, "Analysis not found")
    item.resolved = True
    if payload: item.actual_solution = payload.actual_solution
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
    existing_query=select(Repository).where(Repository.owner == payload.owner, Repository.name == payload.name)
    if context[1]: existing_query=existing_query.where(Repository.organization_id == context[1])
    existing = db.scalar(existing_query)
    if existing: raise HTTPException(409, "Repository already exists")
    item = Repository(**payload.model_dump(), organization_id=context[1]); db.add(item); db.commit(); db.refresh(item)
    return repo_out(item, db)

@app.get("/api/repositories/{repository_id}")
def get_repository(repository_id: str, db: Session = Depends(get_db), context=Depends(organization_context)):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    return repo_out(item, db)

@app.patch("/api/repositories/{repository_id}")
def update_repository(repository_id: str, payload: RepositoryUpdate, db: Session = Depends(get_db), context=Depends(require_role("DEVELOPER"))):
    item = db.scalar(select(Repository).where(Repository.id == repository_id, Repository.organization_id == context[1])) if context[1] else db.get(Repository, repository_id)
    if not item: raise HTTPException(404, "Repository not found")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    db.commit(); db.refresh(item)
    return repo_out(item, db)

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
    common = db.execute(select(FailureAnalysis.category, func.count()).where(analysis_scope).group_by(FailureAnalysis.category).order_by(func.count().desc())).first()
    repos = db.scalar(select(func.count()).select_from(Repository).where(Repository.active, Repository.organization_id == context[1] if context[1] else True)) or 0
    return {"totalFailures": total, "resolvedFailures": resolved_count, "unresolvedFailures": total - resolved_count,
            "resolutionRate": round(resolved_count / total * 100, 1) if total else 0,
            "averageConfidence": round(avg * 100, 1), "mostCommonCategory": common[0] if common else "NONE",
            "repositoriesMonitored": repos}

def process_webhook(payload: dict, db: Session):
    run = payload.get("workflow_run", {}); repository = payload.get("repository", {})
    owner = repository.get("owner", {}).get("login", "unknown"); name = repository.get("name", "unknown")
    repo = db.scalar(select(Repository).where(Repository.owner == owner, Repository.name == name))
    if not repo: repo = Repository(owner=owner, name=name); db.add(repo); db.flush()
    log = f"Workflow {run.get('name', 'unknown')} failed. GitHub logs were unavailable; inspect run {run.get('html_url', '')}."
    if settings.github_token and run.get("id"):
        try:
            log = GitHubClient(settings.github_token).workflow_logs(owner, name, int(run["id"]), settings.github_log_max_bytes)
        except (GitHubClientError, ValueError):
            logger.warning("GitHub logs unavailable for workflow run %s", run.get("id"))
    processed = process_log(log, settings.max_log_size_bytes, settings.max_ai_log_characters)
    result, provider = analyze_with_fallback(processed["ai_log"], processed["evidence"])
    item = FailureAnalysis(repository_id=repo.id, workflow_name=run.get("name", "GitHub workflow"), branch=run.get("head_branch", ""),
                           commit_sha=run.get("head_sha", ""), source="GITHUB", category=result["category"], summary=result["summary"],
                           root_cause=result.get("rootCause", ""), failed_step=result.get("failedStep", "Unknown"), confidence=result["confidence"],
                           severity=result["severity"], cleaned_log=processed["cleaned_log"], raw_log_excerpt="\n".join(result.get("evidence", [])))
    db.add(item); db.commit()
    queue_delivery(db, item, repo)

@app.post("/api/webhooks/github")
async def webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    body = await request.body(); signature = request.headers.get("x-hub-signature-256", "")
    if settings.github_webhook_secret:
        expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature): raise HTTPException(401, "Invalid webhook signature")
    event = request.headers.get("x-github-event", ""); payload = await request.json()
    if event == "ping": return {"ok": True, "event": "ping"}
    if event != "workflow_run": return {"ok": True, "ignored": True}
    run = payload.get("workflow_run", {})
    if run.get("status") != "completed" or run.get("conclusion") != "failure": return {"ok": True, "ignored": True}
    sha = run.get("head_sha", ""); name = run.get("name", "")
    if db.scalar(select(FailureAnalysis).where(FailureAnalysis.commit_sha == sha, FailureAnalysis.workflow_name == name, FailureAnalysis.source == "GITHUB")):
        return {"ok": True, "duplicate": True}
    job,created=enqueue_job(db,"workflow_run",None,request.headers.get("x-github-delivery"),str(run.get("id")) if run.get("id") else None)
    if created: background_tasks.add_task(process_webhook, payload, db)
    return {"ok": True, "queued": created, "jobId": job.id, "duplicate": not created}
