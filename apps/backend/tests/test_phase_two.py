from io import BytesIO
from zipfile import ZipFile
from unittest.mock import Mock
import uuid
import httpx
import pytest
from sqlalchemy import select
import app.services.ai as ai
import app.worker as worker_module
from app.db import SessionLocal, initialize_database
from app.models import FailureAnalysis, Job, Repository, WorkflowRun
from app.services.ai import GroqAnalyzer, analyze_with_fallback
from app.services.github import GitHubClient, GitHubPermanentError, GitHubTemporaryError
from app.services.similarity import keywords

def test_groq_result_is_validated_and_evidence_is_restricted():
    client=Mock(); client.chat.completions.create.return_value=Mock(choices=[Mock(message=Mock(content='{"summary":"x","category":"COMPILATION_ERROR","rootCause":"bad type","failedStep":"build","evidence":["TS2322","invented"],"suggestedActions":[{"description":"fix","priority":1}],"confidence":0.9,"severity":"HIGH"}'))])
    result,provider=GroqAnalyzer(client).analyze('TS2322', ['TS2322'])
    assert provider=='GROQ' and result['evidence']==['TS2322']

def test_ai_failure_falls_back_without_network(monkeypatch):
    client=Mock(); client.chat.completions.create.side_effect=TimeoutError()
    analyzer=GroqAnalyzer(client)
    monkeypatch.setattr(ai, 'get_analyzer', lambda: analyzer)
    result,provider=analyze_with_fallback('npm ERR module not found',['npm ERR module not found'])
    assert provider=='RULE_BASED'

def test_worker_persists_real_run_block_when_ai_selects_checkout_noise(monkeypatch):
    initialize_database()
    real_log = '''##[group]Checking out the ref
/usr/bin/git checkout --progress --force
##[endgroup]

[command]/usr/bin/git log -1 --format=%H
<commit>

##[group]Run if [ -z "${PIPELINEMEDIC_REQUIRED_ENDPOINT:-}" ]; then
if [ -z "${PIPELINEMEDIC_REQUIRED_ENDPOINT:-}" ]; then
  echo "Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT"
  exit 1
fi
shell: /usr/bin/bash -e {0}
##[endgroup]
Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT
##[error]Process completed with exit code 1.
'''

    class FakeGitHubClient:
        def workflow_logs(self, owner, repo, run_id, max_bytes):
            return real_log

    ai_payload = {
        'summary': 'Configuration Error detected from workflow evidence.',
        'category': 'CONFIGURATION_ERROR',
        'rootCause': 'Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT',
        'failedStep': 'Checking out the ref',
        'evidence': [
            'echo "Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT"',
            'Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT',
            '##[error]Process completed with exit code 1.'
        ],
        'suggestedActions': [{'description': 'fix', 'priority': 1}],
        'confidence': 0.9,
        'severity': 'HIGH'
    }
    client = Mock()
    client.chat.completions.create.return_value = Mock(choices=[Mock(message=Mock(content='{"summary":"Configuration Error detected from workflow evidence.","category":"CONFIGURATION_ERROR","rootCause":"Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT","failedStep":"Checking out the ref","evidence":["echo \"Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT\"","Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT","##[error]Process completed with exit code 1."],"suggestedActions":[{"description":"fix","priority":1}],"confidence":0.9,"severity":"HIGH"}'))])
    monkeypatch.setattr(ai, 'get_analyzer', lambda: GroqAnalyzer(client))
    monkeypatch.setattr(ai.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai.settings, 'groq_api_key', 'demo-key')

    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        repo = Repository(owner='worker-owner', name=f'worker-repo-{suffix}', organization_id='worker-org', github_token='ghp_demo_token', default_branch='main')
        db.add(repo); db.commit(); db.refresh(repo)
        run = WorkflowRun(
            repository_id=repo.id,
            organization_id='worker-org',
            github_run_id='999104',
            run_attempt=1,
            github_run_url='https://github.example/runs/999104',
            workflow_name='CI',
            branch='main',
            head_sha='abc123456',
            status='completed',
            conclusion='failure',
            raw_payload='{}',
        )
        db.add(run); db.commit(); db.refresh(run)
        job = Job(kind='ANALYZE_WORKFLOW_RUN', status='QUEUED', workflow_run_id='999104', run_attempt=1, organization_id='worker-org')
        db.add(job); db.commit(); db.refresh(job)
        worker_module.handle_analyze_workflow_run(job, db, FakeGitHubClient())

    with SessionLocal() as db:
        analysis = db.scalar(select(FailureAnalysis).where(FailureAnalysis.workflow_run_id == '999104', FailureAnalysis.run_attempt == 1))
        assert analysis is not None
        assert analysis.category == 'CONFIGURATION_ERROR'
        assert 'Missing required environment variable:' in analysis.root_cause
        assert analysis.failed_step != 'Checking out the ref'
        assert 'PIPELINEMEDIC_REQUIRED_ENDPOINT' in (analysis.failed_command or '') or 'if [ -z "${PIPELINEMEDIC_REQUIRED_ENDPOINT:-}" ]' in (analysis.failed_step or '')


def test_zip_logs_are_extracted_safely():
    buffer=BytesIO()
    with ZipFile(buffer,'w') as archive:
        archive.writestr('job.txt','ERROR module not found')
        archive.writestr('../unsafe.txt','should not be read')
    response=Mock(status_code=200,content=buffer.getvalue(),headers={})
    client=Mock(); client.get.return_value=response
    text=GitHubClient('demo-token',client).workflow_logs('owner','repo',123)
    assert 'module not found' in text and 'should not be read' not in text

def test_redirected_zip_logs_are_downloaded_and_extracted():
    buffer=BytesIO()
    with ZipFile(buffer,'w') as archive:
        archive.writestr('pytest.txt','FAILED tests/test_example.py::test_failure - AssertionError')
    redirect=Mock(status_code=302,content=b'',headers={'location':'https://logs.example.invalid/archive'})
    archive_response=Mock(status_code=200,content=buffer.getvalue(),headers={'content-type':'application/zip'})
    client=Mock(); client.get.side_effect=[redirect,archive_response]
    text=GitHubClient('demo-token',client).workflow_logs('owner','repo',123)
    assert 'FAILED tests/test_example.py::test_failure' in text
    assert client.get.call_count == 2

@pytest.mark.parametrize("status,expected", [(401, GitHubPermanentError), (403, GitHubPermanentError), (404, GitHubPermanentError), (429, GitHubTemporaryError), (500, GitHubTemporaryError)])
def test_workflow_log_http_failures_are_typed(status, expected):
    response = Mock(status_code=status, content=b"", headers={})
    client = Mock(); client.get.return_value = response
    with pytest.raises(expected):
        GitHubClient("token", client).workflow_logs("owner", "repo", 123)

def test_workflow_log_timeout_is_retryable():
    client = Mock(); client.get.side_effect = httpx.TimeoutException("timeout")
    with pytest.raises(GitHubTemporaryError):
        GitHubClient("token", client).workflow_logs("owner", "repo", 123)

def test_empty_and_corrupt_archives_are_permanent_log_failures():
    empty = Mock(status_code=200, content=b"not-a-zip", headers={})
    client = Mock(); client.get.return_value = empty
    with pytest.raises(GitHubPermanentError):
        GitHubClient("token", client).workflow_logs("owner", "repo", 123)

def test_similarity_keywords_are_normalized():
    assert keywords('ERROR: Module Not Found') == {'module','not','found'}
