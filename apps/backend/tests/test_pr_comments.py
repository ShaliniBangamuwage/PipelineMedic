from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import FailureAnalysis, PRCommentDelivery, Repository
from app.services.github import GitHubClient, GitHubPermanentError, GitHubTemporaryError
from app.services.pr_comments import MARKER, MAX_COMMENT_LENGTH, deliver, report

@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pr-comments.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def analysis(**kwargs):
    values = dict(id='analysis-1', summary='Build failed', category='COMPILATION_ERROR', severity='HIGH', confidence=.92,
                  root_cause='bad [input]', failed_step='build', branch='main', commit_sha='abc',
                  cleaned_log='ERROR one\nERROR two\nERROR three\nERROR four\nERROR five\nERROR six',
                  raw_log_excerpt='ERROR one\nERROR two\nERROR three\nERROR four\nERROR five\nERROR six')
    values.update(kwargs)
    return FailureAnalysis(**values)


def repository(**kwargs):
    values = dict(owner='acme', name='app', pr_comments_enabled=True, pr_comment_min_confidence=.8,
                  pr_comment_allowed_branches='main', pr_comment_include_similar_incident=True,
                  pr_comment_include_patch=False)
    values.update(kwargs)
    return Repository(**values)


def test_report_is_bounded_sanitized_and_limited():
    text = report(analysis(raw_log_excerpt='token=secret\n' + ('x' * 10000)))
    assert len(text) <= MAX_COMMENT_LENGTH
    assert 'secret' not in text and '[input]' not in text
    assert text.count('- ') <= 5 and MARKER.format(analysis_id='analysis-1') in text


def test_github_discovery_paginates_and_selects_open_matching_sha():
    client = Mock()
    client.request.side_effect = [Mock(status_code=200, json=lambda: [{'number': 2, 'state': 'closed', 'head': {'sha': 'abc'}}] * 100), Mock(status_code=200, json=lambda: [{'number': 3, 'state': 'open', 'head': {'sha': 'abc'}}])]
    result = GitHubClient('token', client).pull_requests_for_run('acme', 'app', 'main', 'abc')
    assert result[0]['number'] == 3 and client.request.call_count == 2


def test_delivery_creates_new_comment_and_persists_result(db_session):
    repo = repository(id='repo-1'); item = analysis(repository_id='repo-1', organization_id='org-1')
    delivery = PRCommentDelivery(repository_id=repo.id, analysis_id=item.id, organization_id='org-1', status='QUEUED')
    db_session.add_all([repo, item, delivery]); db_session.commit()
    client = Mock(); client.pull_requests_for_run.return_value = [{'number': 4, 'state': 'open'}]; client.comments.return_value = []; client.create_comment.return_value = {'id': 55, 'html_url': 'https://github.test/comment/55'}
    deliver(db_session, delivery, item, repo, client)
    assert delivery.status == 'DELIVERED' and delivery.github_comment_id == '55' and delivery.delivered_at
    client.create_comment.assert_called_once()


def test_delivery_updates_marker_comment_without_duplicate(db_session):
    repo = repository(id='repo-2'); item = analysis(id='analysis-2', repository_id='repo-2')
    delivery = PRCommentDelivery(repository_id=repo.id, analysis_id=item.id, status='QUEUED')
    db_session.add_all([repo, item, delivery]); db_session.commit()
    client = Mock(); client.pull_requests_for_run.return_value = [{'number': 4, 'state': 'open'}]; client.comments.return_value = [{'id': 9, 'body': MARKER.format(analysis_id='analysis-2')}]; client.update_comment.return_value = {'id': 9, 'html_url': 'https://github.test/comment/9'}
    deliver(db_session, delivery, item, repo, client)
    client.update_comment.assert_called_once(); client.create_comment.assert_not_called()


def test_delivery_failure_classes_are_persisted(db_session):
    repo = repository(id='repo-3'); item = analysis(id='analysis-3', repository_id='repo-3')
    delivery = PRCommentDelivery(repository_id=repo.id, analysis_id=item.id, status='QUEUED')
    db_session.add_all([repo, item, delivery]); db_session.commit()
    client = Mock(); client.pull_requests_for_run.side_effect = GitHubTemporaryError('token=secret')
    try: deliver(db_session, delivery, item, repo, client)
    except GitHubTemporaryError: pass
    assert delivery.status == 'RETRYING' and 'secret' not in delivery.last_error_message
    client.pull_requests_for_run.side_effect = GitHubPermanentError('403 permission denied')
    deliver(db_session, delivery, item, repo, client)
    assert delivery.status == 'FAILED' and delivery.last_error_code == 'PERMISSION'
