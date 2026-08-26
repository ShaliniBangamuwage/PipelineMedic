from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client=TestClient(app)

def test_organization_endpoints_reject_when_auth_enabled(monkeypatch):
    monkeypatch.setattr(settings,'auth_enabled',True)
    assert client.get('/api/organizations').status_code==401
    assert client.get('/api/repositories').status_code==401
    monkeypatch.setattr(settings,'auth_enabled',False)

def test_invalid_access_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings,'auth_enabled',True)
    assert client.get('/api/organizations',headers={'Authorization':'Bearer invalid'}).status_code==401
    monkeypatch.setattr(settings,'auth_enabled',False)

def test_demo_analysis_remains_available_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(settings,'auth_enabled',False)
    response=client.post('/api/demo/analyze',data={'log':'TS2322: invalid type'})
    assert response.status_code==200
