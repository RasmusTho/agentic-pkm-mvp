from fastapi.testclient import TestClient

from app.main import app


def test_context_endpoint_returns_keys():
    client = TestClient(app)
    r = client.get("/context")
    assert r.status_code == 200
    data = r.json()
    for key in ("system", "projects", "preferences"):
        assert key in data
