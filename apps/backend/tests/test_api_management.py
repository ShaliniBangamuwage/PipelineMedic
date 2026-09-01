from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import ApiKey, ApiUsageLog, OrganizationMember, OrganizationRole


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'api_management.db'}"
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
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-that-is-long-enough-123456")
    monkeypatch.setattr(settings, "api_key_rate_limit_per_minute", 1)
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


def test_api_keys_can_be_issued_and_used_for_org_scoped_requests(client):
    test_client, _ = client
    token = register(test_client, "owner-api@example.com", "Api Org")
    organization = org_id(test_client, token)

    issue = test_client.post(
        "/api/api-keys",
        headers=auth(token, organization),
        json={"name": "Integration key", "expires_in_days": 30},
    )
    assert issue.status_code == 200, issue.text
    payload = issue.json()
    assert payload["name"] == "Integration key"
    assert "key" in payload
    assert payload["organizationId"] == organization

    api_key = payload["key"]
    repo = test_client.post(
        "/api/repositories",
        headers={"Authorization": f"Bearer {api_key}", "X-Organization-ID": organization},
        json={"owner": "acme", "name": "api-repo", "default_branch": "main"},
    )
    assert repo.status_code == 200, repo.text
    assert repo.json()["fullName"] == "acme/api-repo"


def test_api_key_rate_limit_and_usage_are_enforced(client):
    test_client, db_session = client
    token = register(test_client, "rate-api@example.com", "Rate Org")
    organization = org_id(test_client, token)

    issue = test_client.post(
        "/api/api-keys",
        headers=auth(token, organization),
        json={"name": "Rate limit key", "expires_in_days": 7},
    )
    api_key = issue.json()["key"]

    headers = {"Authorization": f"Bearer {api_key}", "X-Organization-ID": organization}
    first = test_client.get("/api/organizations", headers=headers)
    second = test_client.get("/api/organizations", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429, second.text
    assert second.headers.get("Retry-After")

    db = db_session()
    usage = db.execute(select(ApiUsageLog).where(ApiUsageLog.organization_id == organization)).scalars().all()
    assert usage
    db.close()


def test_invalid_api_key_is_rejected(client):
    test_client, _ = client
    response = test_client.get(
        "/api/organizations",
        headers={"Authorization": "Bearer definitely-not-a-valid-api-key", "X-Organization-ID": "missing-org"},
    )
    assert response.status_code in (401, 404), response.text
