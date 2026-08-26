import hashlib
import hmac
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client=TestClient(app)

def test_health_endpoint():
    response=client.get('/api/health')
    assert response.status_code==200 and response.json()['status']=='healthy'

def test_repository_crud_and_feedback():
    owner='phase-two-owner'; name='phase-two-repo'
    created=client.post('/api/repositories',json={'owner':owner,'name':name,'default_branch':'main'}); assert created.status_code in (200,409)
    item=created.json() if created.status_code==200 else client.get('/api/repositories').json()['items'][0]
    repository_id=item['id']
    updated=client.patch(f'/api/repositories/{repository_id}',json={'active':False}); assert updated.status_code==200
    assert client.delete(f'/api/repositories/{repository_id}').status_code==200

def test_invalid_webhook_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(settings,'github_webhook_secret','test-secret')
    payload=b'{"zen":"test"}'
    response=client.post('/api/webhooks/github',content=payload,headers={'x-github-event':'ping','x-hub-signature-256':'sha256=invalid'})
    assert response.status_code==401
    monkeypatch.setattr(settings,'github_webhook_secret','')
