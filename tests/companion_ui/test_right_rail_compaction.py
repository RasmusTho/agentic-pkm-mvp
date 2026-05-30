"""Right rail compaction for non-actionable states (#1401).

Applies ``ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md`` §§8, 9, 11: the right
companion rail must earn its space. When only non-actionable states exist (no
proposals, no candidates, Canvas idle/disabled, Find unavailable, Resurface
degraded, suggestions idle, generic persistence), the rail collapses the noisy
idle cards into a single compact posture treatment. Actionable and
safety-critical states — active Panel proposal, Panel receipt/block reason,
WriteGuard block, Canvas recovery/conflict — keep the rail expanded. Internal
runtime/test labels must not leak into the default human copy.

SSR markup/contract tests against the rendered dev-page HTML.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html

_IDLE_TOKENS = (
    "in_memory",
    "SUGGESTION idle",
    "FIND unavailable",
    "composer enabled",
    "user not present",
)


def _fields(**overrides) -> dict:
    base = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody content here.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "in_memory",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "panel_last_response": {},
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
    base.update(overrides)
    return base


def _html(**overrides) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_fields(**overrides),
    )


def _rail(html: str) -> str:
    start = html.index('data-testid="workspace-agent-rail"')
    end = html.index("</aside>", start)
    return html[start:end]


# ---------------------------------------------------------------------------
# AC: compact non-actionable states
# ---------------------------------------------------------------------------


def test_right_rail_compacts_non_actionable_states():
    rail = _rail(_html())
    # A single compact posture treatment is present...
    assert 'data-testid="workspace-rail-posture"' in rail
    assert 'data-rail-posture="idle"' in rail
    # ...and the noisy idle cards are collapsed behind one details affordance.
    assert 'data-testid="workspace-rail-idle-details"' in rail


# ---------------------------------------------------------------------------
# AC: does not render multiple idle cards
# ---------------------------------------------------------------------------


def test_right_rail_does_not_render_multiple_idle_cards():
    rail = _rail(_html())
    posture_idx = rail.index('data-testid="workspace-rail-posture"')
    details_idx = rail.index('data-testid="workspace-rail-idle-details"')
    # Exactly one compact posture group is the default visible treatment.
    assert rail.count('data-testid="workspace-rail-posture"') == 1
    # The idle canvas/panel cards live inside the collapsed details, not as
    # separate top-level cards above it.
    canvas_idx = rail.index('data-testid="workspace-canvas-state"')
    assert posture_idx < details_idx < canvas_idx


# ---------------------------------------------------------------------------
# AC: active Panel proposal keeps the rail expanded
# ---------------------------------------------------------------------------


def test_active_panel_proposal_keeps_rail_expanded():
    proposals = [
        {
            "proposal_id": "p1",
            "summary": "Add a link",
            "action_mode": "confirm_required",
            "status": "staged",
        }
    ]
    rail = _rail(_html(panel_state="proposals-staged", panel_proposal_count=1, panel_proposals=proposals))
    # Rail is expanded (no idle compaction) and the proposal is visible.
    assert 'data-testid="workspace-rail-idle-details"' not in rail
    assert 'data-rail-posture="active"' in rail


# ---------------------------------------------------------------------------
# AC: receipt / block reason keeps the outcome visible
# ---------------------------------------------------------------------------


def test_panel_receipt_or_block_reason_keeps_outcome_visible():
    response = {
        "status": "executed",
        "receipt": {
            "receipt_id": "r1",
            "outcome": "applied",
            "message": "done",
            "persistence": "durable",
        },
    }
    rail = _rail(_html(panel_last_response=response))
    assert 'data-testid="workspace-rail-idle-details"' not in rail
    assert 'data-testid="workspace-panel-receipt"' in rail


# ---------------------------------------------------------------------------
# AC: WriteGuard block overrides compaction
# ---------------------------------------------------------------------------


def test_writeguard_block_overrides_compaction():
    rail = _rail(_html(guard_writeguard_status="blocked"))
    assert 'data-testid="workspace-rail-idle-details"' not in rail
    assert 'data-testid="workspace-guard-indicator"' in rail


# ---------------------------------------------------------------------------
# AC: Canvas recovery / conflict overrides compaction
# ---------------------------------------------------------------------------


def test_canvas_recovery_overrides_compaction():
    rail = _rail(_html(canvas_recovery_needed=True))
    assert 'data-testid="workspace-rail-idle-details"' not in rail


# ---------------------------------------------------------------------------
# AC: internal labels do not leak into the default copy
# ---------------------------------------------------------------------------


def test_internal_labels_do_not_leak_to_default_copy():
    html = _html()
    rail = _rail(html)
    details_idx = rail.index('data-testid="workspace-rail-idle-details"')
    head = rail[:details_idx]
    # The default (pre-details) rail copy is the human posture line...
    assert "Companion" in head
    # ...and carries no internal/test labels (those live behind the details).
    for token in _IDLE_TOKENS:
        assert token not in head, f"internal label {token!r} leaked into default rail copy"


# ---------------------------------------------------------------------------
# #1419 — degraded/disabled-only state must NOT expand the rail
# ---------------------------------------------------------------------------


def test_rail_compacts_for_degraded_disabled_only_state():
    # Matches the user UAT screenshot: runtime degraded + Canvas disabled +
    # workspace update disabled + Find unavailable + Resurface degraded +
    # Suggestions idle + idle Reorient + no proposals/recovery/block.
    rail = _rail(_html(
        guard_degraded=True,
        guard_canvas_enabled=False,
        guard_workspace_update_available=False,
        find_payload_available=False,
        reorient_sections={"open_loops": []},  # idle reorient (no items)
        resurface_candidates=[],
        suggestion_state="idle",
        panel_state="idle",
        panel_proposal_count=0,
    ))
    # None of those are actionable → compact posture, not "needs attention".
    assert 'data-rail-posture="idle"' in rail
    assert "needs attention" not in rail
    # The disabled/degraded cards collapse behind the single details treatment.
    assert 'data-testid="workspace-rail-idle-details"' in rail


def test_generic_guard_degraded_alone_is_not_actionable():
    rail = _rail(_html(guard_degraded=True))
    assert 'data-rail-posture="idle"' in rail
    assert 'data-testid="workspace-rail-idle-details"' in rail


def test_idle_reorient_payload_does_not_expand_rail():
    # An empty-section reorient dict must not force the rail open.
    rail = _rail(_html(reorient_sections={"open_loops": [], "facts": []}))
    assert 'data-rail-posture="idle"' in rail
    assert 'data-testid="workspace-rail-idle-details"' in rail


def test_actionable_reorient_with_items_still_expands_rail():
    # A reorient payload with real items is an actionable orientation step.
    rail = _rail(_html(reorient_sections={"open_loops": [{"text": "Close loop X", "source_path": "n.md"}]}))
    assert 'data-testid="workspace-rail-idle-details"' not in rail


def test_writeguard_block_still_expands_despite_compaction_fix():
    # Safety-critical write block must remain visible (regression guard).
    rail = _rail(_html(guard_writeguard_status="blocked", guard_degraded=True))
    assert 'data-testid="workspace-rail-idle-details"' not in rail
    assert 'data-testid="workspace-guard-indicator"' in rail
