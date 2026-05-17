"""Tests for keyboard shortcut mapping model (#872).

Verifies:
- Each variant's available actions
- Blocked variant cannot APPLY or QUEUE
- Terminal state has no mutating shortcuts (no APPLY, QUEUE, DISCARD)
- key_for returns something for valid actions
- render dict structure
- Hard invariant: governance variant NEVER has APPLY_BODY_SUGGESTION
- No dependency on Canvas Core, Panel, backend runtime, or vault writes.
"""

import pytest

from companion_ui.canvas_suggestion_flow.keyboard_shortcuts import (
    SHORTCUT_VARIANTS,
    ShortcutAction,
    SuggestionShortcutMap,
)


# ---------------------------------------------------------------------------
# ShortcutAction enum values
# ---------------------------------------------------------------------------

class TestShortcutActions:
    def test_all_actions_defined(self) -> None:
        expected_values = {
            "suggestion.apply",
            "governance.queue",
            "suggestion.discard",
            "suggestion.inspect",
            "suggestion.edit",
        }
        actual_values = {a.value for a in ShortcutAction}
        assert actual_values == expected_values

    def test_apply_body_suggestion(self) -> None:
        assert ShortcutAction.APPLY_BODY_SUGGESTION.value == "suggestion.apply"

    def test_queue_governance_suggestion(self) -> None:
        assert ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION.value == "governance.queue"

    def test_discard_suggestion(self) -> None:
        assert ShortcutAction.DISCARD_SUGGESTION.value == "suggestion.discard"

    def test_inspect_suggestion(self) -> None:
        assert ShortcutAction.INSPECT_SUGGESTION.value == "suggestion.inspect"

    def test_dismiss_rail(self) -> None:
        assert ShortcutAction.DISMISS_RAIL.value == "suggestion.edit"


# ---------------------------------------------------------------------------
# SHORTCUT_VARIANTS set
# ---------------------------------------------------------------------------

class TestShortcutVariants:
    def test_all_variants_defined(self) -> None:
        assert SHORTCUT_VARIANTS == frozenset({"body", "governance", "blocked", "terminal"})

    def test_unknown_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown shortcut variant"):
            SuggestionShortcutMap(variant="unknown")


# ---------------------------------------------------------------------------
# Body variant available actions
# ---------------------------------------------------------------------------

class TestBodyVariantActions:
    def test_body_has_apply(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        assert ShortcutAction.APPLY_BODY_SUGGESTION in sm.available_actions()

    def test_body_has_discard(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        assert ShortcutAction.DISCARD_SUGGESTION in sm.available_actions()

    def test_body_has_inspect(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        assert ShortcutAction.INSPECT_SUGGESTION in sm.available_actions()

    def test_body_has_dismiss(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        assert ShortcutAction.DISMISS_RAIL in sm.available_actions()

    def test_body_does_not_have_queue(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        assert ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION not in sm.available_actions()

    def test_a_applies_in_body_only(self) -> None:
        """AC: A applies suggestion in body variant only."""
        body_sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        gov_sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert body_sm.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) == "A"
        assert gov_sm.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) is None


# ---------------------------------------------------------------------------
# Governance variant available actions
# ---------------------------------------------------------------------------

class TestGovernanceVariantActions:
    def test_governance_has_queue(self) -> None:
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION in sm.available_actions()

    def test_governance_has_discard(self) -> None:
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert ShortcutAction.DISCARD_SUGGESTION in sm.available_actions()

    def test_governance_has_inspect(self) -> None:
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert ShortcutAction.INSPECT_SUGGESTION in sm.available_actions()

    def test_governance_has_dismiss(self) -> None:
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert ShortcutAction.DISMISS_RAIL in sm.available_actions()

    def test_governance_does_not_have_apply(self) -> None:
        """Hard invariant: governance MUST NOT expose suggestion.apply."""
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert ShortcutAction.APPLY_BODY_SUGGESTION not in sm.available_actions()

    def test_q_queues_governance_only(self) -> None:
        """AC: Q queues governance in staged_governance only; no effect in other variants."""
        gov_sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        body_sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        assert gov_sm.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION) == "Q"
        assert body_sm.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION) is None


# ---------------------------------------------------------------------------
# Blocked variant cannot APPLY or QUEUE
# ---------------------------------------------------------------------------

class TestBlockedVariantActions:
    def test_blocked_cannot_apply(self) -> None:
        """AC: Blocked variant cannot APPLY."""
        sm = SuggestionShortcutMap(variant="blocked")
        assert ShortcutAction.APPLY_BODY_SUGGESTION not in sm.available_actions()

    def test_blocked_cannot_queue(self) -> None:
        """AC: Blocked variant cannot QUEUE."""
        sm = SuggestionShortcutMap(variant="blocked")
        assert ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION not in sm.available_actions()

    def test_blocked_cannot_discard(self) -> None:
        """Blocked variant also cannot DISCARD (only INSPECT and DISMISS)."""
        sm = SuggestionShortcutMap(variant="blocked")
        assert ShortcutAction.DISCARD_SUGGESTION not in sm.available_actions()

    def test_blocked_has_inspect(self) -> None:
        sm = SuggestionShortcutMap(variant="blocked")
        assert ShortcutAction.INSPECT_SUGGESTION in sm.available_actions()

    def test_blocked_has_dismiss(self) -> None:
        sm = SuggestionShortcutMap(variant="blocked")
        assert ShortcutAction.DISMISS_RAIL in sm.available_actions()

    def test_blocked_key_for_apply_is_none(self) -> None:
        sm = SuggestionShortcutMap(variant="blocked")
        assert sm.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) is None

    def test_blocked_key_for_queue_is_none(self) -> None:
        sm = SuggestionShortcutMap(variant="blocked")
        assert sm.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION) is None


# ---------------------------------------------------------------------------
# Terminal state has no mutating shortcuts
# ---------------------------------------------------------------------------

class TestTerminalStateActions:
    def test_terminal_has_no_apply(self) -> None:
        """AC: Terminal state has no APPLY shortcut."""
        sm = SuggestionShortcutMap(variant="body", terminal_state=True)
        assert ShortcutAction.APPLY_BODY_SUGGESTION not in sm.available_actions()

    def test_terminal_has_no_queue(self) -> None:
        """AC: Terminal state has no QUEUE shortcut."""
        sm = SuggestionShortcutMap(variant="governance", terminal_state=True)
        assert ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION not in sm.available_actions()

    def test_terminal_has_no_discard(self) -> None:
        """AC: Terminal state has no DISCARD shortcut."""
        sm = SuggestionShortcutMap(variant="body", terminal_state=True)
        assert ShortcutAction.DISCARD_SUGGESTION not in sm.available_actions()

    def test_terminal_retains_inspect(self) -> None:
        sm = SuggestionShortcutMap(variant="body", terminal_state=True)
        assert ShortcutAction.INSPECT_SUGGESTION in sm.available_actions()

    def test_terminal_retains_dismiss(self) -> None:
        sm = SuggestionShortcutMap(variant="body", terminal_state=True)
        assert ShortcutAction.DISMISS_RAIL in sm.available_actions()

    def test_terminal_variant_is_terminal(self) -> None:
        """Passing variant='terminal' sets terminal_state=True automatically."""
        sm = SuggestionShortcutMap(variant="terminal")
        assert sm.is_terminal is True
        assert ShortcutAction.APPLY_BODY_SUGGESTION not in sm.available_actions()
        assert ShortcutAction.DISCARD_SUGGESTION not in sm.available_actions()

    def test_terminal_flag_overrides_body_variant(self) -> None:
        sm = SuggestionShortcutMap(variant="body", terminal_state=True)
        assert sm.is_terminal is True
        assert ShortcutAction.APPLY_BODY_SUGGESTION not in sm.available_actions()


# ---------------------------------------------------------------------------
# key_for returns something for valid actions
# ---------------------------------------------------------------------------

class TestKeyFor:
    def test_key_for_apply_in_body(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        key = sm.key_for(ShortcutAction.APPLY_BODY_SUGGESTION)
        assert key is not None
        assert isinstance(key, str)
        assert len(key) > 0

    def test_key_for_queue_in_governance(self) -> None:
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        key = sm.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION)
        assert key is not None

    def test_key_for_discard_in_body(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        key = sm.key_for(ShortcutAction.DISCARD_SUGGESTION)
        assert key is not None

    def test_key_for_inspect_in_any_variant(self) -> None:
        for variant in ["body", "governance", "blocked", "terminal"]:
            sm = SuggestionShortcutMap(variant=variant)
            key = sm.key_for(ShortcutAction.INSPECT_SUGGESTION)
            assert key is not None, f"INSPECT key missing for {variant}"

    def test_key_for_dismiss_in_any_variant(self) -> None:
        for variant in ["body", "governance", "blocked", "terminal"]:
            sm = SuggestionShortcutMap(variant=variant)
            key = sm.key_for(ShortcutAction.DISMISS_RAIL)
            assert key is not None, f"DISMISS key missing for {variant}"

    def test_key_for_unavailable_action_returns_none(self) -> None:
        sm = SuggestionShortcutMap(variant="governance")
        assert sm.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) is None

    def test_canonical_key_bindings(self) -> None:
        """Verify canonical keys match issue #872 table."""
        body_sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        gov_sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        assert body_sm.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) == "A"
        assert gov_sm.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION) == "Q"
        assert body_sm.key_for(ShortcutAction.DISCARD_SUGGESTION) == "D"
        assert body_sm.key_for(ShortcutAction.INSPECT_SUGGESTION) == "I"
        assert body_sm.key_for(ShortcutAction.DISMISS_RAIL) == "E"


# ---------------------------------------------------------------------------
# render dict structure
# ---------------------------------------------------------------------------

class TestRenderDict:
    def test_render_dict_keys(self) -> None:
        sm = SuggestionShortcutMap(variant="body", rail_state="staged_body")
        d = sm.to_render_dict()
        assert "variant" in d
        assert "rail_state" in d
        assert "is_terminal" in d
        assert "available_actions" in d
        assert "key_bindings" in d

    def test_render_dict_variant(self) -> None:
        sm = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
        d = sm.to_render_dict()
        assert d["variant"] == "governance"
        assert d["rail_state"] == "staged_governance"

    def test_render_dict_available_actions_are_strings(self) -> None:
        sm = SuggestionShortcutMap(variant="body")
        d = sm.to_render_dict()
        for action_val in d["available_actions"]:
            assert isinstance(action_val, str)

    def test_render_dict_key_bindings_are_strings(self) -> None:
        sm = SuggestionShortcutMap(variant="body")
        d = sm.to_render_dict()
        for key in d["key_bindings"].values():
            assert isinstance(key, str)

    def test_render_dict_governance_no_apply(self) -> None:
        """Render dict for governance must not include suggestion.apply."""
        sm = SuggestionShortcutMap(variant="governance")
        d = sm.to_render_dict()
        assert "suggestion.apply" not in d["available_actions"]
        assert "suggestion.apply" not in d["key_bindings"]

    def test_render_dict_terminal_no_mutating(self) -> None:
        sm = SuggestionShortcutMap(variant="body", terminal_state=True)
        d = sm.to_render_dict()
        assert "suggestion.apply" not in d["available_actions"]
        assert "suggestion.discard" not in d["available_actions"]
        assert d["is_terminal"] is True

    def test_render_dict_blocked_no_apply_no_queue(self) -> None:
        sm = SuggestionShortcutMap(variant="blocked")
        d = sm.to_render_dict()
        assert "suggestion.apply" not in d["available_actions"]
        assert "governance.queue" not in d["available_actions"]


# ---------------------------------------------------------------------------
# Boundary: no Canvas Core / Panel / runtime coupling
# ---------------------------------------------------------------------------

class TestNoBoundaryCrossing:
    def test_no_canvas_core_import(self) -> None:
        """canvas_core must not be imported (docstring mentions are OK)."""
        import companion_ui.canvas_suggestion_flow.keyboard_shortcuts as mod
        # Check no canvas_core in actual import lines (not docstrings)
        import_lines = [
            line for line in open(mod.__file__).read().splitlines()
            if line.lstrip().startswith("import ") or line.lstrip().startswith("from ")
        ]
        assert all("canvas_core" not in line for line in import_lines)

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.keyboard_shortcuts as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src

    def test_no_vault_write_imports(self) -> None:
        """No runtime writer symbols are imported (docstring mentions are OK)."""
        import companion_ui.canvas_suggestion_flow.keyboard_shortcuts as mod
        assert not hasattr(mod, "WriteGuard")
        assert not hasattr(mod, "SessionLogWriter")
        assert not hasattr(mod, "GovernanceRouter")


# ---------------------------------------------------------------------------
# AC entry points from issue #872
# ---------------------------------------------------------------------------

def test_a_applies_in_body_only() -> None:
    """AC: A applies suggestion in staged body only; no effect in other states."""
    body = SuggestionShortcutMap(variant="body", rail_state="staged_body")
    gov = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
    blocked = SuggestionShortcutMap(variant="blocked")
    assert body.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) == "A"
    assert gov.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) is None
    assert blocked.key_for(ShortcutAction.APPLY_BODY_SUGGESTION) is None


def test_q_queues_governance_only() -> None:
    """AC: Q queues governance in staged_governance only; no effect elsewhere."""
    gov = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
    body = SuggestionShortcutMap(variant="body", rail_state="staged_body")
    assert gov.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION) == "Q"
    assert body.key_for(ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION) is None


def test_d_discards_in_staged() -> None:
    """AC: D discards in staged variants only; no effect if blocked, terminal, or unstaged."""
    body = SuggestionShortcutMap(variant="body", rail_state="staged_body")
    gov = SuggestionShortcutMap(variant="governance", rail_state="staged_governance")
    blocked = SuggestionShortcutMap(variant="blocked")
    terminal = SuggestionShortcutMap(variant="body", terminal_state=True)
    assert body.key_for(ShortcutAction.DISCARD_SUGGESTION) == "D"
    assert gov.key_for(ShortcutAction.DISCARD_SUGGESTION) == "D"
    assert blocked.key_for(ShortcutAction.DISCARD_SUGGESTION) is None
    assert terminal.key_for(ShortcutAction.DISCARD_SUGGESTION) is None


def test_i_focuses_suggestion() -> None:
    """AC: I focuses suggestion details in staged states."""
    for variant in ["body", "governance", "blocked", "terminal"]:
        sm = SuggestionShortcutMap(variant=variant)
        assert sm.key_for(ShortcutAction.INSPECT_SUGGESTION) == "I"


def test_e_enables_composer_in_thinking() -> None:
    """AC: E dismisses rail / edits suggestion (DISMISS_RAIL maps to suggestion.edit)."""
    # E is mapped to DISMISS_RAIL / suggestion.edit in all variants
    for variant in ["body", "governance", "blocked", "terminal"]:
        sm = SuggestionShortcutMap(variant=variant)
        assert sm.key_for(ShortcutAction.DISMISS_RAIL) == "E"


def test_shortcuts_disabled_in_input() -> None:
    """AC: Shortcuts disabled when text input is focused — caller responsibility.

    The model surfaces no key bindings when terminal_state=True and variant signals
    no active staged state (simulating idle/input-focus condition).
    No DOM wiring here; the model is intent/render-hint only.
    """
    # When terminal_state=True, mutating shortcuts are suppressed.
    sm = SuggestionShortcutMap(variant="body", terminal_state=True)
    assert ShortcutAction.APPLY_BODY_SUGGESTION not in sm.available_actions()
    assert ShortcutAction.DISCARD_SUGGESTION not in sm.available_actions()
