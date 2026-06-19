"""Tests for Panel confirm/correct/reject interaction state model (#1041).

Verifies:
- confirm() moves to confirming state; does not execute locally.
- correct() creates corrected state without mutating original silently.
- reject() marks proposal declined with no execution.
- No bulk confirmation is possible.
- Same-turn generated→executed is not a legal transition.
- Terminal states are not escapable.
- PanelInteractionSession enforces per-proposal tracking.
- No dependency on Canvas Core or vault writes.
"""

import pytest

from companion_ui.panel.interactions import (
    PROPOSAL_INTERACTION_STATES,
    ProposalInteractionState,
    PanelInteractionSession,
)


class TestProposalInteractionStateSetup:
    def test_default_state_is_staged(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        assert s.state == "staged"

    def test_proposal_id_required(self) -> None:
        with pytest.raises(ValueError, match="proposal_id is required"):
            ProposalInteractionState(proposal_id="")

    def test_unknown_state_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown interaction state"):
            ProposalInteractionState(proposal_id="p1", state="bogus")

    def test_all_states_defined(self) -> None:
        for state in [
            "staged", "confirming", "submitted", "corrected",
            "correction-pending", "rejected", "blocked", "clarification-needed",
        ]:
            assert state in PROPOSAL_INTERACTION_STATES


class TestConfirmInteraction:
    def test_confirm_moves_to_confirming(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.confirm()
        assert s.state == "confirming"

    def test_confirm_does_not_execute(self) -> None:
        # After confirm(), state is 'confirming', NOT 'submitted' or 'executed'.
        s = ProposalInteractionState(proposal_id="p1")
        s.confirm()
        assert s.state == "confirming"
        assert not s.is_terminal

    def test_mark_submitted_after_confirming(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.confirm()
        s.mark_submitted()
        assert s.state == "submitted"

    def test_submitted_is_not_terminal(self) -> None:
        # submitted awaits a runtime response; blocked can still arrive async.
        s = ProposalInteractionState(proposal_id="p1")
        s.confirm()
        s.mark_submitted()
        assert s.is_terminal is False
        assert s.awaiting_runtime is True

    def test_submitted_can_receive_blocked_from_runtime(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.confirm()
        s.mark_submitted()
        s.mark_blocked()
        assert s.state == "blocked"
        assert s.is_terminal is False

    def test_confirm_from_non_staged_raises(self) -> None:
        s = ProposalInteractionState(proposal_id="p1", state="rejected")
        with pytest.raises(ValueError, match="Cannot confirm proposal in state"):
            s.confirm()

    def test_no_direct_generated_to_executed_transition(self) -> None:
        # 'staged' cannot go directly to 'submitted' — confirming is required.
        s = ProposalInteractionState(proposal_id="p1")
        with pytest.raises(ValueError, match="Illegal Panel interaction transition"):
            s._transition("submitted")


class TestCorrectInteraction:
    def test_correct_moves_to_corrected(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.correct("Move to Archive instead")
        assert s.state == "corrected"

    def test_correction_text_stored(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.correct("Override: archive")
        assert s.correction_text == "Override: archive"

    def test_empty_correction_text_raises(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        with pytest.raises(ValueError, match="correction_text must be non-empty"):
            s.correct("")

    def test_correct_from_non_staged_raises(self) -> None:
        s = ProposalInteractionState(proposal_id="p1", state="confirming")
        with pytest.raises(ValueError, match="Cannot correct proposal in state"):
            s.correct("some text")

    def test_corrected_can_then_confirm(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.correct("Move to Archive")
        s.confirm()
        assert s.state == "confirming"

    def test_corrected_can_then_reject(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.correct("adjustment")
        s.reject()
        assert s.state == "rejected"


class TestRejectInteraction:
    def test_reject_moves_to_rejected(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.reject()
        assert s.state == "rejected"

    def test_rejected_is_terminal(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.reject()
        assert s.is_terminal is True

    def test_rejected_cannot_transition(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.reject()
        with pytest.raises(ValueError, match="Illegal Panel interaction transition"):
            s._transition("staged")

    def test_reject_from_non_actionable_raises(self) -> None:
        s = ProposalInteractionState(proposal_id="p1", state="confirming")
        with pytest.raises(ValueError, match="Cannot reject proposal in state"):
            s.reject()


class TestBlockedAndClarification:
    def test_blocked_can_retry(self) -> None:
        s = ProposalInteractionState(proposal_id="p1", state="confirming")
        s.mark_blocked()
        assert s.state == "blocked"
        s._transition("staged")
        assert s.state == "staged"

    def test_clarification_needed(self) -> None:
        s = ProposalInteractionState(proposal_id="p1")
        s.request_clarification("Which folder?")
        assert s.state == "clarification-needed"
        assert s.clarification_question == "Which folder?"

    def test_request_clarification_rejected_leaves_no_stale_question(self) -> None:
        # From a non-staged state, request_clarification is an illegal transition.
        # It must validate BEFORE mutating, so no stale question is left behind and
        # the state is unchanged (mirrors correct()'s guard-before-mutate ordering).
        s = ProposalInteractionState(proposal_id="p1", state="confirming")
        with pytest.raises(ValueError, match="Illegal Panel interaction transition"):
            s.request_clarification("Which folder?")
        assert not s.clarification_question
        assert s.state == "confirming"

        # The legal staged path still sets the question and transitions.
        ok = ProposalInteractionState(proposal_id="p2")
        ok.request_clarification("Which folder?")
        assert ok.state == "clarification-needed"
        assert ok.clarification_question == "Which folder?"


class TestPanelInteractionSession:
    def test_artifact_id_required(self) -> None:
        with pytest.raises(ValueError, match="artifact_id is required"):
            PanelInteractionSession(artifact_id="")

    def test_register_and_get_proposal(self) -> None:
        session = PanelInteractionSession(artifact_id="note-a")
        state = session.register_proposal("p1")
        assert state.state == "staged"
        assert session.get("p1") is state

    def test_duplicate_registration_raises(self) -> None:
        session = PanelInteractionSession(artifact_id="note-a")
        session.register_proposal("p1")
        with pytest.raises(ValueError, match="already registered"):
            session.register_proposal("p1")

    def test_get_unknown_proposal_raises(self) -> None:
        session = PanelInteractionSession(artifact_id="note-a")
        with pytest.raises(KeyError, match="Unknown proposal_id"):
            session.get("nonexistent")

    def test_bulk_confirm_not_supported(self) -> None:
        session = PanelInteractionSession(artifact_id="note-a")
        with pytest.raises(NotImplementedError, match="Bulk confirmation is not supported"):
            session.bulk_confirm_not_supported()

    def test_per_proposal_independence(self) -> None:
        session = PanelInteractionSession(artifact_id="note-a")
        s1 = session.register_proposal("p1")
        s2 = session.register_proposal("p2")

        s1.confirm()
        assert s1.state == "confirming"
        assert s2.state == "staged"

        s2.reject()
        assert s2.state == "rejected"
        assert s1.state == "confirming"

    def test_summary_includes_all_proposals(self) -> None:
        session = PanelInteractionSession(artifact_id="note-a")
        session.register_proposal("p1")
        session.register_proposal("p2")
        summary = session.summary()
        assert summary["proposal_count"] == 2
        assert "p1" in summary["proposals"]
        assert "p2" in summary["proposals"]

    def test_no_canvas_core_dependency(self) -> None:
        import companion_ui.panel.interactions as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src
        assert "canvas_suggestion_flow" not in src

    def test_no_vault_write_in_module(self) -> None:
        import companion_ui.panel.interactions as mod
        src = open(mod.__file__).read()
        assert "SessionLogWriter" not in src
        assert "WriteGuard" not in src
