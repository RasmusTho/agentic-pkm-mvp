"""ReceiptPill and ReceiptsStrip display models for the Canvas bounded suggestion flow (#871).

ReceiptPill — inline pill rendered in the conversation thread when a governance
intent is queued.  Links to Panel via the governance.openReceipt intent.

ReceiptsStrip — sticky strip at the bottom of the rail listing non-terminal
pending governance receipts for the session.  Has aria-live="polite" so
upstream status transitions are announced.

Receipts are display/status objects only.

Boundary invariants:
- These models MUST NOT write to the vault.
- These models MUST NOT call GovernanceRouter, SessionLogWriter, WriteGuard,
  or any runtime writer.
- Body-edit applies do NOT generate a receipt (body edits are co-authoring, not
  governance events).
- The Companion UI NEVER auto-applies or auto-rejects a governance receipt; the
  status shown here is read-only.
- governance.openReceipt hands off to AI Panel anchored to the receipt_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Supported outcome values for a ReceiptPill.
RECEIPT_OUTCOMES: frozenset[str] = frozenset({"applied", "queued", "discarded", "blocked"})

# Terminal outcomes — pills with these outcomes are removed from ReceiptsStrip.
_TERMINAL_OUTCOMES: frozenset[str] = frozenset({"applied", "discarded"})


@dataclass
class ReceiptPill:
    """Render model for a single governance receipt pill.

    Links to Panel via the ``governance.openReceipt`` intent token.

    Fields
    ------
    receipt_id        Unique receipt identifier (UUID or slug).
    suggestion_id     Paired suggestion that triggered the governance event.
    artifact_id       Artifact the governance event targets.
    outcome           One of: applied | queued | discarded | blocked.
    label             Short human-readable label (e.g. "queued · rec-001 · move").
    display_timestamp ISO-8601 or display-formatted timestamp string.
    message           Optional extra context surfaced by the governance layer.
    """

    receipt_id: str
    suggestion_id: str
    artifact_id: str
    outcome: str
    label: str
    display_timestamp: str
    message: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.receipt_id:
            raise ValueError("receipt_id is required")
        if not self.suggestion_id:
            raise ValueError("suggestion_id is required")
        if not self.artifact_id:
            raise ValueError("artifact_id is required")
        if self.outcome not in RECEIPT_OUTCOMES:
            raise ValueError(
                f"Unknown receipt outcome: {self.outcome!r}. "
                f"Must be one of {sorted(RECEIPT_OUTCOMES)}."
            )
        if not self.label:
            raise ValueError("label is required for user-facing display")
        if not self.display_timestamp:
            raise ValueError("display_timestamp is required")

    @property
    def is_terminal(self) -> bool:
        """True when the outcome is terminal (applied or discarded)."""
        return self.outcome in _TERMINAL_OUTCOMES

    def to_render_dict(self) -> dict:
        """Serialisable dict for the UI layer.

        Maps to the ReceiptPill HTML element attributes defined in issue #871:
          data-testid="receipt-pill"
          data-receipt-id="<uuid>"
          data-status="<outcome>"
          data-intent="governance.openReceipt"
        """
        d: dict = {
            "data_testid": "receipt-pill",
            "data_receipt_id": self.receipt_id,
            "data_suggestion_id": self.suggestion_id,
            "data_artifact_id": self.artifact_id,
            "data_status": self.outcome,
            "data_intent": "governance.openReceipt",
            "aria_label": (
                f"Governance receipt {self.receipt_id}, {self.outcome}. Open in Panel."
            ),
            "label": self.label,
            "display_timestamp": self.display_timestamp,
            "is_terminal": self.is_terminal,
        }
        if self.message is not None:
            d["message"] = self.message
        return d


@dataclass
class ReceiptsStrip:
    """Render model for the sticky governance receipts strip in the rail.

    Holds a list of ReceiptPill objects.  The strip renders only non-terminal
    receipts (queued and blocked) when filtering for display; callers may also
    access the full list.

    aria-live="polite" is included in to_render_dict() so upstream status
    transitions are announced to assistive technology.

    The strip MUST NOT write to the vault.  It reads receipt state supplied
    by the Panel locality (preventing orphaned pills when a Panel record is
    dismissed elsewhere).
    """

    pills: list[ReceiptPill] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when there are no pills at all."""
        return len(self.pills) == 0

    @property
    def latest(self) -> Optional[ReceiptPill]:
        """The most recently added ReceiptPill, or None if empty."""
        if self.is_empty:
            return None
        return self.pills[-1]

    @property
    def non_terminal_pills(self) -> list[ReceiptPill]:
        """Pills with non-terminal outcomes (queued, blocked) — shown in the strip."""
        return [p for p in self.pills if not p.is_terminal]

    def to_render_dict(self) -> dict:
        """Serialisable dict for the UI layer.

        Maps to the ReceiptsStrip HTML element attributes defined in issue #871:
          data-testid="receipts-strip"
          aria-live="polite"
        """
        return {
            "data_testid": "receipts-strip",
            "aria_live": "polite",
            "is_empty": self.is_empty,
            "pill_count": len(self.pills),
            "non_terminal_pill_count": len(self.non_terminal_pills),
            "pills": [p.to_render_dict() for p in self.pills],
            "non_terminal_pills": [p.to_render_dict() for p in self.non_terminal_pills],
        }
