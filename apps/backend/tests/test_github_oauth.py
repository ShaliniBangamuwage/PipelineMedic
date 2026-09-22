import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app.core.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, OrganizationMember, OAuthLoginState, User
import app.auth_routes as auth_routes

@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'oauth.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "oauth-test-secret-that-is-long-enough-123456")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost")
    monkeypatch.setattr(settings, "github_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "github_oauth_callback_url", "http://localhost:8000/api/auth/github/callback")
    with TestClient(app) as test_client:
        yield test_client, TestSession
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "auth_enabled", False)


def test_oauth_start_generates_state_pkce_and_redirect(client):
    test_client, TestSession = client
    response = test_client.get("/api/auth/github", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    query = parse_qs(urlparse(location).query)
    assert query["client_id"] == ["client-id"]
    assert query["scope"] == ["read:user user:email"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"]
    assert response.cookies.get("github_oauth_state") == query["state"][0]
    with TestSession() as db:
        record = db.scalar(select(OAuthLoginState).where(OAuthLoginState.state_hash == hashlib.sha256(query["state"][0].encode()).hexdigest()))
        assert record is not None
        assert record.code_verifier


def test_oauth_callback_rejects_invalid_state(client):
    test_client, _ = client
    response = test_client.get("/api/auth/github/callback?code=code&state=wrong", follow_redirects=False)
    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


def test_oauth_production_uses_cross_site_session_cookies(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "frontend_url", "https://pipelinemedic-frontend.vercel.app")
    monkeypatch.setattr(auth_routes, "_github_exchange", lambda code, verifier: "github-access-token")
    monkeypatch.setattr(auth_routes, "_github_identity", lambda token: ("12345", "octo-login", "octo@example.com"))

    start = test_client.get("/api/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = test_client.get(f"/api/auth/github/callback?code=code&state={state}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "https://pipelinemedic-frontend.vercel.app/overview"
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "samesite=none" in set_cookie
    assert "secure" in set_cookie


def test_oauth_creates_one_user_and_workspace_then_reuses_both(client, monkeypatch):
    test_client, TestSession = client
    monkeypatch.setattr(auth_routes, "_github_exchange", lambda code, verifier: "github-access-token")
    monkeypatch.setattr(auth_routes, "_github_identity", lambda token: ("12345", "octo-login", "octo@example.com"))

    def login_once():
        start = test_client.get("/api/auth/github", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        return test_client.get(f"/api/auth/github/callback?code=code&state={state}", follow_redirects=False)

    first = login_once()
    assert first.status_code == 303
    assert first.headers["location"] == "http://localhost/overview"
    first_refresh = first.cookies.get("refresh_token")
    assert first_refresh
    with TestSession() as db:
        first_user = db.scalar(select(User).where(User.github_user_id == "12345"))
        assert first_user is not None
        first_org_count = len(db.scalars(select(OrganizationMember).where(OrganizationMember.user_id == first_user.id)).all())
        assert first_org_count == 1

    second = login_once()
    assert second.status_code == 303
    with TestSession() as db:
        assert len(db.scalars(select(User).where(User.github_user_id == "12345")).all()) == 1
        assert len(db.scalars(select(Organization).where(Organization.slug == "octo-login's-workspace")).all()) == 1
    assert second.cookies.get("refresh_token") != first_refresh


def test_oauth_links_only_verified_email_to_existing_account(client, monkeypatch):
    test_client, TestSession = client
    password_response = test_client.post("/api/auth/register", json={"email": "octo@example.com", "password": "long-password-123", "organization": "Existing Org"})
    assert password_response.status_code == 200
    with TestSession() as db:
        existing = db.scalar(select(User).where(User.email == "octo@example.com"))
        existing_id = existing.id
    monkeypatch.setattr(auth_routes, "_github_exchange", lambda code, verifier: "github-access-token")
    monkeypatch.setattr(auth_routes, "_github_identity", lambda token: ("67890", "octo-login", "octo@example.com"))
    start = test_client.get("/api/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = test_client.get(f"/api/auth/github/callback?code=code&state={state}", follow_redirects=False)
    assert response.status_code == 303
    with TestSession() as db:
        linked = db.get(User, existing_id)
        assert linked.github_user_id == "67890"
        assert len(db.scalars(select(User).where(User.email == "octo@example.com")).all()) == 1
