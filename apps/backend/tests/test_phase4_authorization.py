import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_db
from app.main import app
from app.core.config import settings
from app.models import OrganizationMember, OrganizationRole, Repository

@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}", connect_args={'check_same_thread': False}); Base.metadata.create_all(engine); Session = sessionmaker(bind=engine)
    def override():
        db = Session()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override; monkeypatch.setattr(settings, 'auth_enabled', True); monkeypatch.setattr(settings, 'jwt_secret', 'phase4-test-secret-' + 'x' * 32)
    with TestClient(app) as client: yield client, Session
    app.dependency_overrides.clear(); monkeypatch.setattr(settings, 'auth_enabled', False)

def register(client, email, org):
    return client.post('/api/auth/register', json={'email': email, 'password': 'long-password-123', 'organization': org}).json()

def setup_repo(client, Session, email='owner@example.com'):
    auth = register(client, email, 'Org One'); token = auth['access_token']; auth_headers = {'Authorization': f'Bearer {token}'}; org = client.get('/api/auth/me', headers=auth_headers).json()['organizations'][0]['id']; headers = {**auth_headers, 'X-Organization-ID': org}
    repo = client.post('/api/repositories', headers=headers, json={'owner': 'acme', 'name': 'repo'}).json(); return token, org, repo['id'], headers, Session

def test_settings_roles_and_cross_org_isolation(auth_client):
    client, Session = auth_client; token, org, repo_id, owner_headers, _ = setup_repo(client, Session)
    assert client.patch(f'/api/repositories/{repo_id}/pr-comment-settings', headers=owner_headers, json={'pr_comments_enabled': True, 'pr_comment_min_confidence': .9, 'pr_comment_allowed_branches': 'main', 'pr_comment_include_similar_incident': True, 'pr_comment_include_patch': False}).status_code == 200
    db = Session(); owner = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == org)); owner.role = OrganizationRole.ADMIN.value; db.commit(); db.close()
    assert client.get(f'/api/repositories/{repo_id}/pr-comment-settings', headers=owner_headers).status_code == 200
    assert client.patch(f'/api/repositories/{repo_id}/pr-comment-settings', headers={'Authorization': 'Bearer invalid', 'X-Organization-ID': org}, json={}).status_code == 401

def test_unauthenticated_and_cross_org_settings_rejected(auth_client):
    client, Session = auth_client; _, org, repo_id, _, _ = setup_repo(client, Session)
    assert client.get(f'/api/repositories/{repo_id}/pr-comment-settings').status_code == 401
    auth2 = register(client, 'other@example.com', 'Org Two'); auth2_headers = {'Authorization': f"Bearer {auth2['access_token']}"}; org2 = client.get('/api/auth/me', headers=auth2_headers).json()['organizations'][0]['id']; headers = {**auth2_headers, 'X-Organization-ID': org2}
    assert client.get(f'/api/repositories/{repo_id}/pr-comment-settings', headers=headers).status_code == 404
