from unittest.mock import Mock
import httpx
import pytest
from app.services.github import GitHubClient, GitHubPermanentError, GitHubTemporaryError

def response(status=200, payload=None, headers=None):
    item = Mock(status_code=status, headers=headers or {}, json=lambda: payload or [])
    return item

def test_comment_pagination_and_http_operations():
    client = Mock(); client.request.side_effect = [response(payload=[{'id': 1}] * 100), response(payload=[{'id': 2}])]
    assert [x['id'] for x in GitHubClient('secret-token', client).comments('o', 'r', 1)] == [1] * 100 + [2]
    client.request.side_effect = [response(payload={'id': 4, 'html_url': 'u'}), response(payload={'id': 4, 'html_url': 'u'})]
    github = GitHubClient('secret-token', client)
    github.create_comment('o', 'r', 1, 'body'); github.update_comment('o', 'r', '4', 'body')
    assert client.request.call_count == 4

def test_pr_selection_requires_branch_and_head_sha():
    client = Mock(); client.request.return_value = response(payload=[
        {'number': 1, 'state': 'open', 'head': {'sha': 'wrong'}},
        {'number': 2, 'state': 'closed', 'head': {'sha': 'abc'}},
        {'number': 3, 'state': 'open', 'head': {'sha': 'abc'}},
    ])
    result = GitHubClient('token', client).pull_requests_for_run('o', 'r', 'feature', 'abc')
    assert [x['number'] for x in result] == [3, 2]
    assert client.request.call_args.kwargs['params']['head'] == 'o:feature'

@pytest.mark.parametrize('status,headers', [(401, {}), (403, {}), (404, {}), (422, {})])
def test_permanent_http_errors(status, headers):
    client = Mock(); client.request.return_value = response(status, headers=headers)
    with pytest.raises(GitHubPermanentError): GitHubClient('token', client).comments('o', 'r', 1)

@pytest.mark.parametrize('status,headers', [(429, {'retry-after': '5'}), (403, {'x-ratelimit-remaining': '0'}), (500, {}), (502, {}), (503, {})])
def test_temporary_http_errors(status, headers):
    client = Mock(); client.request.return_value = response(status, headers=headers)
    with pytest.raises(GitHubTemporaryError): GitHubClient('token', client).comments('o', 'r', 1)

def test_timeout_and_network_failure_are_temporary():
    for error in (httpx.TimeoutException('timeout'), httpx.ConnectError('offline')):
        client = Mock(); client.request.side_effect = error
        with pytest.raises(GitHubTemporaryError): GitHubClient('secret-token', client).comments('o', 'r', 1)

def test_token_is_not_in_error():
    client = Mock(); client.request.return_value = response(403, headers={})
    with pytest.raises(GitHubPermanentError) as error: GitHubClient('secret-token', client).comments('o', 'r', 1)
    assert 'secret-token' not in str(error.value)
