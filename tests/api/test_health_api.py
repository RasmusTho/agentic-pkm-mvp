from fastapi.testclient import TestClient

from app.api.app import app


def test_health_endpoint_returns_checks() -> None:
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "checks" in data
    assert "trace_id" in data
