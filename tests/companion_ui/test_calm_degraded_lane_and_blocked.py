"""CUIDR-08 unit tests for the calm-grammar lane + blocked-recourse helpers.

These exercise the pure mapping functions added to ``calm_degraded`` (the sole
emitter of lane labels + blocked reason/recourse copy). Presentation only: the
lane and block classification are server-authoritative; these helpers map the
declared token to human copy and never classify.
"""

from __future__ import annotations

from companion_ui.workspace.calm_degraded import (
    BLOCKED_REASON_FALLBACK,
    BLOCKED_RECOURSE_FALLBACK,
    LANE_LABEL_BODY_EDIT,
    LANE_LABEL_GOVERNED,
    blocked_reason,
    blocked_recourse,
    lane_label,
)


class TestLaneLabel:
    def test_explicit_governed_token(self) -> None:
        assert lane_label("governed") == LANE_LABEL_GOVERNED

    def test_explicit_body_edit_token(self) -> None:
        assert lane_label("body_edit") == LANE_LABEL_BODY_EDIT

    def test_governed_flag_true(self) -> None:
        assert lane_label(None, governed=True) == LANE_LABEL_GOVERNED

    def test_governed_flag_false(self) -> None:
        assert lane_label(None, governed=False) == LANE_LABEL_BODY_EDIT

    def test_token_wins_over_flag(self) -> None:
        # An explicit body-edit token overrides a (contradictory) governed flag.
        assert lane_label("body_edit", governed=True) == LANE_LABEL_BODY_EDIT

    def test_default_is_governed_label(self) -> None:
        # Surfaces that *are* the governed lane call without a declaration.
        assert lane_label() == LANE_LABEL_GOVERNED

    def test_body_edit_label_states_not_recorded(self) -> None:
        assert "not recorded" in LANE_LABEL_BODY_EDIT.lower()

    def test_governed_label_states_receipt(self) -> None:
        assert "receipt" in LANE_LABEL_GOVERNED.lower()


class TestBlockedReason:
    def test_known_gate_humanised(self) -> None:
        reason = blocked_reason({"gate": "writeguard"})
        assert "safe mode" in reason.lower()
        assert "writeguard" not in reason.lower()

    def test_message_passthrough_when_unknown_gate(self) -> None:
        reason = blocked_reason(
            {"gate": "novel-gate", "message": "A custom held explanation."}
        )
        assert reason == "A custom held explanation."

    def test_unknown_gate_no_message_falls_back(self) -> None:
        assert blocked_reason({"gate": "novel-gate"}) == BLOCKED_REASON_FALLBACK

    def test_empty_payload_falls_back(self) -> None:
        assert blocked_reason({}) == BLOCKED_REASON_FALLBACK
        assert blocked_reason(None) == BLOCKED_REASON_FALLBACK


class TestBlockedRecourse:
    def test_explicit_recourse_wins(self) -> None:
        rec = blocked_recourse(
            {"gate": "writeguard", "recourse": "Ping the operator."}
        )
        assert rec == "Ping the operator."

    def test_known_gate_canonical_recourse(self) -> None:
        rec = blocked_recourse({"gate": "stale-source"})
        assert "reopen" in rec.lower()

    def test_unknown_gate_falls_back(self) -> None:
        assert blocked_recourse({"gate": "novel"}) == BLOCKED_RECOURSE_FALLBACK

    def test_empty_payload_falls_back(self) -> None:
        assert blocked_recourse({}) == BLOCKED_RECOURSE_FALLBACK
        assert blocked_recourse(None) == BLOCKED_RECOURSE_FALLBACK
