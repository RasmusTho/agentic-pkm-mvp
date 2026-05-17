"""Tests for Panel visual shell stub (#1045).

Validates:
- All 8 required Panel states are buildable from stub data.
- Each shell view is serialisable and contains the expected keys.
- Proposal rows carry confirm/correct/reject affordance slots.
- no-match and blocked states carry a visible reason string.
- No runtime imports, no vault writes, no Canvas Core imports.

Validation level: Level 1 — isolated Companion UI Panel shell.
No runtime startup, no backend API, no vault write path.
"""

from __future__ import annotations

import pytest

from companion_ui.panel.visual_shell import (
    REQUIRED_PANEL_STATES,
    PanelShellView,
    build_all_states,
    build_blocked_view,
    build_confirming_view,
    build_executing_view,
    build_idle_view,
    build_no_match_view,
    build_proposals_staged_view,
    build_receipt_displayed_view,
    build_running_view,
)
from companion_ui.panel.render_model import PANEL_STATES_REQUIRED

ARTIFACT_ID = "note-stub-test-01"


# ---------------------------------------------------------------------------
# Required states coverage
# ---------------------------------------------------------------------------


def test_required_panel_states_match_render_model():
    assert REQUIRED_PANEL_STATES == PANEL_STATES_REQUIRED


def test_build_all_states_returns_all_required():
    views = build_all_states(ARTIFACT_ID)
    assert set(views.keys()) == REQUIRED_PANEL_STATES


def test_all_views_are_panel_shell_view_instances():
    views = build_all_states(ARTIFACT_ID)
    for state, view in views.items():
        assert isinstance(view, PanelShellView), f"{state} returned {type(view)}"


def test_all_views_serialisable():
    views = build_all_states(ARTIFACT_ID)
    for state, view in views.items():
        d = view.as_dict()
        assert isinstance(d, dict), f"{state} as_dict() not a dict"
        assert "render" in d
        assert "proposals" in d
        assert "receipts" in d


# ---------------------------------------------------------------------------
# Per-state render assertions
# ---------------------------------------------------------------------------


def test_idle_state():
    v = build_idle_view(ARTIFACT_ID)
    assert v.render["state"] == "idle"
    assert v.render["artifact_id"] == ARTIFACT_ID
    assert not v.proposals
    assert not v.receipts


def test_running_state_has_loading_flag():
    v = build_running_view(ARTIFACT_ID)
    assert v.render["state"] == "running"
    assert v.render.get("loading") is True


def test_proposals_staged_has_proposal_rows():
    v = build_proposals_staged_view(ARTIFACT_ID)
    assert v.render["state"] == "proposals-staged"
    assert len(v.proposals) == 2
    assert v.render["proposal_count"] == 2


def test_proposals_staged_rows_have_affordances():
    v = build_proposals_staged_view(ARTIFACT_ID)
    for row in v.proposals:
        affordances = row["affordances"]
        assert affordances["confirm"] is True, "confirm affordance must be available"
        assert affordances["correct"] is True, "correct affordance must be available"
        assert affordances["reject"] is True, "reject affordance must be available"


def test_proposals_staged_rows_have_artifact_id():
    v = build_proposals_staged_view(ARTIFACT_ID)
    for row in v.proposals:
        assert row["artifact_id"] == ARTIFACT_ID


def test_proposals_staged_has_interaction_summary():
    v = build_proposals_staged_view(ARTIFACT_ID)
    assert v.interaction_summary is not None
    assert v.interaction_summary["artifact_id"] == ARTIFACT_ID
    assert v.interaction_summary["proposal_count"] == 2


def test_confirming_state():
    v = build_confirming_view(ARTIFACT_ID)
    assert v.render["state"] == "confirming"
    assert v.interaction_summary is not None
    # prop-001 should be in 'confirming' interaction state
    prop_states = v.interaction_summary["proposals"]
    assert prop_states["prop-001"]["state"] == "confirming"


def test_executing_state_has_loading_flag():
    v = build_executing_view(ARTIFACT_ID)
    assert v.render["state"] == "executing"
    assert v.render.get("loading") is True


def test_receipt_displayed_has_receipt():
    v = build_receipt_displayed_view(ARTIFACT_ID)
    assert v.render["state"] == "receipt-displayed"
    assert len(v.receipts) == 1
    receipt = v.receipts[0]
    assert receipt["outcome"] == "success"
    assert receipt["artifact_id"] == ARTIFACT_ID


# ---------------------------------------------------------------------------
# Visible failure states
# ---------------------------------------------------------------------------


def test_no_match_state_has_visible_reason():
    v = build_no_match_view(ARTIFACT_ID)
    assert v.render["state"] == "no-match"
    assert v.render.get("message"), "no-match must carry a non-empty reason message"


def test_no_match_state_custom_reason():
    reason = "Note has no applicable rules or LLM proposals."
    v = build_no_match_view(ARTIFACT_ID, reason=reason)
    assert v.render["message"] == reason


def test_blocked_state_has_visible_reason():
    v = build_blocked_view(ARTIFACT_ID)
    assert v.render["state"] == "blocked"
    assert v.render.get("message"), "blocked must carry a non-empty reason message"


def test_blocked_state_has_blocked_receipt():
    v = build_blocked_view(ARTIFACT_ID)
    assert len(v.receipts) == 1
    assert v.receipts[0]["outcome"] == "blocked"


def test_blocked_state_custom_reason():
    reason = "WriteGuard denied: capability not in allowlist."
    v = build_blocked_view(ARTIFACT_ID, reason=reason)
    assert v.render["message"] == reason


def test_no_match_is_visible_failure():
    v = build_no_match_view(ARTIFACT_ID)
    from companion_ui.panel.render_model import PanelRenderState
    rs = PanelRenderState(artifact_id=ARTIFACT_ID, state="no-match")
    assert rs.is_visible_failure is True


def test_blocked_is_visible_failure():
    from companion_ui.panel.render_model import PanelRenderState
    rs = PanelRenderState(artifact_id=ARTIFACT_ID, state="blocked")
    assert rs.is_visible_failure is True


# ---------------------------------------------------------------------------
# Stub data only — no network, no vault writes
# ---------------------------------------------------------------------------


def test_no_runtime_api_imports():
    """visual_shell must not import runtime/vault/Canvas Core modules.

    Checks the module's own namespace — not sys.modules globally, since other
    tests in the suite legitimately load canvas_core modules.
    """
    import types
    import companion_ui.panel.visual_shell as vs

    forbidden_prefixes = (
        "companion_ui.canvas_core",
        "companion_ui.canvas_suggestion_flow",
        "runtime",
        "vault",
    )

    violations = []
    for attr_name, attr_val in vars(vs).items():
        if isinstance(attr_val, types.ModuleType):
            mod_name = getattr(attr_val, "__name__", "")
            if any(mod_name.startswith(p) for p in forbidden_prefixes):
                violations.append(mod_name)

    assert not violations, f"visual_shell directly imports forbidden modules: {violations}"


def test_all_states_use_stub_artifact_id():
    views = build_all_states(ARTIFACT_ID)
    for state, view in views.items():
        assert view.render["artifact_id"] == ARTIFACT_ID, (
            f"State {state!r} render artifact_id mismatch"
        )


def test_default_artifact_id_accepted():
    # build_all_states has a default — must not raise
    views = build_all_states()
    assert len(views) == len(REQUIRED_PANEL_STATES)
