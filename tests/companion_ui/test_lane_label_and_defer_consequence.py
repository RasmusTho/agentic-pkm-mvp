"""C2 (CUIDR-08): agent cards label the recording distinction; Defer states it.

Spec: docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/BLOCKED_RECOURSE_AND_LANE_LABELING.md
:: Acceptance Criteria — C2 (static).

Every agent card states in words whether applying it is recorded (produces a
durable receipt) or not. The recorded/not-recorded line is the most prominent
text on the card. Defer states its consequence. The lane is sourced from the
server-declared payload (`lane` token / `governed` flag) — never inferred from
colour, button count, or proposal content.
"""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.calm_degraded import (
    DEFER_CONSEQUENCE,
    LANE_LABEL_BODY_EDIT,
    LANE_LABEL_GOVERNED,
)
from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(proposal: dict[str, Any]) -> dict[str, Any]:
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
        "guard_writeguard_status": "ok",
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


def _proposal(
    *,
    lane: str,
    governed: bool,
    affordances: dict[str, bool],
) -> dict[str, Any]:
    return {
        "proposal_id": "prop-1829",
        "artifact_id": "art-1829",
        "description": "Move note to Projects",
        "evidence": {
            "trigger_summary": "Trigger",
            "action_class": "lifecycle.move",
            "cognition_route": "rule",
        },
        "status": "staged",
        "lane": lane,
        "governed": governed,
        "proposal_origin": None,
        "reflected_receipt": None,
        "affordances": affordances,
    }


def _render(proposal: dict[str, Any]) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=_fields(proposal),
    )


def _lane_label_texts(html: str) -> list[str]:
    pattern = r'data-testid="lane-label"[^>]*>(.*?)</'
    return [m.strip() for m in re.findall(pattern, html, re.S)]


def _render_with_suggestion_card(variant: str) -> str:
    fields = _fields(
        _proposal(
            lane="governed",
            governed=True,
            affordances={"confirm": True, "reject": True},
        )
    )
    fields["suggestion_state"] = "staged_body" if variant == "body" else "staged_governance"
    fields["suggestion_cards"] = [
        {
            "data_variant": variant,
            "data_suggestion_id": "sugg-1",
            "title": "Add summary paragraph",
            "preview_text": "The project has entered…",
            "available_intents": (
                ["suggestion.apply", "suggestion.discard"]
                if variant == "body"
                else ["governance.queue", "suggestion.discard"]
            ),
        }
    ]
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def test_body_edit_lane_label_not_recorded() -> None:
    """A body-edit-lane card labels Apply as not recorded (no receipt).

    Covers the *actual* body-edit lane surface: the S2 suggestion card rendered
    by _render_suggestion_cards (variant="body"), not only the governed rail.
    """
    html = _render_with_suggestion_card("body")
    # The suggestion card carries the lane label.
    card_start = html.find('data-testid="suggestion-card"')
    assert card_start != -1, "body-edit suggestion card must render"
    card_html = html[card_start:]
    labels = _lane_label_texts(card_html)
    assert labels, "lane-label must render on the body-edit suggestion card"
    assert any("not recorded" in label.lower() for label in labels)
    assert LANE_LABEL_BODY_EDIT in html


def test_governance_suggestion_card_labels_queue_not_apply_receipt() -> None:
    """A governance-variant suggestion card only QUEUES (governance.queue) — it
    must not borrow the governed-apply "→ receipt" label (that would overstate
    the recording guarantee). It names the queue-then-record reality instead.
    """
    from companion_ui.workspace.calm_degraded import (
        LANE_LABEL_GOVERNANCE_QUEUE,
        LANE_LABEL_GOVERNED,
    )

    html = _render_with_suggestion_card("governance")
    card_start = html.find('data-testid="suggestion-card"')
    assert card_start != -1
    # Scope to the suggestion-card element only (the page also renders a
    # separate governed rail proposal that legitimately carries the governed
    # label).
    card_end = html.find("</div>", html.find("suggestion-card-actions", card_start))
    card_html = html[card_start : card_end if card_end != -1 else len(html)]
    labels = _lane_label_texts(card_html)
    assert labels
    # The queue label is shown on the suggestion card; the governed-apply line
    # is NOT (a Queue is not an Apply→receipt).
    assert any("queue" in label.lower() for label in labels)
    assert LANE_LABEL_GOVERNANCE_QUEUE in card_html
    assert LANE_LABEL_GOVERNED not in card_html


def test_body_edit_lane_label_via_governed_payload() -> None:
    """The governed rail card honours an explicit server-declared body-edit lane."""
    html = _render(
        _proposal(
            lane="body_edit",
            governed=False,
            affordances={"confirm": True, "reject": True},
        )
    )
    labels = _lane_label_texts(html)
    assert labels, "lane-label must render"
    assert any("not recorded" in label.lower() for label in labels)
    assert LANE_LABEL_BODY_EDIT in html


def test_governed_lane_label_receipt() -> None:
    """A governed-lane card labels Apply as a vault change producing a receipt."""
    html = _render(
        _proposal(
            lane="governed",
            governed=True,
            affordances={"confirm": True, "reject": True, "correct": True},
        )
    )
    labels = _lane_label_texts(html)
    assert labels, "lane-label must render"
    assert any("receipt" in label.lower() for label in labels)
    assert LANE_LABEL_GOVERNED in html


def test_defer_consequence_present() -> None:
    """A card carrying a Defer button also carries a non-empty consequence line."""
    html = _render(
        _proposal(
            lane="governed",
            governed=True,
            affordances={"confirm": True, "reject": True, "correct": True},
        )
    )
    assert 'data-testid="defer-consequence"' in html
    assert DEFER_CONSEQUENCE in html


def test_lane_label_is_most_prominent_text() -> None:
    """The lane label renders before the proposal description on the card."""
    html = _render(
        _proposal(
            lane="governed",
            governed=True,
            affordances={"confirm": True, "reject": True, "correct": True},
        )
    )
    # Within the proposal-row card the lane-label appears ahead of the
    # description (headline position) in document order.
    row_start = html.find('data-testid="workspace-panel-proposal-row"')
    assert row_start != -1, "proposal row must render"
    row_html = html[row_start:]
    lane_idx = row_html.find('data-testid="lane-label"')
    desc_idx = row_html.find("panel-section-title")
    assert lane_idx != -1 and desc_idx != -1
    assert lane_idx < desc_idx
