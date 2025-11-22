from fastapi.testclient import TestClient

from app.api.app import app


def test_status_endpoint_returns_snapshot():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "timestamp" in body
    assert "sot_version" in body
    assert isinstance(body.get("stores"), list)
