from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.settings_service import SettingsService
from tests.api._vault_test_helpers import bind_initialized_vault


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_workspace_offer_is_inert_until_explicit_reflection_action(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    manager = bind_initialized_vault(monkeypatch, vault)
    note = vault / "Notes" / "Evening.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: evening-note\ntype: note\n---\n\nEvening anchor.\n",
        encoding="utf-8",
    )
    SettingsService().update_setting(
        manager.context,
        "journalingEveningNudgeEnabled",
        True,
    )
    monkeypatch.setattr(
        companion_module,
        "_reflection_now",
        lambda: datetime(2026, 7, 15, 20, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    workspace = client.get(
        "/api/companion/workspace",
        params={"note_path": "Notes/Evening.md"},
    )

    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["reflection_offer"] == {
        "label": "Reflect on today?",
        "action": "journaling.reflection.begin",
        "tap_required": True,
    }
    assert not list((vault / ".chats").rglob("*.md"))

    started = client.post(
        "/api/companion/journaling/reflection/start",
        json={"note_path": "Notes/Evening.md", "for_date": "2026-07-15"},
    )

    assert started.status_code == 200, started.text
    payload = started.json()
    assert payload["state"] == "started"
    assert payload["note_path"] == "Notes/Evening.md"
    assert payload["opening_turn"]
    transcripts = list((vault / ".chats").rglob("*.md"))
    assert len(transcripts) == 1
    assert "**Agent:**" in transcripts[0].read_text(encoding="utf-8")
