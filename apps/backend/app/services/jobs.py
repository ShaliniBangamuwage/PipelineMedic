from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Job
class JobStatus(str,Enum): QUEUED='QUEUED'; RUNNING='RUNNING'; COMPLETED='COMPLETED'; FAILED='FAILED'; RETRYING='RETRYING'

_SENSITIVE_ERROR = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)\s*[=:]\s*[^\s,;]+")

def redact_error(error: Exception | str, limit: int = 500) -> str:
    text = str(error).replace("\r", " ").replace("\n", " ")
    return _SENSITIVE_ERROR.sub(r"\1=[REDACTED]", text)[:limit]

def redis_client():
    if not settings.redis_url:
        return None
    import redis
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)

def publish(job_id: str, client=None) -> bool:
    client = client or redis_client()
    if client is None:
        return False
    client.rpush(settings.redis_queue_name, str(job_id))
    return True

def queue_depth(client=None) -> int | None:
    client = client or redis_client()
    if client is None:
        return None
    try:
        return int(client.llen(settings.redis_queue_name))
    except Exception:
        return None

def redis_health(client=None) -> bool | None:
    client = client or redis_client()
    if client is None:
        return None
    try:
        return bool(client.ping())
    except Exception:
        return False
def enqueue(db:Session,kind:str,organization_id:str|None,delivery_id:str|None,run_id:str|None):
    query=select(Job).where(Job.delivery_id==delivery_id,Job.workflow_run_id==run_id)
    existing=db.scalar(query) if delivery_id or run_id else None
    if existing:return existing,False
    item=Job(kind=kind,organization_id=organization_id,delivery_id=delivery_id,workflow_run_id=run_id,status=JobStatus.QUEUED.value);db.add(item);db.commit();db.refresh(item)
    if settings.redis_url:
        try: publish(item.id)
        except Exception: pass
    return item,True
def out(job):return {'id':job.id,'kind':job.kind,'status':job.status,'deliveryId':job.delivery_id,'workflowRunId':job.workflow_run_id,'attempts':job.attempts,'errorCode':None,'nextRetryAt':job.next_retry_at.isoformat() if job.next_retry_at else None,'createdAt':job.created_at.isoformat() if job.created_at else None}
def retry(job,max_attempts:int|None=None):
    max_attempts = max_attempts or settings.worker_max_attempts
    if job.attempts>=max_attempts: job.status=JobStatus.FAILED.value; return False
    job.attempts+=1; job.status=JobStatus.RETRYING.value if job.attempts>1 else JobStatus.QUEUED.value
    from datetime import datetime, timezone
    job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=settings.worker_backoff_seconds * (2 ** max(0, job.attempts - 1)))
    return True
