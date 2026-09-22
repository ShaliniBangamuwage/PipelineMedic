from datetime import datetime, timedelta, timezone
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
import app.services.email as email_service
from app.core.config import settings
from app.db import Base, engine, get_db
from app.main import app
from app.models import FailureAnalysis, Invitation, OrganizationMember, OrganizationRole, Repository, User

@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_url=f"sqlite:///{tmp_path / 'authz.db'}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    test_engine=create_engine(database_url, connect_args={"check_same_thread":False})
    Base.metadata.create_all(test_engine)
    TestSession=sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    def override_db():
        db=TestSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    monkeypatch.setattr(settings,"auth_enabled",True)
    monkeypatch.setattr(settings,"jwt_secret","test-secret-that-is-long-enough-123456")
    monkeypatch.setattr(settings,"expose_invitation_urls",True)
    with TestClient(app) as test_client:
        yield test_client, TestSession
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings,"auth_enabled",False)

def register(client,email,organization):
    response=client.post("/api/auth/register",json={"email":email,"password":"long-password-123","organization":organization})
    assert response.status_code==200, response.text
    return response.json()["access_token"]

def auth(token,organization=None):
    headers={"Authorization":f"Bearer {token}"}
    if organization: headers["X-Organization-ID"]=organization
    return headers

def org_id(client,token):
    return client.get("/api/auth/me",headers=auth(token)).json()["organizations"][0]["id"]

def make_viewer(TestSession, client, token):
    organization=org_id(client,token)
    db=TestSession(); member=db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==organization)); member.role=OrganizationRole.VIEWER.value; db.commit(); db.close(); return organization

def test_invalid_and_expired_jwt_are_rejected(client):
    test_client,TestSession=client
    assert test_client.get("/api/organizations",headers=auth("invalid")).status_code==401
    expired=jwt.encode({"sub":"missing","type":"access","exp":datetime.now(timezone.utc)-timedelta(minutes=1)},settings.jwt_secret,algorithm="HS256")
    assert test_client.get("/api/organizations",headers=auth(expired)).status_code==401

def test_refresh_rotation_and_reuse_rejection(client):
    test_client,_=client
    register(test_client,"rotate@example.com","Rotate")
    login=test_client.post("/api/auth/login",json={"email":"rotate@example.com","password":"long-password-123"})
    old=login.cookies.get("refresh_token")
    rotated=test_client.post("/api/auth/refresh",json={"refresh_token":old})
    assert rotated.status_code==200 and rotated.cookies.get("refresh_token")
    assert test_client.post("/api/auth/refresh",json={"refresh_token":old}).status_code==401

def test_organization_listing_isolation_and_permissions(client):
    test_client,TestSession=client
    owner=register(test_client,"owner@example.com","Owners")
    viewer=register(test_client,"viewer@example.com","Viewers")
    viewer_org=make_viewer(TestSession, test_client, viewer); owner_org=org_id(test_client,owner)
    assert test_client.get("/api/organizations",headers=auth(owner)).json()["items"][0]["id"]==owner_org
    assert test_client.get("/api/organizations/%s"%viewer_org,headers=auth(owner,owner_org)).status_code==404
    created=test_client.post("/api/repositories",headers=auth(owner,owner_org),json={"owner":"acme","name":"payments","default_branch":"main"})
    assert created.status_code==200
    repository_id=created.json()["id"]
    assert test_client.get(f"/api/repositories/{repository_id}",headers=auth(viewer,viewer_org)).status_code==404
    assert test_client.post("/api/repositories",headers=auth(viewer,viewer_org),json={"owner":"acme","name":"other"}).status_code==403

def test_viewer_cannot_mutate_and_owner_can_create_organization(client):
    test_client,TestSession=client
    owner=register(test_client,"owner2@example.com","Owner two")
    viewer=register(test_client,"viewer2@example.com","Viewer two")
    viewer_org=make_viewer(TestSession, test_client, viewer); owner_org=org_id(test_client,owner)
    assert test_client.post("/api/organizations",headers=auth(viewer),json={"name":"Viewer owned org"}).status_code==200
    assert test_client.post("/api/organizations",headers=auth(owner),json={"name":"Second org"}).status_code==200
    assert test_client.patch(f"/api/organizations/{viewer_org}",headers=auth(viewer,viewer_org),json={"name":"Nope"}).status_code==403
    assert test_client.delete(f"/api/organizations/{owner_org}",headers=auth(viewer,viewer_org)).status_code==403

def test_final_owner_cannot_be_demoted_or_removed(client):
    test_client,_=client
    owner=register(test_client,"final-owner@example.com","Final owner")
    organization=org_id(test_client,owner)
    members=test_client.get(f"/api/organizations/{organization}/members",headers=auth(owner,organization)).json()["items"]
    member_id=members[0]["id"]
    assert test_client.patch(f"/api/organizations/{organization}/members/{member_id}",headers=auth(owner,organization),json={"role":"VIEWER"}).status_code==400
    assert test_client.delete(f"/api/organizations/{organization}/members/{member_id}",headers=auth(owner,organization)).status_code==400

def test_invitation_duplicate_expired_revoked_and_acceptance(client):
    test_client,TestSession=client
    owner=register(test_client,"invite-owner@example.com","Invite org")
    organization=org_id(test_client,owner)
    payload={"email":"invitee@example.com","role":"DEVELOPER"}
    first=test_client.post(f"/api/organizations/{organization}/invitations",headers=auth(owner,organization),json=payload)
    assert first.status_code==200 and "invitationUrl" in first.json()
    assert test_client.post(f"/api/organizations/{organization}/invitations",headers=auth(owner,organization),json=payload).status_code==409
    invitation_id=first.json()["id"]
    assert test_client.delete(f"/api/organizations/{organization}/invitations/{invitation_id}",headers=auth(owner,organization)).status_code==200
    assert test_client.get(f"/api/organizations/{organization}/invitations",headers=auth(owner,organization)).json()["items"][0]["revoked"] is True
    expired=test_client.post(f"/api/organizations/{organization}/invitations",headers=auth(owner,organization),json={"email":"expired@example.com","role":"VIEWER"}).json()
    db=TestSession(); expired_record=db.execute(select(Invitation).where(Invitation.id==expired["id"])).scalar_one(); expired_record.expires_at=datetime.now(timezone.utc)-timedelta(days=1); db.commit(); db.close()
    invitee=register(test_client,"invitee@example.com","Invitee home")
    token=first.json()["invitationUrl"].split("/")[-1]
    assert test_client.post(f"/api/invitations/{token}/accept",headers=auth(invitee)).status_code==400
    assert test_client.post(f"/api/invitations/{expired['id']}/accept",headers=auth(invitee)).status_code in (400,404)

def test_invitation_uses_frontend_url_and_accepts_normalized_email(client, monkeypatch):
    test_client,_=client
    monkeypatch.setattr(settings,"frontend_url","https://app.example.com")
    monkeypatch.setattr(settings,"expose_invitation_urls",True)

    owner=register(test_client,"owner-email@example.com","Invite URL org")
    organization=org_id(test_client,owner)

    invite_response=test_client.post(
        f"/api/organizations/{organization}/invitations",
        headers=auth(owner,organization),
        json={"email":"Member.Name+Example@Example.com","role":"DEVELOPER"},
    )
    assert invite_response.status_code==200, invite_response.text
    assert invite_response.json()["invitationUrl"].startswith("https://app.example.com/invitations/")

    invitee=register(test_client,"member.name+example@example.com","Invitee home")
    token=invite_response.json()["invitationUrl"].split("/")[-1]
    accept_response=test_client.post(f"/api/invitations/{token}/accept",headers=auth(invitee))
    assert accept_response.status_code==200, accept_response.text
    assert accept_response.json()["organizationId"]==organization


def test_cross_organization_analysis_feedback_resolution_similarity_dashboard_and_demo_exclusion(client):
    test_client,TestSession=client
    first=register(test_client,"analysis-one@example.com","Analysis one")
    second=register(test_client,"analysis-two@example.com","Analysis two")
    first_org=org_id(test_client,first); second_org=org_id(test_client,second)
    created=test_client.post("/api/demo/analyze",headers=auth(first,first_org),data={"log":"TS2322: invalid type"})
    assert created.status_code==200
    analysis_id=created.json()["id"]
    assert test_client.get(f"/api/analyses/{analysis_id}",headers=auth(second,second_org)).status_code==404
    assert test_client.post(f"/api/analyses/{analysis_id}/feedback",headers=auth(second,second_org),json={"accurate":False}).status_code==404
    assert test_client.patch(f"/api/analyses/{analysis_id}/resolve",headers=auth(second,second_org),json={}).status_code==404
    assert test_client.get(f"/api/analyses/{analysis_id}/similar",headers=auth(second,second_org)).status_code==404
    assert test_client.get("/api/dashboard/summary",headers=auth(second,second_org)).json()["totalFailures"]==0
    db=TestSession(); db.add(FailureAnalysis(category="UNKNOWN",summary="demo",root_cause="demo",failed_step="demo",confidence=.2,severity="LOW",cleaned_log="demo",raw_log_excerpt="",source="DEMO")); db.commit(); db.close()
    assert test_client.get("/api/analyses",headers=auth(second,second_org)).json()["total"]==0
    from app.core.config import settings as runtime_settings
    runtime_settings.auth_enabled=False
    assert test_client.get("/api/analyses").status_code==200

def test_empty_organization_overview_is_successful_and_context_is_required(client):
    test_client, _ = client
    token = register(test_client, "empty-dashboard@example.com", "Empty dashboard")
    organization = org_id(test_client, token)
    headers = auth(token, organization)

    assert test_client.get("/api/dashboard/summary", headers=headers).json()["totalFailures"] == 0
    assert test_client.get("/api/dashboard/insights", headers=headers).status_code == 200
    assert test_client.get("/api/dashboard/trends", headers=headers).json()["series"] == []
    assert test_client.get("/api/analyses", headers=headers).json()["items"] == []
    assert test_client.get("/api/dashboard/summary", headers=auth(token)).status_code == 400


def test_invitation_uses_first_frontend_origin_from_comma_separated_config(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com, https://www.app.example.com")
    monkeypatch.setattr(settings, "expose_invitation_urls", True)

    owner = register(test_client, "owner-comma@example.com", "Comma org")
    organization = org_id(test_client, owner)

    response = test_client.post(
        f"/api/organizations/{organization}/invitations",
        headers=auth(owner, organization),
        json={"email": "invitee-comma@example.com", "role": "DEVELOPER"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["invitationUrl"].startswith("https://app.example.com/invitations/")


def test_invitation_email_uses_resend_when_configured(monkeypatch):
    captured = {}

    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")
    monkeypatch.setattr(settings, "resend_api_key", "test-resend-key")
    monkeypatch.setattr(settings, "resend_from_email", "noreply@example.com")

    class FakeResponse:
        status_code = 200
        text = '{"id":"email_123"}'

        def json(self):
            return {"id": "email_123"}

    def fake_post(url, headers=None, json=None, timeout=15.0):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(email_service.httpx, "post", fake_post)

    assert email_service.send_invitation_email("invitee@example.com", "Org", "https://app.example.com/invitations/abc", "Owner") is True
    assert captured["url"].startswith("https://api.resend.com/emails")
    assert captured["headers"]["Authorization"] == "Bearer test-resend-key"
    assert captured["json"]["from"] == "noreply@example.com"
    assert captured["json"]["to"] == ["invitee@example.com"]
