from fastapi.testclient import TestClient
from app.api.app import app


def test_trace_header_roundtrip(monkeypatch):
    captured = {}

    def fake_insert(obj, topic, trace_id, **kwargs):
        captured["trace_id"] = trace_id
        captured["obj"] = obj
        captured["topic"] = topic
        captured["kwargs"] = kwargs

    monkeypatch.setattr("app.api.routes.ingest.insert_object_and_outbox", fake_insert)
    client = TestClient(app)
    response = client.post(
        "/ingest",
        json={"uuid": "trace-1", "title": "T", "review_state": "inbox", "content": "body"},
        headers={"x-trace-id": "abc123"},
    )
    assert response.status_code == 200
    assert response.headers.get("x-trace-id") == "abc123"
    assert captured["trace_id"] == "abc123"
    assert captured["kwargs"].get("object_id") == "trace-1"
