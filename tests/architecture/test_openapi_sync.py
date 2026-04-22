from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app


def test_openapi_includes_documented_routes():
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    paths = set((data.get("paths") or {}).keys())
    expected = {"/api/status", "/api/ask", "/api/orientation"}
    missing = expected - paths
    assert not missing, f"Documented API routes missing from OpenAPI: {missing}"
