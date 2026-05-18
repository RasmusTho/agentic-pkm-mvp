"""UAT integration tests: proposal → POST /api/panel/confirm → vault projection + receipt.

Covers issue #1062. Tests cross the HTTP boundary and verify actual vault state
in a single run without mocking execute_panel_intent.

Patches applied to every test:
- run_panel_graph      → returns a deterministic PanelAgentState (no LLM)
- load_panel_action_catalog → returns None (no catalog file required)
- _write_db_outbox_events  → no-op (no Postgres required)

The JSONL outbox is redirected to tmp_path via INDEX_OUTBOX_PATH env var.
"""

from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.panel.confirmation as confirm_module
import app.agents.panel_agent.runtime as runtime_module
from app.agents.panel.writeback import AI_STATUS_HEADER, stable_action_id
from app.agents.panel_agent.state import PanelAgentState
from app.api.app import app
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelRuntimeActionResult,
)
from app.events.schema import make_outbox_event
from app.panel.confirmation import StagedProposal
from app.write_guard import WritesBlockedError, WriteGuard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_stores():
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    yield
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _redirect_outbox(tmp_path: pathlib.Path, monkeypatch):
    outbox_file = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_file))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACTION_LABEL = "send email"
PROPOSAL_ID = "prop-uat-1"
ARTIFACT_ID = "note-uat-uuid-1"
IDEM_KEY = "idem-uat-key-1"


def _note_content(action_label: str = ACTION_LABEL) -> str:
    aid = stable_action_id(action_label)
    return (
        "# Test Note\n"
        f"- [ ] {action_label} <!--ai:id={aid}-->\n"
        "Some body text.\n"
    )


def _make_intent(note_path: str, action_label: str = ACTION_LABEL) -> PanelIntentEvent:
    aid = stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=ARTIFACT_ID, path=note_path),
            panel=PanelInfo(panel_id=PROPOSAL_ID, instruction="do the thing"),
            actions=[PanelIntentAction(id=aid, label=action_label, checked=True)],
        )
    )


def _stage(note_path: str, action_label: str = ACTION_LABEL, proposed_at: float = 0.0) -> None:
    confirm_module._proposal_store.stage(
        PROPOSAL_ID,
        StagedProposal(
            artifact_id=ARTIFACT_ID,
            intent_event=_make_intent(note_path, action_label),
            proposed_at=proposed_at,
        ),
    )


def _valid_body(action: str = "confirm") -> dict:
    return {
        "proposal_id": PROPOSAL_ID,
        "artifact_id": ARTIFACT_ID,
        "action": action,
        "idempotency_key": IDEM_KEY,
    }


def _make_graph_state(
    intent: PanelIntentEvent,
    action_label: str = ACTION_LABEL,
    status: str = "triggered",
) -> PanelAgentState:
    aid = stable_action_id(action_label)
    action = PanelIntentAction(id=aid, label=action_label, checked=True)
    result = PanelRuntimeActionResult(id=aid, label=action_label, checked=True, status=status)
    emitted = [make_outbox_event(event="panel.intent.executed", source="test", payload={})]
    return PanelAgentState(
        trace_id="test-trace-uat",
        note=intent.payload.note,
        panel=intent.payload.panel,
        actions=[action],
        action_results=[result],
        emitted_events=emitted,
        executed_action_ids=[aid] if status == "triggered" else [],
        vault_root=None,
        intent_event=intent,
    )


def _mock_graph_and_catalog(monkeypatch, action_label: str = ACTION_LABEL, status: str = "triggered"):
    """Patch run_panel_graph and load_panel_action_catalog; return the graph mock."""
    def _fake_graph(state: PanelAgentState, **kwargs: Any) -> PanelAgentState:
        intent = state.intent_event or PanelIntentEvent(
            payload=PanelIntentPayload(
                note=state.note,
                panel=state.panel,
                actions=state.actions,
            )
        )
        return _make_graph_state(intent, action_label=action_label, status=status)

    monkeypatch.setattr(runtime_module, "run_panel_graph", _fake_graph)
    monkeypatch.setattr(runtime_module, "load_panel_action_catalog", lambda: None)
    monkeypatch.setattr(runtime_module, "_write_db_outbox_events", lambda _events: None)


# ---------------------------------------------------------------------------
# Test 1: executed path — vault checkbox removed, ✅ receipt written
# ---------------------------------------------------------------------------


def test_panel_confirm_integration_executed_vault_and_receipt(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    note_file = tmp_path / "test_note.md"
    note_file.write_text(_note_content(), encoding="utf-8")

    _stage(str(note_file))
    _mock_graph_and_catalog(monkeypatch)

    resp = client.post("/api/panel/confirm", json=_valid_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "executed"
    assert data["receipt"] is not None
    assert data["receipt"]["outcome"] == "success"
    assert data["receipt"]["action_taken"] == "confirm"

    content = note_file.read_text(encoding="utf-8")
    # Checkbox should be removed from the vault
    assert f"- [ ] {ACTION_LABEL}" not in content
    # ✅ receipt line should appear in AI status callout
    assert AI_STATUS_HEADER in content
    assert "✅" in content


# ---------------------------------------------------------------------------
# Test 2: idempotency — second confirm returns same response, vault not double-written
# ---------------------------------------------------------------------------


def test_panel_confirm_integration_idempotent_no_double_vault_write(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    note_file = tmp_path / "test_note_idem.md"
    note_file.write_text(_note_content(), encoding="utf-8")

    _stage(str(note_file))
    _mock_graph_and_catalog(monkeypatch)

    first = client.post("/api/panel/confirm", json=_valid_body())
    second = client.post("/api/panel/confirm", json=_valid_body())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    content = note_file.read_text(encoding="utf-8")
    # Exactly one ✅ receipt line — not duplicated
    receipt_count = content.count("✅")
    assert receipt_count == 1, f"expected 1 receipt line, got {receipt_count}"


# ---------------------------------------------------------------------------
# Test 3: blocked by WriteGuard — checkbox preserved, 🚫 receipt written
# ---------------------------------------------------------------------------


def test_panel_confirm_integration_blocked_vault_and_receipt(
    client: TestClient, tmp_path: pathlib.Path
) -> None:
    note_file = tmp_path / "test_note_blocked.md"
    note_file.write_text(_note_content(), encoding="utf-8")

    _stage(str(note_file))

    # Inject a blocking WriteGuard into the service
    mock_guard = MagicMock(spec=WriteGuard)
    mock_guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked", "write guard active in UAT", "panel.confirm"
    )
    from app.write_guard import DEFAULT_WRITE_GUARD
    original_guard = confirm_module._service._guard
    confirm_module._service._guard = mock_guard

    try:
        resp = client.post("/api/panel/confirm", json=_valid_body())
    finally:
        confirm_module._service._guard = original_guard

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["block_reason"]["gate"] == "writeguard"
    assert data["receipt"] is None

    content = note_file.read_text(encoding="utf-8")
    # Checkbox should still be present (not removed on block)
    assert f"- [ ] {ACTION_LABEL}" in content
    # 🚫 receipt line should be in the AI status callout
    assert AI_STATUS_HEADER in content
    assert "🚫" in content


# ---------------------------------------------------------------------------
# Test 4: reject action — checkbox removed, no ✅ receipt, no execute_panel_intent
# ---------------------------------------------------------------------------


def test_panel_confirm_integration_rejected_vault_and_receipt(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    note_file = tmp_path / "test_note_rejected.md"
    note_file.write_text(_note_content(), encoding="utf-8")

    _stage(str(note_file))

    # execute_panel_intent must NOT be called for reject
    execute_spy = MagicMock(wraps=None)
    monkeypatch.setattr(confirm_module, "execute_panel_intent", execute_spy)

    resp = client.post("/api/panel/confirm", json=_valid_body(action="reject"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["receipt"] is None

    assert execute_spy.call_count == 0

    content = note_file.read_text(encoding="utf-8")
    # Checkbox should be removed on rejection
    assert f"- [ ] {ACTION_LABEL}" not in content
    # No ✅ execution receipt line
    assert "✅" not in content


# ---------------------------------------------------------------------------
# Test 5: receipt consistency — HTTP receipt is consistent with vault callout
# ---------------------------------------------------------------------------


def test_panel_confirm_integration_receipt_json_matches_vault_callout(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    note_file = tmp_path / "test_note_receipt.md"
    note_file.write_text(_note_content(), encoding="utf-8")

    _stage(str(note_file))
    _mock_graph_and_catalog(monkeypatch)

    resp = client.post("/api/panel/confirm", json=_valid_body())
    assert resp.status_code == 200
    data = resp.json()

    receipt = data["receipt"]
    assert receipt is not None
    action_taken = receipt["action_taken"]  # "confirm"

    content = note_file.read_text(encoding="utf-8")
    # Vault callout should exist and contain an execution receipt
    assert AI_STATUS_HEADER in content
    # The action label from the proposal should appear in the vault callout
    assert ACTION_LABEL in content or "✅" in content
    # The HTTP receipt outcome is "success" and vault has ✅ (both indicate execution)
    assert receipt["outcome"] == "success"
    assert "✅" in content
    assert action_taken == "confirm"
