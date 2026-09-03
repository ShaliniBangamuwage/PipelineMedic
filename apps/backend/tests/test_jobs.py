from app.db import SessionLocal
from app.models import Job
from app.services.jobs import JobStatus, retry
from app.services.jobs import redact_error
from app.worker import worker_health, process_job
from app.core.config import settings


def test_retry_transitions_and_exhaustion():
    job=Job(kind='test',status=JobStatus.QUEUED.value,attempts=0)
    assert retry(job,3) and job.status==JobStatus.QUEUED.value and job.attempts==1
    assert retry(job,3) and job.status==JobStatus.RETRYING.value
    assert retry(job,3) and job.attempts==3
    assert not retry(job,3) and job.status==JobStatus.FAILED_PERMANENT.value

def test_worker_health_reports_inline_mode_without_secrets(monkeypatch):
    monkeypatch.setattr(settings, 'redis_url', '')
    health = worker_health()
    assert health['mode'] == 'inline'
    assert 'redis_url' not in str(health).lower()

def test_process_job_dead_letters_after_retry_exhaustion():
    with SessionLocal() as db:
        job = Job(kind='test', status=JobStatus.QUEUED.value, attempts=3)
        db.add(job)
        db.commit(); db.refresh(job)

    status = process_job(job.id, lambda _job: (_ for _ in ()).throw(RuntimeError('persistent failure')))
    assert status == JobStatus.FAILED_PERMANENT.value

    with SessionLocal() as db:
        refreshed = db.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.FAILED_PERMANENT.value


def test_worker_error_redaction_is_bounded():
    result = redact_error('password=hunter2 token=secret\n' + ('x' * 1000))
    assert 'hunter2' not in result and 'secret' not in result and len(result) <= 500
