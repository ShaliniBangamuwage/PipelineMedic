import signal
import time
import json
import re
from collections.abc import Callable
from sqlalchemy import select
from app.core.config import settings
from app.db import SessionLocal
from app.models import FailureAnalysis, Job, PatchSuggestion, PRCommentDelivery, Repository
from app.services.github import GitHubClient
from app.services.pr_comments import deliver
from app.services.patch_generation import OpenAICompatiblePatchProvider, PatchProviderError, PatchTemporaryError, generate_and_validate
from app.services.jobs import JobStatus, publish, queue_depth, redact_error, redis_client, redis_health, retry

class TemporaryJobError(Exception):
    pass

class PermanentJobError(Exception):
    pass

def worker_health():
    configured = bool(settings.redis_url)
    connected = redis_health() if configured else None
    return {"mode": "redis" if configured else "inline", "redisConnected": connected,
            "consumerAvailable": not configured or connected,
            "queueName": settings.redis_queue_name if configured else None,
            "queueDepth": queue_depth() if configured and connected else None}

def _claim(job_id: str) -> Job | None:
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.id == job_id))
        if not job or job.status not in (JobStatus.QUEUED.value, JobStatus.RETRYING.value):
            return None
        job.status = JobStatus.RUNNING.value
        job.error_message = None
        db.commit()
        db.refresh(job)
        db.expunge(job)
        return job

def process_job(job_id: str, handler: Callable[[Job], None]) -> str | None:
    claimed = _claim(job_id)
    if not claimed:
        return None
    try:
        handler(claimed)
    except PermanentJobError as error:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED.value
                job.error_message = redact_error(error)
                db.commit()
                return job.status
    except Exception as error:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not job:
                return None
            if retry(job):
                job.error_message = redact_error(error)
                db.commit()
                try:
                    publish(job.id)
                except Exception:
                    pass
                return job.status
            job.status = JobStatus.FAILED.value
            job.error_message = redact_error(error)
            db.commit()
            return job.status
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job:
            job.status = JobStatus.COMPLETED.value
            job.error_message = None
            job.next_retry_at = None
            db.commit()
            return job.status
    return None

def run_once(handler: Callable[[Job], None] | None = None) -> bool:
    """Preserve inline mode for demos and local execution."""
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.status == JobStatus.QUEUED.value).order_by(Job.created_at))
        job_id = job.id if job else None
    if not job_id:
        return False
    process_job(job_id, handler or (lambda _: None))
    return True

def consume(handler: Callable[[Job], None], client=None, stop: Callable[[], bool] | None = None):
    client = client or redis_client()
    if client is None:
        raise RuntimeError("Redis mode requires REDIS_URL")
    stop = stop or (lambda: False)
    while not stop():
        try:
            message = client.blpop(settings.redis_queue_name, timeout=2)
            if message:
                process_job(message[1], handler)
        except Exception:
            if stop():
                break
            time.sleep(settings.worker_backoff_seconds)

def handle_job(job: Job, db, github_client=None, patch_provider=None):
    if job.kind == "PR_COMMENT_DELIVERY":
        delivery = db.get(PRCommentDelivery, job.workflow_run_id)
        analysis = db.get(FailureAnalysis, delivery.analysis_id) if delivery else None
        repository = db.get(Repository, delivery.repository_id) if delivery else None
        if delivery and analysis and repository:
            deliver(db, delivery, analysis, repository, github_client or GitHubClient(settings.github_token))
        return
    if job.kind != "PATCH_GENERATION":
        return
    patch = db.get(PatchSuggestion, job.workflow_run_id)
    analysis = db.get(FailureAnalysis, patch.analysis_id) if patch else None
    repository = db.get(Repository, patch.repository_id) if patch and patch.repository_id else None
    if not patch or not analysis:
        return
    patch.status = "GENERATING"
    db.commit()
    try:
        context, fingerprint = ("", "")
        if repository and settings.github_token:
            paths = re.findall(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|ts|tsx|js|jsx|java|go|cs)", analysis.cleaned_log or "")[:20]
            context, fingerprint = (github_client or GitHubClient(settings.github_token)).source_context(repository.owner, repository.name, paths, analysis.commit_sha, settings.patch_context_max_bytes)
        generated, validation = generate_and_validate(patch_provider or OpenAICompatiblePatchProvider(), context, analysis.root_cause)
        patch.provider, patch.model = "GROQ", settings.groq_model
        patch.unified_diff, patch.explanation, patch.confidence = generated.unified_diff, generated.explanation, generated.confidence
        patch.affected_files, patch.validation_errors = json.dumps(validation.affected_files), json.dumps(validation.validation_errors)
        patch.risk_level, patch.source_context_fingerprint = validation.risk_level, fingerprint
        patch.status = "READY" if validation.valid else "REJECTED_BY_VALIDATION"
    except PatchTemporaryError:
        raise
    except PatchProviderError as error:
        patch.status = "FAILED"
        patch.validation_errors = json.dumps([redact_error(error)])
    db.commit()

def main():
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not settings.redis_url:
        while not stopping and run_once():
            pass
        return
    def handle(job: Job):
        with SessionLocal() as db:
            handle_job(job, db, GitHubClient(settings.github_token))
    consume(handle, stop=lambda: stopping)

if __name__ == "__main__":
    main()