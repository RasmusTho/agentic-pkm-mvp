"""Portrait/mobile bottom sheet model for the bounded suggestion rail (#873).

At viewport widths < 900 px, the Hugin rail becomes a bottom sheet replacing
the side rail.  This module models the snap state and transition rules without
any CSS, React, DOM, localStorage, or gesture handling.

Snap points (from issue #873 §Snap points):
  PEEK             60 px  Default / collapsed; shows Hugin dot + turn count.
  HALF             50vh   Expanded conversation; document still visible above.
  FULL_MINUS_CHROME calc(100vh - 64px)  Full conversation.
  CLOSED           Not visible at all.

Auto-snap rule (contract §873):
  When a proposal arrives (state → staged-body or staged-gov), the sheet
  auto-snaps from PEEK → HALF.  Auto-snap to FULL_MINUS_CHROME is FORBIDDEN —
  the document must remain visible at the insertion point.

Body remains primary; the sheet is an overlay/secondary surface.

Immutable transition model: transition_to() returns a NEW PortraitSheet
instance rather than mutating state in place.

Boundary:
  - No CSS, React, DOM, localStorage, or gesture handling.
  - No imports from companion_ui.canvas_core, companion_ui.panel, or runtime writers.
  - No vault writes, no watcher code, no backend API calls.
  - rail_state is accepted as a plain string (pass-through from the rail state
    machine) — no import coupling to rail_state_machine.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique


@unique
class SheetSnap(Enum):
    """Snap points for the portrait bottom sheet.

    Ordering reflects sheet height from smallest to largest, excluding CLOSED.
    """

    PEEK = "peek"
    HALF = "half"
    FULL_MINUS_CHROME = "full"
    CLOSED = "closed"


# Auto-snap policy: auto-snap target when a proposal arrives.
# FULL_MINUS_CHROME is the forbidden auto-snap target (document must stay visible).
AUTO_SNAP_ON_PROPOSAL: SheetSnap = SheetSnap.HALF
FORBIDDEN_AUTO_SNAP: SheetSnap = SheetSnap.FULL_MINUS_CHROME

# Height hints (design reference — not CSS; caller uses these as hints).
_SNAP_HEIGHT_HINT: dict[SheetSnap, str] = {
    SheetSnap.PEEK:             "60px",
    SheetSnap.HALF:             "50vh",
    SheetSnap.FULL_MINUS_CHROME: "calc(100vh - 64px)",
    SheetSnap.CLOSED:           "0",
}


@dataclass(frozen=True)
class PortraitSheet:
    """Immutable render model for the portrait bottom sheet.

    suggestion_id  — the active suggestion this sheet is presenting.
    current_snap   — current snap point (SheetSnap enum).
    rail_state     — pass-through from rail state machine (plain string,
                     no import coupling to rail_state_machine internals).

    Body content remains primary; the sheet is an overlay/secondary surface.
    All interactive elements should be ≥ 44 px height in portrait (touch targets).

    Use transition_to() to obtain a new instance with an updated snap point.
    """

    suggestion_id: str
    current_snap: SheetSnap
    rail_state: str = "idle"

    def transition_to(self, snap: SheetSnap) -> "PortraitSheet":
        """Return a new PortraitSheet with current_snap set to snap.

        Immutable: this instance is unchanged.
        """
        return PortraitSheet(
            suggestion_id=self.suggestion_id,
            current_snap=snap,
            rail_state=self.rail_state,
        )

    def auto_snap_on_proposal(self) -> "PortraitSheet":
        """Return a new PortraitSheet auto-snapped to HALF on proposal arrival.

        Implements the contract: auto-snap from PEEK → HALF when a proposal
        arrives.  FULL_MINUS_CHROME is forbidden as an auto-snap target.
        """
        return self.transition_to(AUTO_SNAP_ON_PROPOSAL)

    def is_visible(self) -> bool:
        """True unless current_snap is CLOSED."""
        return self.current_snap is not SheetSnap.CLOSED

    def height_hint(self) -> str:
        """Design-reference height string for the current snap point."""
        return _SNAP_HEIGHT_HINT[self.current_snap]

    def to_render_dict(self) -> dict:
        """Serialisable dict for the UI layer.

        The dict carries rendering hints for the sheet component:
        - current_snap: snap point enum value string
        - height_hint: design reference height
        - is_visible: whether the sheet is shown
        - body_is_primary: True — document body is always the primary surface;
          this sheet is overlay/secondary
        - auto_snap_target: the permitted auto-snap target (always HALF)
        - forbidden_auto_snap: auto-snap to FULL is forbidden (document must stay visible)
        - touch_target_min_height: minimum interactive element height (44px, §873 contract)
        - receipts_strip_position: sticky top (ReceiptsStrip renders at top of sheet)
        """
        return {
            "data_testid": "portrait-sheet",
            "suggestion_id": self.suggestion_id,
            "rail_state": self.rail_state,
            "current_snap": self.current_snap.value,
            "height_hint": self.height_hint(),
            "is_visible": self.is_visible(),
            "body_is_primary": True,
            "is_overlay": True,
            "auto_snap_target": AUTO_SNAP_ON_PROPOSAL.value,
            "forbidden_auto_snap": FORBIDDEN_AUTO_SNAP.value,
            "touch_target_min_height": "44px",
            "receipts_strip_position": "sticky-top",
        }
