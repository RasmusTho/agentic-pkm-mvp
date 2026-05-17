"""SuggestionCard render model for the Canvas bounded suggestion flow (#868).

Three variants driven by server-declared proposal class:
  body       — body-edit proposal; Apply + Discard + Inspect.
  governance — governance-bearing proposal; Queue + Discard + Inspect; NO Apply.
  blocked    — CANVAS_ENABLED=0 or write-guard; Acknowledge only; role="alert".

Hard invariant: the governance variant MUST NOT expose the suggestion.apply intent.
The UI never re-classifies the server-declared variant.

This model does not call canvas_writer, GovernanceRouter, or session_log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CARD_VARIANTS: frozenset[str] = frozenset({"body", "governance", "blocked"})

# Intent tokens per variant. Canonical names from CANVAS_SUGGESTION_FLOW.md §data-intent.
_BODY_INTENTS: tuple[str, ...] = ("suggestion.apply", "suggestion.discard", "suggestion.inspect")
_GOVERNANCE_INTENTS: tuple[str, ...] = ("governance.queue", "suggestion.discard", "suggestion.inspect")
_BLOCKED_INTENTS: tuple[str, ...] = ("blocked.acknowledge",)

# data-testid tokens for primary action buttons.
_BODY_TESTIDS: dict[str, str] = {
    "suggestion.apply":   "apply-suggestion",
    "suggestion.discard": "discard-suggestion",
}
_GOVERNANCE_TESTIDS: dict[str, str] = {
    "governance.queue":   "queue-governance",
    "suggestion.discard": "discard-suggestion",
}

# Colour hint tokens (design guidance, not hard contract).
_VARIANT_COLOR_HINT: dict[str, str] = {
    "body":       "amber",
    "governance": "gold",
    "blocked":    "neutral",
}

# ARIA role override for the blocked variant (§Contracts).
_VARIANT_ARIA_ROLE: dict[str, Optional[str]] = {
    "body":       None,
    "governance": None,
    "blocked":    "alert",
}

# Governance classification notice text (design reference copy).
_GOVERNANCE_CLASSIFICATION_NOTICE = (
    "Cannot be applied from chat — must be queued."
)


@dataclass
class SuggestionCard:
    """Render model for a single SuggestionCard in the rail thread.

    suggestion_id must match the data-suggestion-id on the paired SuggestedInsertion.
    variant is server-declared; this model does not change it.
    denial_reason is required for the blocked variant (surfaced in aria-describedby).
    """

    suggestion_id: str
    variant: str
    title: str
    preview_text: str
    denial_reason: Optional[str] = None
    _intents: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.suggestion_id:
            raise ValueError("suggestion_id is required")
        if self.variant not in CARD_VARIANTS:
            raise ValueError(f"Unknown SuggestionCard variant: {self.variant!r}")
        if not self.title:
            raise ValueError("title is required for user-facing display")
        if self.variant == "blocked" and not self.denial_reason:
            raise ValueError("denial_reason is required for the blocked variant")
        if self.variant == "governance":
            object.__setattr__(self, "_intents", _GOVERNANCE_INTENTS)
        elif self.variant == "body":
            object.__setattr__(self, "_intents", _BODY_INTENTS)
        else:
            object.__setattr__(self, "_intents", _BLOCKED_INTENTS)

    @property
    def available_intents(self) -> tuple[str, ...]:
        """Intent tokens available for this card variant."""
        return self._intents

    @property
    def has_apply_intent(self) -> bool:
        """True only for body variant; governance and blocked must return False."""
        return "suggestion.apply" in self._intents

    @property
    def aria_role(self) -> Optional[str]:
        return _VARIANT_ARIA_ROLE[self.variant]

    @property
    def color_hint(self) -> str:
        return _VARIANT_COLOR_HINT[self.variant]

    @property
    def classification_notice(self) -> Optional[str]:
        return _GOVERNANCE_CLASSIFICATION_NOTICE if self.variant == "governance" else None

    def as_render_dict(self) -> dict:
        """Serialisable dict for the UI layer."""
        d: dict = {
            "data_testid": "suggestion-card",
            "data_variant": self.variant,
            "data_suggestion_id": self.suggestion_id,
            "title": self.title,
            "preview_text": self.preview_text,
            "color_hint": self.color_hint,
            "available_intents": list(self._intents),
            "aria_role": self.aria_role,
        }
        if self.variant == "governance":
            d["classification_notice"] = self.classification_notice
            d["data_testid_classification"] = "suggestion-card-classification"
        if self.variant == "blocked":
            d["denial_reason"] = self.denial_reason
        return d


def make_stub_body_card(
    suggestion_id: str = "sugg-001",
    title: str = "Add summary paragraph",
    preview_text: str = "The project has entered...",
) -> SuggestionCard:
    """Stub body-variant SuggestionCard for testing."""
    return SuggestionCard(
        suggestion_id=suggestion_id,
        variant="body",
        title=title,
        preview_text=preview_text,
    )


def make_stub_governance_card(
    suggestion_id: str = "sugg-002",
    title: str = "Move note to Projects",
    preview_text: str = "lifecycle.move → Projects/",
) -> SuggestionCard:
    """Stub governance-variant SuggestionCard for testing."""
    return SuggestionCard(
        suggestion_id=suggestion_id,
        variant="governance",
        title=title,
        preview_text=preview_text,
    )


def make_stub_blocked_card(
    suggestion_id: str = "sugg-003",
    title: str = "Edit blocked",
    preview_text: str = "CANVAS_ENABLED=0",
    denial_reason: str = "Canvas writes are currently disabled.",
) -> SuggestionCard:
    """Stub blocked-variant SuggestionCard for testing."""
    return SuggestionCard(
        suggestion_id=suggestion_id,
        variant="blocked",
        title=title,
        preview_text=preview_text,
        denial_reason=denial_reason,
    )
