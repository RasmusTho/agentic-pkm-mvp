from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app


def test_source_understanding_p0_selected_passage_api_path() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/source-understanding/p0",
        json={
            "source_id": "paper-1",
            "source_ref": "Sources/paper.md#lines-12-18",
            "title": "Paper excerpt",
            "scope": "selected_passage",
            "selection_start_line": 12,
            "selection_end_line": 18,
            "text": "The source claims the intervention preserves review posture. Evidence is local.",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["scope"] == "selected_passage"
    assert data["status"] == "non-authoritative understanding projection"
    assert data["source"]["source_ref"] == "Sources/paper.md#lines-12-18"
    assert data["claims"]
    assert data["evidence"]
    assert data["durable_writes"] is False
    assert data["memory_writes"] is False
    assert data["mutation_intents"] == []
