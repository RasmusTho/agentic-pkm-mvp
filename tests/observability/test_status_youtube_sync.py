from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.observability import status_service
from app.observability.status_model import YouTubeSyncStatus

pytestmark = pytest.mark.not_pg


def test_status_slice_wired_into_system_status(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = YouTubeSyncStatus(
        status="connected",
        ok=True,
        auth_status="connected",
        sources={"total": 1, "enabled": 1, "degraded": 0},
        queue={"depth": 2, "dead_letters": 0},
        quota={"spent_today": 2, "budget": 10000, "exhausted": False},
    )
    monkeypatch.setattr(status_service, "_get_youtube_sync_status", lambda: expected)

    response = TestClient(app).get("/api/status")

    assert response.status_code == 200
    payload = response.json()["youtube_sync"]
    assert payload["auth_status"] == "connected"
    assert payload["sources"]["enabled"] == 1
    assert payload["queue"]["depth"] == 2
    assert payload["quota"]["budget"] == 10000
