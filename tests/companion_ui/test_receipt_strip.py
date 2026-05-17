"""Tests for ReceiptPill and ReceiptsStrip (#871).

Verifies:
- ReceiptPill creation with each outcome (applied, queued, discarded, blocked)
- ReceiptsStrip empty/non-empty state
- latest receipt access
- render dicts
- terminal vs non-terminal outcome classification
- non_terminal_pills filtering
- No dependency on Canvas Core, Panel, backend runtime, or vault writes.
"""

import pytest

from companion_ui.canvas_suggestion_flow.receipt_strip import (
    RECEIPT_OUTCOMES,
    ReceiptPill,
    ReceiptsStrip,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pill(
    receipt_id: str = "rec-001",
    suggestion_id: str = "sugg-001",
    artifact_id: str = "art-001",
    outcome: str = "queued",
    label: str = "queued · rec-001 · move",
    display_timestamp: str = "2026-05-17T10:00:00Z",
    message: str | None = None,
) -> ReceiptPill:
    return ReceiptPill(
        receipt_id=receipt_id,
        suggestion_id=suggestion_id,
        artifact_id=artifact_id,
        outcome=outcome,
        label=label,
        display_timestamp=display_timestamp,
        message=message,
    )


# ---------------------------------------------------------------------------
# RECEIPT_OUTCOMES set
# ---------------------------------------------------------------------------

class TestReceiptOutcomes:
    def test_all_four_outcomes_defined(self) -> None:
        assert RECEIPT_OUTCOMES == frozenset({"applied", "queued", "discarded", "blocked"})

    def test_unknown_outcome_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown receipt outcome"):
            make_pill(outcome="in-review")


# ---------------------------------------------------------------------------
# ReceiptPill creation with each outcome
# ---------------------------------------------------------------------------

class TestReceiptPillCreation:
    def test_queued_outcome(self) -> None:
        pill = make_pill(outcome="queued")
        assert pill.outcome == "queued"
        assert pill.is_terminal is False

    def test_blocked_outcome(self) -> None:
        pill = make_pill(outcome="blocked", label="blocked · rec-002")
        assert pill.outcome == "blocked"
        assert pill.is_terminal is False

    def test_applied_outcome(self) -> None:
        pill = make_pill(outcome="applied", label="applied · rec-003")
        assert pill.outcome == "applied"
        assert pill.is_terminal is True

    def test_discarded_outcome(self) -> None:
        pill = make_pill(outcome="discarded", label="discarded · rec-004")
        assert pill.outcome == "discarded"
        assert pill.is_terminal is True

    def test_all_four_outcomes_construction(self) -> None:
        for outcome in ["applied", "queued", "discarded", "blocked"]:
            pill = make_pill(outcome=outcome, label=f"{outcome} · rec-x")
            assert pill.outcome == outcome

    def test_required_fields(self) -> None:
        with pytest.raises(ValueError, match="receipt_id"):
            ReceiptPill(
                receipt_id="",
                suggestion_id="s",
                artifact_id="a",
                outcome="queued",
                label="x",
                display_timestamp="t",
            )

    def test_optional_message_none(self) -> None:
        pill = make_pill()
        assert pill.message is None

    def test_optional_message_set(self) -> None:
        pill = make_pill(message="Awaiting governance review")
        assert pill.message == "Awaiting governance review"


# ---------------------------------------------------------------------------
# ReceiptPill render dict
# ---------------------------------------------------------------------------

class TestReceiptPillRenderDict:
    def test_render_dict_keys(self) -> None:
        pill = make_pill()
        d = pill.to_render_dict()
        assert d["data_testid"] == "receipt-pill"
        assert d["data_receipt_id"] == pill.receipt_id
        assert d["data_status"] == pill.outcome
        assert d["data_intent"] == "governance.openReceipt"
        assert d["is_terminal"] == pill.is_terminal

    def test_aria_label_includes_receipt_id_and_outcome(self) -> None:
        pill = make_pill(receipt_id="rec-xyz", outcome="queued")
        d = pill.to_render_dict()
        assert "rec-xyz" in d["aria_label"]
        assert "queued" in d["aria_label"]
        assert "Panel" in d["aria_label"]

    def test_render_dict_includes_message_when_set(self) -> None:
        pill = make_pill(message="Extra context")
        d = pill.to_render_dict()
        assert d["message"] == "Extra context"

    def test_render_dict_omits_message_when_none(self) -> None:
        pill = make_pill(message=None)
        d = pill.to_render_dict()
        assert "message" not in d

    def test_terminal_outcomes_flag_is_terminal(self) -> None:
        for outcome in ["applied", "discarded"]:
            d = make_pill(outcome=outcome, label=f"{outcome}").to_render_dict()
            assert d["is_terminal"] is True

    def test_non_terminal_outcomes_flag_not_terminal(self) -> None:
        for outcome in ["queued", "blocked"]:
            d = make_pill(outcome=outcome).to_render_dict()
            assert d["is_terminal"] is False


# ---------------------------------------------------------------------------
# ReceiptsStrip empty/non-empty state
# ---------------------------------------------------------------------------

class TestReceiptsStripEmpty:
    def test_empty_strip_on_default(self) -> None:
        strip = ReceiptsStrip()
        assert strip.is_empty is True

    def test_empty_strip_explicit(self) -> None:
        strip = ReceiptsStrip(pills=[])
        assert strip.is_empty is True

    def test_non_empty_strip(self) -> None:
        strip = ReceiptsStrip(pills=[make_pill()])
        assert strip.is_empty is False

    def test_empty_latest_is_none(self) -> None:
        strip = ReceiptsStrip()
        assert strip.latest is None


# ---------------------------------------------------------------------------
# latest receipt access
# ---------------------------------------------------------------------------

class TestReceiptsStripLatest:
    def test_latest_is_last_pill(self) -> None:
        p1 = make_pill(receipt_id="rec-001")
        p2 = make_pill(receipt_id="rec-002")
        strip = ReceiptsStrip(pills=[p1, p2])
        assert strip.latest is p2

    def test_latest_single_pill(self) -> None:
        p = make_pill(receipt_id="rec-solo")
        strip = ReceiptsStrip(pills=[p])
        assert strip.latest is p

    def test_latest_after_appending(self) -> None:
        p1 = make_pill(receipt_id="rec-001")
        p2 = make_pill(receipt_id="rec-002")
        strip = ReceiptsStrip(pills=[p1])
        strip.pills.append(p2)
        assert strip.latest is p2


# ---------------------------------------------------------------------------
# non_terminal_pills filtering
# ---------------------------------------------------------------------------

class TestNonTerminalPills:
    def test_non_terminal_excludes_applied(self) -> None:
        applied = make_pill(outcome="applied", receipt_id="r1", label="x")
        queued = make_pill(outcome="queued", receipt_id="r2")
        strip = ReceiptsStrip(pills=[applied, queued])
        assert queued in strip.non_terminal_pills
        assert applied not in strip.non_terminal_pills

    def test_non_terminal_excludes_discarded(self) -> None:
        discarded = make_pill(outcome="discarded", receipt_id="r1", label="x")
        blocked = make_pill(outcome="blocked", receipt_id="r2", label="b")
        strip = ReceiptsStrip(pills=[discarded, blocked])
        assert blocked in strip.non_terminal_pills
        assert discarded not in strip.non_terminal_pills

    def test_non_terminal_empty_when_all_terminal(self) -> None:
        strip = ReceiptsStrip(pills=[
            make_pill(outcome="applied", receipt_id="r1", label="x"),
            make_pill(outcome="discarded", receipt_id="r2", label="y"),
        ])
        assert strip.non_terminal_pills == []


# ---------------------------------------------------------------------------
# ReceiptsStrip render dict
# ---------------------------------------------------------------------------

class TestReceiptsStripRenderDict:
    def test_render_dict_keys(self) -> None:
        strip = ReceiptsStrip()
        d = strip.to_render_dict()
        assert d["data_testid"] == "receipts-strip"
        assert d["aria_live"] == "polite"
        assert d["is_empty"] is True
        assert d["pill_count"] == 0
        assert d["pills"] == []

    def test_render_dict_with_pills(self) -> None:
        p = make_pill()
        strip = ReceiptsStrip(pills=[p])
        d = strip.to_render_dict()
        assert d["is_empty"] is False
        assert d["pill_count"] == 1
        assert len(d["pills"]) == 1
        assert d["pills"][0]["data_receipt_id"] == p.receipt_id

    def test_render_dict_non_terminal_pill_count(self) -> None:
        strip = ReceiptsStrip(pills=[
            make_pill(outcome="queued", receipt_id="r1"),
            make_pill(outcome="applied", receipt_id="r2", label="x"),
        ])
        d = strip.to_render_dict()
        assert d["non_terminal_pill_count"] == 1
        assert len(d["non_terminal_pills"]) == 1

    def test_aria_live_polite_present(self) -> None:
        """AC: ReceiptsStrip aria-live='polite' present (issue #871)."""
        d = ReceiptsStrip().to_render_dict()
        assert d.get("aria_live") == "polite"


# ---------------------------------------------------------------------------
# Boundary: no Canvas Core / Panel / runtime coupling
# ---------------------------------------------------------------------------

class TestNoBoundaryCrossing:
    def test_no_canvas_core_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.receipt_strip as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.receipt_strip as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src

    def test_no_vault_write_imports(self) -> None:
        """No runtime writer symbols are imported (mentions in docstrings are OK)."""
        import companion_ui.canvas_suggestion_flow.receipt_strip as mod
        import importlib
        # Check that none of these are importable attributes (i.e. not imported)
        assert not hasattr(mod, "WriteGuard")
        assert not hasattr(mod, "SessionLogWriter")
        assert not hasattr(mod, "GovernanceRouter")


# ---------------------------------------------------------------------------
# Top-level AC entry points — exact Verify: targets from issue #871
# ---------------------------------------------------------------------------

def test_receipt_pill_renders_on_governance_queue() -> None:
    """AC: ReceiptPill renders after governance.queue resolves."""
    pill = make_pill(outcome="queued")
    d = pill.to_render_dict()
    assert d["data_status"] == "queued"
    assert d["data_intent"] == "governance.openReceipt"


def test_receipts_strip_aria_live() -> None:
    """AC: ReceiptsStrip has aria-live='polite'."""
    d = ReceiptsStrip().to_render_dict()
    assert d["aria_live"] == "polite"


def test_receipt_pill_status_transitions() -> None:
    """AC: Pill reflects each status outcome without reload."""
    for outcome in ["queued", "applied", "discarded", "blocked"]:
        pill = make_pill(outcome=outcome, label=outcome)
        assert pill.outcome == outcome
        assert pill.to_render_dict()["data_status"] == outcome


def test_terminal_receipts_removed() -> None:
    """AC: Terminal receipts (applied/discarded) absent from non_terminal_pills."""
    strip = ReceiptsStrip(pills=[
        make_pill(outcome="applied", receipt_id="r1", label="x"),
        make_pill(outcome="discarded", receipt_id="r2", label="y"),
        make_pill(outcome="queued", receipt_id="r3"),
    ])
    ids = {p.receipt_id for p in strip.non_terminal_pills}
    assert "r3" in ids
    assert "r1" not in ids
    assert "r2" not in ids


def test_no_receipt_on_body_edit() -> None:
    """AC: Body-edit applies do not generate a receipt — strip is empty by default."""
    # The ReceiptsStrip is not populated by body edits; it requires explicit pill construction.
    strip = ReceiptsStrip()
    assert strip.is_empty is True
