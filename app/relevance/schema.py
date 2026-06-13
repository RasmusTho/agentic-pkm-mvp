"""Moment artifact schema for the Contextual Relevance Engine.

Implements the vault-native moment defined in
``docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md``: a non-authoritative proposal that
something deserves the human's attention now, with its trigger, the need served,
source-linked references, a derived urgency assessment, a lifecycle, and a
receipt. A moment is a projection/proposal, never silent truth.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

# Ordinal urgency bands (routine < timely < pressing < critical). The evaluator
# records an *assessment*, not an authoritative intrinsic property; the scarcity
# gate (CRE-02) compares it to the current interruptibility threshold.
UrgencyBand = Literal["routine", "timely", "pressing", "critical"]
URGENCY_ORDER: tuple[UrgencyBand, ...] = ("routine", "timely", "pressing", "critical")

NeedBasis = Literal[
    "open-loop-pressure",
    "attentional-relevance",
    "reorientation",
    "commitment-risk",
]

MomentLifecycle = Literal["proposed", "surfaced", "engaged", "dismissed", "deferred", "expired"]


def urgency_rank(band: UrgencyBand) -> int:
    """Return the ordinal rank of an urgency band for threshold comparison."""

    return URGENCY_ORDER.index(band)


class MomentTrigger(BaseModel):
    """What in the context model produced this moment (the provenance of *why now*)."""

    kind: str
    source_ref: str | None = None


class MomentNeed(BaseModel):
    """The human need served, in salience vocabulary."""

    basis: NeedBasis
    summary: str


class SurfacedRef(BaseModel):
    """A reference the moment brings into view — never a copy of the source."""

    ref: str
    uuid: str | None = None
    why: str


class MomentUrgency(BaseModel):
    """A derived urgency assessment at emission. Not an authoritative field."""

    band: UrgencyBand
    basis: str
    evaluator: str


class MomentProvenance(BaseModel):
    """How the moment was produced, for reproducibility/observability."""

    produced_by: str
    inputs_digest: str


class Moment(BaseModel):
    """A first-class, vault-native, non-authoritative moment artifact."""

    uuid: str
    type: Literal["moment"] = "moment"
    created: str
    trigger: MomentTrigger
    need: MomentNeed
    surfaced_refs: list[SurfacedRef] = Field(default_factory=list)
    urgency: MomentUrgency
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    lifecycle: MomentLifecycle = "proposed"
    authority: Literal["non-authoritative"] = "non-authoritative"
    authority_class: Literal["proposal"] = "proposal"
    receipt_ref: str | None = None
    provenance: MomentProvenance

    def to_frontmatter(self) -> dict[str, Any]:
        """Render the machine-legible frontmatter, in contract field order."""

        return {
            "uuid": self.uuid,
            "type": self.type,
            "created": self.created,
            "trigger": self.trigger.model_dump(exclude_none=True),
            "need": self.need.model_dump(),
            "surfaced_refs": [ref.model_dump(exclude_none=True) for ref in self.surfaced_refs],
            "urgency": self.urgency.model_dump(),
            "context_snapshot": dict(self.context_snapshot),
            "lifecycle": self.lifecycle,
            "authority": self.authority,
            "authority_class": self.authority_class,
            "receipt_ref": self.receipt_ref,
            "provenance": self.provenance.model_dump(),
        }

    def to_markdown_body(self) -> str:
        """Render the human-legible projection body (a proposal, not a verdict)."""

        lines = [
            f"# {self.need.summary}",
            "",
            "> A proposal, not a verdict. Pointers the system thinks may help you orient right now.",
            "> Open what's useful; ignore the rest. Nothing here changes your notes.",
            "",
            f"**Why now:** {self.need.summary} ({self.need.basis})",
            "",
            "## Bring into view",
            "",
        ]
        if self.surfaced_refs:
            for ref in self.surfaced_refs:
                lines.append(f"- [{ref.ref}]({_link(ref.ref)}) — {ref.why}")
        else:
            lines.append("- (nothing pressing right now)")
        lines += [
            "",
            f"_Materialized by the Contextual Relevance Engine · {self.authority} "
            f"projection of vault-native data · no external source read._",
        ]
        return "\n".join(lines)


def _link(ref: str) -> str:
    """Encode spaces for a Markdown link target while keeping the path readable."""

    return ref.replace(" ", "%20")


def moment_from_frontmatter(frontmatter: Mapping[str, Any]) -> Moment:
    """Reconstruct a Moment from a materialized artifact's frontmatter."""

    return Moment.model_validate(dict(frontmatter))


__all__ = [
    "Moment",
    "MomentTrigger",
    "MomentNeed",
    "SurfacedRef",
    "MomentUrgency",
    "MomentProvenance",
    "UrgencyBand",
    "URGENCY_ORDER",
    "NeedBasis",
    "MomentLifecycle",
    "urgency_rank",
    "moment_from_frontmatter",
]
