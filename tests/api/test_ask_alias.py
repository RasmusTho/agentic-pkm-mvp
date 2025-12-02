from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app


client = TestClient(app)


def test_ask_accepts_question_field() -> None:
    resp = client.post("/api/ask", json={"question": "hello?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "sources" in data


def test_ask_accepts_query_alias() -> None:
    resp = client.post("/api/ask", json={"query": "hello?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "sources" in data
