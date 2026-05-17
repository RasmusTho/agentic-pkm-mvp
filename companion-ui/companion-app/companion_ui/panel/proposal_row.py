"""Panel proposal row and status/receipt rendering model (#1040).

Each Panel proposal row represents one artifact-local proposed intention.
Proposals are individually actionable — no bulk acceptance.
The model does not execute proposals or write vault files.

Source contract: companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md :: Part 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Available affordances on a proposal row.
PROPOSAL_AFFORDANCES: set[str] = {"confirm", "correct", "reject"}

# Valid proposal-row-level statuses (pre-decision).
PROPOSAL_STATUS_VALUES: set[str] = {
    "staged",
    "confirming",
    "corrected",
    "rejected",
    "blocked",
}

# Valid receipt outcome values.
RECEIPT_OUTCOMES: set[str] = {
    "success",
    "blocked",
    "logged",
    "partial",
}


@dataclass
class ProposalEvidence:
    """Provenance/evidence for why a proposal was generated.

    Must be visible at confirmation time (may be collapsible in default view).
    """

    trigger_summary: str
    action_class: str
    cognition_route: str
    raw: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "trigger_summary": self.trigger_summary,
            "action_class": self.action_class,
            "cognition_route": self.cognition_route,
        }


@dataclass
class ProposalRow:
    """Render model for a single artifact-local proposed intention.

    artifact_id is required — proposals are always artifact-local.
    proposal_id is the canonical action/intent ID used for runtime correlation.
    Each row carries confirm/correct/reject affordances; none are auto-applied.
    """

    proposal_id: str
    artifact_id: str
    description: str
    evidence: ProposalEvidence
    available_affordances: set[str] = field(default_factory=lambda: set(PROPOSAL_AFFORDANCES))
    status: str = "staged"

    def __post_init__(self) -> None:
        if not self.proposal_id:
            raise ValueError("proposal_id is required")
        if not self.artifact_id:
            raise ValueError("artifact_id is required — proposals are artifact-local")
        if not self.description:
            raise ValueError("description is required for user-facing display")
        if self.status not in PROPOSAL_STATUS_VALUES:
            raise ValueError(f"Unknown proposal status: {self.status!r}")
        unknown = self.available_affordances - PROPOSAL_AFFORDANCES
        if unknown:
            raise ValueError(f"Unknown affordances: {unknown!r}")

    def can_confirm(self) -> bool:
        return "confirm" in self.available_affordances and self.status == "staged"

    def can_correct(self) -> bool:
        return "correct" in self.available_affordances and self.status == "staged"

    def can_reject(self) -> bool:
        return "reject" in self.available_affordances and self.status == "staged"

    def as_render_dict(self) -> dict:
        """Return a serialisable dict for UI layer consumption."""
        return {
            "proposal_id": self.proposal_id,
            "artifact_id": self.artifact_id,
            "description": self.description,
            "evidence": self.evidence.as_dict(),
            "status": self.status,
            "affordances": {
                "confirm": self.can_confirm(),
                "correct": self.can_correct(),
                "reject": self.can_reject(),
            },
        }


@dataclass
class ProposalReceipt:
    """Status/receipt model for a completed (or blocked) proposal action.

    Receipts are not ephemeral — they persist until the user dismisses them
    or navigates away.  They do not write vault files; the runtime owns the
    durable AI-status callout in the vault.
    """

    proposal_id: str
    artifact_id: str
    action_taken: str
    outcome: str
    timestamp: datetime
    message: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.proposal_id:
            raise ValueError("proposal_id is required")
        if not self.artifact_id:
            raise ValueError("artifact_id is required")
        if self.outcome not in RECEIPT_OUTCOMES:
            raise ValueError(f"Unknown receipt outcome: {self.outcome!r}")

    def as_render_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "artifact_id": self.artifact_id,
            "action_taken": self.action_taken,
            "outcome": self.outcome,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        }


def make_stub_proposal_row(
    proposal_id: str = "prop-001",
    artifact_id: str = "note-a",
    description: str = "Move note to Projects",
    cognition_route: str = "rule",
) -> ProposalRow:
    """Return a stub ProposalRow for testing and development."""
    evidence = ProposalEvidence(
        trigger_summary="Note has active project tag and no lifecycle classification",
        action_class="lifecycle.move",
        cognition_route=cognition_route,
    )
    return ProposalRow(
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        description=description,
        evidence=evidence,
    )


def make_stub_receipt(
    proposal_id: str = "prop-001",
    artifact_id: str = "note-a",
    action_taken: str = "lifecycle.move",
    outcome: str = "success",
    message: Optional[str] = None,
) -> ProposalReceipt:
    """Return a stub ProposalReceipt for testing and development."""
    return ProposalReceipt(
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        action_taken=action_taken,
        outcome=outcome,
        timestamp=datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc),
        message=message,
    )
