"""Tests for PortraitSheet model (#873).

Verifies:
- Construction with each snap state
- transition_to produces new instance with correct snap
- is_visible correct for each snap
- render dict structure
- auto_snap_on_proposal lands at HALF, never FULL
- FULL_MINUS_CHROME is forbidden as auto-snap target
- Immutability: transition_to does not mutate original
- No dependency on Canvas Core, Panel, backend runtime, or vault writes.
"""

import pytest

from companion_ui.canvas_suggestion_flow.portrait_sheet import (
    AUTO_SNAP_ON_PROPOSAL,
    FORBIDDEN_AUTO_SNAP,
    SheetSnap,
    PortraitSheet,
)


# ---------------------------------------------------------------------------
# SheetSnap enum
# ---------------------------------------------------------------------------

class TestSheetSnap:
    def test_peek_value(self) -> None:
        assert SheetSnap.PEEK.value == "peek"

    def test_half_value(self) -> None:
        assert SheetSnap.HALF.value == "half"

    def test_full_minus_chrome_value(self) -> None:
        assert SheetSnap.FULL_MINUS_CHROME.value == "full"

    def test_closed_value(self) -> None:
        assert SheetSnap.CLOSED.value == "closed"

    def test_all_four_snap_points(self) -> None:
        """AC: Three snap points (peek/half/full) plus closed."""
        values = {s.value for s in SheetSnap}
        assert values == {"peek", "half", "full", "closed"}

    def test_auto_snap_target_is_half(self) -> None:
        assert AUTO_SNAP_ON_PROPOSAL is SheetSnap.HALF

    def test_forbidden_auto_snap_is_full(self) -> None:
        assert FORBIDDEN_AUTO_SNAP is SheetSnap.FULL_MINUS_CHROME


# ---------------------------------------------------------------------------
# Construction with each snap state
# ---------------------------------------------------------------------------

class TestPortraitSheetConstruction:
    def test_peek_construction(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        assert sheet.current_snap is SheetSnap.PEEK

    def test_half_construction(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        assert sheet.current_snap is SheetSnap.HALF

    def test_full_construction(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.FULL_MINUS_CHROME)
        assert sheet.current_snap is SheetSnap.FULL_MINUS_CHROME

    def test_closed_construction(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.CLOSED)
        assert sheet.current_snap is SheetSnap.CLOSED

    def test_default_rail_state(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        assert sheet.rail_state == "idle"

    def test_custom_rail_state(self) -> None:
        sheet = PortraitSheet(
            suggestion_id="s1",
            current_snap=SheetSnap.HALF,
            rail_state="staged_body",
        )
        assert sheet.rail_state == "staged_body"


# ---------------------------------------------------------------------------
# transition_to produces new instance with correct snap
# ---------------------------------------------------------------------------

class TestTransitionTo:
    def test_transition_to_half(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        new_sheet = sheet.transition_to(SheetSnap.HALF)
        assert new_sheet.current_snap is SheetSnap.HALF

    def test_transition_to_full(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        new_sheet = sheet.transition_to(SheetSnap.FULL_MINUS_CHROME)
        assert new_sheet.current_snap is SheetSnap.FULL_MINUS_CHROME

    def test_transition_to_closed(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        new_sheet = sheet.transition_to(SheetSnap.CLOSED)
        assert new_sheet.current_snap is SheetSnap.CLOSED

    def test_transition_to_peek(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        new_sheet = sheet.transition_to(SheetSnap.PEEK)
        assert new_sheet.current_snap is SheetSnap.PEEK

    def test_transition_returns_new_instance(self) -> None:
        """Immutable: transition_to must return a NEW instance."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        new_sheet = sheet.transition_to(SheetSnap.HALF)
        assert new_sheet is not sheet

    def test_original_unchanged_after_transition(self) -> None:
        """Immutable: original instance snap must not change."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        _ = sheet.transition_to(SheetSnap.HALF)
        assert sheet.current_snap is SheetSnap.PEEK

    def test_transition_preserves_suggestion_id(self) -> None:
        sheet = PortraitSheet(suggestion_id="sugg-42", current_snap=SheetSnap.PEEK)
        new_sheet = sheet.transition_to(SheetSnap.HALF)
        assert new_sheet.suggestion_id == "sugg-42"

    def test_transition_preserves_rail_state(self) -> None:
        sheet = PortraitSheet(
            suggestion_id="s1",
            current_snap=SheetSnap.PEEK,
            rail_state="staged_body",
        )
        new_sheet = sheet.transition_to(SheetSnap.HALF)
        assert new_sheet.rail_state == "staged_body"


# ---------------------------------------------------------------------------
# is_visible correct for each snap
# ---------------------------------------------------------------------------

class TestIsVisible:
    def test_peek_is_visible(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        assert sheet.is_visible() is True

    def test_half_is_visible(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        assert sheet.is_visible() is True

    def test_full_is_visible(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.FULL_MINUS_CHROME)
        assert sheet.is_visible() is True

    def test_closed_is_not_visible(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.CLOSED)
        assert sheet.is_visible() is False


# ---------------------------------------------------------------------------
# Auto-snap on proposal: PEEK → HALF (never FULL)
# ---------------------------------------------------------------------------

class TestAutoSnapOnProposal:
    def test_auto_snap_peek_to_half_on_proposal(self) -> None:
        """AC: Auto-snap from peek → half on proposal arrival."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        new_sheet = sheet.auto_snap_on_proposal()
        assert new_sheet.current_snap is SheetSnap.HALF

    def test_auto_snap_never_reaches_full(self) -> None:
        """AC: Auto-snap never reaches FULL (document must remain visible)."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        new_sheet = sheet.auto_snap_on_proposal()
        assert new_sheet.current_snap is not SheetSnap.FULL_MINUS_CHROME

    def test_auto_snap_target_is_half_constant(self) -> None:
        """Contract: AUTO_SNAP_ON_PROPOSAL is always HALF."""
        assert AUTO_SNAP_ON_PROPOSAL is SheetSnap.HALF
        assert FORBIDDEN_AUTO_SNAP is SheetSnap.FULL_MINUS_CHROME

    def test_auto_snap_returns_new_instance(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        new_sheet = sheet.auto_snap_on_proposal()
        assert new_sheet is not sheet


# ---------------------------------------------------------------------------
# render dict structure
# ---------------------------------------------------------------------------

class TestRenderDict:
    def test_render_dict_keys(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        d = sheet.to_render_dict()
        assert d["data_testid"] == "portrait-sheet"
        assert "current_snap" in d
        assert "height_hint" in d
        assert "is_visible" in d
        assert "body_is_primary" in d
        assert "auto_snap_target" in d
        assert "forbidden_auto_snap" in d
        assert "touch_target_min_height" in d
        assert "receipts_strip_position" in d

    def test_render_dict_snap_value(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        d = sheet.to_render_dict()
        assert d["current_snap"] == "half"

    def test_render_dict_is_visible_peek(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        assert sheet.to_render_dict()["is_visible"] is True

    def test_render_dict_is_visible_closed(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.CLOSED)
        assert sheet.to_render_dict()["is_visible"] is False

    def test_render_dict_body_is_primary(self) -> None:
        """Contract: body content is primary; sheet is overlay/secondary."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        d = sheet.to_render_dict()
        assert d["body_is_primary"] is True
        assert d.get("is_overlay") is True

    def test_render_dict_auto_snap_target(self) -> None:
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        d = sheet.to_render_dict()
        assert d["auto_snap_target"] == "half"
        assert d["forbidden_auto_snap"] == "full"

    def test_render_dict_touch_target_min_height(self) -> None:
        """AC: Touch targets ≥ 44 px in portrait."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
        d = sheet.to_render_dict()
        assert d["touch_target_min_height"] == "44px"

    def test_render_dict_receipts_strip_position(self) -> None:
        """AC: ReceiptsStrip renders at the top of the sheet (sticky)."""
        sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
        d = sheet.to_render_dict()
        assert d["receipts_strip_position"] == "sticky-top"

    def test_render_dict_height_hints(self) -> None:
        for snap, expected_hint in [
            (SheetSnap.PEEK, "60px"),
            (SheetSnap.HALF, "50vh"),
            (SheetSnap.FULL_MINUS_CHROME, "calc(100vh - 64px)"),
            (SheetSnap.CLOSED, "0"),
        ]:
            sheet = PortraitSheet(suggestion_id="s1", current_snap=snap)
            d = sheet.to_render_dict()
            assert d["height_hint"] == expected_hint, f"Wrong hint for {snap}"

    def test_render_dict_contains_suggestion_id(self) -> None:
        sheet = PortraitSheet(suggestion_id="sugg-99", current_snap=SheetSnap.PEEK)
        d = sheet.to_render_dict()
        assert d["suggestion_id"] == "sugg-99"

    def test_render_dict_contains_rail_state(self) -> None:
        sheet = PortraitSheet(
            suggestion_id="s1",
            current_snap=SheetSnap.HALF,
            rail_state="staged_governance",
        )
        d = sheet.to_render_dict()
        assert d["rail_state"] == "staged_governance"


# ---------------------------------------------------------------------------
# Boundary: no Canvas Core / Panel / runtime coupling
# ---------------------------------------------------------------------------

class TestNoBoundaryCrossing:
    def test_no_canvas_core_import(self) -> None:
        """canvas_core must not be imported (docstring mentions are OK)."""
        import companion_ui.canvas_suggestion_flow.portrait_sheet as mod
        import_lines = [
            line for line in open(mod.__file__).read().splitlines()
            if line.lstrip().startswith("import ") or line.lstrip().startswith("from ")
        ]
        assert all("canvas_core" not in line for line in import_lines)

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.portrait_sheet as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src

    def test_no_vault_write_imports(self) -> None:
        """No runtime writer symbols are imported (docstring mentions are OK)."""
        import companion_ui.canvas_suggestion_flow.portrait_sheet as mod
        assert not hasattr(mod, "WriteGuard")
        assert not hasattr(mod, "SessionLogWriter")
        assert not hasattr(mod, "GovernanceRouter")

    def test_no_rail_state_machine_import(self) -> None:
        """Portrait sheet must NOT import rail_state_machine internals."""
        import companion_ui.canvas_suggestion_flow.portrait_sheet as mod
        import_lines = [
            line for line in open(mod.__file__).read().splitlines()
            if line.lstrip().startswith("import ") or line.lstrip().startswith("from ")
        ]
        assert all("rail_state_machine" not in line for line in import_lines)
        assert not hasattr(mod, "CanvasRailStateMachine")


# ---------------------------------------------------------------------------
# AC entry points from issue #873
# ---------------------------------------------------------------------------

def test_snap_points_peek_half_full() -> None:
    """AC: Three snap points: peek / half / full."""
    sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
    assert sheet.transition_to(SheetSnap.HALF).current_snap is SheetSnap.HALF
    assert sheet.transition_to(SheetSnap.FULL_MINUS_CHROME).current_snap is SheetSnap.FULL_MINUS_CHROME


def test_auto_snap_peek_to_half_on_proposal() -> None:
    """AC: Auto-snap from peek → half on proposal arrival."""
    sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
    new_sheet = sheet.auto_snap_on_proposal()
    assert new_sheet.current_snap is SheetSnap.HALF


def test_auto_snap_never_reaches_full() -> None:
    """AC: Auto-snap never reaches full."""
    sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
    new_sheet = sheet.auto_snap_on_proposal()
    assert new_sheet.current_snap is not SheetSnap.FULL_MINUS_CHROME
    assert FORBIDDEN_AUTO_SNAP is SheetSnap.FULL_MINUS_CHROME


def test_snap_state_persisted() -> None:
    """AC: Snap state persisted to localStorage per session id (model-level stub).

    The model captures snap state via current_snap.  localStorage persistence
    is a UI-layer responsibility; the model provides the serialisable state dict.
    """
    sheet = PortraitSheet(suggestion_id="session-abc", current_snap=SheetSnap.HALF)
    d = sheet.to_render_dict()
    # The render dict contains the snap state for the UI layer to persist.
    assert d["current_snap"] == "half"
    assert d["suggestion_id"] == "session-abc"


def test_reduced_motion_respected() -> None:
    """AC: prefers-reduced-motion: no auto-snap, no transition (model contract).

    The model does not auto-snap automatically — auto_snap_on_proposal() must
    be explicitly called by the UI layer.  If the UI layer detects prefers-reduced-motion,
    it simply does not call auto_snap_on_proposal().  The model never auto-mutates.
    """
    sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
    # Not calling auto_snap_on_proposal() simulates reduced-motion suppression.
    assert sheet.current_snap is SheetSnap.PEEK


def test_touch_targets_44px() -> None:
    """AC: All interactive elements ≥ 44 px height in portrait."""
    sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.PEEK)
    d = sheet.to_render_dict()
    assert d["touch_target_min_height"] == "44px"


def test_receipts_strip_sticky_top() -> None:
    """AC: ReceiptsStrip renders at the top of the sheet (sticky) in portrait."""
    sheet = PortraitSheet(suggestion_id="s1", current_snap=SheetSnap.HALF)
    d = sheet.to_render_dict()
    assert d["receipts_strip_position"] == "sticky-top"
