"""Tests for SuggestedInsertion in-document preview marker (#869).

Verifies:
- <ins> element renders with correct staging attributes (amber tint hint).
- data-state transitions: staged→applied on apply; staged→discarded on discard.
- data-receipt populated after apply; aria-label includes anchor reference.
- Discarded state removes element from DOM (is_visible=False).
- Governance proposals do not produce a SuggestedInsertion (boundary note).
- No Canvas Core / Panel / runtime dependency.
"""

import pytest

from companion_ui.canvas_suggestion_flow.suggested_insertion import (
    INSERTION_STATES,
    SuggestedInsertion,
    make_stub_insertion,
)


# ---------------------------------------------------------------------------
# AC: staged styling — amber colour hint, correct label, ins element
# ---------------------------------------------------------------------------

class TestSuggestedInsertionStagedStyling:
    def test_suggested_insertion_staged_styling(self) -> None:
        ins = make_stub_insertion()
        assert ins.state == "staged"
        assert ins.color_hint == "amber"

    def test_staged_label(self) -> None:
        ins = make_stub_insertion()
        assert ins.label == "PROPOSED · UNCOMMITTED"

    def test_staged_is_visible(self) -> None:
        ins = make_stub_insertion()
        assert ins.is_visible is True

    def test_staged_render_dict_element_is_ins(self) -> None:
        ins = make_stub_insertion()
        d = ins.as_render_dict()
        assert d["element"] == "ins"

    def test_staged_render_dict_css_class(self) -> None:
        ins = make_stub_insertion()
        d = ins.as_render_dict()
        assert d["css_class"] == "suggested-insertion"

    def test_staged_render_dict_data_testid(self) -> None:
        ins = make_stub_insertion()
        d = ins.as_render_dict()
        assert d["data_testid"] == "suggested-insertion-block"

    def test_staged_render_dict_data_state(self) -> None:
        ins = make_stub_insertion()
        d = ins.as_render_dict()
        assert d["data_state"] == "staged"

    def test_staged_render_dict_color_hint(self) -> None:
        ins = make_stub_insertion()
        d = ins.as_render_dict()
        assert d["color_hint"] == "amber"

    def test_staged_receipt_is_empty(self) -> None:
        ins = make_stub_insertion()
        assert ins.receipt_id == ""
        d = ins.as_render_dict()
        assert d["data_receipt"] == ""


# ---------------------------------------------------------------------------
# AC: state transitions staged→applied and staged→discarded
# ---------------------------------------------------------------------------

class TestSuggestedInsertionStateTransitions:
    def test_suggested_insertion_state_transitions_apply(self) -> None:
        ins = make_stub_insertion()
        ins.apply(receipt_id="rcpt-001")
        assert ins.state == "applied"

    def test_suggested_insertion_state_transitions_discard(self) -> None:
        ins = make_stub_insertion()
        ins.discard()
        assert ins.state == "discarded"

    def test_applied_color_hint_is_vault_green(self) -> None:
        ins = make_stub_insertion()
        ins.apply()
        assert ins.color_hint == "vault-green"

    def test_discarded_color_hint_is_none(self) -> None:
        ins = make_stub_insertion()
        ins.discard()
        assert ins.color_hint is None

    def test_cannot_apply_from_applied(self) -> None:
        ins = make_stub_insertion()
        ins.apply()
        with pytest.raises(ValueError, match="Cannot apply"):
            ins.apply()

    def test_cannot_discard_from_applied(self) -> None:
        ins = make_stub_insertion()
        ins.apply()
        with pytest.raises(ValueError, match="Cannot discard"):
            ins.discard()

    def test_cannot_apply_from_discarded(self) -> None:
        ins = make_stub_insertion()
        ins.discard()
        with pytest.raises(ValueError, match="Cannot apply"):
            ins.apply()

    def test_all_states_defined(self) -> None:
        assert INSERTION_STATES == {"staged", "applied", "discarded"}


# ---------------------------------------------------------------------------
# AC: data-receipt populated after apply; aria-label includes anchor
# ---------------------------------------------------------------------------

class TestSuggestedInsertionReceiptPopulated:
    def test_suggested_insertion_receipt_populated(self) -> None:
        ins = make_stub_insertion()
        ins.apply(receipt_id="rcpt-abc")
        assert ins.receipt_id == "rcpt-abc"
        d = ins.as_render_dict()
        assert d["data_receipt"] == "rcpt-abc"

    def test_applied_label_includes_receipt_id(self) -> None:
        ins = make_stub_insertion()
        ins.apply(receipt_id="rcpt-xyz")
        assert "rcpt-xyz" in ins.label

    def test_applied_label_without_receipt_id(self) -> None:
        ins = make_stub_insertion()
        ins.apply()
        assert ins.label == "APPLIED"

    def test_aria_label_includes_anchor(self) -> None:
        ins = make_stub_insertion(anchor_description="3 lines after ## Summary")
        assert "3 lines after ## Summary" in ins.aria_label

    def test_aria_label_prefix(self) -> None:
        ins = make_stub_insertion(anchor_description="after the intro paragraph")
        assert ins.aria_label.startswith("Proposed insertion")

    def test_aria_label_in_render_dict(self) -> None:
        ins = make_stub_insertion(anchor_description="after heading")
        d = ins.as_render_dict()
        assert "after heading" in d["aria_label"]

    def test_suggestion_id_in_render_dict(self) -> None:
        ins = make_stub_insertion(suggestion_id="sugg-test-99")
        d = ins.as_render_dict()
        assert d["data_suggestion_id"] == "sugg-test-99"


# ---------------------------------------------------------------------------
# AC: discarded state removes element from DOM
# ---------------------------------------------------------------------------

class TestSuggestedInsertionDiscardedRemoved:
    def test_suggested_insertion_discarded_removed(self) -> None:
        ins = make_stub_insertion()
        ins.discard()
        assert ins.is_visible is False

    def test_discarded_render_dict_is_visible_false(self) -> None:
        ins = make_stub_insertion()
        ins.discard()
        d = ins.as_render_dict()
        assert d["is_visible"] is False

    def test_discarded_data_state_in_render_dict(self) -> None:
        ins = make_stub_insertion()
        ins.discard()
        d = ins.as_render_dict()
        assert d["data_state"] == "discarded"

    def test_staged_is_visible_true(self) -> None:
        ins = make_stub_insertion()
        d = ins.as_render_dict()
        assert d["is_visible"] is True

    def test_applied_is_visible_true(self) -> None:
        ins = make_stub_insertion()
        ins.apply()
        assert ins.is_visible is True


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

class TestSuggestedInsertionRequiredFields:
    def test_suggestion_id_required(self) -> None:
        with pytest.raises(ValueError, match="suggestion_id is required"):
            SuggestedInsertion(
                suggestion_id="",
                anchor_description="after intro",
                proposed_text="text",
            )

    def test_anchor_description_required(self) -> None:
        with pytest.raises(ValueError, match="anchor_description is required"):
            SuggestedInsertion(
                suggestion_id="s1",
                anchor_description="",
                proposed_text="text",
            )

    def test_proposed_text_required(self) -> None:
        with pytest.raises(ValueError, match="proposed_text is required"):
            SuggestedInsertion(
                suggestion_id="s1",
                anchor_description="after intro",
                proposed_text="",
            )


# ---------------------------------------------------------------------------
# Boundary: governance proposals do not produce SuggestedInsertion
# ---------------------------------------------------------------------------

class TestGovernanceBoundary:
    def test_governance_does_not_render_insertion_module_note(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggested_insertion as mod
        src = open(mod.__file__).read()
        assert "governance proposals do not produce" in src.lower() or \
               "no in-document preview for governance" in src.lower()

    def test_no_canvas_core_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggested_insertion as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggested_insertion as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src

    def test_no_vault_write(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggested_insertion as mod
        src = open(mod.__file__).read()
        assert "WriteGuard" not in src
        # canvas_writer may appear in docstring explanation; ensure it is not imported
        assert "import canvas_writer" not in src
        assert "canvas_writer." not in src
