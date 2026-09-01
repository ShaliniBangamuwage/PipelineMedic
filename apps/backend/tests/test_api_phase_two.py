import hashlib
import hmac
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.core.config import settings
from app.db import SessionLocal
from app.models import FailureAnalysis, Repository, WorkflowRun, Job
import app.worker as worker_module
from app.worker import _claim

@pytest.fixture(autouse=True)
def disable_auth(monkeypatch):
    monkeypatch.setattr(settings, 'auth_enabled', False)
    monkeypatch.setattr(settings, 'jwt_secret', 'phase-two-test-secret-that-is-long-enough-123456')
    yield
    monkeypatch.setattr(settings, 'auth_enabled', False)

client=TestClient(app)

def test_health_endpoint():
    response=client.get('/api/health')
    assert response.status_code==200 and response.json()['status']=='healthy'

def test_repository_crud_and_feedback():
    owner='phase-two-owner'; name='phase-two-repo'
    created=client.post('/api/repositories',json={'owner':owner,'name':name,'default_branch':'main'}); assert created.status_code in (200,409)
    item=created.json() if created.status_code==200 else client.get('/api/repositories').json()['items'][0]
    repository_id=item['id']
    updated=client.patch(f'/api/repositories/{repository_id}',json={'active':False}); assert updated.status_code==200
    assert client.delete(f'/api/repositories/{repository_id}').status_code==200

def test_invalid_webhook_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(settings,'github_webhook_secret','test-secret')
    payload=b'{"zen":"test"}'
    response=client.post('/api/webhooks/github',content=payload,headers={'x-github-event':'ping','x-hub-signature-256':'sha256=invalid'})
    assert response.status_code==401
    monkeypatch.setattr(settings,'github_webhook_secret','')


def test_workflow_job_failure_webhook_persists_and_queues(monkeypatch):
    monkeypatch.setattr(settings, 'github_webhook_secret', 'test-secret')
    payload = {
        'action': 'completed',
        'workflow_job': {
            'id': 999,
            'run_id': 777,
            'run_url': 'https://github.example/runs/777',
            'name': 'CI',
            'head_branch': 'main',
            'head_sha': 'abc123',
            'status': 'completed',
            'conclusion': 'failure',
            'html_url': 'https://github.example/jobs/999',
        },
        'repository': {'name': 'demo', 'owner': {'login': 'octo'}},
    }
    body = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_job', 'x-hub-signature-256': signature})
    assert response.status_code == 200
    assert response.json()['ok'] is True
    with SessionLocal() as db:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.github_run_id == '777'))
        assert run is not None
        assert run.workflow_name == 'CI'
        job = db.scalar(select(Job).where(Job.workflow_run_id == '777'))
        assert job is not None
        assert job.kind == 'ANALYZE_WORKFLOW_RUN'
    monkeypatch.setattr(settings, 'github_webhook_secret', '')


def test_inline_worker_uses_real_job_handler():
    with SessionLocal() as db:
        repo = Repository(owner='inline-owner', name='inline-repo', default_branch='main')
        db.add(repo)
        db.commit(); db.refresh(repo)
        run = WorkflowRun(
            repository_id=repo.id,
            github_run_id='inline-run-999',
            github_run_url='https://github.example/runs/inline-run-999',
            workflow_name='CI',
            branch='main',
            head_sha='inline-sha-999',
            status='completed',
            conclusion='failure',
            raw_payload='{}',
        )
        db.add(run)
        db.commit(); db.refresh(run)
        job = Job(kind='ANALYZE_WORKFLOW_RUN', status='QUEUED', workflow_run_id='inline-run-999', organization_id=None)
        db.add(job)
        db.commit(); db.refresh(job)

    assert worker_module.run_once() is True

    with SessionLocal() as db:
        refreshed = db.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == 'COMPLETED'
        analysis = db.scalar(select(FailureAnalysis).where(FailureAnalysis.commit_sha == 'inline-sha-999', FailureAnalysis.workflow_name == 'CI', FailureAnalysis.source == 'GITHUB'))
        assert analysis is not None


def test_workflow_run_endpoints_and_dashboard_trends():
    with SessionLocal() as db:
        repo = Repository(owner='octo', name='demo', default_branch='main')
        db.add(repo); db.commit(); db.refresh(repo)
        run = WorkflowRun(
            repository_id=repo.id,
            github_run_id='12345',
            github_run_url='https://github.example/runs/12345',
            workflow_name='CI',
            branch='main',
            head_sha='abc123',
            status='completed',
            conclusion='failure',
            raw_payload='{}',
        )
        db.add(run); db.commit(); db.refresh(run)
        db.add(FailureAnalysis(
            repository_id=repo.id,
            workflow_name='CI',
            branch='main',
            commit_sha='abc123',
            source='GITHUB',
            category='COMPILATION_ERROR',
            summary='Build failed',
            root_cause='Type mismatch',
            failed_step='Run tests',
            confidence=0.91,
            severity='HIGH',
            cleaned_log='Build failed: Type mismatch',
            raw_log_excerpt='Build failed: Type mismatch',
            resolved=False,
        ))
        db.commit()

    list_response = client.get('/api/workflow-runs')
    assert list_response.status_code == 200
    body = list_response.json()
    assert body['total'] >= 1
    item = body['items'][0]
    assert item['github_run_id'] == '12345'

    detail_response = client.get(f"/api/workflow-runs/{item['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()['workflow_name'] == 'CI'

    trends = client.get('/api/dashboard/trends')
    assert trends.status_code == 200
    payload = trends.json()
    assert 'series' in payload
    assert 'categories' in payload
    assert 'branches' in payload
    assert 'repeatedVsUnique' in payload


def test_dashboard_summary_includes_proposal_metrics():
    response = client.get('/api/dashboard/summary')
    assert response.status_code == 200
    payload = response.json()
    for key in [
        'totalFailures',
        'resolvedFailures',
        'unresolvedFailures',
        'resolutionRate',
        'averageConfidence',
        'mostCommonCategory',
        'averageAnalysisTimeMinutes',
        'averageResolutionTimeMinutes',
        'failureRateByRepository',
    ]:
        assert key in payload, payload


def test_dashboard_insights_include_flaky_and_mttr_signals():
    with SessionLocal() as db:
        repo = Repository(owner='advanced-owner', name='advanced-repo', default_branch='main')
        db.add(repo)
        db.commit(); db.refresh(repo)
        for offset in (0, 1):
            db.add(FailureAnalysis(
                repository_id=repo.id,
                workflow_name='CI',
                branch='main',
                commit_sha=f'advanced-{offset}',
                source='GITHUB',
                category='UNIT_TEST_FAILURE',
                summary='Test suite is flaky',
                root_cause='Assertion mismatch',
                failed_step='pytest',
                confidence=0.88,
                severity='MEDIUM',
                cleaned_log='Assertion mismatch in flaky test',
                raw_log_excerpt='Assertion mismatch in flaky test',
                resolved=False,
                created_at=datetime.now(timezone.utc) - timedelta(days=offset),
                analysis_time_minutes=5.0,
                resolution_time_minutes=30.0,
            ))
        db.commit()

    response = client.get('/api/dashboard/insights')
    assert response.status_code == 200
    payload = response.json()
    assert 'mttrMinutes' in payload
    assert 'flakySignals' in payload
    assert 'notifications' in payload
    assert payload['flakySignals']
    assert payload['notifications']


def test_atomic_claim_only_allows_one_worker_to_take_a_job():
    with SessionLocal() as db:
        job = Job(kind='ANALYZE_WORKFLOW_RUN', status='QUEUED', workflow_run_id='concurrency-job', organization_id=None)
        db.add(job)
        db.commit(); db.refresh(job)
        results = []
        errors = []

        def attempt():
            try:
                result = _claim(job.id)
                results.append(result is not None)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Unexpected exceptions during concurrent claim: {errors}"
        assert len(results) == 2, "Both threads should complete without crashing"
        assert results.count(True) == 1
        with SessionLocal() as fresh_db:
            assert fresh_db.get(Job, job.id).status == 'RUNNING'


def test_failed_permanent_job_retry_endpoint_and_queue_status():
    with SessionLocal() as db:
        job = Job(kind='ANALYZE_WORKFLOW_RUN', status='FAILED_PERMANENT', workflow_run_id='dlq-job-1', organization_id=None)
        db.add(job)
        db.commit(); db.refresh(job)
        response = client.post(f'/api/jobs/{job.id}/retry')
        assert response.status_code == 200
        payload = response.json()
        assert payload['status'] == 'QUEUED'
        assert payload['attempts'] == 0

    queue_status = client.get('/api/dashboard/queue-status')
    assert queue_status.status_code == 200
    assert 'pending' in queue_status.json()
    assert 'failedPermanent' in queue_status.json()

