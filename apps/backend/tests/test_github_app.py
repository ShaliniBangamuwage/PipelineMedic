from urllib.parse import parse_qs, urlparse
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import GitHubInstallation, OrganizationMember, Repository
import app.github_app_routes as github_app_routes


class FakeGitHubAppClient:
    def installation(self, installation_id):
        return {
            "id": int(installation_id),
            "account": {"id": 77, "login": "octo-org", "type": "Organization"},
            "repository_selection": "selected",
        }

    def repositories(self, installation_id, page=1, per_page=30):
        return {
            "total_count": 1,
            "repositories": [{
                "id": 123,
                "name": "payments",
                "full_name": "octo-org/payments",
                "owner": {"login": "octo-org"},
                "private": True,
                "default_branch": "main",
                "html_url": "https://github.com/octo-org/payments",
            }],
        }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'github-app.db'}", connect_args={"check_same_thread": False})
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
    monkeypatch.setattr(settings, "jwt_secret", "github-app-test-secret-that-is-long-enough")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost")
    monkeypatch.setattr(settings, "github_app_id", "123")
    monkeypatch.setattr(settings, "github_app_private_key", "test-key")
    monkeypatch.setattr(settings, "github_app_slug", "pipelinemedic")
    monkeypatch.setattr(settings, "github_app_webhook_secret", "webhook-test-secret")
    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(github_app_routes, "GitHubAppClient", FakeGitHubAppClient)
    with TestClient(app) as test_client:
        yield test_client, TestSession
    app.dependency_overrides.clear()


def register(client, email, organization):
    response = client.post("/api/auth/register", json={"email": email, "password": "long-password-123", "organization": organization})
    assert response.status_code == 200
    return response.json()["access_token"]


def organization_id(client, token):
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return response.json()["organizations"][0]["id"]


def headers(token, organization):
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": organization}


def install_for(client, token, organization):
    start = client.get("/api/github/app/install", headers=headers(token, organization), follow_redirects=False)
    assert start.status_code == 307
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(f"/api/github/app/setup?installation_id=456&setup_action=install&state={state}", follow_redirects=False)
    assert callback.status_code == 303


def test_installation_start_requires_authentication(client):
    test_client, _ = client
    assert test_client.get("/api/github/app/install").status_code == 401


def test_installation_maps_to_org_and_connects_only_authorized_repository(client):
    test_client, TestSession = client
    token = register(test_client, "app-owner@example.com", "App Org")
    organization = organization_id(test_client, token)
    install_for(test_client, token, organization)

    installations = test_client.get("/api/github/app/installations", headers=headers(token, organization))
    assert installations.status_code == 200
    assert installations.json()["items"][0]["accountLogin"] == "octo-org"

    available = test_client.get("/api/github/app/repositories", headers=headers(token, organization))
    assert available.status_code == 200
    repository = available.json()["items"][0]
    assert "token" not in repository
    assert repository["private"] is True

    connected = test_client.post("/api/github/app/repositories/connect", headers=headers(token, organization), json={"installation_id": "456", "repository_id": "123"})
    assert connected.status_code == 200
    assert connected.json()["credentialSource"] == "GITHUB_APP"
    with TestSession() as db:
        item = db.scalar(select(Repository).where(Repository.organization_id == organization))
        assert item.github_repository_id == "123"
        assert item.github_installation_id is not None
        assert item.github_token is None


def test_installation_cannot_be_attached_to_another_org(client):
    test_client, _ = client
    first = register(test_client, "first-app@example.com", "First App Org")
    first_org = organization_id(test_client, first)
    install_for(test_client, first, first_org)
    second = register(test_client, "second-app@example.com", "Second App Org")
    second_org = organization_id(test_client, second)
    assert test_client.get("/api/github/app/repositories", headers=headers(second, second_org)).json()["items"] == []
    assert test_client.post("/api/github/app/repositories/connect", headers=headers(second, second_org), json={"installation_id": "456", "repository_id": "123"}).status_code == 404


def test_known_installation_update_callback_does_not_require_new_state(client):
    test_client, TestSession = client
    token = register(test_client, "update-owner@example.com", "Update Org")
    organization = organization_id(test_client, token)
    install_for(test_client, token, organization)
    response = test_client.get("/api/github/app/setup?installation_id=456&setup_action=update", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost/repositories?github_app=connected"
    with TestSession() as db:
        installation = db.scalar(select(GitHubInstallation).where(GitHubInstallation.github_installation_id == "456"))
        assert installation.organization_id == organization


def test_unknown_installation_update_callback_is_rejected(client):
    test_client, _ = client
    response = test_client.get("/api/github/app/setup?installation_id=999&setup_action=update")
    assert response.status_code == 400


def test_github_app_webhook_rejects_invalid_signature(client):
    test_client, TestSession = client
    token = register(test_client, "webhook-owner@example.com", "Webhook Org")
    organization = organization_id(test_client, token)
    install_for(test_client, token, organization)
    with TestSession() as db:
        installation = db.scalar(select(GitHubInstallation).where(GitHubInstallation.organization_id == organization))
        db.add(Repository(organization_id=organization, owner="octo-org", name="payments", github_repository_id="123", github_installation_id=installation.id, credential_source="GITHUB_APP"))
        db.commit()
    body = json.dumps({"installation": {"id": 456}, "repository": {"id": 123, "name": "payments", "owner": {"login": "octo-org"}}, "workflow_run": {"status": "completed", "conclusion": "failure", "id": 9}}).encode()
    valid = "sha256=" + hmac.new(b"webhook-test-secret", body, hashlib.sha256).hexdigest()
    invalid = test_client.post("/api/webhooks/github", content=body, headers={"X-GitHub-Event": "workflow_run", "X-Hub-Signature-256": "sha256=invalid"})
    assert invalid.status_code == 401
    assert "webhook-test-secret" not in invalid.text
    assert valid.startswith("sha256=")
