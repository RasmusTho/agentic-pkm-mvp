"""A3 (CUIDR-08): a Blocked proposal shows a plain-language reason + recourse.

Spec: docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/BLOCKED_RECOURSE_AND_LANE_LABELING.md
:: Acceptance Criteria — A3 (static).

A WriteGuard-held proposal presents in the calm (non-red) treatment and states
both *why* the hold fired and *what would unblock it*, humanised from the
server-declared block payload via the CUIDR-01 grammar. No proposal collapses to
a mute "unavailable"/"held" dead end with no explanation. Presentation only — the
block classification is server-authoritative and arrives in the payload.
"""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.calm_degraded import (
    BLOCKED_REASON_FALLBACK,
    BLOCKED_RECOURSE_FALLBACK,
)
from companion_ui.workspace.panel_palette import _blocked_html
from companion_ui.workspace.real_note_workspace_dev_page import (
    _proposal_rows_from_panel,
)
from companion_ui.workspace.serve_dev_page import (
    _render_panel_confirm_response,
    render_index_html,
)


def _fields(*, writeguard_blocked: bool, block_reason: dict | None) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "proposal_id": "prop-1829",
        "artifact_id": "art-1829",
        "description": "Move note to Projects",
        "evidence": {
            "trigger_summary": "Trigger",
            "action_class": "lifecycle.move",
            "cognition_route": "rule",
        },
        "status": "blocked" if writeguard_blocked else "staged",
        "lane": "governed",
        "governed": True,
        "proposal_origin": None,
        "reflected_receipt": None,
        "affordances": {"confirm": True, "correct": True, "reject": True},
    }
    if block_reason is not None:
        proposal["block_reason"] = block_reason
    return {
        "title": "Note Title",
        "note_path": "Notes/panel.md",
        "artifact_id": "art-1829",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "proposals-staged",
        "panel_proposal_count": 1,
        "panel_proposals": [proposal],
        "panel_message": "",
        "guard_writeguard_status": "blocked" if writeguard_blocked else "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }


def _render(*, writeguard_blocked: bool, block_reason: dict | None) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=_fields(
            writeguard_blocked=writeguard_blocked, block_reason=block_reason
        ),
    )


def _text_for_testid(html: str, testid: str) -> str:
    pattern = (
        r'data-testid="' + re.escape(testid) + r'"[^>]*>(.*?)</span>'
    )
    matches = re.findall(pattern, html, re.S)
    return " ".join(m.strip() for m in matches)


def test_blocked_proposal_shows_reason_and_recourse() -> None:
    """A WriteGuard-held proposal carries both reason and recourse, humanised."""
    block_reason = {
        "gate": "writeguard",
        "recourse": "Writes resume automatically once safe mode clears. "
        "No action is needed now.",
    }
    html = _render(writeguard_blocked=True, block_reason=block_reason)

    reason = _text_for_testid(html, "palette-blocked-reason")
    recourse = _text_for_testid(html, "palette-blocked-recourse")

    assert reason, "blocked reason must be present and non-empty"
    assert recourse, "blocked recourse must be present and non-empty"
    # Humanised plain language — no raw enum / rule identifier leaks.
    assert "safe mode" in reason.lower()
    assert "writes resume automatically" in recourse.lower()
    assert "writeguard" not in reason.lower()


def test_blocked_proposal_reason_falls_back_when_payload_absent() -> None:
    """A block with no detail still states a calm reason + recourse, not a dead end."""
    html = _render(writeguard_blocked=True, block_reason=None)

    reason = _text_for_testid(html, "palette-blocked-reason")
    recourse = _text_for_testid(html, "palette-blocked-recourse")

    assert BLOCKED_REASON_FALLBACK in reason
    assert recourse, "fallback recourse must still be present"
    assert BLOCKED_RECOURSE_FALLBACK in recourse


def test_normaliser_passes_through_server_declared_block_and_lane() -> None:
    """The panel→rows normaliser preserves server-declared lane/governed/block.

    Without this pass-through, live rail/palette cards would always fall back to
    the default governed label and the calm block fallback even when the runtime
    declared a specific lane or recourse (the live-path gap Codex flagged).
    """
    panel = {
        "proposals": [
            {
                "proposal_id": "prop-x",
                "artifact_id": "note-uuid-1",
                "description": "Move note to Projects",
                "status": "blocked",
                "lane": "body_edit",
                "governed": False,
                "block_reason": {
                    "gate": "stale-source",
                    "recourse": "Reopen the note to refresh the proposal.",
                },
                "evidence": {
                    "trigger_summary": "Trigger",
                    "action_class": "lifecycle.move",
                    "cognition_route": "rule",
                },
            }
        ]
    }
    rows = _proposal_rows_from_panel(panel=panel, artifact_id="note-uuid-1")
    assert len(rows) == 1
    row = rows[0]
    assert row["lane"] == "body_edit"
    assert row["governed"] is False
    assert row["block_reason"]["gate"] == "stale-source"
    assert (
        row["block_reason"]["recourse"]
        == "Reopen the note to refresh the proposal."
    )


def test_normaliser_omits_undeclared_lane_and_block() -> None:
    """Absent server fields are not invented — they stay off the row."""
    panel = {
        "proposals": [
            {
                "proposal_id": "prop-y",
                "artifact_id": "note-uuid-1",
                "description": "Move note to Projects",
                "status": "staged",
                "evidence": {
                    "trigger_summary": "Trigger",
                    "action_class": "lifecycle.move",
                    "cognition_route": "rule",
                },
            }
        ]
    }
    rows = _proposal_rows_from_panel(panel=panel, artifact_id="note-uuid-1")
    assert "lane" not in rows[0]
    assert "governed" not in rows[0]
    assert "block_reason" not in rows[0]


def test_proposal_level_blocked_without_global_writeguard_renders_recourse() -> None:
    """A proposal-level ``status:"blocked"`` while the GLOBAL WriteGuard is OK
    still shows the reason + recourse — not the mute "unavailable" dead end.

    Covers the stale-source / identity-mismatch / same-turn case where the
    runtime blocks one proposal but the global WriteGuard banner is fine.
    """
    fields = _fields(writeguard_blocked=False, block_reason=None)
    # Global WriteGuard stays OK; only this proposal is server-declared blocked.
    fields["guard_writeguard_status"] = "ok"
    fields["panel_proposals"][0]["status"] = "blocked"
    fields["panel_proposals"][0]["block_reason"] = {
        "gate": "stale-source",
        "recourse": "Reopen the note to refresh the proposal.",
    }
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )

    reason = _text_for_testid(html, "palette-blocked-reason")
    recourse = _text_for_testid(html, "palette-blocked-recourse")

    assert reason, "proposal-level blocked must still carry a reason"
    assert recourse, "proposal-level blocked must still carry recourse"
    assert "reopen the note" in recourse.lower()
    # The calm reason/recourse card is present on the panel proposal row...
    assert 'data-testid="workspace-panel-proposal-blocked"' in html
    # ...and that row no longer emits the mute "unavailable" dead-end span.
    assert 'data-testid="workspace-panel-proposal-unavailable"' not in html


def test_block_reason_hold_with_staged_status_has_no_active_buttons() -> None:
    """A server-declared ``block_reason`` is a hold even when the status still
    reads ``staged`` — the rail must not render active Apply/Discard/Defer.

    Parity with the palette row model (which folds the same condition into
    guard_held before computing availability). Otherwise the two surfaces
    diverge: active buttons next to a blocked reason/recourse card.
    """
    fields = _fields(writeguard_blocked=False, block_reason=None)
    fields["guard_writeguard_status"] = "ok"
    # Status stays staged; only block_reason marks the hold.
    fields["panel_proposals"][0]["status"] = "staged"
    fields["panel_proposals"][0]["block_reason"] = {
        "gate": "identity-mismatch",
    }
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )

    # The panel proposal row is held: it carries the blocked affordance status
    # and the calm reason/recourse card, and exposes no active panel action
    # buttons (the rail's confirm buttons use data-testid="workspace-panel-action";
    # the separate act-mode flow uses act-* test-ids and is out of scope).
    assert 'data-testid="workspace-panel-proposal-blocked"' in html
    assert 'data-testid="workspace-panel-action"' not in html
    assert _text_for_testid(html, "palette-blocked-reason")
    assert _text_for_testid(html, "palette-blocked-recourse")
    # The row's own affordance status is blocked, not active.
    row_match = re.search(
        r'data-testid="workspace-panel-proposal-row"[^>]*'
        r'data-affordance-status="([^"]+)"',
        html,
    )
    assert row_match is not None
    assert row_match.group(1) == "blocked"


def test_palette_row_proposal_level_blocked_is_held_with_recourse() -> None:
    """The palette row model treats a proposal-level ``status:"blocked"`` as
    guard-held (even when the GLOBAL WriteGuard is OK), so its held row carries
    the reason + recourse rather than collapsing to "unavailable"."""
    from companion_ui.workspace.panel_palette import (
        _row_actions_html,
        palette_row_model,
    )

    proposal = {
        "proposal_id": "prop-stale",
        "artifact_id": "art-1",
        "description": "Move note to Projects",
        "status": "blocked",
        "block_reason": {
            "gate": "stale-source",
            "recourse": "Reopen the note to refresh the proposal.",
        },
        "evidence": {
            "trigger_summary": "Trigger",
            "action_class": "lifecycle.move",
            "cognition_route": "rule",
        },
        "affordances": {"confirm": True, "reject": True, "correct": True},
    }
    # Global WriteGuard is OK; the block is proposal-level only.
    row = palette_row_model(proposal, writeguard_blocked=False)
    assert row["guard_held"] is True
    assert row["available"] is False

    actions_html = _row_actions_html(row)
    assert 'data-testid="palette-blocked-reason"' in actions_html
    assert 'data-testid="palette-blocked-recourse"' in actions_html
    assert "reopen the note" in actions_html.lower()
    assert 'data-guard-gate="stale-source"' in actions_html


def test_palette_blocked_without_reason_uses_fallback_copy() -> None:
    """A confirm response blocked with NO ``block_reason`` still renders a calm
    blocked card with the fallback reason + recourse (palette path)."""
    html = _blocked_html({"status": "blocked", "proposal_id": "prop-z"})

    assert 'data-testid="palette-blocked"' in html
    assert BLOCKED_REASON_FALLBACK in html
    assert BLOCKED_RECOURSE_FALLBACK in html


def test_rail_confirm_blocked_without_reason_uses_fallback_copy() -> None:
    """The rail confirm renderer mirrors the palette: a blocked response with no
    ``block_reason`` still shows a calm blocked card + fallback recourse."""
    html = _render_panel_confirm_response({"status": "blocked"})

    assert 'data-testid="workspace-panel-blocked-reason"' in html
    reason = _text_for_testid(html, "palette-blocked-reason")
    recourse = _text_for_testid(html, "palette-blocked-recourse")
    assert BLOCKED_REASON_FALLBACK in reason
    assert BLOCKED_RECOURSE_FALLBACK in recourse


def test_blocked_proposal_stays_calm_non_red() -> None:
    """The held proposal keeps the calm treatment: no buttons, no alarm role."""
    html = _render(
        writeguard_blocked=True,
        block_reason={"gate": "writeguard"},
    )
    # The held proposal does not re-expose Apply/Discard/Defer action buttons.
    assert 'data-testid="workspace-panel-action"' not in html
    # Nothing-was-mutated calm posture present; not an error/alarm treatment.
    assert "nothing was mutated" in html.lower()
