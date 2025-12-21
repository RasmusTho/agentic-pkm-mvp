from fastapi.testclient import TestClient

from app.api.app import app


def test_openapi_includes_operator_endpoints() -> None:
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json().get("paths") or {}
    for route in ["/api/health", "/api/settings/validate", "/api/events/tail", "/api/status"]:
        assert route in paths
