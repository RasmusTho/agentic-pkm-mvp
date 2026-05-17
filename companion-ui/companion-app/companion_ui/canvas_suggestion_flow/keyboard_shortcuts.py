"""Keyboard shortcut mapping model for the Canvas bounded suggestion rail (#872).

Scoped shortcuts active only when the rail is in a staged state awaiting user
action on a suggestion.  Shortcuts produce intent tokens / render hints only.

No DOM event listeners, no global hotkey registration, no runtime side effects.

Rules from issue #872:
- body variant: APPLY_BODY_SUGGESTION (A), DISCARD (D), INSPECT (I), DISMISS (E)
- governance variant: QUEUE_GOVERNANCE_SUGGESTION (Q), DISCARD (D), INSPECT (I), DISMISS (E)
- blocked variant: INSPECT (I), DISMISS_RAIL (E) only — cannot APPLY or QUEUE
- terminal state: no mutating shortcuts (no APPLY, QUEUE, DISCARD)

Hard invariants:
- APPLY_BODY_SUGGESTION is NEVER available for the governance variant.
- QUEUE_GOVERNANCE_SUGGESTION is NEVER available for the body variant.
- Blocked and terminal states cannot APPLY or QUEUE.
- Composer always has keyboard focus unless rail is in a staged state.
- Shortcuts do not fire if a text input is focused elsewhere (caller responsibility).

Boundary:
- No imports from companion_ui.canvas_core, companion_ui.panel, or any runtime writer.
- No vault writes, no event dispatch, no DOM interaction.
"""

from __future__ import annotations

from enum import Enum, unique
from typing import Optional


@unique
class ShortcutAction(Enum):
    """Available shortcut actions in the canvas suggestion rail."""

    APPLY_BODY_SUGGESTION = "suggestion.apply"
    QUEUE_GOVERNANCE_SUGGESTION = "governance.queue"
    DISCARD_SUGGESTION = "suggestion.discard"
    INSPECT_SUGGESTION = "suggestion.inspect"
    DISMISS_RAIL = "suggestion.edit"


# Canonical key bindings for each action (issue #872 table).
_ACTION_KEY: dict[ShortcutAction, str] = {
    ShortcutAction.APPLY_BODY_SUGGESTION:      "A",
    ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION: "Q",
    ShortcutAction.DISCARD_SUGGESTION:         "D",
    ShortcutAction.INSPECT_SUGGESTION:         "I",
    ShortcutAction.DISMISS_RAIL:               "E",
}

# Valid rail variant names accepted by SuggestionShortcutMap.
SHORTCUT_VARIANTS: frozenset[str] = frozenset({"body", "governance", "blocked", "terminal"})

# Actions available per variant when NOT in a terminal state.
# Hard invariant: governance variant MUST NOT include APPLY_BODY_SUGGESTION.
# Hard invariant: body variant MUST NOT include QUEUE_GOVERNANCE_SUGGESTION.
# Hard invariant: blocked variant MUST NOT include APPLY or QUEUE.
_VARIANT_ACTIONS: dict[str, frozenset[ShortcutAction]] = {
    "body": frozenset({
        ShortcutAction.APPLY_BODY_SUGGESTION,
        ShortcutAction.DISCARD_SUGGESTION,
        ShortcutAction.INSPECT_SUGGESTION,
        ShortcutAction.DISMISS_RAIL,
    }),
    "governance": frozenset({
        ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION,
        ShortcutAction.DISCARD_SUGGESTION,
        ShortcutAction.INSPECT_SUGGESTION,
        ShortcutAction.DISMISS_RAIL,
    }),
    "blocked": frozenset({
        ShortcutAction.INSPECT_SUGGESTION,
        ShortcutAction.DISMISS_RAIL,
    }),
    # "terminal" is handled separately: no mutating shortcuts regardless of other state.
    "terminal": frozenset({
        ShortcutAction.INSPECT_SUGGESTION,
        ShortcutAction.DISMISS_RAIL,
    }),
}

# Mutating actions — forbidden in terminal state and blocked variant.
_MUTATING_ACTIONS: frozenset[ShortcutAction] = frozenset({
    ShortcutAction.APPLY_BODY_SUGGESTION,
    ShortcutAction.QUEUE_GOVERNANCE_SUGGESTION,
    ShortcutAction.DISCARD_SUGGESTION,
})

# Rail states in which a suggestion is staged and awaiting user action.
# Mutating shortcuts (APPLY, QUEUE, DISCARD) are only offered when the rail
# is in one of these states — matches CANVAS_SUGGESTION_FLOW.md §States.
_STAGED_STATES: frozenset[str] = frozenset({"staged_body", "staged_governance"})


class SuggestionShortcutMap:
    """Keyboard shortcut map for the bounded suggestion rail.

    Takes a variant (body | governance | blocked | terminal) and an optional
    rail state string (pass-through from the rail state machine — not coupled
    to its internals beyond accepting a string).

    terminal_state — if True, all mutating shortcuts (APPLY, QUEUE, DISCARD) are
    suppressed regardless of variant.  This mirrors the terminal-presentation-state
    lock in the rail state machine.

    Shortcuts produce intent tokens / render hints only — no DOM wiring here.
    """

    def __init__(
        self,
        variant: str,
        rail_state: str = "idle",
        *,
        terminal_state: bool = False,
    ) -> None:
        if variant not in SHORTCUT_VARIANTS:
            raise ValueError(
                f"Unknown shortcut variant: {variant!r}. "
                f"Must be one of {sorted(SHORTCUT_VARIANTS)}."
            )
        self._variant = variant
        self._rail_state = rail_state
        self._terminal_state = terminal_state or (variant == "terminal")

    @property
    def variant(self) -> str:
        return self._variant

    @property
    def rail_state(self) -> str:
        return self._rail_state

    @property
    def is_terminal(self) -> bool:
        return self._terminal_state

    def available_actions(self) -> list[ShortcutAction]:
        """Return the list of available ShortcutActions for this variant/state.

        Mutating shortcuts (APPLY, QUEUE, DISCARD) are suppressed when:
        - the rail is in a terminal presentation state, OR
        - the rail_state is not a staged state (idle, thinking, apply_pending, etc.)

        Only INSPECT and DISMISS remain when shortcuts are gated out.
        """
        base = _VARIANT_ACTIONS[self._variant]
        if self._terminal_state or self._rail_state not in _STAGED_STATES:
            base = base - _MUTATING_ACTIONS
        return sorted(base, key=lambda a: a.value)

    def key_for(self, action: ShortcutAction) -> Optional[str]:
        """Return the key string for action if it is available, else None."""
        if action in self.available_actions():
            return _ACTION_KEY[action]
        return None

    def to_render_dict(self) -> dict:
        """Serialisable dict for the UI layer.

        Contains the variant, rail state, terminal flag, and a mapping of
        available action intent tokens to their key bindings.  The UI layer
        uses this to render keyboard shortcut hints and to gate intent dispatch.
        """
        actions = self.available_actions()
        bindings = {a.value: _ACTION_KEY[a] for a in actions}
        return {
            "variant": self._variant,
            "rail_state": self._rail_state,
            "is_terminal": self._terminal_state,
            "available_actions": [a.value for a in actions],
            "key_bindings": bindings,
        }
