from unittest.mock import Mock
from app.services.github import GitHubClient

def test_source_context_redacts_bounds_and_fingerprints():
    client = Mock(); client.request.return_value = Mock(status_code=200, headers={}, json=lambda: {'encoding':'base64','content':'c2VjcmV0PXRva2VuX3ZhbHVl'})
    context, fingerprint = GitHubClient('token', client).source_context('o','r',['app.py'], 'sha', 1000)
    assert 'token_value' not in context and 'REDACTED' in context and len(fingerprint) == 64

def test_source_context_rejects_traversal_and_env():
    client = Mock(); client.request.return_value = Mock(status_code=200, headers={}, json=lambda: {'encoding':'base64','content':'eA=='})
    GitHubClient('token', client).source_context('o','r',['../.env','app.py'], 'sha', 1000)
    assert client.request.call_count == 1
