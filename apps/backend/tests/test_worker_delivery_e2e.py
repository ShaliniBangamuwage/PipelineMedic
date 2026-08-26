from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import FailureAnalysis, Job, PRCommentDelivery, Repository
from app.services.jobs import JobStatus
from app.services.pr_comments import MARKER, queue_delivery
from app.services.github import GitHubPermanentError, GitHubTemporaryError
from app.worker import handle_job, process_job
import app.worker as worker
from app.core.config import settings

@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'github_token', 'test-token')
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

def seed(db, enabled=True, confidence=.95, branch='main', suffix=''):
    repo = Repository(id='repo' + suffix, owner='acme', name='app' + suffix, pr_comments_enabled=enabled, pr_comment_min_confidence=.8, pr_comment_allowed_branches='main')
    analysis = FailureAnalysis(id='analysis' + suffix, organization_id='org', repository_id='repo' + suffix, summary='Failure', category='UNKNOWN', severity='HIGH', confidence=confidence, root_cause='bad token=secret', failed_step='build', branch=branch, commit_sha='sha' + suffix, cleaned_log='app.py failed', raw_log_excerpt='token=secret')
    db.add_all([repo, analysis]); db.commit()
    delivery, created = queue_delivery(db, analysis, repo)
    return repo, analysis, delivery, created

def test_eligible_delivery_worker_creates_and_persists_comment(session_factory):
    db = session_factory(); repo, analysis, delivery, created = seed(db); assert created and delivery.status == 'QUEUED'
    job = db.scalar(select(Job).where(Job.workflow_run_id == delivery.id)); assert job.kind == 'PR_COMMENT_DELIVERY'
    client = Mock(); client.pull_requests_for_run.return_value = [{'number': 8, 'state': 'open', 'head': {'sha': 'sha'}}]; client.comments.return_value = []; client.create_comment.return_value = {'id': 22, 'html_url': 'https://github.com/comment/22'}
    handle_job(job, db, client)
    assert delivery.status == 'DELIVERED' and delivery.github_comment_id == '22' and delivery.github_comment_url and delivery.delivered_at
    client.create_comment.assert_called_once(); assert 'secret' not in client.create_comment.call_args.args[-1]

def test_existing_marker_updates_without_duplicate(session_factory):
    db = session_factory(); repo, analysis, delivery, _ = seed(db); job = db.scalar(select(Job).where(Job.workflow_run_id == delivery.id))
    client = Mock(); client.pull_requests_for_run.return_value = [{'number': 8, 'state': 'open'}]; client.comments.return_value = [{'id': 9, 'body': MARKER.format(analysis_id=analysis.id)}]; client.update_comment.return_value = {'id': 9, 'html_url': 'https://github.com/comment/9'}
    handle_job(job, db, client)
    client.update_comment.assert_called_once(); client.create_comment.assert_not_called()

def test_temporary_worker_failure_retries_then_succeeds(session_factory, monkeypatch):
    db = session_factory(); repo, analysis, delivery, _ = seed(db); job = db.scalar(select(Job).where(Job.workflow_run_id == delivery.id)); client = Mock(); client.pull_requests_for_run.side_effect = [GitHubTemporaryError('password=secret'), [{'number': 8, 'state': 'open'}]]; client.comments.return_value = []; client.create_comment.return_value = {'id': 33, 'html_url': 'https://github.com/comment/33'}
    monkeypatch.setattr(worker, 'SessionLocal', session_factory)
    assert process_job(job.id, lambda claimed: handle_job(claimed, db, client)) == JobStatus.QUEUED.value
    db.expire_all(); assert delivery.status == 'RETRYING'
    result = process_job(job.id, lambda claimed: handle_job(claimed, db, client))
    assert result == JobStatus.COMPLETED.value, client.method_calls
    assert delivery.status == 'DELIVERED'

def test_permanent_failure_and_skip_conditions(session_factory):
    db = session_factory(); repo, analysis, delivery, _ = seed(db); client = Mock(); client.pull_requests_for_run.side_effect = GitHubPermanentError('403 permission')
    handle_job(Job(id='unused'), db, client) if False else None
    handle_job(Job(kind='PR_COMMENT_DELIVERY', workflow_run_id=delivery.id), db, client)
    assert delivery.status == 'FAILED' and delivery.last_error_code == 'PERMISSION'
    for index, (kwargs, code) in enumerate([({'enabled': False}, 'DISABLED'), ({'confidence': .1}, 'LOW_CONFIDENCE'), ({'branch': 'dev'}, 'BRANCH_NOT_ALLOWED')]):
        local = session_factory(); _, _, skipped, _ = seed(local, suffix=str(index), **kwargs); assert skipped.status == 'SKIPPED' and skipped.last_error_code == code

def test_duplicate_delivery_is_idempotent(session_factory):
    db = session_factory(); repo, analysis, first, created = seed(db); second, created_again = queue_delivery(db, analysis, repo)
    assert created and not created_again and first.id == second.id
