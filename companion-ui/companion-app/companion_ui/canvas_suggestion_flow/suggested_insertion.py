"""SuggestedInsertion in-document preview marker model (#869).

Represents the <ins> element placed inline at the insertion anchor while a
body-edit proposal is staged.  Tracks the three lifecycle states defined in
CANVAS_SUGGESTION_FLOW.md:

  staged    — Amber left-border; label "PROPOSED · UNCOMMITTED".
  applied   — Vault-green left-border; label "APPLIED · <receipt-id>".
  discarded — Element removed from DOM (display:none / not rendered).

Only rendered for body-edit proposals.  Governance proposals do not produce a
SuggestedInsertion (no in-document preview for governance mutations).

This model does not write to the vault.  canvas_writer owns durable writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

INSERTION_STATES: frozenset[str] = frozenset({"staged", "applied", "discarded"})

# CSS class and colour-hint tokens (design guidance).
_STATE_COLOR_HINT: dict[str, Optional[str]] = {
    "staged":    "amber",
    "applied":   "vault-green",
    "discarded": None,
}

_STATE_LABEL: dict[str, str] = {
    "staged":    "PROPOSED · UNCOMMITTED",
    "applied":   "APPLIED",       # caller appends · <receipt-id>
    "discarded": "",
}

# Allowed state transitions for the insertion block.
_LEGAL_INSERTION_TRANSITIONS: dict[str, frozenset[str]] = {
    "staged":    frozenset({"applied", "discarded"}),
    "applied":   frozenset(),
    "discarded": frozenset(),
}


@dataclass
class SuggestedInsertion:
    """Render model for the inline in-document preview marker.

    suggestion_id must match the paired SuggestionCard's suggestion_id.
    anchor_description describes the insertion point (e.g. "3 lines after ## Summary").
    proposed_text is the full text to be inserted.
    receipt_id is populated on apply; empty string otherwise.
    """

    suggestion_id: str
    anchor_description: str
    proposed_text: str
    _state: str = "staged"
    _receipt_id: str = ""

    def __post_init__(self) -> None:
        if not self.suggestion_id:
            raise ValueError("suggestion_id is required")
        if not self.anchor_description:
            raise ValueError("anchor_description is required for aria-label")
        if not self.proposed_text:
            raise ValueError("proposed_text is required")
        if self._state not in INSERTION_STATES:
            raise ValueError(f"Unknown SuggestedInsertion state: {self._state!r}")

    @property
    def state(self) -> str:
        return self._state

    @property
    def receipt_id(self) -> str:
        return self._receipt_id

    @property
    def color_hint(self) -> Optional[str]:
        return _STATE_COLOR_HINT[self._state]

    @property
    def label(self) -> str:
        if self._state == "applied" and self._receipt_id:
            return f"APPLIED · {self._receipt_id}"
        return _STATE_LABEL[self._state]

    @property
    def aria_label(self) -> str:
        return f"Proposed insertion, {self.anchor_description}"

    @property
    def is_visible(self) -> bool:
        """False when discarded — element should be removed/hidden from DOM."""
        return self._state != "discarded"

    def apply(self, receipt_id: str = "") -> None:
        """Transition staged → applied, populating receipt_id."""
        if "applied" not in _LEGAL_INSERTION_TRANSITIONS[self._state]:
            raise ValueError(
                f"Cannot apply SuggestedInsertion from state {self._state!r}"
            )
        self._state = "applied"
        self._receipt_id = receipt_id

    def discard(self) -> None:
        """Transition staged → discarded."""
        if "discarded" not in _LEGAL_INSERTION_TRANSITIONS[self._state]:
            raise ValueError(
                f"Cannot discard SuggestedInsertion from state {self._state!r}"
            )
        self._state = "discarded"

    def as_render_dict(self) -> dict:
        """Serialisable dict for the UI layer (maps to <ins> element attributes)."""
        return {
            "element": "ins",
            "css_class": "suggested-insertion",
            "data_testid": "suggested-insertion-block",
            "data_suggestion_id": self.suggestion_id,
            "data_state": self._state,
            "data_receipt": self._receipt_id,
            "aria_label": self.aria_label,
            "color_hint": self.color_hint,
            "label": self.label,
            "proposed_text": self.proposed_text,
            "is_visible": self.is_visible,
        }


def make_stub_insertion(
    suggestion_id: str = "sugg-001",
    anchor_description: str = "3 lines after ## Summary",
    proposed_text: str = "The project has entered the active phase.\n",
) -> SuggestedInsertion:
    """Stub SuggestedInsertion in staged state for testing."""
    return SuggestedInsertion(
        suggestion_id=suggestion_id,
        anchor_description=anchor_description,
        proposed_text=proposed_text,
    )
