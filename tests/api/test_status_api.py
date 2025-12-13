from fastapi.testclient import TestClient

from app.api.app import app


def test_status_endpoint_returns_snapshot():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "timestamp" in body
    assert body.get("sot_version")
    assert body.get("sot_baseline_version")
    assert body.get("sot_forward_line_version")
    assert isinstance(body.get("stores"), list)
