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


def test_status_slice_uses_accepted_gate_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.knowledge_acquisition.sync_observability as observed

    context = object()
    captured = {}
    monkeypatch.setattr(observed, "resolve_active_vault_context", lambda: context)

    def collect(**kwargs):
        captured["vault_context"] = kwargs.get("vault_context")
        return {
            "status": "connected",
            "ok": True,
            "reason_code": None,
            "reason_codes": [],
            "enabled": True,
            "runner_enabled": True,
            "runner_offline": False,
            "auth": {"status": "connected", "reason_code": None},
            "auth_status": "connected",
            "auth_reason_code": None,
            "token_store_key_present": True,
            "sources": {"total": 1, "enabled": 1, "degraded": 0, "next_due_at": None},
            "queue": {"depth": 0, "pending": 0, "in_progress": 0, "dead_letters": 0},
            "quota": {"spent_today": 0, "budget": 10000, "remaining": 10000, "exhausted": False, "available": True},
            "suggested_actions": [],
        }

    monkeypatch.setattr(observed, "collect_youtube_sync_status", collect)

    response = TestClient(app).get("/api/status")

    assert response.status_code == 200
    assert captured["vault_context"] is context
    youtube_sync = response.json()["youtube_sync"]
    assert youtube_sync["enabled"] is True
    assert youtube_sync["runner_enabled"] is True
    assert youtube_sync["status"] == "connected"
