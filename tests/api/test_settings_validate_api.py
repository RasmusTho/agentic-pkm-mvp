from fastapi.testclient import TestClient

from app.api.app import app


def test_settings_validate_endpoint_returns_issues() -> None:
    client = TestClient(app)
    resp = client.get("/api/settings/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "issues" in data
