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


def _layout_open_tag(html: str) -> str:
    """Return the opening ``<div class="workspace-layout ...">`` tag.

    The rail ambient/active state is carried on the layout element as a
    ``data-rail-state`` attribute so CSS can reclaim the rail column width for
    the note column when the rail has nothing to act on (CUIDR-03).
    """
    start = html.index('class="workspace-layout workspace-layout--three-col"')
    # Walk back to the opening '<' of the tag and forward to its closing '>'.
    open_lt = html.rindex("<", 0, start)
    close_gt = html.index(">", start)
    return html[open_lt : close_gt + 1]


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


# ---------------------------------------------------------------------------
# CUIDR-03 (#2446) — rail ambient-until-active
#
# Idle shell: the rail demotes to a thin ambient strip and the note column
# reclaims the width (it is no longer a permanently-reserved empty third). The
# rail expands to full active width iff the payload carries a suggestion,
# proposal, or receipt. Safety-critical states (WriteGuard blocked, canvas
# recovery_needed, actionable reorient-with-items) keep it expanded too.
#
# The ambient/active decision is carried on the layout element as
# ``data-rail-state`` so CSS can switch ``grid-template-columns`` between the
# ambient (thin-strip) and active (full-rail) layouts. Presentation only — the
# underlying classification still arrives from the runtime payload.
# ---------------------------------------------------------------------------


def test_idle_shell_rail_is_ambient_strip():
    html = _html()
    layout = _layout_open_tag(html)
    # Idle shell → rail demoted to the ambient strip on the layout grid...
    assert 'data-rail-state="ambient"' in layout
    rail = _rail(html)
    # ...and the rail posture is idle (no active proposals).
    assert 'data-rail-posture="idle"' in rail
    # The idle sub-module cards do not render as a visible stack — they are
    # collapsed behind the single details affordance (minimal presence cue),
    # not a permanently-reserved third of cards.
    assert 'data-testid="workspace-rail-idle-details"' in rail


def test_active_payload_expands_rail():
    proposals = [
        {
            "proposal_id": "p1",
            "summary": "Add a link",
            "action_mode": "confirm_required",
            "status": "staged",
        }
    ]
    html = _html(panel_state="proposals-staged", panel_proposal_count=1, panel_proposals=proposals)
    layout = _layout_open_tag(html)
    assert 'data-rail-state="active"' in layout
    rail = _rail(html)
    assert 'data-rail-posture="active"' in rail
    assert 'data-testid="workspace-rail-idle-details"' not in rail


def test_receipt_alone_expands_rail():
    # A governed receipt arriving after Apply is content, not decoration — the
    # rail must never be ambient when a receipt exists.
    response = {
        "status": "executed",
        "receipt": {
            "receipt_id": "r1",
            "outcome": "applied",
            "message": "done",
            "persistence": "durable",
        },
    }
    html = _html(panel_last_response=response)
    assert 'data-rail-state="active"' in _layout_open_tag(html)
    assert 'data-testid="workspace-rail-idle-details"' not in _rail(html)


def test_governance_receipt_alone_expands_rail():
    html = _html(governance_receipts=[{"receipt_id": "r9", "outcome": "applied"}])
    assert 'data-rail-state="active"' in _layout_open_tag(html)


def test_suggestion_card_alone_expands_rail():
    html = _html(suggestion_cards=[{"id": "s1", "text": "Consider linking note X"}])
    assert 'data-rail-state="active"' in _layout_open_tag(html)


def test_zero_content_returns_to_ambient():
    # After an active payload, a payload with all counts at zero collapses back
    # to ambient. No intermediate expanded state persists.
    html = _html(
        panel_state="idle",
        panel_proposal_count=0,
        panel_proposals=[],
        panel_last_response={},
        governance_receipts=[],
        suggestion_cards=[],
        suggestion_state="idle",
    )
    assert 'data-rail-state="ambient"' in _layout_open_tag(html)


def test_rail_active_contract_parametrized():
    # Parametrise over (suggestion, proposal, receipt, all-absent) and assert
    # the rendered rail state matches the single active-iff contract in each
    # case. (Hand-rolled to avoid a pytest.mark.parametrize import churn.)
    cases = [
        ("proposal", {"panel_proposal_count": 1,
                       "panel_proposals": [{"proposal_id": "p", "summary": "x",
                                            "action_mode": "confirm_required", "status": "staged"}]},
         "active"),
        ("suggestion-card", {"suggestion_cards": [{"id": "s", "text": "t"}]}, "active"),
        ("suggestion-staged", {"suggestion_state": "staged_body"}, "active"),
        # Preparatory / non-content suggestion states stay ambient — there is
        # no intermediate "loading" expanded rail (CUIDR-03; Codex P2).
        ("suggestion-thinking", {"suggestion_state": "thinking"}, "ambient"),
        ("suggestion-blocked-no-cards", {"suggestion_state": "blocked"}, "ambient"),
        ("panel-receipt", {"panel_last_response": {"status": "executed",
                            "receipt": {"receipt_id": "r", "outcome": "applied",
                                        "message": "m", "persistence": "durable"}}}, "active"),
        ("governance-receipt", {"governance_receipts": [{"receipt_id": "r"}]}, "active"),
        ("all-absent", {}, "ambient"),
    ]
    for name, overrides, expected in cases:
        layout = _layout_open_tag(_html(**overrides))
        assert f'data-rail-state="{expected}"' in layout, (
            f"case {name!r}: expected rail-state {expected!r}"
        )


def test_safety_critical_states_stay_active_without_content():
    # Binding forewarning: WriteGuard blocked, canvas recovery_needed, and
    # actionable reorient-with-items must keep the rail expanded even with no
    # suggestion/proposal/receipt.
    safety_cases = [
        ("writeguard-blocked", {"guard_writeguard_status": "blocked"}),
        ("canvas-recovery", {"canvas_recovery_needed": True}),
        ("reorient-with-items",
         {"reorient_sections": {"open_loops": [{"text": "Close loop X", "source_path": "n.md"}]}}),
    ]
    for name, overrides in safety_cases:
        html = _html(**overrides)
        assert 'data-rail-state="active"' in _layout_open_tag(html), (
            f"safety case {name!r} must keep the rail active"
        )


def test_panel_blocked_state_keeps_rail_active():
    # A blocked Panel carries a failure reason the user must see; it must not be
    # hidden behind the ambient strip's collapsed body (Codex P2).
    html = _html(panel_state="blocked", panel_message="Action not permitted")
    assert 'data-rail-state="active"' in _layout_open_tag(html)
    assert 'data-testid="workspace-rail-idle-details"' not in _rail(html)


def test_panel_no_match_state_keeps_rail_active():
    # A no-match Panel carries a no_match_reason mapped into panel_render.message
    # — a first-class visible Panel state. It must not collapse into the ambient
    # strip where the reason is hidden (Codex P2 follow-up).
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_fields(
            panel_render={"state": "no-match", "message": "No matching note found."}
        ),
    )
    assert 'data-rail-state="active"' in _layout_open_tag(html)
    assert 'data-testid="workspace-rail-idle-details"' not in _rail(html)


def test_nonempty_panel_message_keeps_rail_active():
    # Generalised: any non-empty Panel message is content the user must see.
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_fields(panel_render={"state": "idle", "message": "Heads up: something to read."}),
    )
    assert 'data-rail-state="active"' in _layout_open_tag(html)


def test_open_loops_cta_hidden_in_ambient_strip():
    # The open-loops orientation CTA renders outside .rail-placeholder-body; in
    # the ambient strip it must be CSS-hidden, not left as a clipped button, and
    # an open-loops count alone must NOT force the rail active (it is
    # orientation metadata, not a suggestion/proposal/receipt) (Codex P3).
    html = _html(orientation_open_loops_count=3)
    assert 'data-rail-state="ambient"' in _layout_open_tag(html)
    # The ambient CSS hides the open-loops region within the strip.
    assert (
        '[data-rail-state="ambient"] .agent-rail .panel-rail-open-loops' in html
    )


def test_populated_commitments_keep_rail_active():
    # A populated commitments surface carries the user's active next/waiting/
    # review responsibilities, rendered read-only inside .rail-placeholder-body.
    # The ambient strip hides that body, so populated commitments must keep the
    # rail active or the user's responsibilities become invisible (Codex P1).
    html = _html(
        commitments_surface={
            "state": "populated",
            "next_action": [{"title": "Reply to Anna", "note_path": "Inbox/anna.md"}],
            "review_cycle": [],
            "as_of": "2026-06-22T10:00:00Z",
        }
    )
    assert 'data-rail-state="active"' in _layout_open_tag(html)
    assert 'data-testid="workspace-rail-idle-details"' not in _rail(html)


def test_nonpopulated_commitments_states_stay_ambient():
    # empty / not-shown / degraded are confident-zero or availability cues, not
    # content the user must act on — they stay ambient (mirrors the reorient
    # "real items only" rule).
    for state in ("empty", "not-shown", "degraded"):
        html = _html(commitments_surface={"state": state})
        assert 'data-rail-state="ambient"' in _layout_open_tag(html), (
            f"commitments state {state!r} must not force the rail active"
        )


def test_find_candidates_keep_rail_active():
    # Non-empty Find results are shipped read-side content rendered inside
    # .rail-placeholder-body; the ambient strip hides that body, so they must
    # keep the rail active or the results become invisible (Codex P2 re-review).
    html = _html(
        find_candidates=[{"title": "Matching note", "note_path": "n.md"}],
        find_payload_available=True,
    )
    assert 'data-rail-state="active"' in _layout_open_tag(html)
    assert 'data-testid="workspace-rail-idle-details"' not in _rail(html)


def test_resurface_candidates_keep_rail_active():
    # Non-empty Resurface (why-now) candidates are read-side content the user can
    # act on; they must not collapse into the hidden ambient body (Codex P2).
    html = _html(
        resurface_candidates=[{"title": "Why now", "note_path": "n.md", "reason": "due"}]
    )
    assert 'data-rail-state="active"' in _layout_open_tag(html)
    assert 'data-testid="workspace-rail-idle-details"' not in _rail(html)


def test_empty_find_resurface_payloads_stay_ambient():
    # An empty candidate list (find unavailable / resurface degraded) is an
    # availability cue, not content — it stays ambient.
    html = _html(find_candidates=[], resurface_candidates=[], find_payload_available=False)
    assert 'data-rail-state="ambient"' in _layout_open_tag(html)


def test_narrow_viewport_single_column_overrides_rail_state_grid():
    # The CUIDR-03 ambient/active grid rules use an attribute selector
    # ([data-rail-state=...], specificity 0,2,0). The narrow-viewport
    # single-column overrides must match that specificity, or the 3-column
    # template survives at <=899px and crushes the note into the 280px track
    # (Codex P1 re-review). Assert the responsive overrides are qualified.
    html = _html()
    qualified = (
        '.workspace-layout--three-col[data-rail-state="active"],\n'
        '      .workspace-layout--three-col[data-rail-state="ambient"] {\n'
        '        grid-template-columns: 1fr;'
    )
    # Both narrow-viewport media blocks (<800px and <=899px) carry the qualified
    # override so it wins over the ambient/active grid rules' specificity.
    assert html.count(qualified) >= 2, (
        "both narrow-viewport single-column overrides must match the "
        "[data-rail-state] specificity (0,2,0)"
    )
    # No bare single-column override should remain (specificity 0,1,0 would lose
    # to the [data-rail-state] grid rules and re-crush the note).
    assert (
        ".workspace-layout--three-col {\n        grid-template-columns: 1fr;" not in html
    )
