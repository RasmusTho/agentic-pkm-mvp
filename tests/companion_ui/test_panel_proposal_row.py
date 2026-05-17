"""Tests for Panel proposal row and status/receipt rendering model (#1040).

Verifies:
- ProposalRow carries required fields: proposal_id, artifact_id, description, evidence.
- Affordances (confirm/correct/reject) are exposed without executing them.
- ProposalReceipt carries action_taken, outcome, timestamp.
- Per-row model: decisions are individual, bulk acceptance is not supported.
- No dependency on Canvas bounded suggestion flow or Canvas Core.
- No vault writes.
"""

import pytest
from datetime import datetime, timezone

from companion_ui.panel.proposal_row import (
    ProposalEvidence,
    ProposalRow,
    ProposalReceipt,
    make_stub_proposal_row,
    make_stub_receipt,
)


class TestProposalEvidence:
    def test_evidence_fields(self) -> None:
        e = ProposalEvidence(
            trigger_summary="Note has project tag",
            action_class="lifecycle.move",
            cognition_route="rule",
        )
        assert e.trigger_summary == "Note has project tag"
        assert e.action_class == "lifecycle.move"
        assert e.cognition_route == "rule"

    def test_evidence_as_dict(self) -> None:
        e = ProposalEvidence(
            trigger_summary="trigger",
            action_class="class",
            cognition_route="route",
        )
        d = e.as_dict()
        assert "trigger_summary" in d
        assert "action_class" in d
        assert "cognition_route" in d


class TestProposalRowRequiredFields:
    def test_proposal_id_required(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        with pytest.raises(ValueError, match="proposal_id is required"):
            ProposalRow(proposal_id="", artifact_id="note-a", description="desc", evidence=e)

    def test_artifact_id_required(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        with pytest.raises(ValueError, match="artifact_id is required"):
            ProposalRow(proposal_id="p1", artifact_id="", description="desc", evidence=e)

    def test_description_required(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        with pytest.raises(ValueError, match="description is required"):
            ProposalRow(proposal_id="p1", artifact_id="note-a", description="", evidence=e)

    def test_unknown_status_raises(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        with pytest.raises(ValueError, match="Unknown proposal status"):
            ProposalRow(
                proposal_id="p1",
                artifact_id="note-a",
                description="desc",
                evidence=e,
                status="bogus",
            )

    def test_unknown_affordance_raises(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        with pytest.raises(ValueError, match="Unknown affordances"):
            ProposalRow(
                proposal_id="p1",
                artifact_id="note-a",
                description="desc",
                evidence=e,
                available_affordances={"confirm", "teleport"},
            )


class TestProposalRowAffordances:
    def test_staged_row_can_confirm(self) -> None:
        row = make_stub_proposal_row()
        assert row.can_confirm() is True

    def test_staged_row_can_correct(self) -> None:
        row = make_stub_proposal_row()
        assert row.can_correct() is True

    def test_staged_row_can_reject(self) -> None:
        row = make_stub_proposal_row()
        assert row.can_reject() is True

    def test_corrected_row_can_confirm(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        row = ProposalRow(
            proposal_id="p1",
            artifact_id="note-a",
            description="desc",
            evidence=e,
            status="corrected",
        )
        assert row.can_confirm() is True

    def test_corrected_row_can_reject(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        row = ProposalRow(
            proposal_id="p1",
            artifact_id="note-a",
            description="desc",
            evidence=e,
            status="corrected",
        )
        assert row.can_reject() is True

    def test_confirming_row_cannot_confirm(self) -> None:
        e = ProposalEvidence("t", "c", "r")
        row = ProposalRow(
            proposal_id="p1",
            artifact_id="note-a",
            description="desc",
            evidence=e,
            status="confirming",
        )
        assert row.can_confirm() is False
        assert row.can_correct() is False
        assert row.can_reject() is False

    def test_render_dict_includes_affordances(self) -> None:
        row = make_stub_proposal_row()
        d = row.as_render_dict()
        assert "affordances" in d
        assert "confirm" in d["affordances"]
        assert "correct" in d["affordances"]
        assert "reject" in d["affordances"]

    def test_render_dict_includes_evidence(self) -> None:
        row = make_stub_proposal_row()
        d = row.as_render_dict()
        assert "evidence" in d
        assert "action_class" in d["evidence"]


class TestProposalRowPerRowDecision:
    def test_each_row_is_independent(self) -> None:
        row_a = make_stub_proposal_row(proposal_id="p-a", artifact_id="note-a")
        row_b = make_stub_proposal_row(proposal_id="p-b", artifact_id="note-a")
        assert row_a.proposal_id != row_b.proposal_id
        assert row_a.can_confirm() is True
        assert row_b.can_confirm() is True

    def test_no_bulk_confirm_api_on_row(self) -> None:
        row = make_stub_proposal_row()
        assert not hasattr(row, "bulk_confirm")

    def test_artifact_local_binding(self) -> None:
        row = make_stub_proposal_row(artifact_id="note-xyz")
        assert row.artifact_id == "note-xyz"


class TestProposalReceipt:
    def test_receipt_required_fields(self) -> None:
        with pytest.raises(ValueError, match="proposal_id is required"):
            ProposalReceipt(
                proposal_id="",
                artifact_id="note-a",
                action_taken="act",
                outcome="success",
                timestamp=datetime.now(tz=timezone.utc),
            )

    def test_receipt_unknown_outcome_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown receipt outcome"):
            ProposalReceipt(
                proposal_id="p1",
                artifact_id="note-a",
                action_taken="act",
                outcome="unknown-outcome",
                timestamp=datetime.now(tz=timezone.utc),
            )

    def test_stub_receipt_fields(self) -> None:
        r = make_stub_receipt()
        assert r.action_taken == "lifecycle.move"
        assert r.outcome == "success"
        assert r.timestamp is not None

    def test_receipt_render_dict(self) -> None:
        r = make_stub_receipt(message="Moved to Projects.")
        d = r.as_render_dict()
        assert d["action_taken"] == "lifecycle.move"
        assert d["outcome"] == "success"
        assert "timestamp" in d
        assert d["message"] == "Moved to Projects."

    def test_receipt_blocked_outcome(self) -> None:
        r = make_stub_receipt(outcome="blocked", message="Policy denied.")
        d = r.as_render_dict()
        assert d["outcome"] == "blocked"

    def test_no_canvas_core_dependency(self) -> None:
        import companion_ui.panel.proposal_row as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src
        assert "canvas_suggestion_flow" not in src

    def test_no_vault_write_in_module(self) -> None:
        import companion_ui.panel.proposal_row as mod
        src = open(mod.__file__).read()
        assert "SessionLogWriter" not in src
        assert "WriteGuard" not in src
