"""Panel confirmation endpoint acceptance tests (no Postgres required).

All behavioral ACs from issue #1053, run against the module-level stores so
each test starts with a clean slate.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.panel.confirmation as confirm_module
from app.api.app import app
from app.events.panel import NoteRef, PanelInfo, PanelIntentEvent, PanelIntentPayload
from app.panel.confirmation import StagedProposal
from app.write_guard import WritesBlockedError


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intent(proposal_id: str = "prop-1", artifact_id: str = "note-uuid-1") -> PanelIntentEvent:
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=artifact_id, path="notes/test.md"),
            panel=PanelInfo(panel_id=proposal_id, instruction="do the thing"),
        )
    )


def _stage(
    proposal_id: str = "prop-1",
    artifact_id: str = "note-uuid-1",
    proposed_at: float | None = None,
) -> None:
    """Stage a proposal. proposed_at=0.0 (default) puts it safely outside same-turn window."""
    confirm_module._proposal_store.stage(
        proposal_id,
        StagedProposal(
            artifact_id=artifact_id,
            intent_event=_make_intent(proposal_id, artifact_id),
            proposed_at=0.0 if proposed_at is None else proposed_at,
        ),
    )


def _mock_execute(monkeypatch, events: list[str] | None = None) -> MagicMock:
    events = events or ["panel.intent.executed"]
    mock_result = MagicMock()
    mock_result.emitted_events = [{"event": e} for e in events]
    mock_fn = MagicMock(return_value=mock_result)
    monkeypatch.setattr(confirm_module, "execute_panel_intent", mock_fn)
    return mock_fn


def _valid_body(
    proposal_id: str = "prop-1",
    artifact_id: str = "note-uuid-1",
    action: str = "confirm",
    idempotency_key: str = "idem-key-1",
) -> dict:
    return {
        "proposal_id": proposal_id,
        "artifact_id": artifact_id,
        "action": action,
        "idempotency_key": idempotency_key,
    }


# ---------------------------------------------------------------------------
# AC tests
# ---------------------------------------------------------------------------


def test_panel_confirm_endpoint_returns_receipt_on_success(
    client: TestClient, monkeypatch
) -> None:
    _stage()
    _mock_execute(monkeypatch)
    resp = client.post("/api/panel/confirm", json=_valid_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "executed"
    assert data["receipt"] is not None
    assert data["receipt"]["outcome"] == "success"
    assert data["proposal_id"] == "prop-1"


def test_confirmed_panel_action_returns_receipt_visibility(
    client: TestClient, monkeypatch
) -> None:
    """Operational loop (confirm step): a confirmed action routed through the
    governed Panel confirmation API exposes an explicit, inspectable receipt
    posture. The response is a projection of receipt visibility, not the durable
    authority store — durable receipts live in the vault AI-status callout.
    """
    _stage()
    _mock_execute(monkeypatch)
    resp = client.post("/api/panel/confirm", json=_valid_body())
    assert resp.status_code == 200
    data = resp.json()
    # confirmation remains routed through the governed Panel confirmation API
    assert data["status"] == "executed"
    assert data["receipt"] is not None
    # receipt posture is explicit: the confirmed action produced a durable,
    # vault-visible receipt that the UI/API surfaces as visibility, not authority.
    assert data["receipt_visibility"] == "durable_vault_visible"


def test_panel_confirm_endpoint_idempotent(client: TestClient, monkeypatch) -> None:
    _stage()
    mock_fn = _mock_execute(monkeypatch)
    body = _valid_body()

    first = client.post("/api/panel/confirm", json=body)
    second = client.post("/api/panel/confirm", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert mock_fn.call_count == 1  # executed only once


def test_panel_confirm_endpoint_rejects_missing_proposal_id(client: TestClient) -> None:
    body = _valid_body()
    del body["proposal_id"]
    resp = client.post("/api/panel/confirm", json=body)
    assert resp.status_code == 422


def test_panel_confirm_endpoint_rejects_missing_artifact_id(client: TestClient) -> None:
    body = _valid_body()
    del body["artifact_id"]
    resp = client.post("/api/panel/confirm", json=body)
    assert resp.status_code == 422


def test_panel_confirm_endpoint_rejects_invalid_action(client: TestClient) -> None:
    body = _valid_body(action="execute")
    resp = client.post("/api/panel/confirm", json=body)
    assert resp.status_code == 422


def test_panel_confirm_endpoint_rejects_unknown_proposal_id(client: TestClient) -> None:
    # No proposal staged — proposal_id is unknown; contract requires 4xx
    resp = client.post("/api/panel/confirm", json=_valid_body(proposal_id="nonexistent"))
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "unknown_proposal"


def test_panel_confirm_endpoint_blocked_on_writeguard(client: TestClient) -> None:
    _stage()
    from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
    mock_guard = MagicMock(spec=WriteGuard)
    mock_guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked", "write guard active", "panel.confirm"
    )
    confirm_module._service._guard = mock_guard

    resp = client.post("/api/panel/confirm", json=_valid_body())
    confirm_module._service._guard = DEFAULT_WRITE_GUARD

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["block_reason"]["gate"] == "writeguard"


def test_panel_confirm_endpoint_reject_action_no_execution(
    client: TestClient, monkeypatch
) -> None:
    _stage()
    mock_fn = _mock_execute(monkeypatch)
    resp = client.post("/api/panel/confirm", json=_valid_body(action="reject"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["receipt"] is None
    assert mock_fn.call_count == 0  # no vault execution


def test_panel_confirm_endpoint_does_not_allow_same_turn_execution(
    client: TestClient, monkeypatch
) -> None:
    _stage(proposed_at=time.time())  # staged right now — same-turn window
    _mock_execute(monkeypatch)
    resp = client.post("/api/panel/confirm", json=_valid_body())
    assert resp.status_code == 422
    assert "same-turn" in resp.json()["detail"].lower()


def test_panel_confirm_endpoint_events_emitted_in_response(
    client: TestClient, monkeypatch
) -> None:
    _stage()
    _mock_execute(monkeypatch, events=["panel.intent.executed", "panel.action.triggered"])
    resp = client.post("/api/panel/confirm", json=_valid_body())
    assert resp.status_code == 200
    data = resp.json()
    assert "panel.intent.executed" in data["events_emitted"]
    assert "panel.action.triggered" in data["events_emitted"]


def test_companion_ui_does_not_write_vault_directly() -> None:
    """Architecture guard: no vault-write code in companion_ui/ modules."""
    import ast
    import pathlib

    vault_write_calls = {"write_text", "write_bytes", "open"}
    companion_ui_root = pathlib.Path(__file__).parents[2] / "companion-ui"
    if not companion_ui_root.exists():
        pytest.skip("companion-ui directory not present")

    violations: list[str] = []
    for py_file in companion_ui_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in vault_write_calls:
                violations.append(f"{py_file}:{node.col_offset} uses .{node.attr}")

    assert not violations, (
        "companion_ui modules must not write vault files directly:\n"
        + "\n".join(violations)
    )
