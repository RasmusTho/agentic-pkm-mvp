"""Tests for Canvas Core governance-bearing escape hatch routing (#1029).

These tests verify that governance-bearing edit classes are classified correctly,
blocked from the direct body-edit path, routed to the appropriate governed surface,
and that the module does not couple to Canvas bounded suggestion flow internals.

ACs from #1029:
- test_frontmatter_change_routes_to_governed_path
- test_cross_note_operation_routes_to_governed_path
- test_lifecycle_operation_routes_to_governed_path
- test_system_artifact_operation_blocked_from_canvas_core
- test_ambiguous_operation_defaults_to_governance_bearing
- test_escape_hatch_status_visible
- test_escape_hatch_preserves_surface_distinctions
"""

import pytest

from companion_ui.canvas_core.escape_hatch import (
    GOVERNANCE_BEARING_CLASSES,
    CanvasEscapeHatchRouter,
    EscapeHatchResult,
)


# ---------------------------------------------------------------------------
# AC: frontmatter/classification changes are rejected from direct path and routed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("edit_class", ["frontmatter", "classification"])
def test_frontmatter_change_routes_to_governed_path(edit_class: str) -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route(edit_class)

    assert isinstance(result, EscapeHatchResult)
    assert result.is_governance_bearing is True
    assert result.route_target in ("canvas_bounded_suggestion", "panel", "governed_execution")
    assert result.route_target != "none"
    assert result.status_message
    assert edit_class in GOVERNANCE_BEARING_CLASSES


# ---------------------------------------------------------------------------
# AC: cross-note operations are rejected from direct path and routed
# ---------------------------------------------------------------------------


def test_cross_note_operation_routes_to_governed_path() -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route("cross_note")

    assert result.is_governance_bearing is True
    assert result.route_target == "governed_execution"
    assert "cross_note" in GOVERNANCE_BEARING_CLASSES


# ---------------------------------------------------------------------------
# AC: note lifecycle operations are rejected from direct path and routed
# ---------------------------------------------------------------------------


def test_lifecycle_operation_routes_to_governed_path() -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route("lifecycle")

    assert result.is_governance_bearing is True
    assert result.route_target == "panel"


@pytest.mark.parametrize("edit_class", ["promotion", "commitment_state"])
def test_lifecycle_adjacent_routes_to_panel(edit_class: str) -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route(edit_class)

    assert result.is_governance_bearing is True
    assert result.route_target == "panel"


# ---------------------------------------------------------------------------
# AC: companion note, receipt, and system artifact operations are blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit_class",
    ["companion_note", "receipt", "system_artifact", "session_log"],
)
def test_system_artifact_operation_blocked_from_canvas_core(edit_class: str) -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route(edit_class)

    assert result.is_governance_bearing is True
    assert result.route_target == "governed_execution"
    assert edit_class in GOVERNANCE_BEARING_CLASSES


# ---------------------------------------------------------------------------
# AC: ambiguous operations default to governance-bearing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit_class",
    ["unknown_class", "future_class_not_yet_defined", "", "some_ambiguous_op"],
)
def test_ambiguous_operation_defaults_to_governance_bearing(edit_class: str) -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route(edit_class)

    assert result.is_governance_bearing is True, (
        f"Ambiguous edit class {edit_class!r} must default to governance-bearing"
    )
    assert result.route_target == "governed_execution"
    assert result.status_message


def test_safe_body_edit_is_not_governance_bearing() -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route("body")

    assert result.is_governance_bearing is False
    assert result.route_target == "none"


# ---------------------------------------------------------------------------
# AC: routed/blocked status is visible and does not claim the action was applied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("edit_class", sorted(GOVERNANCE_BEARING_CLASSES))
def test_escape_hatch_status_visible(edit_class: str) -> None:
    router = CanvasEscapeHatchRouter()
    result = router.route(edit_class)

    assert result.status_message, "status_message must be non-empty"
    # These phrases positively claim the action was applied — must not appear.
    positive_applied_phrases = (
        "successfully applied",
        "action was applied",
        "has been applied",
        "mutation was applied",
        "edit was applied",
        "change was applied",
    )
    lower_msg = result.status_message.lower()
    for phrase in positive_applied_phrases:
        assert phrase not in lower_msg, (
            f"status_message must not claim the action was applied; got: {result.status_message!r}"
        )


# ---------------------------------------------------------------------------
# AC: routing boundary preserves distinction between Panel, Canvas bounded
#     suggestion flow, and governed execution
# ---------------------------------------------------------------------------


def test_escape_hatch_preserves_surface_distinctions() -> None:
    router = CanvasEscapeHatchRouter()

    panel_result = router.route("lifecycle")
    suggestion_result = router.route("frontmatter")
    governed_result = router.route("cross_note")

    assert panel_result.route_target == "panel"
    assert suggestion_result.route_target == "canvas_bounded_suggestion"
    assert governed_result.route_target == "governed_execution"

    # All three targets are distinct.
    targets = {panel_result.route_target, suggestion_result.route_target, governed_result.route_target}
    assert len(targets) == 3, "All three route targets must be distinct"


def test_escape_hatch_does_not_reference_suggestion_flow_internals() -> None:
    """Escape hatch module must not couple to Canvas bounded suggestion flow internals."""
    import inspect
    from companion_ui.canvas_core import escape_hatch as mod

    src = inspect.getsource(mod)
    # The staging prototype HTML file must not be imported or referenced.
    assert "canvas_suggestion_flow.html" not in src
    assert "staged_body" not in src
    assert "staged_governance" not in src
    assert "SuggestionDiscard" not in src
    assert "discard_suggestion" not in src
