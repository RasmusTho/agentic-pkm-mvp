"""Canvas Core governance-bearing escape hatch routing (#1029).

When a Canvas co-authoring session encounters a governance-bearing operation,
the operation must not be applied directly through the Canvas body-edit path.
This module classifies the operation and produces a routing decision so the
caller can surface blocked/routed status without pretending the action was applied.

Route targets:
  "panel"                   — artifact-local intent manifestation (Panel surface,
                              #995/#996/#1019); for lifecycle/maturity/commitment decisions.
  "canvas_bounded_suggestion" — Canvas bounded suggestion queue (#868–#874);
                              for frontmatter/classification adjacent to body content.
  "governed_execution"      — runtime governed execution boundary; for system-owned
                              artifacts (receipts, session logs, companion notes, cross-note ops).

Ambiguous or unrecognised edit classes default to governance-bearing and are
routed to governed_execution.

This module does NOT:
  - implement Panel UI,
  - implement Canvas bounded suggestion components,
  - execute governance-bearing mutations,
  - import or couple to staging-prototype files or staged-proposal concepts.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Governance-bearing edit class registry
# ---------------------------------------------------------------------------

# All classes that are governance-bearing and must not pass through the
# Canvas direct body-edit path.  Extends the body_edit.GOVERNANCE_BEARING_EDIT_CLASSES
# set with additional classes that require escape-hatch routing.
GOVERNANCE_BEARING_CLASSES: frozenset[str] = frozenset(
    {
        "frontmatter",
        "classification",
        "cross_note",
        "lifecycle",
        "promotion",
        "commitment_state",
        "companion_note",
        "receipt",
        "session_log",
        "system_artifact",
    }
)

# Classes that indicate the operation is non-governance-bearing (safe for direct body edit).
# Any class not in this set and not in GOVERNANCE_BEARING_CLASSES is treated as
# ambiguous and defaults to governance-bearing.
SAFE_EDIT_CLASSES: frozenset[str] = frozenset({"body"})

# ---------------------------------------------------------------------------
# Route target registry
# ---------------------------------------------------------------------------

# Routing heuristic for governance-bearing classes:
#   Panel:                    artifact-local intent/lifecycle decisions.
#   canvas_bounded_suggestion: frontmatter/classification, adjacent to body editing.
#   governed_execution:        system-owned artifacts, cross-note, and all ambiguous cases.

_PANEL_CLASSES: frozenset[str] = frozenset({"lifecycle", "promotion", "commitment_state"})
_CANVAS_SUGGESTION_CLASSES: frozenset[str] = frozenset({"frontmatter", "classification"})
# Everything else → governed_execution (includes cross_note, companion_note, receipt,
# session_log, system_artifact, and any unrecognised class).

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscapeHatchResult:
    """Classification and routing decision for a governance-bearing operation.

    Callers must surface this status to the user.  The action is NOT applied;
    this result declares what happened and where the request should go.
    """

    edit_class: str
    is_governance_bearing: bool
    route_target: str  # "panel" | "canvas_bounded_suggestion" | "governed_execution"
    status_message: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class CanvasEscapeHatchRouter:
    """Routes governance-bearing Canvas operations to the appropriate governed path.

    Usage:
        router = CanvasEscapeHatchRouter()
        result = router.route("lifecycle")
        # result.is_governance_bearing → True
        # result.route_target → "panel"
        # result.status_message → human-readable blocked/routed explanation
    """

    def route(self, edit_class: str) -> EscapeHatchResult:
        """Classify an operation and return the routing decision.

        A non-governance-bearing class (e.g., "body") returns a result where
        is_governance_bearing is False and route_target is "none" — callers
        may proceed with the direct body-edit path.

        An unrecognised class is treated as ambiguous and defaults to
        governance-bearing (governed_execution route).
        """
        if edit_class in SAFE_EDIT_CLASSES:
            return EscapeHatchResult(
                edit_class=edit_class,
                is_governance_bearing=False,
                route_target="none",
                status_message=f"Edit class {edit_class!r} is safe for direct Canvas body-edit.",
            )

        is_governance_bearing = True
        route_target = self._resolve_route(edit_class)
        status_message = self._build_status_message(edit_class, route_target)

        return EscapeHatchResult(
            edit_class=edit_class,
            is_governance_bearing=is_governance_bearing,
            route_target=route_target,
            status_message=status_message,
        )

    def is_governance_bearing(self, edit_class: str) -> bool:
        """Return True if the edit class is governance-bearing or ambiguous."""
        return edit_class not in SAFE_EDIT_CLASSES

    def _resolve_route(self, edit_class: str) -> str:
        if edit_class in _PANEL_CLASSES:
            return "panel"
        if edit_class in _CANVAS_SUGGESTION_CLASSES:
            return "canvas_bounded_suggestion"
        return "governed_execution"

    def _build_status_message(self, edit_class: str, route_target: str) -> str:
        descriptions = {
            "panel": "routed to Panel for artifact-local intent confirmation",
            "canvas_bounded_suggestion": (
                "routed to Canvas bounded suggestion queue for staged review"
            ),
            "governed_execution": (
                "routed to governed execution boundary — direct mutation blocked"
            ),
        }
        description = descriptions.get(route_target, "blocked from direct Canvas body-edit path")
        return (
            f"Operation class {edit_class!r} is governance-bearing and was blocked from "
            f"the Canvas direct body-edit path: {description}."
        )


__all__ = [
    "GOVERNANCE_BEARING_CLASSES",
    "SAFE_EDIT_CLASSES",
    "CanvasEscapeHatchRouter",
    "EscapeHatchResult",
]
