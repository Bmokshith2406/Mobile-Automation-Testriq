import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"

def test_ready_uninitialized():
    # Because init_client() is called on startup, if we just use TestClient without "with" context
    # it might not have run startup events, so HTTP client isn't initialized.
    response = client.get("/ready")
    assert response.status_code == 503

def test_ready_initialized():
    with TestClient(app) as initialized_client:
        response = initialized_client.get("/ready")
        assert response.status_code == 200
        assert response.text == "ready"
