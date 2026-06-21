"""Governed capture append API contract tests (SEP-08a, issue #1790).

`POST /api/companion/capture` is the bounded capture action: friction-free
intake appended to the vault inbox note through the existing governed
machinery (policy -> validation -> deterministic writer -> event pipeline).

Normative invariants under test (SYSTEM_ENTRY_POINT_SPEC.md §Resolved Q17):

- the capture rides the governed pipeline and lands in the vault inbox per
  the inbox note convention; no parallel write path;
- no due dates and no app-managed task states anywhere in the contract;
- a capture is never silently dropped: validation and blocked states are
  explicit errors and write nothing;
- the acknowledgement is runtime-produced (the deterministic writer's
  receipt), never fabricated by the endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.capture as capture_module
from app.api.app import app
from app.write_guard import WritesBlockedError

_TASK_SEMANTIC_FIELDS = (
    "due_date",
    "due",
    "deadline",
    "task_state",
    "task_status",
    "status",
    "checked",
    "completed",
    "priority",
    "reminder",
    "remind_at",
    "recurrence",
)


def _setup_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)
    return vault, outbox


def _outbox_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_capture_appends_to_inbox_through_governed_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, outbox = _setup_vault(tmp_path, monkeypatch)

    # Spy on the policy gate so the test proves the governed path ran,
    # while keeping the real WriteGuard decision in force.
    guard_actions: list[str] = []
    real_gate = capture_module.DEFAULT_WRITE_GUARD.assert_writes_allowed

    def _spy(action: str) -> None:
        guard_actions.append(action)
        real_gate(action)

    monkeypatch.setattr(
        capture_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _spy
    )

    resp = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Call the bank\nabout the mortgage amortization"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Policy gate ran with the bounded capture action.
    assert guard_actions == ["companion.capture.append"]

    # The capture landed in the vault inbox per the note convention.
    inbox_note = vault / "Inbox" / "inbox.md"
    assert data["note_path"] == "Inbox/inbox.md"
    assert inbox_note.exists()
    written = inbox_note.read_text(encoding="utf-8")
    assert "] Call the bank\n  about the mortgage amortization" in written
    assert written.startswith("- [")

    # The acknowledgement is the deterministic writer's runtime receipt,
    # not a fabricated one.
    assert data["outcome"] == "written"
    assert data["operation"] == "append_note"
    assert data["adapter"] == "fs_vault"
    assert data["captured_at"]
    assert data["captured_at"] in written
    assert data["trace_id"]
    governed_write = data["governed_write"]
    assert governed_write["policy_decision"]["status"] == "approved"
    assert governed_write["policy_decision"]["source"] == "WriteGuard"
    assert governed_write["decision_token"]["resource"] == "Inbox/inbox.md"
    assert governed_write["decision_token"]["write_class"] == "vault_capture_append"
    assert governed_write["authority_receipt"]["outcome"] == "applied"
    assert governed_write["authority_receipt"]["operation"] == "append_note"
    assert governed_write["authority_receipt"]["adapter"] == "fs_vault"
    assert governed_write["authority_receipt"]["state_owner"] == "knowledge"

    # The governed event pipeline recorded the applied append.
    assert "capture.inbox.appended" in data["events_emitted"]
    events = _outbox_events(outbox)
    capture_events = [e for e in events if e.get("event") == "capture.inbox.appended"]
    assert len(capture_events) == 1
    payload = capture_events[0].get("payload") or {}
    assert payload.get("note_path") == "Inbox/inbox.md"
    assert payload.get("decision_token_id") == governed_write["decision_token"]["token_id"]
    assert (
        payload.get("authority_receipt_id")
        == governed_write["authority_receipt"]["receipt_id"]
    )
    assert payload.get("governed_write") == governed_write
    assert capture_events[0].get("trace_id") == data["trace_id"]

    # A second capture appends — it does not replace the inbox note.
    resp2 = TestClient(app).post(
        "/api/companion/capture", json={"text": "Renew the passport"}
    )
    assert resp2.status_code == 200, resp2.text
    written_after = inbox_note.read_text(encoding="utf-8")
    assert "Call the bank" in written_after
    assert "Renew the passport" in written_after


def test_capture_has_no_task_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, _ = _setup_vault(tmp_path, monkeypatch)
    client = TestClient(app)
    inbox_note = vault / "Inbox" / "inbox.md"

    # Due-date / task-state fields are rejected explicitly, never silently
    # discarded — and nothing is written when they are rejected.
    for field in _TASK_SEMANTIC_FIELDS:
        resp = client.post(
            "/api/companion/capture",
            json={"text": "capture text", field: "2026-07-01"},
        )
        assert resp.status_code == 422, f"{field}: {resp.text}"
        assert not inbox_note.exists(), field

    # The published request schema admits text only — no due-date or
    # task-state field exists anywhere in the contract.
    openapi = app.openapi()
    request_schema = openapi["components"]["schemas"]["CaptureRequest"]
    assert set(request_schema["properties"].keys()) == {"text"}
    assert request_schema.get("additionalProperties") is False

    response_schema = openapi["components"]["schemas"]["CaptureResponse"]
    response_fields = set(response_schema["properties"].keys())
    assert not response_fields.intersection(_TASK_SEMANTIC_FIELDS)

    # A successful capture is plain vault intake: a timestamped bullet,
    # not a checkbox/task item, and the response carries no task fields.
    resp = client.post("/api/companion/capture", json={"text": "plain capture"})
    assert resp.status_code == 200, resp.text
    assert not set(resp.json().keys()).intersection(_TASK_SEMANTIC_FIELDS)
    written = inbox_note.read_text(encoding="utf-8")
    assert "plain capture" in written
    assert "- [ ]" not in written
    assert "- [x]" not in written


def test_capture_validation_never_silently_drops_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, outbox = _setup_vault(tmp_path, monkeypatch)
    client = TestClient(app)
    inbox_note = vault / "Inbox" / "inbox.md"

    # Missing and empty text fail loudly via schema validation.
    assert client.post("/api/companion/capture", json={}).status_code == 422
    assert client.post("/api/companion/capture", json={"text": ""}).status_code == 422

    # Whitespace-only text is an explicit, named rejection.
    resp = client.post("/api/companion/capture", json={"text": "   \n\t  "})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "empty_capture"

    # No partial/silent writes and no events from rejected captures.
    assert not inbox_note.exists()
    assert _outbox_events(outbox) == []


def test_capture_writeguard_block_is_explicit_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, outbox = _setup_vault(tmp_path, monkeypatch)

    def _blocked(action: str) -> None:
        raise WritesBlockedError(state="safe_mode", reason="test lock", action=action)

    monkeypatch.setattr(
        capture_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked
    )

    resp = TestClient(app).post(
        "/api/companion/capture", json={"text": "must not be silently dropped"}
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "writeguard_blocked"
    assert detail["state"] == "blocked"
    assert detail["message"]

    assert not (vault / "Inbox" / "inbox.md").exists()
    assert _outbox_events(outbox) == []
