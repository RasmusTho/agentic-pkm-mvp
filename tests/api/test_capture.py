from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app


def _setup_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)
    return vault


def test_capture_append_adds_separator_when_existing_file_has_no_trailing_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    inbox = vault / "Inbox" / "inbox.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("- [2026-06-10T08:00:00Z] Existing capture", encoding="utf-8")

    resp = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Follow-up capture"},
    )

    assert resp.status_code == 200, resp.text
    written = inbox.read_text(encoding="utf-8")
    assert "Existing capture\n- [" in written
    assert "] Follow-up capture\n" in written


def test_capture_append_preserves_empty_and_newline_terminated_inbox_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    client = TestClient(app)
    inbox = vault / "Inbox" / "inbox.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("", encoding="utf-8")

    empty_resp = client.post(
        "/api/companion/capture",
        json={"text": "First capture"},
    )

    assert empty_resp.status_code == 200, empty_resp.text
    first_written = inbox.read_text(encoding="utf-8")
    assert first_written.startswith("- [")
    assert "] First capture\n" in first_written

    newline_resp = client.post(
        "/api/companion/capture",
        json={"text": "Second capture"},
    )

    assert newline_resp.status_code == 200, newline_resp.text
    written = inbox.read_text(encoding="utf-8")
    assert "First capture\n- [" in written
    assert "] Second capture\n" in written
    assert "\n\n- [" not in written
