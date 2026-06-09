"""Tests for reflecting the executed handoff receipt into the canvas context (#1728).

Implements CANVAS_CHAT_SURFACE/REFLECT_HANDOFF_RECEIPT (CHAT-PANEL-HANDOFF-03).

CHAT-PANEL-HANDOFF-02 (#1727) made the canvas-originated Panel proposal navigable
from the canvas region (handoff ``intent_id``/``action_type`` + "view in Panel"
affordance). This task closes the hybrid loop: once that proposal executes and a
durable receipt exists, the canvas region reflects the receipt posture back into
the originating context — read-only and server-declared.

Server declares, UI renders:
- The receipt projection is supplied by the server, keyed by ``intent_id``
  (mirroring the existing operational-loop receipt-visibility semantics on
  ``app/panel/confirmation.py`` / ``panel.receipts``).
- Correlation is strictly by the server-provided ``intent_id`` from
  CHAT-PANEL-HANDOFF-01; the UI invents no receipts and infers no success.
- If no durable receipt exists for the canvas intent, the region surfaces a
  pending/blocked posture as declared — it fabricates nothing.
- Reflection only applies to a canvas-originated proposal
  (``proposal_origin == "canvas_coauthoring"``); non-canvas origins are untouched.
"""

from __future__ import annotations

import json

from companion_ui.workspace.real_note_workspace_shell import (
    CanvasCoAuthorRegion,
)
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
)


INTENT_ID = "a1b2c3d4e5f6"
OTHER_INTENT_ID = "deadbeef0000"
ACTION_TYPE = "maturity_transition"


def _handoff_409(
    *,
    intent_id: str = INTENT_ID,
    action_type: str = ACTION_TYPE,
) -> WorkspaceClientHTTPError:
    """Build the structured governance-bearing 409 (CHAT-PANEL-HANDOFF-01)."""
    body = json.dumps(
        {
            "status": "routed_to_panel",
            "intent_id": intent_id,
            "action_type": action_type,
            "detail": "Governance-bearing — routed to the gated Panel pipeline.",
        }
    )
    return WorkspaceClientHTTPError(409, body)


def _routed_region(
    *,
    intent_id: str = INTENT_ID,
    action_type: str = ACTION_TYPE,
) -> CanvasCoAuthorRegion:
    """A canvas region that has already been routed to Panel via a 409."""
    region = CanvasCoAuthorRegion(enabled=True)
    region.handle_coauthor_error(
        _handoff_409(intent_id=intent_id, action_type=action_type)
    )
    return region


def _receipt_projection(
    *,
    intent_id: str = INTENT_ID,
    outcome: str = "executed",
    receipt_id: str = "rcpt-001",
    visibility: str = "durable_vault_visible",
) -> dict[str, dict[str, str]]:
    """Server-declared receipt-visibility projection keyed by intent_id.

    Mirrors the ``panel.receipts`` / ``receipt_visibility`` projection the
    operational loop already consumes (``app/panel/confirmation.py``).
    """
    return {
        intent_id: {
            "outcome": outcome,
            "receipt_id": receipt_id,
            "receipt_visibility": visibility,
        }
    }


# ---------------------------------------------------------------------------
# AC 1: durable receipt for a canvas-originated proposal is reflected by intent_id
# ---------------------------------------------------------------------------


def test_receipt_reflected_for_canvas_origin() -> None:
    region = _routed_region()

    region.reflect_receipt(
        receipt_projection=_receipt_projection(),
        proposal_origin="canvas_coauthoring",
    )

    posture = region.reflected_receipt
    assert posture is not None
    assert region.has_reflected_receipt is True
    # The reflected posture carries the server-declared outcome + receipt identity,
    # correlated by the handoff intent_id.
    assert posture["intent_id"] == INTENT_ID
    assert posture["outcome"] == "executed"
    assert posture["receipt_id"] == "rcpt-001"
    assert posture["receipt_visibility"] == "durable_vault_visible"
    # Posture is settled (a durable receipt exists), not pending.
    assert posture["state"] == "receipt_visible"


# ---------------------------------------------------------------------------
# AC 2: no durable receipt -> pending/blocked posture, nothing invented
# ---------------------------------------------------------------------------


def test_no_receipt_shows_pending_not_invented() -> None:
    region = _routed_region()

    # Empty projection: server connected but no durable receipt for this intent.
    region.reflect_receipt(
        receipt_projection={},
        proposal_origin="canvas_coauthoring",
    )

    posture = region.reflected_receipt
    assert posture is not None
    # Pending posture: correlated by intent_id but no durable receipt yet.
    assert posture["state"] == "pending"
    assert posture["intent_id"] == INTENT_ID
    # Nothing fabricated.
    assert posture["outcome"] is None
    assert posture["receipt_id"] is None
    assert posture["receipt_visibility"] is None
    # The region must not claim a durable receipt is visible.
    assert region.has_reflected_receipt is False


def test_no_handoff_intent_means_no_reflection() -> None:
    """Without a server-provided intent_id there is nothing to correlate against."""
    region = CanvasCoAuthorRegion(enabled=True)

    region.reflect_receipt(
        receipt_projection=_receipt_projection(),
        proposal_origin="canvas_coauthoring",
    )

    assert region.reflected_receipt is None
    assert region.has_reflected_receipt is False


# ---------------------------------------------------------------------------
# AC 3: reflected receipt is read-only and server-declared
# ---------------------------------------------------------------------------


def test_reflected_receipt_is_read_only_server_declared() -> None:
    region = _routed_region()

    region.reflect_receipt(
        receipt_projection=_receipt_projection(),
        proposal_origin="canvas_coauthoring",
    )

    posture = region.reflected_receipt
    assert posture is not None
    # Read-only, server-declared: no mutation affordance is added by reflection.
    assert posture["affordance_status"] == "read-only"
    assert posture["authority_role"] == "server_declared"

    # The UI must not infer success. A non-canvas origin yields no reflection
    # even when a matching receipt exists in the projection.
    non_canvas = _routed_region()
    non_canvas.reflect_receipt(
        receipt_projection=_receipt_projection(),
        proposal_origin=None,
    )
    assert non_canvas.reflected_receipt is None

    # Reflection adds no mutation affordances to the region.
    assert region.mutation_affordances == ["canvas-intent-input", "canvas-undo"]


# ---------------------------------------------------------------------------
# AC 4: correlation is strictly by the server-provided intent_id
# ---------------------------------------------------------------------------


def test_receipt_correlation_by_intent_id() -> None:
    region = _routed_region(intent_id=INTENT_ID)

    # Projection holds a receipt for a DIFFERENT intent_id only.
    region.reflect_receipt(
        receipt_projection=_receipt_projection(intent_id=OTHER_INTENT_ID),
        proposal_origin="canvas_coauthoring",
    )

    posture = region.reflected_receipt
    # No receipt matches this region's intent_id -> pending, not the other receipt.
    assert posture is not None
    assert posture["state"] == "pending"
    assert posture["intent_id"] == INTENT_ID
    assert posture["receipt_id"] is None
    assert region.has_reflected_receipt is False

    # Now provide a projection that DOES match -> the matching receipt reflects.
    region.reflect_receipt(
        receipt_projection=_receipt_projection(
            intent_id=INTENT_ID, receipt_id="rcpt-match"
        ),
        proposal_origin="canvas_coauthoring",
    )
    matched = region.reflected_receipt
    assert matched is not None
    assert matched["state"] == "receipt_visible"
    assert matched["receipt_id"] == "rcpt-match"


def test_blocked_receipt_posture_reflected_not_inferred() -> None:
    """A server-declared blocked posture is reflected verbatim, not inferred as success."""
    region = _routed_region()

    region.reflect_receipt(
        receipt_projection=_receipt_projection(
            outcome="blocked",
            visibility="blocked_no_durable_receipt",
            receipt_id="",
        ),
        proposal_origin="canvas_coauthoring",
    )

    posture = region.reflected_receipt
    assert posture is not None
    # Outcome present and visibility blocked -> not a durable receipt visible.
    assert posture["outcome"] == "blocked"
    assert posture["receipt_visibility"] == "blocked_no_durable_receipt"
    assert posture["state"] == "blocked"
    assert region.has_reflected_receipt is False


# ---------------------------------------------------------------------------
# Optional: served HTML reflects the receipt posture in the panel rail row
# ---------------------------------------------------------------------------


def test_panel_rail_html_renders_reflected_receipt() -> None:
    """The served Panel rail HTML surfaces the reflected receipt posture."""
    from companion_ui.workspace.serve_dev_page import _render_panel_proposal_rows

    html = _render_panel_proposal_rows(
        [
            {
                "proposal_id": INTENT_ID,
                "artifact_id": "note-uuid-1",
                "description": "promote to evergreen",
                "status": "executed",
                "proposal_origin": "canvas_coauthoring",
                "reflected_receipt": {
                    "intent_id": INTENT_ID,
                    "outcome": "executed",
                    "receipt_id": "rcpt-001",
                    "receipt_visibility": "durable_vault_visible",
                    "state": "receipt_visible",
                    "affordance_status": "read-only",
                    "authority_role": "server_declared",
                },
                "affordances": {"confirm": True},
                "evidence": {"trigger_summary": "t"},
            }
        ],
        writeguard_blocked=False,
    )
    assert 'data-testid="workspace-panel-reflected-receipt"' in html
    assert 'data-receipt-state="receipt_visible"' in html
    assert 'data-receipt-visibility="durable_vault_visible"' in html
    assert "rcpt-001" in html


def test_proposal_rows_adapter_passes_through_reflected_receipt() -> None:
    """The live adapter preserves a server-declared reflected_receipt verbatim.

    Without this pass-through the served HTML branch would be dead in the real
    workspace flow (server payload -> _proposal_rows_from_panel ->
    ProposalRow.as_render_dict -> _render_panel_proposal_rows).
    """
    from companion_ui.workspace.real_note_workspace_dev_page import (
        _proposal_rows_from_panel,
    )

    reflected = {
        "intent_id": INTENT_ID,
        "outcome": "executed",
        "receipt_id": "rcpt-001",
        "receipt_visibility": "durable_vault_visible",
        "state": "receipt_visible",
        "affordance_status": "read-only",
        "authority_role": "server_declared",
    }
    panel = {
        "proposals": [
            {
                "proposal_id": INTENT_ID,
                "artifact_id": "note-uuid-1",
                "description": "promote to evergreen",
                "status": "staged",
                "proposal_origin": "canvas_coauthoring",
                "reflected_receipt": reflected,
                "evidence": {
                    "trigger_summary": "t",
                    "action_class": "maturity_transition",
                    "cognition_route": "rule",
                },
            }
        ]
    }
    rows = _proposal_rows_from_panel(panel=panel, artifact_id="note-uuid-1")

    assert len(rows) == 1
    assert rows[0]["reflected_receipt"] == reflected


def test_proposal_rows_adapter_omits_reflected_receipt_when_undeclared() -> None:
    """No server-declared reflected_receipt -> None (the UI invents nothing)."""
    from companion_ui.workspace.real_note_workspace_dev_page import (
        _proposal_rows_from_panel,
    )

    panel = {
        "proposals": [
            {
                "proposal_id": "prop-x",
                "artifact_id": "note-uuid-1",
                "description": "ordinary proposal",
                "status": "staged",
                "evidence": {
                    "trigger_summary": "t",
                    "action_class": "lifecycle.move",
                    "cognition_route": "rule",
                },
            }
        ]
    }
    rows = _proposal_rows_from_panel(panel=panel, artifact_id="note-uuid-1")

    assert rows[0]["reflected_receipt"] is None


def test_panel_rail_html_omits_reflected_receipt_when_absent() -> None:
    """No server-declared receipt projection -> no reflected-receipt block."""
    from companion_ui.workspace.serve_dev_page import _render_panel_proposal_rows

    html = _render_panel_proposal_rows(
        [
            {
                "proposal_id": "prop-x",
                "artifact_id": "note-uuid-1",
                "description": "ordinary proposal",
                "status": "staged",
                "affordances": {"confirm": True},
                "evidence": {"trigger_summary": "t"},
            }
        ],
        writeguard_blocked=False,
    )
    assert "workspace-panel-reflected-receipt" not in html
