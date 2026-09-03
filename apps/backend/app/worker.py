import signal
import time
import json
import re
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from sqlalchemy import select, text
from app.core.config import settings
from app.db import SessionLocal
from app.models import FailureAnalysis, Job, PatchSuggestion, PRCommentDelivery, Repository, WorkflowRun
from app.services.github import GitHubClient, GitHubClientError
from app.services.pr_comments import deliver
from app.services.patch_generation import OpenAICompatiblePatchProvider, PatchProviderError, PatchTemporaryError, generate_and_validate
from app.services.log_processing import process_log
from app.services.ai import analyze_with_fallback
from app.services.jobs import JobStatus, acquire_distributed_lock, publish, queue_depth, redact_error, redis_client, redis_health, release_distributed_lock, retry
from app.services.pr_comments import queue_delivery

logger = logging.getLogger("pipelinemedic.worker")

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
        if db.bind and db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

        if db.bind and db.bind.dialect.name == "postgresql":
            result = db.execute(
                text("UPDATE jobs SET status = :status, error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = :job_id AND status IN (:queued, :retrying) RETURNING id, kind, attempts, status"),
                {"status": JobStatus.RUNNING.value, "job_id": job_id, "queued": JobStatus.QUEUED.value, "retrying": JobStatus.RETRYING.value},
            )
            row = result.fetchone()
            if not row:
                db.rollback()
                return None
            db.commit()
            job = db.get(Job, job_id)
            if not job:
                return None
            job.status = JobStatus.RUNNING.value
            job.error_message = None
            db.expunge(job)
            return job

        result = db.execute(
            text("UPDATE jobs SET status = :status, error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = :job_id AND status IN (:queued, :retrying)"),
            {"status": JobStatus.RUNNING.value, "job_id": job_id, "queued": JobStatus.QUEUED.value, "retrying": JobStatus.RETRYING.value},
        )
        if result.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        job = db.get(Job, job_id)
        if not job:
            return None
        job.status = JobStatus.RUNNING.value
        job.error_message = None
        db.expunge(job)
        return job

def process_job(job_id: str, handler: Callable[[Job], None]) -> str | None:
    claimed = _claim(job_id)
    if not claimed:
        logger.info("job claim skipped: id=%s", job_id)
        return None
    started_at = datetime.now(timezone.utc)
    lock_token = acquire_distributed_lock(job_id)
    logger.info("job claimed: id=%s kind=%s attempts=%s lock_acquired=%s", job_id, claimed.kind, claimed.attempts, lock_token is not None)
    try:
        handler(claimed)
    except PermanentJobError as error:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED_PERMANENT.value
                job.error_message = redact_error(error)
                job.next_retry_at = None
                db.commit()
                logger.info("job failed permanently: id=%s kind=%s attempts=%s", job_id, job.kind, job.attempts)
                return job.status
    except Exception as error:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not job:
                return None
            if retry(job):
                job.error_message = redact_error(error)
                db.commit()
                logger.info("job retry scheduled: id=%s kind=%s attempts=%s", job_id, job.kind, job.attempts)
                try:
                    publish(job.id)
                except Exception:
                    pass
                return job.status
            job.status = JobStatus.FAILED_PERMANENT.value
            job.error_message = redact_error(error)
            job.next_retry_at = None
            db.commit()
            logger.info("job failed permanently: id=%s kind=%s attempts=%s", job_id, job.kind, job.attempts)
            return job.status
    finally:
        release_distributed_lock(job_id, lock_token)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job:
            job.status = JobStatus.COMPLETED.value
            job.error_message = None
            job.next_retry_at = None
            db.commit()
            logger.info("job completed: id=%s kind=%s attempts=%s", job_id, job.kind, job.attempts)
            return job.status
    return None

def _process_inline_job(job: Job):
    with SessionLocal() as db:
        handle_job(job, db, GitHubClient(settings.github_token))


def run_once(handler: Callable[[Job], None] | None = None, job_id: str | None = None) -> bool:
    """Preserve inline mode for demos and local execution.

    In local/demo mode we prefer the most recently queued item so a newly
    enqueued workflow run is picked up promptly instead of waiting behind stale
    backlog entries from earlier tests or manual runs.
    """
    with SessionLocal() as db:
        if job_id:
            job = db.scalar(select(Job).where(Job.id == job_id, Job.status == JobStatus.QUEUED.value))
        else:
            job = db.scalar(select(Job).where(Job.status == JobStatus.QUEUED.value).order_by(Job.created_at.desc()))
        selected_id = job.id if job else None
    if not selected_id:
        return False
    process_job(selected_id, handler or _process_inline_job)
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
    if job.kind == "ANALYZE_WORKFLOW_RUN":
        handle_analyze_workflow_run(job, db, github_client)
        return
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

def handle_analyze_workflow_run(job: Job, db, github_client=None):
    workflow_run = db.scalar(select(WorkflowRun).where(WorkflowRun.github_run_id == job.workflow_run_id))
    if not workflow_run:
        return
    repository = db.get(Repository, workflow_run.repository_id)
    if not repository:
        return
    log = f"Workflow {workflow_run.workflow_name} failed. GitHub logs were unavailable; inspect run {workflow_run.github_run_url}."
    if settings.github_token and workflow_run.github_run_id:
        try:
            log = (github_client or GitHubClient(settings.github_token)).workflow_logs(
                repository.owner, repository.name, int(workflow_run.github_run_id), settings.github_log_max_bytes
            )
        except (GitHubClientError, ValueError):
            pass
    processed = process_log(log, settings.max_log_size_bytes, settings.max_ai_log_characters)
    result, provider = analyze_with_fallback(processed["ai_log"], processed["evidence"])
    sha = workflow_run.head_sha
    name = workflow_run.workflow_name
    if db.scalar(select(FailureAnalysis).where(FailureAnalysis.commit_sha == sha, FailureAnalysis.workflow_name == name, FailureAnalysis.source == "GITHUB")):
        return
    item = FailureAnalysis(
        repository_id=repository.id,
        workflow_name=workflow_run.workflow_name,
        branch=workflow_run.branch,
        commit_sha=workflow_run.head_sha,
        source="GITHUB",
        category=result["category"],
        summary=result["summary"],
        root_cause=result.get("rootCause", ""),
        failed_step=result.get("failedStep", "Unknown"),
        confidence=result["confidence"],
        severity=result["severity"],
        cleaned_log=processed["cleaned_log"],
        raw_log_excerpt="\n".join(result.get("evidence", []))
    )
    db.add(item)
    db.commit()
    queue_delivery(db, item, repository)

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', force=True)
    logger.setLevel(logging.INFO)
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