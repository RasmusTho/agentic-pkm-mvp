"""Link a ContextBundle to a governed write proposal (CONTEXT-BUNDLES-05).

Bundle evidence may support a write proposal but must not bypass write guards
or silently upgrade may_propose into may_write. Propose, stage, apply, and
log remain distinct states — the bundle never collapses them into one step.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.context_bundles.schema import ContextBundle


class BundleProposalViolation(Exception):
    """Raised when a bundle attempts to bypass write guards or lacks proposal authority."""


ProposalState = Literal["proposed", "staged", "applied", "logged"]


class WriteProposal(BaseModel):
    bundle_id: str
    affected_artifacts: list[str] = Field(default_factory=list)
    proposal_basis: str
    state: ProposalState = "proposed"
    may_propose: bool = True
    may_write: bool = False


def build_write_proposal_from_bundle(
    bundle: ContextBundle,
    *,
    affected_artifacts: list[str],
    proposal_basis: str,
    now: datetime | None = None,
) -> WriteProposal:
    """Create a governed write proposal backed by a ContextBundle.

    Requires ``may_propose=True`` and rejects ``may_write=True`` — bundle
    evidence may justify a proposal but must not itself authorize the apply
    step. Also rejects expired bundles — stale retrieval snapshots must not
    silently continue to justify new write proposals.
    The governed write boundary (write guards, APPLY rules, trust semantics)
    remains upstream of this surface.
    """
    if not bundle.authority.may_propose:
        raise BundleProposalViolation(
            f"bundle {bundle.id} does not carry may_propose=True; "
            "cannot link bundle to a write proposal without explicit propose authority"
        )
    if bundle.authority.may_write:
        raise BundleProposalViolation(
            f"bundle {bundle.id} carries may_write=True; "
            "bundle authority must not bypass write guards — use governed write surface instead"
        )
    if bundle.expiry and bundle.expiry.stale_after is not None:
        _now = now or datetime.now(tz=timezone.utc)
        stale_after = bundle.expiry.stale_after
        if stale_after.tzinfo is None:
            stale_after = stale_after.replace(tzinfo=timezone.utc)
        if _now >= stale_after:
            raise BundleProposalViolation(
                f"bundle {bundle.id} is expired (stale_after={stale_after.isoformat()}); "
                "expired bundles must not justify new write proposals"
            )

    return WriteProposal(
        bundle_id=bundle.id,
        affected_artifacts=list(affected_artifacts),
        proposal_basis=proposal_basis,
        state="proposed",
        may_propose=True,
        may_write=False,
    )


__all__ = [
    "BundleProposalViolation",
    "WriteProposal",
    "build_write_proposal_from_bundle",
]
