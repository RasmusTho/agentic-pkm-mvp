"""Tests for Panel confirm/reject browser wiring (#1138)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)
from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError


class _FakeClient:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        post_response: dict[str, Any] | Exception | None = None,
    ) -> None:
        self.payloads = payloads
        self.post_response = post_response or {
            "proposal_id": "proposal-1",
            "artifact_id": "art-1138",
            "status": "executed",
            "outcome": "success",
            "receipt": {
                "message": "Done",
                "outcome": "success",
                "timestamp": "2026-05-21T19:00:00Z",
            },
            "idempotency_key": "server-key",
        }
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response


def _workspace_payload(
    *,
    proposal_status: str = "staged",
    writeguard_status: str = "ok",
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1138",
            "note_path": "Notes/panel.md",
            "title": "Panel Note",
            "body": "# Panel Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": None,
            "session_state": None,
            "user_present": False,
            "can_edit_body": False,
            "recovery_needed": False,
            "session_log_path": None,
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal-1",
                    "artifact_id": "art-1138",
                    "description": "Do the thing",
                    "status": proposal_status,
                    "evidence": {
                        "trigger_summary": "Trigger summary",
                        "action_class": "bounded.panel_action",
                        "cognition_route": "rule",
                    },
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
        },
        "guards": {"canvas_enabled": True, "writeguard_status": writeguard_status},
        "runtime": {},
        "suggestions": {},
    }


def _workspace_payload_for_note(
    *,
    artifact_id: str,
    note_path: str,
) -> dict[str, Any]:
    payload = _workspace_payload()
    payload["artifact"] = {
        **payload["artifact"],
        "artifact_id": artifact_id,
        "note_path": note_path,
    }
    return payload


def _loaded_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/panel.md"))
    assert state.is_loaded is True
    return page


def _html(page: RealNoteWorkspaceDevPage) -> str:
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def test_confirm_calls_api() -> None:
    client = _FakeClient([_workspace_payload(), _workspace_payload()])
    page = _loaded_page(client)

    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    assert client.post_calls[0][0] == "/api/panel/confirm"
    payload = client.post_calls[0][1]
    assert payload["proposal_id"] == "proposal-1"
    assert payload["artifact_id"] == "art-1138"
    assert payload["action"] == "confirm"
    assert payload["idempotency_key"]


def test_reject_calls_api() -> None:
    client = _FakeClient([_workspace_payload(), _workspace_payload()])
    page = _loaded_page(client)

    page.reject_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    assert client.post_calls[0][1]["action"] == "reject"


def test_workspace_refreshed_after_confirm() -> None:
    client = _FakeClient([_workspace_payload(), _workspace_payload()])
    page = _loaded_page(client)

    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    workspace_get_calls = [
        call for call in client.get_calls if call[0] == "/api/companion/workspace"
    ]
    assert workspace_get_calls == [
        ("/api/companion/workspace", {"note_path": "Notes/panel.md"}),
        ("/api/companion/workspace", {"note_path": "Notes/panel.md"}),
    ]


def test_receipt_rendered_after_executed() -> None:
    client = _FakeClient([_workspace_payload(), _workspace_payload()])
    page = _loaded_page(client)
    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    html = _html(page)

    assert 'data-testid="workspace-panel-receipt"' in html
    assert 'data-receipt-persistence="durable-runtime-projection"' in html
    assert 'data-testid="workspace-panel-receipt-outcome"' in html
    assert 'data-testid="workspace-panel-receipt-message"' in html
    assert 'data-testid="workspace-panel-receipt-timestamp"' in html
    assert "success" in html
    assert "Done" in html
    assert "2026-05-21T19:00:00Z" in html


def test_blocked_reason_rendered() -> None:
    client = _FakeClient(
        [_workspace_payload(), _workspace_payload()],
        post_response={
            "proposal_id": "proposal-1",
            "artifact_id": "art-1138",
            "status": "blocked",
            "outcome": "blocked",
            "block_reason": {"gate": "writeguard", "message": "Writes blocked"},
            "idempotency_key": "server-key",
        },
    )
    page = _loaded_page(client)
    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    html = _html(page)

    assert 'data-testid="workspace-panel-blocked-reason"' in html
    assert 'data-testid="workspace-panel-block-gate"' in html
    assert "writeguard" in html
    assert "Writes blocked" in html


def test_same_turn_blocked_copy_rendered_without_page_error() -> None:
    client = _FakeClient(
        [_workspace_payload()],
        post_response=WorkspaceClientHTTPError(422, "same-turn confirmation denied"),
    )
    page = _loaded_page(client)
    state = page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    html = _html(page)

    assert state.is_loaded is True
    assert state.error is None
    assert 'data-testid="workspace-panel-blocked-reason"' in html
    assert "same-turn" in html
    assert (
        "Same-turn confirmation is not allowed. "
        "The proposal must be confirmed in a later interaction."
    ) in html


def test_panel_response_cleared_when_switching_notes() -> None:
    client = _FakeClient([
        _workspace_payload_for_note(artifact_id="art-1138-a", note_path="Notes/a.md"),
        _workspace_payload_for_note(artifact_id="art-1138-a", note_path="Notes/a.md"),
        _workspace_payload_for_note(artifact_id="art-1138-b", note_path="Notes/b.md"),
    ])
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="Notes/a.md"))
    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138-a",
        note_path="Notes/a.md",
    )

    state = page.load(NoteLoadIntent(note_path="Notes/b.md"))

    assert state.panel_last_response is None


def test_panel_actions_active_only_for_staged_proposal() -> None:
    html = _html(_loaded_page(_FakeClient([_workspace_payload()])))

    assert 'data-testid="workspace-panel-proposal-row"' in html
    assert 'data-proposal-id="proposal-1"' in html
    assert 'data-artifact-id="art-1138"' in html
    assert 'data-testid="workspace-panel-proposal-id"' in html
    assert 'data-testid="workspace-panel-artifact-id"' in html
    assert 'data-affordance-status="active"' in html
    assert 'data-panel-action="confirm"' in html
    assert 'data-panel-action="correct"' in html
    assert 'data-panel-action="reject"' in html
    assert 'data-runtime-backed="true"' in html


def test_panel_evidence_disclosure_contains_route_fields() -> None:
    html = _html(_loaded_page(_FakeClient([_workspace_payload()])))

    assert 'data-testid="workspace-panel-evidence"' in html
    assert 'data-testid="workspace-panel-evidence-disclosure"' in html
    assert 'data-testid="workspace-panel-trigger-summary"' in html
    assert 'data-testid="workspace-panel-action-class"' in html
    assert 'data-testid="workspace-panel-cognition-route"' in html
    assert "Trigger summary" in html
    assert "bounded.panel_action" in html
    assert "rule" in html


def test_inverse_action_is_display_only_when_declared() -> None:
    client = _FakeClient(
        [_workspace_payload(), _workspace_payload()],
        post_response={
            "proposal_id": "proposal-1",
            "artifact_id": "art-1138",
            "status": "executed",
            "outcome": "success",
            "receipt": {
                "message": "Done",
                "outcome": "success",
                "inverse_action": "undo-panel-action-1",
            },
            "idempotency_key": "server-key",
        },
    )
    page = _loaded_page(client)
    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-1138",
        note_path="Notes/panel.md",
    )

    html = _html(page)

    assert 'data-testid="workspace-panel-inverse-action"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-runtime-backed="false"' in html
    assert "undo-panel-action-1" in html
    assert 'data-panel-action="inverse"' not in html


def test_unknown_or_expired_panel_proposal_state_is_unavailable() -> None:
    html = _html(
        _loaded_page(_FakeClient([_workspace_payload(proposal_status="expired")]))
    )

    assert 'data-testid="workspace-panel-proposal-unavailable"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert "expired proposal unavailable" in html
    assert 'data-panel-action="confirm"' not in html


def test_corrected_panel_proposal_remains_confirmable_and_rejectable() -> None:
    html = _html(
        _loaded_page(_FakeClient([_workspace_payload(proposal_status="corrected")]))
    )

    assert 'data-testid="workspace-panel-proposal-row"' in html
    assert 'data-affordance-status="active"' in html
    assert 'data-panel-action="confirm"' in html
    assert 'data-panel-action="reject"' in html
    assert 'data-panel-action="correct"' not in html
    assert 'data-testid="workspace-panel-proposal-unavailable"' not in html


def test_writeguard_blocked_panel_actions_are_marked_blocked() -> None:
    html = _html(
        _loaded_page(_FakeClient([_workspace_payload(writeguard_status="blocked")]))
    )

    assert 'data-testid="workspace-guard-indicator"' in html
    assert "WriteGuard blocked" in html
    assert 'data-testid="workspace-panel-proposal-unavailable"' in html
    assert 'data-affordance-status="blocked"' in html
    assert 'data-panel-action="confirm"' not in html
