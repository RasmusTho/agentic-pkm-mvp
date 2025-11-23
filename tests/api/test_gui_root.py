from fastapi.testclient import TestClient

from app.api.app import app


def test_gui_root_serves_dashboard_html():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Agentic PKM – Reality-MVP Dashboard" in resp.text
