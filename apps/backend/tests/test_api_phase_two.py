import hashlib
import hmac
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
import app.db as db_module
from app.main import app
from app.core.config import settings
from app.db import Base, SessionLocal, ensure_legacy_sqlite_schema, get_db
from app.models import FailureAnalysis, Repository, WorkflowRun, Job, GitHubInstallation
from app.services.analyzer import analyze as analyze_failure, compute_failure_fingerprint
from app.services.github import GitHubPermanentError, GitHubTemporaryError
from app.core.config import Settings
import app.worker as worker_module
from app.worker import _claim

ORIGINAL_SESSION_LOCAL = SessionLocal

@pytest.fixture(autouse=True)
def disable_auth(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'phase-two.db'}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    db_module.SessionLocal = TestSession
    worker_module.SessionLocal = TestSession
    globals()['SessionLocal'] = TestSession
    monkeypatch.setattr(settings, 'auth_enabled', False)
    monkeypatch.setattr(settings, 'jwt_secret', 'phase-two-test-secret-that-is-long-enough-123456')
    yield
    app.dependency_overrides.clear()
    db_module.SessionLocal = ORIGINAL_SESSION_LOCAL
    worker_module.SessionLocal = ORIGINAL_SESSION_LOCAL
    globals()['SessionLocal'] = ORIGINAL_SESSION_LOCAL
    monkeypatch.setattr(settings, 'auth_enabled', False)

client=TestClient(app)

def test_legacy_schema_migration_adds_missing_repository_columns():
    legacy_engine = create_engine('sqlite:///:memory:')
    with legacy_engine.begin() as conn:
        conn.execute(text("CREATE TABLE repositories (id VARCHAR(36) PRIMARY KEY, owner VARCHAR(100), name VARCHAR(100), default_branch VARCHAR(100), active BOOLEAN, created_at DATETIME, updated_at DATETIME)"))
    ensure_legacy_sqlite_schema(legacy_engine)
    with legacy_engine.begin() as conn:
        columns = {column['name'] for column in inspect(conn).get_columns('repositories')}
    assert {'organization_id', 'github_token', 'webhook_secret'} <= columns


def test_legacy_analysis_column_sql_uses_postgres_compatible_types():
    sqlite_columns = db_module._legacy_analysis_columns_sql(True)
    postgres_columns = db_module._legacy_analysis_columns_sql(False)
    assert sqlite_columns['first_seen'] == 'DATETIME'
    assert postgres_columns['first_seen'] == 'TIMESTAMP WITH TIME ZONE'
    assert postgres_columns['resolved'] == 'BOOLEAN DEFAULT FALSE'


def test_legacy_schema_migration_removes_global_repo_unique_constraint():
    legacy_engine = create_engine('sqlite:///:memory:')
    with legacy_engine.begin() as conn:
        conn.execute(text("CREATE TABLE repositories (id VARCHAR(36) PRIMARY KEY, organization_id VARCHAR(36), owner VARCHAR(100), name VARCHAR(100), default_branch VARCHAR(100), active BOOLEAN, pr_comments_enabled BOOLEAN DEFAULT 0, pr_comment_min_confidence FLOAT DEFAULT 0.8, pr_comment_allowed_branches TEXT DEFAULT 'main', pr_comment_include_similar_incident BOOLEAN DEFAULT 1, pr_comment_include_patch BOOLEAN DEFAULT 0, github_token TEXT, webhook_secret VARCHAR(255) NOT NULL DEFAULT '', created_at DATETIME, updated_at DATETIME, UNIQUE(owner, name))"))
    ensure_legacy_sqlite_schema(legacy_engine)
    with legacy_engine.begin() as conn:
        conn.execute(text("INSERT INTO repositories (id, organization_id, owner, name, default_branch, active, pr_comments_enabled, pr_comment_min_confidence, pr_comment_allowed_branches, pr_comment_include_similar_incident, pr_comment_include_patch, github_token, webhook_secret, created_at, updated_at) VALUES ('a', 'org-1', 'octo', 'demo-trends', 'main', 1, 0, 0.8, 'main', 1, 0, NULL, 'secret-a', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')"))
        conn.execute(text("INSERT INTO repositories (id, organization_id, owner, name, default_branch, active, pr_comments_enabled, pr_comment_min_confidence, pr_comment_allowed_branches, pr_comment_include_similar_incident, pr_comment_include_patch, github_token, webhook_secret, created_at, updated_at) VALUES ('b', 'org-2', 'octo', 'demo-trends', 'main', 1, 0, 0.8, 'main', 1, 0, NULL, 'secret-b', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')"))
        indexes = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='repositories' AND name='uq_repository_org_owner_name'")).fetchall()
    assert indexes


def test_legacy_analysis_organization_is_backfilled_from_repository():
    legacy_engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(legacy_engine)
    from sqlalchemy.orm import sessionmaker
    LegacySession = sessionmaker(bind=legacy_engine)
    with LegacySession() as db:
        repo = Repository(id='backfill-repo', organization_id='backfill-org', owner='backfill-owner', name='backfill-name')
        analysis = FailureAnalysis(id='backfill-analysis', organization_id=None, repository_id=repo.id, workflow_name='CI', category='UNKNOWN', summary='Failure', root_cause='Cause', confidence=.5, severity='LOW', cleaned_log='log', raw_log_excerpt='log')
        db.add_all([repo, analysis]); db.commit()
    ensure_legacy_sqlite_schema(legacy_engine)
    with LegacySession() as db:
        assert db.get(FailureAnalysis, 'backfill-analysis').organization_id == 'backfill-org'


def test_health_endpoint():
    response=client.get('/api/health')
    assert response.status_code==200 and response.json()['status']=='healthy'


def test_analysis_response_exposes_suggested_actions():
    with SessionLocal() as db:
        repo = Repository(owner='suggestion-owner', name='suggestion-repo', default_branch='main', organization_id='org-suggestions')
        db.add(repo); db.commit(); db.refresh(repo)
        analysis = FailureAnalysis(
            organization_id='org-suggestions', repository_id=repo.id,
            workflow_name='CI', category='DEPENDENCY_ERROR', summary='Install failed',
            root_cause='Missing dependency', failed_step='npm install', confidence=0.9,
            severity='HIGH', cleaned_log='npm ERR! missing dependency', raw_log_excerpt='npm ERR! missing dependency',
            suggested_actions='[{"description":"Install the missing package lock and retry CI.", "priority": 1}]',
        )
        db.add(analysis); db.commit(); db.refresh(analysis)

    response = client.get(f'/api/analyses/{analysis.id}')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['suggestedActions'][0]['description'] == 'Install the missing package lock and retry CI.'


def test_rule_analyzer_uses_evidence_specific_recommendations():
    log = '''
    pytest tests/test_auth.py::test_login_flow -q
    FAILED tests/test_auth.py::test_login_flow
    E assert user.is_admin is True
    E AssertionError: assert False
    '''
    result = analyze_failure(log, [
        'FAILED tests/test_auth.py::test_login_flow',
        'E assert user.is_admin is True',
        'AssertionError: assert False',
    ])
    assert result['failing_test'] == 'tests/test_auth.py::test_login_flow'
    assert result['assertion_evidence'] == 'E assert user.is_admin is True'
    assert any('test_login_flow' in action['description'] for action in result['suggested_actions'])


def test_analysis_fingerprint_tracks_occurrence_metadata():
    from app.main import synchronize_analysis_fingerprint_metadata

    with SessionLocal() as db:
        repo = Repository(owner='fp-owner', name='fp-repo', default_branch='main', organization_id='org-fingerprint')
        db.add(repo); db.commit(); db.refresh(repo)

        first = FailureAnalysis(
            organization_id='org-fingerprint', repository_id=repo.id,
            workflow_name='CI', category='UNIT_TEST_FAILURE', summary='Login assertion failed',
            root_cause='Bad assertion', failed_step='pytest', confidence=0.8,
            severity='HIGH', cleaned_log='FAILED tests/test_auth.py::test_login_flow', raw_log_excerpt='FAILED tests/test_auth.py::test_login_flow',
            suggested_actions='[]', fingerprint='', occurrence_count=1,
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
        )
        db.add(first); db.commit(); db.refresh(first)

        synchronize_analysis_fingerprint_metadata(db, first)

        second = FailureAnalysis(
            organization_id='org-fingerprint', repository_id=repo.id,
            workflow_name='CI', category='UNIT_TEST_FAILURE', summary='Login assertion failed',
            root_cause='Bad assertion', failed_step='pytest', confidence=0.8,
            severity='HIGH', cleaned_log='FAILED tests/test_auth.py::test_login_flow', raw_log_excerpt='FAILED tests/test_auth.py::test_login_flow',
            suggested_actions='[]', fingerprint='', occurrence_count=1,
            first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
        )
        db.add(second); db.commit(); db.refresh(second)

        synchronize_analysis_fingerprint_metadata(db, second)

        assert second.fingerprint == first.fingerprint
        assert second.occurrence_count >= 2
        assert second.first_seen is not None and second.last_seen is not None


def test_repository_crud_and_feedback():
    owner='phase-two-owner'; name='phase-two-repo'
    created=client.post('/api/repositories',json={'owner':owner,'name':name,'default_branch':'main'}); assert created.status_code in (200,409)
    item=created.json() if created.status_code==200 else client.get('/api/repositories').json()['items'][0]
    repository_id=item['id']
    updated=client.patch(f'/api/repositories/{repository_id}',json={'active':False}); assert updated.status_code==200
    assert client.delete(f'/api/repositories/{repository_id}').status_code==200


def test_repository_creation_generates_webhook_secret_and_marks_token_state():
    created = client.post('/api/repositories', json={'owner': 'phase-two-owner-2', 'name': 'phase-two-repo-2', 'default_branch': 'main'})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body['webhookSecretShownOnce'] is True
    assert body['webhookSecret']
    assert 'githubTokenConfigured' in body
    assert body['githubTokenConfigured'] is False
    assert body['webhookSecretConfigured'] is True

    repository_id = body['id']
    listed = client.get(f'/api/repositories/{repository_id}')
    assert listed.status_code == 200
    assert 'webhookSecret' not in listed.json()


def test_repository_verification_returns_non_sensitive_metadata(monkeypatch):
    def metadata(self, owner, repo):
        assert owner == 'verify-owner'
        assert repo == 'verify-repo'
        return {'owner': {'login': owner}, 'name': repo, 'full_name': f'{owner}/{repo}', 'default_branch': 'develop', 'private': True, 'visibility': 'private'}

    monkeypatch.setattr('app.main.GitHubClient.repository_metadata', metadata)
    response = client.post('/api/repositories/verify', json={'owner': 'verify-owner', 'name': 'verify-repo', 'github_token': 'ghp_never_returned'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {'verified': True, 'owner': 'verify-owner', 'name': 'verify-repo', 'fullName': 'verify-owner/verify-repo', 'defaultBranch': 'develop', 'visibility': 'private'}
    assert 'ghp_' not in response.text


def test_repository_verification_maps_github_failures_safely(monkeypatch):
    monkeypatch.setattr('app.main.GitHubClient.repository_metadata', lambda *_: (_ for _ in ()).throw(GitHubPermanentError('rejected', 403)))
    response = client.post('/api/repositories/verify', json={'owner': 'verify-owner', 'name': 'verify-repo', 'github_token': 'ghp_never_returned'})
    assert response.status_code == 403
    assert 'ghp_' not in response.text

    monkeypatch.setattr('app.main.GitHubClient.repository_metadata', lambda *_: (_ for _ in ()).throw(GitHubTemporaryError('unavailable')))
    response = client.post('/api/repositories/verify', json={'owner': 'verify-owner', 'name': 'verify-repo', 'github_token': 'ghp_never_returned'})
    assert response.status_code == 503
    assert 'ghp_' not in response.text


def test_production_configuration_requires_authentication_and_strong_secret():
    with pytest.raises(ValueError, match='AUTH_ENABLED'):
        Settings(app_env='production', auth_enabled=False, jwt_secret='x' * 64)
    with pytest.raises(ValueError, match='JWT_SECRET'):
        Settings(app_env='production', auth_enabled=True, jwt_secret='short')


def test_repository_webhook_secret_rotation_returns_secret_once():
    created = client.post('/api/repositories', json={'owner': 'phase-two-owner-rotate', 'name': 'phase-two-repo-rotate'})
    assert created.status_code == 200, created.text
    repository_id = created.json()['id']
    original = created.json()['webhookSecret']

    rotated = client.post(f'/api/repositories/{repository_id}/rotate-webhook-secret')
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()['webhookSecretShownOnce'] is True
    assert rotated.json()['webhookSecret']
    assert rotated.json()['webhookSecret'] != original
    assert 'Update this secret in your GitHub repository webhook settings.' in rotated.json()['message']

    listed = client.get(f'/api/repositories/{repository_id}')
    assert listed.status_code == 200
    assert 'webhookSecret' not in listed.json()


def test_repository_specific_webhook_secret_is_validated(monkeypatch):
    monkeypatch.setattr(settings, 'github_webhook_secret', 'legacy-secret')
    repo = Repository(owner='repo-secret-owner', name='repo-secret-repo', default_branch='main', webhook_secret='repo-secret-123')
    with SessionLocal() as db:
        db.add(repo); db.commit(); db.refresh(repo)
    payload = {
        'action': 'completed',
        'workflow_job': {
            'id': 101,
            'run_id': 202,
            'run_url': 'https://github.example/runs/202',
            'name': 'CI',
            'head_branch': 'main',
            'head_sha': 'abc456',
            'status': 'completed',
            'conclusion': 'failure',
            'html_url': 'https://github.example/jobs/101',
        },
        'repository': {'name': 'repo-secret-repo', 'owner': {'login': 'repo-secret-owner'}},
    }
    body = json.dumps(payload).encode()
    good_signature = 'sha256=' + hmac.new(repo.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    good_response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_job', 'x-hub-signature-256': good_signature})
    assert good_response.status_code == 200, good_response.text
    bad_signature = 'sha256=' + hmac.new('wrong-secret'.encode(), body, hashlib.sha256).hexdigest()
    bad_response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_job', 'x-hub-signature-256': bad_signature})
    assert bad_response.status_code == 401, bad_response.text
    monkeypatch.setattr(settings, 'github_webhook_secret', '')


def test_repository_webhook_secret_update_is_persisted_and_ping_accepts_case_variation():
    with SessionLocal() as db:
        repo = Repository(owner='ShaliniBangamuwage', name='my-portfolio', default_branch='main', webhook_secret='old-secret')
        db.add(repo); db.commit(); db.refresh(repo)
        repository_id = repo.id

    updated = client.patch(f'/api/repositories/{repository_id}', json={'webhook_secret': 'new-secret'})
    assert updated.status_code == 200, updated.text
    assert 'webhookSecret' not in updated.json()

    with SessionLocal() as db:
        repo = db.get(Repository, repository_id)
        assert repo.webhook_secret == 'new-secret'

    payload = {'zen': 'Keep it logically awesome.', 'repository': {'name': 'MY-PORTFOLIO', 'owner': {'login': 'shalinibangamuwage'}}}
    body = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(b'new-secret', body, hashlib.sha256).hexdigest()
    response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'ping', 'x-hub-signature-256': signature})
    assert response.status_code == 200
    assert response.json() == {'ok': True, 'event': 'ping'}


def test_webhook_resolution_prefers_github_app_identity_for_duplicate_owner_name_after_restart(monkeypatch):
    monkeypatch.setattr(settings, 'github_app_webhook_secret', '')
    with SessionLocal() as db:
        installation = GitHubInstallation(
            id='install-shalini',
            organization_id='org-app',
            github_installation_id='456',
            github_account_id='42',
            github_account_login='ShaliniBangamuwage',
            github_account_type='User',
            active=True,
        )
        pat_repo = Repository(
            organization_id='org-pat',
            owner='ShaliniBangamuwage',
            name='my-portfolio',
            default_branch='main',
            active=True,
            credential_source='PAT',
            github_repository_id='999',
            webhook_secret='pat-secret',
        )
        app_repo = Repository(
            organization_id='org-app',
            owner='ShaliniBangamuwage',
            name='my-portfolio',
            default_branch='main',
            active=True,
            credential_source='GITHUB_APP',
            github_repository_id='1100047919',
            github_installation_id=installation.id,
            webhook_secret='app-secret',
        )
        db.add_all([installation, pat_repo, app_repo])
        db.commit()

    payload = {
        'action': 'completed',
        'workflow_run': {
            'id': 987,
            'run_url': 'https://github.example/runs/987',
            'html_url': 'https://github.example/runs/987',
            'name': 'CI',
            'head_branch': 'main',
            'head_sha': 'sha-987',
            'status': 'completed',
            'conclusion': 'failure',
        },
        'repository': {
            'id': 1100047919,
            'name': 'my-portfolio',
            'owner': {'login': 'ShaliniBangamuwage'},
        },
        'installation': {'id': 456},
    }
    body = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(b'app-secret', body, hashlib.sha256).hexdigest()
    response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_run', 'x-hub-signature-256': signature})
    assert response.status_code == 200, response.text
    assert response.json()['event'] == 'workflow_run'


def test_workflow_run_webhook_valid_signature_is_accepted():
    with SessionLocal() as db:
        repo = Repository(owner='workflow-owner', name='workflow-repo', default_branch='main', webhook_secret='workflow-secret')
        db.add(repo); db.commit(); db.refresh(repo)
    payload = {
        'action': 'completed',
        'workflow_run': {
            'id': 303,
            'run_url': 'https://github.example/runs/303',
            'html_url': 'https://github.example/runs/303',
            'name': 'CI',
            'head_branch': 'main',
            'head_sha': 'workflow-sha',
            'status': 'completed',
            'conclusion': 'failure',
        },
        'repository': {'name': 'WORKFLOW-REPO', 'owner': {'login': 'WORKFLOW-OWNER'}},
    }
    body = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(b'workflow-secret', body, hashlib.sha256).hexdigest()
    response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_run', 'x-hub-signature-256': signature})
    assert response.status_code == 200, response.text
    assert response.json()['event'] == 'workflow_run'


def test_workflow_webhook_tracks_distinct_runs_and_rerun_attempts():
    with SessionLocal() as db:
        repo = Repository(owner='attempt-owner', name='attempt-repo', default_branch='main', webhook_secret='attempt-secret')
        db.add(repo); db.commit(); db.refresh(repo)

    def deliver(run_id, attempt, delivery):
        payload = {
            'action': 'completed',
            'workflow_run': {'id': run_id, 'run_attempt': attempt, 'run_url': f'https://example.test/{run_id}', 'name': 'CI', 'head_branch': 'main', 'head_sha': f'sha-{run_id}-{attempt}', 'status': 'completed', 'conclusion': 'failure'},
            'repository': {'name': 'attempt-repo', 'owner': {'login': 'attempt-owner'}},
        }
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'attempt-secret', body, hashlib.sha256).hexdigest()
        return client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_run', 'x-github-delivery': delivery, 'x-hub-signature-256': signature})

    assert deliver(401, 1, 'delivery-401-a').status_code == 200
    assert deliver(402, 1, 'delivery-402-a').status_code == 200
    assert deliver(401, 2, 'delivery-401-b').status_code == 200
    assert deliver(401, 2, 'delivery-401-b').status_code == 200

    with SessionLocal() as db:
        rows = db.scalars(select(WorkflowRun).where(WorkflowRun.github_run_id.in_(['401', '402']))).all()
        assert {(row.github_run_id, row.run_attempt) for row in rows} == {('401', 1), ('401', 2), ('402', 1)}
        jobs = db.scalars(select(Job).where(Job.workflow_run_id.in_(['401', '402']))).all()
        assert {(job.workflow_run_id, job.run_attempt) for job in jobs} == {('401', 1), ('401', 2), ('402', 1)}


def test_invalid_webhook_signature_is_rejected(monkeypatch):
    with SessionLocal() as db:
        repo = Repository(owner='repo-secret-owner', name='repo-secret-repo', default_branch='main', webhook_secret='test-secret')
        db.add(repo); db.commit(); db.refresh(repo)
    payload = {
        'action': 'completed',
        'workflow_job': {
            'id': 101,
            'run_id': 202,
            'run_url': 'https://github.example/runs/202',
            'name': 'CI',
            'head_branch': 'main',
            'head_sha': 'abc456',
            'status': 'completed',
            'conclusion': 'failure',
            'html_url': 'https://github.example/jobs/101',
        },
        'repository': {'name': 'repo-secret-repo', 'owner': {'login': 'repo-secret-owner'}},
    }
    body = json.dumps(payload).encode()
    response = client.post('/api/webhooks/github', content=body, headers={'x-github-event': 'workflow_job', 'x-hub-signature-256': 'sha256=invalid'})
    assert response.status_code == 401


def test_workflow_job_failure_webhook_persists_and_queues(monkeypatch):
    with SessionLocal() as db:
        repo = Repository(owner='octo', name='demo', default_branch='main', webhook_secret='test-secret')
        db.add(repo); db.commit(); db.refresh(repo)
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
    signature = 'sha256=' + hmac.new('test-secret'.encode(), body, hashlib.sha256).hexdigest()
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


def test_inline_worker_uses_real_job_handler(monkeypatch):
    class FakeGitHubClient:
        def __init__(self, token):
            pass

        def workflow_logs(self, owner, repo, run_id, max_bytes):
            return "Run python -m pytest\nAssertionError: expected 2"

    monkeypatch.setattr(worker_module, "GitHubClient", FakeGitHubClient)
    with SessionLocal() as db:
        repo = Repository(owner='inline-owner-phase-two', name='inline-repo-phase-two', organization_id='inline-org', default_branch='main', github_token='ghp_inline_test_token_123')
        db.add(repo)
        db.commit(); db.refresh(repo)
        run = WorkflowRun(
            repository_id=repo.id,
            organization_id='inline-org',
            github_run_id='999001',
            run_attempt=5,
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
        job = Job(kind='ANALYZE_WORKFLOW_RUN', status='QUEUED', workflow_run_id='999001', run_attempt=5, organization_id='inline-org')
        db.add(job)
        db.commit(); db.refresh(job)

    assert worker_module.run_once() is True

    with SessionLocal() as db:
        refreshed = db.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == 'COMPLETED'
        analysis = db.scalar(select(FailureAnalysis).where(FailureAnalysis.commit_sha == 'inline-sha-999', FailureAnalysis.workflow_name == 'CI', FailureAnalysis.source == 'GITHUB'))
        assert analysis is not None
        assert analysis.organization_id == 'inline-org'
        assert analysis.workflow_run_id == '999001'
        assert analysis.run_attempt == 5


def test_analysis_identity_allows_a_new_attempt_without_duplicate_reprocessing():
    with SessionLocal() as db:
        repo = Repository(owner='identity-owner', name='identity-repo', organization_id='identity-org', github_token='ghp_identity_test_token')
        db.add(repo); db.commit(); db.refresh(repo)
        db.add_all([
            WorkflowRun(repository_id=repo.id, organization_id='identity-org', github_run_id='identity-run', run_attempt=1, github_run_url='https://example.test/1', workflow_name='CI', branch='main', head_sha='same-sha', status='completed', conclusion='failure', raw_payload='{}'),
            WorkflowRun(repository_id=repo.id, organization_id='identity-org', github_run_id='identity-run', run_attempt=2, github_run_url='https://example.test/2', workflow_name='CI', branch='main', head_sha='same-sha', status='completed', conclusion='failure', raw_payload='{}'),
        ])
        db.add(FailureAnalysis(organization_id='identity-org', repository_id=repo.id, workflow_run_id='identity-run', run_attempt=1, workflow_name='CI', commit_sha='same-sha', source='GITHUB', category='UNIT_TEST_FAILURE', summary='Attempt one', root_cause='assertion', failed_step='pytest', confidence=.9, severity='HIGH', cleaned_log='FAILED', raw_log_excerpt='FAILED'))
        db.commit()
        existing = db.scalar(select(FailureAnalysis).where(FailureAnalysis.workflow_run_id == 'identity-run', FailureAnalysis.run_attempt == 1))
        new_attempt = db.scalar(select(FailureAnalysis).where(FailureAnalysis.workflow_run_id == 'identity-run', FailureAnalysis.run_attempt == 2))
        assert existing is not None
        assert new_attempt is None


def test_workflow_run_endpoints_and_dashboard_trends():
    with SessionLocal() as db:
        repo = Repository(owner='octo', name='demo-trends', default_branch='main')
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
        repo = Repository(owner='advanced-owner-phase-two', name='advanced-repo-phase-two', default_branch='main')
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

