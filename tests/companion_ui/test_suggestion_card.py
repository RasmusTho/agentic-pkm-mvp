"""Tests for SuggestionCard render model (#868).

Verifies:
- Body variant renders Apply + Discard + Inspect intents.
- Governance variant has NO Apply intent in DOM — hard invariant.
- Blocked variant carries role="alert" and denial reason.
- suggestion_id matches between card and SuggestedInsertion (consistency check).
- No Canvas Core / Panel / runtime dependency.
- No vault writes.
"""

import pytest

from companion_ui.canvas_suggestion_flow.suggestion_card import (
    CARD_VARIANTS,
    SuggestionCard,
    make_stub_body_card,
    make_stub_governance_card,
    make_stub_blocked_card,
)


# ---------------------------------------------------------------------------
# AC: Body variant renders Apply button
# ---------------------------------------------------------------------------

class TestSuggestionCardBodyVariant:
    def test_suggestion_card_body_variant_renders_apply_button(self) -> None:
        card = make_stub_body_card()
        assert "suggestion.apply" in card.available_intents

    def test_body_variant_has_apply_intent_flag(self) -> None:
        card = make_stub_body_card()
        assert card.has_apply_intent is True

    def test_body_variant_has_discard(self) -> None:
        card = make_stub_body_card()
        assert "suggestion.discard" in card.available_intents

    def test_body_variant_has_inspect(self) -> None:
        card = make_stub_body_card()
        assert "suggestion.inspect" in card.available_intents

    def test_body_variant_color_hint_is_amber(self) -> None:
        card = make_stub_body_card()
        assert card.color_hint == "amber"

    def test_body_variant_no_aria_role(self) -> None:
        card = make_stub_body_card()
        assert card.aria_role is None

    def test_body_variant_no_classification_notice(self) -> None:
        card = make_stub_body_card()
        assert card.classification_notice is None

    def test_body_render_dict_includes_apply_in_intents(self) -> None:
        card = make_stub_body_card()
        d = card.as_render_dict()
        assert "suggestion.apply" in d["available_intents"]

    def test_body_render_dict_data_variant(self) -> None:
        card = make_stub_body_card()
        d = card.as_render_dict()
        assert d["data_variant"] == "body"

    def test_body_render_dict_testid(self) -> None:
        card = make_stub_body_card()
        d = card.as_render_dict()
        assert d["data_testid"] == "suggestion-card"


# ---------------------------------------------------------------------------
# AC: Governance variant has NO Apply button
# ---------------------------------------------------------------------------

class TestGovernanceVariantHasNoApplyButton:
    def test_governance_variant_has_no_apply_button(self) -> None:
        card = make_stub_governance_card()
        assert "suggestion.apply" not in card.available_intents

    def test_governance_has_apply_intent_flag_false(self) -> None:
        card = make_stub_governance_card()
        assert card.has_apply_intent is False

    def test_governance_variant_has_queue(self) -> None:
        card = make_stub_governance_card()
        assert "governance.queue" in card.available_intents

    def test_governance_variant_has_discard(self) -> None:
        card = make_stub_governance_card()
        assert "suggestion.discard" in card.available_intents

    def test_governance_variant_has_inspect(self) -> None:
        card = make_stub_governance_card()
        assert "suggestion.inspect" in card.available_intents

    def test_governance_render_dict_no_apply(self) -> None:
        card = make_stub_governance_card()
        d = card.as_render_dict()
        assert "suggestion.apply" not in d["available_intents"]

    def test_governance_color_hint_is_gold(self) -> None:
        card = make_stub_governance_card()
        assert card.color_hint == "gold"

    def test_governance_has_classification_notice(self) -> None:
        card = make_stub_governance_card()
        assert card.classification_notice is not None
        assert "queued" in card.classification_notice.lower()

    def test_governance_render_dict_classification_testid(self) -> None:
        card = make_stub_governance_card()
        d = card.as_render_dict()
        assert d.get("data_testid_classification") == "suggestion-card-classification"

    def test_governance_render_dict_data_variant(self) -> None:
        card = make_stub_governance_card()
        d = card.as_render_dict()
        assert d["data_variant"] == "governance"


# ---------------------------------------------------------------------------
# AC: Blocked variant is alert role
# ---------------------------------------------------------------------------

class TestBlockedVariantIsAlertRole:
    def test_blocked_variant_is_alert_role(self) -> None:
        card = make_stub_blocked_card()
        assert card.aria_role == "alert"

    def test_blocked_variant_carries_denial_reason(self) -> None:
        card = make_stub_blocked_card(denial_reason="Canvas writes are currently disabled.")
        d = card.as_render_dict()
        assert d["denial_reason"] == "Canvas writes are currently disabled."

    def test_blocked_has_no_apply_intent(self) -> None:
        card = make_stub_blocked_card()
        assert "suggestion.apply" not in card.available_intents

    def test_blocked_has_acknowledge_intent(self) -> None:
        card = make_stub_blocked_card()
        assert "blocked.acknowledge" in card.available_intents

    def test_blocked_has_open_panel_intent(self) -> None:
        card = make_stub_blocked_card()
        assert "blocked.openPanel" in card.available_intents

    def test_blocked_requires_denial_reason(self) -> None:
        with pytest.raises(ValueError, match="denial_reason is required"):
            SuggestionCard(
                suggestion_id="sugg-x",
                variant="blocked",
                title="Blocked",
                preview_text="...",
                denial_reason=None,
            )

    def test_blocked_color_hint_is_neutral(self) -> None:
        card = make_stub_blocked_card()
        assert card.color_hint == "neutral"


# ---------------------------------------------------------------------------
# AC: suggestion_id consistency
# ---------------------------------------------------------------------------

class TestSuggestionIdConsistency:
    def test_suggestion_id_consistency(self) -> None:
        from companion_ui.canvas_suggestion_flow.suggested_insertion import (
            make_stub_insertion,
        )
        sid = "sugg-abc-123"
        card = make_stub_body_card(suggestion_id=sid)
        insertion = make_stub_insertion(suggestion_id=sid)
        assert card.suggestion_id == insertion.suggestion_id

    def test_suggestion_id_in_render_dict(self) -> None:
        card = make_stub_body_card(suggestion_id="sugg-xyz")
        d = card.as_render_dict()
        assert d["data_suggestion_id"] == "sugg-xyz"

    def test_suggestion_id_required(self) -> None:
        with pytest.raises(ValueError, match="suggestion_id is required"):
            SuggestionCard(
                suggestion_id="",
                variant="body",
                title="title",
                preview_text="text",
            )

    def test_title_required(self) -> None:
        with pytest.raises(ValueError, match="title is required"):
            SuggestionCard(
                suggestion_id="s1",
                variant="body",
                title="",
                preview_text="text",
            )

    def test_unknown_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown SuggestionCard variant"):
            SuggestionCard(
                suggestion_id="s1",
                variant="unknown",
                title="title",
                preview_text="text",
            )

    def test_all_variants_defined(self) -> None:
        assert CARD_VARIANTS == {"body", "governance", "blocked"}


# ---------------------------------------------------------------------------
# Boundary: no Canvas Core / Panel / runtime coupling
# ---------------------------------------------------------------------------

class TestNoBoundaryCrossing:
    def test_no_canvas_core_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggestion_card as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggestion_card as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src

    def test_no_vault_write(self) -> None:
        import companion_ui.canvas_suggestion_flow.suggestion_card as mod
        src = open(mod.__file__).read()
        assert "WriteGuard" not in src
        # canvas_writer may appear in docstring explanation; ensure it is not imported
        assert "import canvas_writer" not in src
        assert "canvas_writer." not in src


# ---------------------------------------------------------------------------
# Top-level AC entry points — exact Verify: targets from issue #868
# ---------------------------------------------------------------------------

def test_suggestion_card_body_variant_renders_apply_button() -> None:
    """AC: body variant renders Apply button (suggestion.apply intent)."""
    TestSuggestionCardBodyVariant().test_suggestion_card_body_variant_renders_apply_button()


def test_governance_variant_has_no_apply_button() -> None:
    """AC: governance variant has no Apply button in DOM."""
    t = TestGovernanceVariantHasNoApplyButton()
    t.test_governance_variant_has_no_apply_button()
    t.test_governance_render_dict_no_apply()


def test_blocked_variant_is_alert_role() -> None:
    """AC: blocked variant carries role='alert' and denial reason."""
    t = TestBlockedVariantIsAlertRole()
    t.test_blocked_variant_is_alert_role()
    t.test_blocked_variant_carries_denial_reason()


def test_suggestion_id_consistency() -> None:
    """AC: data-suggestion-id matches between card and SuggestedInsertion block."""
    TestSuggestionIdConsistency().test_suggestion_id_consistency()
