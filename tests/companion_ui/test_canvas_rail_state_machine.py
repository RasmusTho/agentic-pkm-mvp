"""Tests for the Canvas rail state machine (#870).

Verifies:
- All 9 canonical states are defined.
- Internal state names are canonical snake_case, not DOM alias names.
- Illegal transitions are rejected (governance→apply, staged→terminal without pending).
- Error paths return to the matching staged state.
- governance_pending returns to idle when a receipt is returned.
- Terminal presentation states (applied, discarded, blocked) lock further action.
- No dependency on Canvas Core, Panel, backend runtime, or vault writes.
"""

import pytest

from companion_ui.canvas_suggestion_flow.rail_state_machine import (
    RAIL_STATES,
    DOM_ALIAS,
    TERMINAL_PRESENTATION_STATES,
    CanvasRailStateMachine,
    make_stub_rail,
)


# ---------------------------------------------------------------------------
# AC: all 9 canonical states defined
# ---------------------------------------------------------------------------

class TestAllStatesDefined:
    def test_all_states_defined(self) -> None:
        expected = {
            "idle",
            "thinking",
            "staged_body",
            "staged_governance",
            "apply_pending",
            "governance_pending",
            "applied",
            "discarded",
            "blocked",
        }
        assert RAIL_STATES == expected

    def test_exactly_nine_states(self) -> None:
        assert len(RAIL_STATES) == 9

    def test_dom_alias_covers_all_states(self) -> None:
        assert set(DOM_ALIAS.keys()) == RAIL_STATES


# ---------------------------------------------------------------------------
# AC: canonical state names used internally; DOM aliases are rendering-only
# ---------------------------------------------------------------------------

class TestCanonicalStateNamesUsed:
    def test_initial_state_is_canonical(self) -> None:
        sm = make_stub_rail()
        assert sm.state == "idle"
        assert sm.state in RAIL_STATES

    def test_dom_alias_differs_from_canonical_for_staged_body(self) -> None:
        assert DOM_ALIAS["staged_body"] == "staged-body"
        assert "staged_body" != "staged-body"

    def test_dom_alias_differs_from_canonical_for_staged_governance(self) -> None:
        assert DOM_ALIAS["staged_governance"] == "staged-gov"

    def test_dom_alias_differs_from_canonical_for_apply_pending(self) -> None:
        assert DOM_ALIAS["apply_pending"] == "pending-apply"

    def test_dom_alias_differs_from_canonical_for_governance_pending(self) -> None:
        assert DOM_ALIAS["governance_pending"] == "pending-gov"

    def test_state_machine_state_property_returns_canonical(self) -> None:
        sm = make_stub_rail("staged_body")
        assert sm.state == "staged_body"
        assert "-" not in sm.state  # canonical names use underscore, not hyphen

    def test_dom_alias_property_returns_alias(self) -> None:
        sm = make_stub_rail("staged_body")
        assert sm.dom_alias == "staged-body"

    def test_unknown_initial_state_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown initial rail state"):
            CanvasRailStateMachine(initial_state="staged-body")  # DOM name, not canonical

    def test_unknown_transition_target_raises(self) -> None:
        sm = make_stub_rail()
        with pytest.raises(ValueError, match="Unknown rail state"):
            sm.transition("staged-body")  # DOM name, not canonical


# ---------------------------------------------------------------------------
# AC: illegal transitions are rejected
# ---------------------------------------------------------------------------

class TestIllegalTransitionsRejected:
    def test_governance_cannot_enter_apply_pending(self) -> None:
        sm = make_stub_rail("staged_governance")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("apply_pending")

    def test_staged_body_cannot_jump_to_applied(self) -> None:
        sm = make_stub_rail("staged_body")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("applied")

    def test_staged_body_cannot_jump_to_idle(self) -> None:
        sm = make_stub_rail("staged_body")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("idle")

    def test_staged_governance_cannot_jump_to_idle(self) -> None:
        sm = make_stub_rail("staged_governance")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("idle")

    def test_idle_cannot_jump_to_staged_body(self) -> None:
        sm = make_stub_rail()
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("staged_body")

    def test_applied_cannot_transition_to_thinking(self) -> None:
        sm = make_stub_rail("applied")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("thinking")

    def test_discarded_cannot_transition_to_thinking(self) -> None:
        sm = make_stub_rail("discarded")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("thinking")

    def test_blocked_cannot_transition_to_thinking(self) -> None:
        sm = make_stub_rail("blocked")
        with pytest.raises(ValueError, match="Illegal canvas rail transition"):
            sm.transition("thinking")


# ---------------------------------------------------------------------------
# AC: error paths return to matching staged state
# ---------------------------------------------------------------------------

class TestErrorPathsReturnToStaged:
    def test_apply_error_returns_to_staged_body(self) -> None:
        sm = make_stub_rail("apply_pending")
        sm.transition("staged_body", error="canvas_writer failed: timeout")
        assert sm.state == "staged_body"
        assert sm.error == "canvas_writer failed: timeout"

    def test_governance_error_returns_to_staged_governance(self) -> None:
        sm = make_stub_rail("governance_pending")
        sm.transition("staged_governance", error="GovernanceRouter unavailable")
        assert sm.state == "staged_governance"
        assert sm.error == "GovernanceRouter unavailable"

    def test_error_is_cleared_on_next_transition(self) -> None:
        sm = make_stub_rail("apply_pending")
        sm.transition("staged_body", error="fail")
        sm.transition("apply_pending")
        assert sm.error is None

    def test_happy_path_has_no_error(self) -> None:
        sm = make_stub_rail("apply_pending")
        sm.transition("applied")
        assert sm.error is None


# ---------------------------------------------------------------------------
# AC: governance_pending returns to idle when receipt returned
# ---------------------------------------------------------------------------

class TestGovernanceReceiptReturnsToIdle:
    def test_governance_pending_to_idle(self) -> None:
        sm = make_stub_rail("governance_pending")
        sm.transition("idle")
        assert sm.state == "idle"

    def test_governance_pending_does_not_produce_receipt_in_state_machine(self) -> None:
        sm = make_stub_rail("governance_pending")
        # state machine is receipt-agnostic; receipt handling is in receipt components
        sm.transition("idle")
        assert sm.state == "idle"

    def test_full_governance_lane(self) -> None:
        sm = make_stub_rail()
        sm.transition("thinking")
        sm.transition("staged_governance")
        sm.transition("governance_pending")
        sm.transition("idle")
        assert sm.state == "idle"

    def test_governance_lane_error_then_retry(self) -> None:
        sm = make_stub_rail("governance_pending")
        sm.transition("staged_governance", error="router error")
        assert sm.state == "staged_governance"
        sm.transition("governance_pending")
        sm.transition("idle")
        assert sm.state == "idle"


# ---------------------------------------------------------------------------
# AC: terminal presentation states lock further action
# ---------------------------------------------------------------------------

class TestTerminalStatesLocked:
    def test_applied_is_terminal_presentation(self) -> None:
        assert "applied" in TERMINAL_PRESENTATION_STATES

    def test_discarded_is_terminal_presentation(self) -> None:
        assert "discarded" in TERMINAL_PRESENTATION_STATES

    def test_blocked_is_terminal_presentation(self) -> None:
        assert "blocked" in TERMINAL_PRESENTATION_STATES

    def test_applied_only_allows_idle(self) -> None:
        sm = make_stub_rail("applied")
        assert sm.is_terminal_presentation is True
        assert sm.allowed_transitions() == frozenset({"idle"})

    def test_discarded_only_allows_idle(self) -> None:
        sm = make_stub_rail("discarded")
        assert sm.is_terminal_presentation is True
        assert sm.allowed_transitions() == frozenset({"idle"})

    def test_blocked_only_allows_idle(self) -> None:
        sm = make_stub_rail("blocked")
        assert sm.is_terminal_presentation is True
        assert sm.allowed_transitions() == frozenset({"idle"})

    def test_applied_cannot_transition_to_staged(self) -> None:
        sm = make_stub_rail("applied")
        with pytest.raises(ValueError):
            sm.transition("staged_body")

    def test_idle_is_not_terminal(self) -> None:
        sm = make_stub_rail("idle")
        assert sm.is_terminal_presentation is False

    def test_composer_enabled_only_in_idle(self) -> None:
        assert make_stub_rail("idle").composer_enabled is True
        assert make_stub_rail("thinking").composer_enabled is False
        assert make_stub_rail("staged_body").composer_enabled is False
        assert make_stub_rail("applied").composer_enabled is False

    def test_full_body_lane(self) -> None:
        sm = make_stub_rail()
        sm.transition("thinking")
        sm.transition("staged_body")
        sm.transition("apply_pending")
        sm.transition("applied")
        sm.transition("idle")
        assert sm.state == "idle"

    def test_full_discard_lane(self) -> None:
        sm = make_stub_rail()
        sm.transition("thinking")
        sm.transition("staged_body")
        sm.transition("discarded")
        sm.transition("idle")
        assert sm.state == "idle"


# ---------------------------------------------------------------------------
# Boundary: no Canvas Core / Panel / runtime coupling
# ---------------------------------------------------------------------------

class TestNoBoundaryCrossing:
    def test_no_canvas_core_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.rail_state_machine as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.rail_state_machine as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src

    def test_no_vault_write(self) -> None:
        import companion_ui.canvas_suggestion_flow.rail_state_machine as mod
        src = open(mod.__file__).read()
        assert "WriteGuard" not in src
        assert "SessionLogWriter" not in src


# ---------------------------------------------------------------------------
# Top-level AC entry points — exact Verify: targets from issue #870
# ---------------------------------------------------------------------------

def test_all_states_defined() -> None:
    """AC: state machine reflects all 9 canonical states."""
    TestAllStatesDefined().test_all_states_defined()


def test_canonical_state_names_used() -> None:
    """AC: internal state names use canonical snake_case; DOM aliases are rendering-only."""
    t = TestCanonicalStateNamesUsed()
    t.test_state_machine_state_property_returns_canonical()
    t.test_dom_alias_property_returns_alias()
    t.test_unknown_initial_state_raises()
    t.test_unknown_transition_target_raises()


def test_illegal_transitions_rejected() -> None:
    """AC: illegal transitions including governance→apply and staged→terminal are rejected."""
    t = TestIllegalTransitionsRejected()
    t.test_governance_cannot_enter_apply_pending()
    t.test_staged_body_cannot_jump_to_applied()
    t.test_staged_governance_cannot_jump_to_idle()


def test_error_paths_return_to_staged() -> None:
    """AC: error paths return to the matching staged state."""
    t = TestErrorPathsReturnToStaged()
    t.test_apply_error_returns_to_staged_body()
    t.test_governance_error_returns_to_staged_governance()


def test_governance_receipt_returns_to_idle() -> None:
    """AC: governance_pending returns to idle when a receipt is returned."""
    t = TestGovernanceReceiptReturnsToIdle()
    t.test_governance_pending_to_idle()
    t.test_full_governance_lane()


def test_terminal_states_locked() -> None:
    """AC: terminal presentation states prevent further action."""
    t = TestTerminalStatesLocked()
    t.test_applied_only_allows_idle()
    t.test_discarded_only_allows_idle()
    t.test_blocked_only_allows_idle()
    t.test_applied_cannot_transition_to_staged()
