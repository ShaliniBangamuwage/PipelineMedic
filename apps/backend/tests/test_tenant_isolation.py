import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import FailureAnalysis, Job, Repository, WorkflowRun
from app.services.jobs import enqueue


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'tenant-isolation.db'}"
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
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "tenant-test-secret-that-is-long-enough-123456")
    with TestClient(app) as test_client:
        yield test_client, TestSession
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "auth_enabled", False)


def register(client, email, organization):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "long-password-123", "organization": organization},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token, organization=None):
    headers = {"Authorization": f"Bearer {token}"}
    if organization:
        headers["X-Organization-ID"] = organization
    return headers


def org_id(client, token):
    return client.get("/api/auth/me", headers=auth(token)).json()["organizations"][0]["id"]


def test_two_user_repo_and_workflow_isolation(client):
    test_client, TestSession = client
    token_a = register(test_client, "tenant-a@example.com", "Org A")
    token_b = register(test_client, "tenant-b@example.com", "Org B")
    org_a = org_id(test_client, token_a)
    org_b = org_id(test_client, token_b)

    repo_a = test_client.post(
        "/api/repositories",
        headers=auth(token_a, org_a),
        json={"owner": "acme", "name": "repo-a", "default_branch": "main", "github_token": "ghp_token_a", "webhook_secret": "secret_a"},
    )
    repo_b = test_client.post(
        "/api/repositories",
        headers=auth(token_b, org_b),
        json={"owner": "acme", "name": "repo-b", "default_branch": "main", "github_token": "ghp_token_b", "webhook_secret": "secret_b"},
    )
    assert repo_a.status_code == 200, repo_a.text
    assert repo_b.status_code == 200, repo_b.text

    repos_a = test_client.get("/api/repositories", headers=auth(token_a, org_a)).json()["items"]
    repos_b = test_client.get("/api/repositories", headers=auth(token_b, org_b)).json()["items"]
    assert [item["fullName"] for item in repos_a] == ["acme/repo-a"]
    assert [item["fullName"] for item in repos_b] == ["acme/repo-b"]

    assert test_client.get(f"/api/repositories/{repo_b.json()['id']}", headers=auth(token_a, org_a)).status_code == 404
    assert test_client.get(f"/api/repositories/{repo_a.json()['id']}", headers=auth(token_b, org_b)).status_code == 404

    with TestSession() as db:
        base_repo_a = db.scalar(select(Repository).where(Repository.id == repo_a.json()["id"]))
        base_repo_b = db.scalar(select(Repository).where(Repository.id == repo_b.json()["id"]))
        assert base_repo_a.organization_id == org_a
        assert base_repo_b.organization_id == org_b

        run_a = WorkflowRun(
            organization_id=org_a,
            repository_id=base_repo_a.id,
            github_run_id="run-a-1",
            github_run_url="https://example.com/a",
            workflow_name="CI",
            branch="main",
            head_sha="sha-a",
            status="completed",
            conclusion="failure",
            raw_payload='{}',
        )
        run_b = WorkflowRun(
            organization_id=org_b,
            repository_id=base_repo_b.id,
            github_run_id="run-b-1",
            github_run_url="https://example.com/b",
            workflow_name="CI",
            branch="main",
            head_sha="sha-b",
            status="completed",
            conclusion="failure",
            raw_payload='{}',
        )
        db.add_all([run_a, run_b])
        db.commit()
        run_a_id = run_a.id
        run_b_id = run_b.id

    assert test_client.get("/api/workflow-runs", headers=auth(token_a, org_a)).json()["total"] == 1
    assert test_client.get("/api/workflow-runs", headers=auth(token_b, org_b)).json()["total"] == 1
    assert test_client.get(f"/api/workflow-runs/{run_b_id}", headers=auth(token_a, org_a)).status_code == 404
    assert test_client.get(f"/api/workflow-runs/{run_a_id}", headers=auth(token_b, org_b)).status_code == 404

    with TestSession() as db:
        job_a = enqueue(db, "ANALYZE_WORKFLOW_RUN", org_a, None, "run-a-1")
        job_b = enqueue(db, "ANALYZE_WORKFLOW_RUN", org_b, None, "run-b-1")
        assert job_a[0].organization_id == org_a
        assert job_b[0].organization_id == org_b


def test_webhook_uses_repo_secret_and_organization_scope(client):
    test_client, TestSession = client
    token_a = register(test_client, "hook-a@example.com", "Hook Org A")
    token_b = register(test_client, "hook-b@example.com", "Hook Org B")
    org_a = org_id(test_client, token_a)
    org_b = org_id(test_client, token_b)

    repo_a = test_client.post(
        "/api/repositories",
        headers=auth(token_a, org_a),
        json={"owner": "hook-owner", "name": "repo-a", "default_branch": "main", "github_token": "ghp_hook_a", "webhook_secret": "hook-secret-a"},
    ).json()
    repo_b = test_client.post(
        "/api/repositories",
        headers=auth(token_b, org_b),
        json={"owner": "hook-owner", "name": "repo-b", "default_branch": "main", "github_token": "ghp_hook_b", "webhook_secret": "hook-secret-b"},
    ).json()

    payload_a = {
        "action": "completed",
        "workflow_job": {
            "id": 101,
            "run_id": 201,
            "run_url": "https://github.example/runs/201",
            "name": "CI",
            "head_branch": "main",
            "head_sha": "sha-a-1",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.example/jobs/101",
        },
        "repository": {"name": "repo-a", "owner": {"login": "hook-owner"}},
    }
    payload_b = {
        "action": "completed",
        "workflow_job": {
            "id": 102,
            "run_id": 202,
            "run_url": "https://github.example/runs/202",
            "name": "CI",
            "head_branch": "main",
            "head_sha": "sha-b-1",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.example/jobs/102",
        },
        "repository": {"name": "repo-b", "owner": {"login": "hook-owner"}},
    }

    body_a = json.dumps(payload_a).encode()
    body_b = json.dumps(payload_b).encode()
    sig_a = "sha256=" + hmac.new("hook-secret-a".encode(), body_a, hashlib.sha256).hexdigest()
    sig_b = "sha256=" + hmac.new("hook-secret-b".encode(), body_b, hashlib.sha256).hexdigest()

    response_a = test_client.post("/api/webhooks/github", content=body_a, headers={"x-github-event": "workflow_job", "x-hub-signature-256": sig_a})
    response_b = test_client.post("/api/webhooks/github", content=body_b, headers={"x-github-event": "workflow_job", "x-hub-signature-256": sig_b})
    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text

    with TestSession() as db:
        run_a = db.scalar(select(WorkflowRun).where(WorkflowRun.github_run_id == "201"))
        run_b = db.scalar(select(WorkflowRun).where(WorkflowRun.github_run_id == "202"))
        assert run_a is not None and run_a.organization_id == org_a
        assert run_b is not None and run_b.organization_id == org_b
        assert run_a.repository_id == repo_a["id"]
        assert run_b.repository_id == repo_b["id"]

        job_a = db.scalar(select(Job).where(Job.workflow_run_id == "201"))
        job_b = db.scalar(select(Job).where(Job.workflow_run_id == "202"))
        assert job_a is not None and job_a.organization_id == org_a
        assert job_b is not None and job_b.organization_id == org_b


def test_webhook_rejects_ambiguous_repository_ownership(client):
    test_client, _ = client
    token_a = register(test_client, "ambiguous-a@example.com", "Ambiguous Org A")
    token_b = register(test_client, "ambiguous-b@example.com", "Ambiguous Org B")
    org_a = org_id(test_client, token_a)
    org_b = org_id(test_client, token_b)
    payload_repo = {"owner": "same-owner", "name": "same-repo", "default_branch": "main", "github_token": "ghp_a", "webhook_secret": "secret-a"}
    assert test_client.post("/api/repositories", headers=auth(token_a, org_a), json=payload_repo).status_code == 200
    payload_repo["github_token"] = "ghp_b"
    payload_repo["webhook_secret"] = "secret-b"
    assert test_client.post("/api/repositories", headers=auth(token_b, org_b), json=payload_repo).status_code == 200

    payload = {"zen": "ping", "repository": {"name": "same-repo", "owner": {"login": "same-owner"}}}
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"secret-a", body, hashlib.sha256).hexdigest()
    response = test_client.post("/api/webhooks/github", content=body, headers={"x-github-event": "ping", "x-hub-signature-256": signature})
    assert response.status_code == 409
    assert "secret" not in response.text.lower()


def test_user_b_cannot_access_org_a_resources(client):
    test_client, TestSession = client
    token_a = register(test_client, "multi-a@example.com", "Org A")
    token_b = register(test_client, "multi-b@example.com", "Org B")
    org_a = org_id(test_client, token_a)
    org_b = org_id(test_client, token_b)

    repo_a = test_client.post(
        "/api/repositories",
        headers=auth(token_a, org_a),
        json={"owner": "acme", "name": "tenant-a", "default_branch": "main", "github_token": "ghp_token_a", "webhook_secret": "secret_a"},
    )
    assert repo_a.status_code == 200, repo_a.text
    repo_a_id = repo_a.json()["id"]

    with TestSession() as db:
        run = WorkflowRun(
            organization_id=org_a,
            repository_id=repo_a_id,
            github_run_id="tenant-run-a",
            github_run_url="https://example.com/a",
            workflow_name="CI",
            branch="main",
            head_sha="sha-a",
            status="completed",
            conclusion="failure",
            raw_payload='{}',
        )
        db.add(run)
        db.commit(); db.refresh(run)

        job = Job(
            organization_id=org_a,
            workflow_run_id=run.github_run_id,
            kind="ANALYZE_WORKFLOW_RUN",
            status="COMPLETED",
            attempts=1,
            run_attempt=1,
        )
        db.add(job)
        db.commit(); db.refresh(job)
        job_id = job.id

        analysis = FailureAnalysis(
            organization_id=org_a,
            repository_id=repo_a_id,
            workflow_run_id=run.github_run_id,
            run_attempt=1,
            workflow_name="CI",
            branch="main",
            commit_sha="sha-a",
            source="GITHUB",
            category="UNIT_TEST_FAILURE",
            summary="pytest failed",
            root_cause="Assertion failure detected",
            failed_step="pytest",
            confidence=0.93,
            severity="HIGH",
            cleaned_log="Run pytest\nAssertionError",
            raw_log_excerpt="AssertionError",
        )
        db.add(analysis)
        db.commit(); db.refresh(analysis)
        analysis_id = analysis.id

    assert test_client.get("/api/repositories", headers=auth(token_b, org_b)).json()["items"] == []
    assert test_client.get(f"/api/repositories/{repo_a_id}", headers=auth(token_b, org_b)).status_code == 404
    assert test_client.patch(f"/api/repositories/{repo_a_id}", headers=auth(token_b, org_b), json={"default_branch": "develop"}).status_code == 404
    assert test_client.delete(f"/api/repositories/{repo_a_id}", headers=auth(token_b, org_b)).status_code == 404
    assert test_client.get("/api/jobs", headers=auth(token_b, org_b)).json()["items"] == []
    assert test_client.get(f"/api/jobs/{job_id}", headers=auth(token_b, org_b)).status_code == 404
    assert test_client.get("/api/analyses", headers=auth(token_b, org_b)).json()["items"] == []
    assert test_client.get(f"/api/analyses/{analysis_id}", headers=auth(token_b, org_b)).status_code == 404
    assert test_client.get(f"/api/organizations/{org_a}", headers=auth(token_b, org_b)).status_code == 404

    assert test_client.get("/api/repositories", headers=auth(token_a, org_a)).json()["items"][0]["fullName"] == "acme/tenant-a"
    assert test_client.get(f"/api/analyses/{analysis_id}", headers=auth(token_a, org_a)).json()["category"] == "UNIT_TEST_FAILURE"


def test_repo_credentials_are_not_fallback_and_secrets_are_hidden(client):
    test_client, _ = client
    token = register(test_client, "secrets@example.com", "Secrets Org")
    org_id_value = org_id(test_client, token)

    repo = test_client.post(
        "/api/repositories",
        headers=auth(token, org_id_value),
        json={"owner": "privacy", "name": "secret-repo", "default_branch": "main"},
    )
    assert repo.status_code == 200, repo.text
    payload = repo.json()
    assert payload["webhookSecretShownOnce"] is True
    assert payload["webhookSecret"]
    assert "githubToken" not in payload
    assert "github_token" not in payload
    assert "webhook_secret" not in payload
    assert "ghp_" not in json.dumps(payload)
    assert "secret_" not in json.dumps(payload)

    repository_id = payload["id"]
    listed = test_client.get(f"/api/repositories/{repository_id}", headers=auth(token, org_id_value))
    assert listed.status_code == 200
    assert "webhookSecret" not in listed.json()

    with pytest.raises(ValueError):
        from app.main import resolve_repository_token

        resolve_repository_token(None)
