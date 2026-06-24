"""CUIDR-07 (#2451): governed receipt first-class in-place confirmation.

Static tests for AC2–AC5. AC1 (live UAT round-trip) requires the running
shell and is listed for the owner's UAT pass on parent #2443.

Tests assert:
- AC2: after a governed Apply the confirmed card is present and the
  Apply/Discard/Defer affordances are absent.
- AC3: the confirmed card state is rendered only for status=="executed" + non-null
  receipt; pending/staged/blocked/rejected must NOT render it.
- AC4: no optimistic confirmation — before the runtime response the card still
  shows proposal affordances, not the confirmed state.
- AC5: the confirmed card remains visible when the receipts overlay is
  unreachable; the overlay content shows the calm degraded copy.

Server-authoritative boundary: every AC that renders a classified value asserts
it is read verbatim from the runtime payload — never synthesised by the client.
"""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.receipts_history import (
    receipts_history_unavailable_fragment,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_RECEIPT_ID = "rcpt-2451-test"
_RECEIPT_OUTCOME = "success"
_RECEIPT_TIMESTAMP = "2026-06-23T10:00:00Z"


def _executed_post_response(
    *,
    receipt_id: str = _RECEIPT_ID,
    outcome: str = _RECEIPT_OUTCOME,
    timestamp: str = _RECEIPT_TIMESTAMP,
) -> dict[str, Any]:
    """Runtime POST /api/panel/confirm response for a governed executed apply."""
    return {
        "proposal_id": "proposal-1",
        "artifact_id": "art-2451",
        "status": "executed",
        "outcome": outcome,
        "receipt": {
            "receipt_id": receipt_id,
            "outcome": outcome,
            "message": "Done",
            "timestamp": timestamp,
        },
        "idempotency_key": "server-key",
    }


def _workspace_payload(*, proposal_status: str = "staged") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-2451",
            "note_path": "Notes/governed.md",
            "title": "Governed Note",
            "body": "# Governed Note\n\nBody.",
            "content_hash": "hash-2451",
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
                    "artifact_id": "art-2451",
                    "description": "Governed action",
                    "status": proposal_status,
                    "evidence": {
                        "trigger_summary": "Trigger",
                        "action_class": "bounded.panel_action",
                        "cognition_route": "rule",
                    },
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
        },
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


class _FakeClient:
    """Minimal HTTP stub for static rendering tests."""

    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        post_response: dict[str, Any] | Exception | None = None,
    ) -> None:
        self.payloads = list(payloads)
        self.post_response = post_response if post_response is not None else _executed_post_response()

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if url == "/api/companion/vault-browser":
            return {}
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        return self.payloads.pop(0) if self.payloads else {}

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response  # type: ignore[return-value]


def _loaded_page(client: _FakeClient) -> RealNoteWorkspaceDevPage:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/governed.md"))
    assert state.is_loaded is True
    return page


def _workspace_payload_post_apply() -> dict[str, Any]:
    """Workspace aggregate returned by the runtime after a governed Apply.

    After execution, the panel is cleared — proposals list is empty and state
    is "idle". The confirmed card renders from ``panel_last_response`` only.
    """
    payload = _workspace_payload()
    payload["panel"] = {
        "state": "idle",
        "proposal_count": 0,
        "proposals": [],
    }
    return payload


def _html_after_confirm(
    *,
    post_response: dict[str, Any] | Exception | None = None,
) -> str:
    """Return rendered HTML after a confirm POST with the given response.

    Uses a post-apply workspace payload (no proposals) to reflect the real
    runtime state after a governed apply clears the panel.
    """
    client = _FakeClient(
        [_workspace_payload(), _workspace_payload_post_apply()],
        post_response=post_response,
    )
    page = _loaded_page(client)
    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-2451",
        note_path="Notes/governed.md",
    )
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/governed.md",
        fields=fields,
    )


# ---------------------------------------------------------------------------
# AC2 — In-place confirmed state
# ---------------------------------------------------------------------------


def test_applied_card_in_place_state() -> None:
    """AC2 (static): after a governed Apply, the confirmed card is present and
    the proposal affordances are gone.

    The card must carry:
      data-testid="workspace-panel-receipt-card"
      data-receipt-state="applied"
      data-receipt-persistence="durable-runtime-projection"
      data-testid="workspace-panel-receipt-link-to-history"
      data-receipt-id="<id>"
      data-intent="receipts.open"
    The heading "Applied · receipt recorded" must be present.
    Apply/Discard/Defer affordances (data-panel-action="confirm|reject|correct")
    must NOT be present.
    """
    html = _html_after_confirm()

    # Confirmed card presence
    assert 'data-testid="workspace-panel-receipt-card"' in html
    assert 'data-receipt-state="applied"' in html
    assert 'data-receipt-persistence="durable-runtime-projection"' in html
    assert "Applied · receipt recorded" in html

    # Link-to-history control
    assert 'data-testid="workspace-panel-receipt-link-to-history"' in html
    assert f'data-receipt-id="{_RECEIPT_ID}"' in html
    assert 'data-intent="receipts.open"' in html
    assert "overlayHost.mount(&#x27;receipts&#x27;, {receiptId:" in html
    assert _RECEIPT_ID in html

    # Apply/Discard/Defer are absent on the confirmed card (read-only state)
    assert 'data-panel-action="confirm"' not in html
    assert 'data-panel-action="reject"' not in html
    assert 'data-panel-action="correct"' not in html


def test_receipt_secondary_line_from_runtime_payload() -> None:
    """AC2 (static): outcome and timestamp on the secondary line come verbatim
    from the runtime confirmation payload — never synthesised client-side."""
    outcome = "success"
    timestamp = "2026-06-23T10:00:00Z"
    html = _html_after_confirm(
        post_response=_executed_post_response(outcome=outcome, timestamp=timestamp)
    )
    # Both values must appear in the HTML (verbatim from runtime payload)
    assert outcome in html
    assert timestamp in html
    # The developer disclosure also carries the raw receipt fields
    assert 'data-testid="workspace-panel-receipt"' in html


# ---------------------------------------------------------------------------
# AC3 — Runtime-only confirmation
# ---------------------------------------------------------------------------


def _html_after_confirm_with_payloads(
    payloads: list[dict[str, Any]],
    *,
    post_response: dict[str, Any],
) -> str:
    """Render HTML after confirm using specific workspace payloads."""
    client = _FakeClient(payloads, post_response=post_response)
    page = _loaded_page(client)
    page.confirm_panel_proposal(
        proposal_id="proposal-1",
        artifact_id="art-2451",
        note_path="Notes/governed.md",
    )
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/governed.md",
        fields=fields,
    )


def test_confirmed_state_requires_runtime_receipt() -> None:
    """AC3 (static): the confirmed card must NOT appear for status=blocked,
    status=staged (pending proposal), or status=executed with a null receipt.
    Server-authoritative boundary: the UI never renders the confirmed state
    without a runtime-confirmed receipt.
    """
    # Blocked status — no confirmed card (blocked response, panel may still have proposals)
    html_blocked = _html_after_confirm_with_payloads(
        [_workspace_payload(), _workspace_payload()],
        post_response={
            "proposal_id": "proposal-1",
            "artifact_id": "art-2451",
            "status": "blocked",
            "outcome": "blocked",
            "block_reason": {"gate": "writeguard", "message": "Writes blocked"},
            "idempotency_key": "server-key",
        },
    )
    assert 'data-receipt-state="applied"' not in html_blocked
    assert 'data-testid="workspace-panel-receipt-card"' not in html_blocked

    # Executed with null receipt — no confirmed card
    html_no_receipt = _html_after_confirm_with_payloads(
        [_workspace_payload(), _workspace_payload_post_apply()],
        post_response={
            "proposal_id": "proposal-1",
            "artifact_id": "art-2451",
            "status": "executed",
            "outcome": "success",
            "receipt": None,
            "idempotency_key": "server-key",
        },
    )
    assert 'data-receipt-state="applied"' not in html_no_receipt
    assert 'data-testid="workspace-panel-receipt-card"' not in html_no_receipt

    # Staged (pre-confirm, no response yet) — no confirmed card
    client = _FakeClient([_workspace_payload()])
    page = _loaded_page(client)
    fields = page.render_fields()
    assert fields is not None
    html_staged = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/governed.md",
        fields=fields,
    )
    assert 'data-receipt-state="applied"' not in html_staged
    assert 'data-testid="workspace-panel-receipt-card"' not in html_staged


# ---------------------------------------------------------------------------
# AC4 — No optimistic confirmation
# ---------------------------------------------------------------------------


def test_no_optimistic_confirmation() -> None:
    """AC4 (static): before the runtime POST response arrives, the card must
    show the proposal affordances (Apply/Discard/Defer) and NOT show
    data-receipt-state="applied". State is set only from the confirmed
    response — never optimistically from client-side state.
    """
    # Render before confirm() is called — proposal should be active
    client = _FakeClient([_workspace_payload()])
    page = _loaded_page(client)
    fields = page.render_fields()
    assert fields is not None
    html_pre = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/governed.md",
        fields=fields,
    )

    # Proposal affordances must be present before confirm
    assert 'data-panel-action="confirm"' in html_pre
    assert 'data-affordance-status="active"' in html_pre

    # Confirmed card must NOT be present before confirm
    assert 'data-receipt-state="applied"' not in html_pre
    assert 'data-testid="workspace-panel-receipt-card"' not in html_pre


# ---------------------------------------------------------------------------
# AC5 — Degraded path
# ---------------------------------------------------------------------------


def test_confirmed_card_degraded_history() -> None:
    """AC5 (static): when the receipts overlay is unreachable, the confirmed
    card remains visible. The degraded copy rendered by
    ``receipts_history_unavailable_fragment`` must contain the calm grammar
    ("receipt recorded — history unavailable" or "Nothing was lost").

    The confirmed card is a stable DOM element; the overlay host's JS
    controller handles the fetch failure independently, showing the calm
    unavailable copy inside the overlay body — it never removes or replaces
    the confirmed card in the rail.

    This test asserts:
    1. The confirmed card is present in the post-confirm HTML (static gate).
    2. The degraded fragment copy is the calm unavailable grammar.
    """
    html = _html_after_confirm()

    # Confirmed card is stable
    assert 'data-testid="workspace-panel-receipt-card"' in html
    assert 'data-receipt-state="applied"' in html

    # Degraded overlay fragment — calm grammar (consumed by CUIDR-01)
    degraded_fragment = receipts_history_unavailable_fragment()
    assert 'data-testid="receipts-history-unavailable"' in degraded_fragment
    assert "data-tone=\"calm\"" in degraded_fragment
    assert "nothing was lost" in degraded_fragment

    # Confirm the degraded fragment does not overwrite or remove the card
    # (the card is rendered server-side; the overlay fragment is fetched
    # client-side and injected into the overlay body, a separate DOM subtree)
    assert 'data-testid="workspace-panel-receipt-card"' not in degraded_fragment
