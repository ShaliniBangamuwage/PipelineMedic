from app.models import Job
from app.services.jobs import JobStatus, retry
from app.services.jobs import redact_error
from app.worker import worker_health

def test_retry_transitions_and_exhaustion():
    job=Job(kind='test',status=JobStatus.QUEUED.value,attempts=0)
    assert retry(job,3) and job.status==JobStatus.QUEUED.value and job.attempts==1
    assert retry(job,3) and job.status==JobStatus.RETRYING.value
    assert retry(job,3) and job.attempts==3
    assert not retry(job,3) and job.status==JobStatus.FAILED.value

def test_worker_health_reports_inline_mode_without_secrets():
    health = worker_health()
    assert health['mode'] == 'inline'
    assert 'redis_url' not in str(health).lower()

def test_worker_error_redaction_is_bounded():
    result = redact_error('password=hunter2 token=secret\n' + ('x' * 1000))
    assert 'hunter2' not in result and 'secret' not in result and len(result) <= 500
