"""Pure runtime/domain models for v6.x Knowledge Compilation and Memory Curation.

Child slice #1534 under parent feature #1533. This is the first executable slice: it
defines the non-canonical, ``SUGGEST``-posture runtime support artifacts —
``CompilationDraft``, ``CurationCandidate``, and ``ReorientationPacket`` — *before* any
proposal builders (#1535), reorientation assembly (#1536), admission handoff (#1537), or
eval/trace harness (#1538) work begins.

Authority posture follows the source contracts:

- ``docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`` — ASSERT / SUGGEST / APPLY. Generated
  outputs default to SUGGEST and may not self-escalate.
- ``docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`` — generated/inferred material
  is never canonical and never action-authorizing without accepted review.
- ``docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md`` — the hidden-authority
  guard (unreviewed memory, embeddings, retrieval ranking, generated summaries cannot
  grant authority) and the bridge/assembly-artifact framing for return-to-work supports.
- ``docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`` — a trace is not a receipt;
  these artifacts reference receipts by id and never *are* receipt authority.
- ``docs/plans/V6X_KNOWLEDGE_COMPILATION_AND_MEMORY_CURATION.md`` — Artifact Model /
  Review and Promotion Posture.

This module is intentionally pure domain code. It must not wire up a database session, an
object store, a knowledge or vault port, a write guard, an outbox emitter, or filesystem
write helpers. Storage, API, events, and UI belong to later slices, not here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrustVerb(str, Enum):
    """Trust verbs from ``TRUST_SEMANTICS_CONTRACT.md``.

    Generated artifacts default to ``SUGGEST``. ``ASSERT``/``APPLY`` may only be carried
    after an explicit human admission decision (#1537); the contract here never
    self-escalates the verb.
    """

    SUGGEST = "SUGGEST"
    ASSERT = "ASSERT"
    APPLY = "APPLY"


class AdmissionState(str, Enum):
    """Review/admission posture for generated artifacts.

    Generated artifacts start ``PENDING_REVIEW`` and require an explicit admission
    decision plus receipt posture before any promotion path (handled in #1537). Aligns
    with the review lifecycle in ``agent_memory.candidate.ReviewState`` without coupling
    to it.
    """

    PENDING_REVIEW = "pending_review"
    ADMITTED = "admitted"
    REJECTED = "rejected"


# Artifact-class tokens. Plain strings to match the house convention
# (see ``app/agent_memory/candidate.py`` -> ``MemoryCandidate.artifact_class``); typed as
# ``Literal`` so they can serve as the pinned per-subclass ``artifact_class`` default.
COMPILATION_DRAFT_CLASS: Literal["compilation_draft"] = "compilation_draft"
CURATION_CANDIDATE_CLASS: Literal["curation_candidate"] = "curation_candidate"
REORIENTATION_PACKET_CLASS: Literal["reorientation_packet"] = "reorientation_packet"

# Bridge/assembly support artifacts compose other material for orientation/return-to-work.
# They are never durable memory, canonical knowledge, or receipt authority.
BRIDGE_ARTIFACT_CLASSES: frozenset[str] = frozenset({REORIENTATION_PACKET_CLASS})

# Durable agent-memory artifact class (``app/agent_memory/candidate.py``). Generated
# knowledge-compilation artifacts must never claim this class.
AGENT_MEMORY_CLASS = "agentic_memory"


class SourceRef(BaseModel):
    """First-class provenance reference for a generated artifact.

    Mirrors the provenance posture of ``agent_memory.candidate`` (``source_refs``) and
    ``context_bundles.schema`` (``ItemProvenance``/``IncludedItem``). Review posture,
    retrieval scores, and the deriving mechanism may be *recorded* here, but recording
    them never grants authority — see ``ContextAuthorityLimits``.
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    note_path: Optional[str] = None
    role: Optional[str] = None
    # Recorded provenance signals — never authoritative on their own:
    review_state: Optional[str] = None  # e.g. "unreviewed"
    retrieval_score: Optional[float] = None  # ranking signal
    derived_by: Optional[str] = None  # e.g. "embedding", "generated_summary"


class ContextAuthorityLimits(BaseModel):
    """Authority-limit flags for a generated artifact.

    Mirrors ``app/context_bundles/schema.py`` -> ``AuthorityFlags``. Generated
    knowledge-compilation artifacts are inform/orient-only: they may never carry write,
    promotion, or action-authorization authority. The hidden-authority guard
    (``CONTEXT_ACTIVATION_SEMANTICS.md``) means unreviewed memory, embeddings, retrieval
    scores, and generated summaries cannot flip the latter three on.
    """

    model_config = ConfigDict(frozen=True)

    may_inform: bool = True
    may_orient: bool = False
    may_propose: bool = False
    may_promote: bool = False
    may_write: bool = False
    may_authorize_action: bool = False


class GeneratedArtifact(BaseModel):
    """Base for non-canonical, ``SUGGEST``-posture generated runtime supports.

    Invariants enforced at construction:

    - at least one ``source_ref`` must be present (no sourceless synthesis);
    - ``canonical`` stays ``False``;
    - the trust verb stays ``SUGGEST`` unless the artifact is explicitly ``ADMITTED``;
    - the artifact can never carry write/promote/action-authorization authority.

    The model (and its nested authority/provenance models) is frozen so these invariants
    cannot be bypassed by post-construction mutation; collection fields are tuples so their
    contents cannot be mutated in place either.
    """

    model_config = ConfigDict(frozen=True)

    artifact_class: str
    artifact_id: str = Field(default_factory=lambda: uuid4().hex)
    canonical: bool = Field(default=False)
    trust_verb: TrustVerb = Field(default=TrustVerb.SUGGEST)
    admission_state: AdmissionState = Field(default=AdmissionState.PENDING_REVIEW)
    inferred: bool = Field(default=True)

    source_refs: tuple[SourceRef, ...] = Field(default_factory=tuple)
    generated_by: Optional[str] = None
    # Operational trace id only. A trace is not a receipt
    # (``RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md``).
    trace_ref: Optional[str] = None

    authority_limits: ContextAuthorityLimits = Field(default_factory=ContextAuthorityLimits)

    # Receipts are referenced by id only — a generated artifact is never itself a receipt.
    admission_receipt_ref: Optional[str] = None

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_bridge_artifact(self) -> bool:
        """True only for bridge/assembly support artifacts (e.g. reorientation packets)."""

        return self.artifact_class in BRIDGE_ARTIFACT_CLASSES

    @property
    def grants_receipt_authority(self) -> bool:
        """Generated artifacts may reference receipts but never *are* receipt authority."""

        return False

    @model_validator(mode="after")
    def _enforce_noncanonical_suggest_posture(self) -> "GeneratedArtifact":
        if not self.source_refs:
            raise ValueError(
                f"{self.artifact_class} requires at least one source_ref "
                f"(provenance) before construction"
            )
        if self.canonical:
            raise ValueError(
                f"generated {self.artifact_class} must remain non-canonical"
            )
        if self.artifact_class == AGENT_MEMORY_CLASS:
            raise ValueError(
                f"generated {self.artifact_class} must not claim durable agent-memory class"
            )
        # Admission requires durable receipt evidence regardless of trust verb: downstream
        # code keys off admission_state, so a self-marked admitted artifact must not be
        # indistinguishable from a reviewed one (RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md;
        # epic #1533: "mutation/promotion requires explicit admission plus receipt posture").
        # The admission handoff that attaches the receipt is slice #1537.
        if self.admission_state is AdmissionState.ADMITTED and not self.admission_receipt_ref:
            raise ValueError(
                f"generated {self.artifact_class} marked admitted requires a durable "
                f"admission_receipt_ref"
            )
        # Trust escalation past SUGGEST additionally requires the explicit ADMITTED decision
        # (which, by the check above, already carries a receipt).
        if (
            self.trust_verb is not TrustVerb.SUGGEST
            and self.admission_state is not AdmissionState.ADMITTED
        ):
            raise ValueError(
                f"generated {self.artifact_class} cannot carry trust_verb "
                f"{self.trust_verb.value} without explicit admission"
            )
        limits = self.authority_limits
        elevated = [
            name
            for name, granted in (
                ("may_write", limits.may_write),
                ("may_promote", limits.may_promote),
                ("may_authorize_action", limits.may_authorize_action),
            )
            if granted
        ]
        if elevated:
            raise ValueError(
                f"generated {self.artifact_class} cannot grant hidden authority: "
                f"{', '.join(elevated)}"
            )
        return self


class CompilationDraft(GeneratedArtifact):
    """Generated synthesis candidate, explicitly non-canonical.

    The bounded contract here only fixes the model and posture; building drafts from
    approved context (preserving source refs and uncertainty) is #1535.
    """

    artifact_class: Literal["compilation_draft"] = COMPILATION_DRAFT_CLASS
    title: str
    body: Optional[str] = None
    uncertainty_notes: Optional[str] = None


class CurationCandidate(GeneratedArtifact):
    """Proposed retained-material set with source links and rationale, non-canonical.

    Building candidates (preserving rationale and explicit exclusions) is #1535.
    """

    artifact_class: Literal["curation_candidate"] = CURATION_CANDIDATE_CLASS
    title: str
    rationale: Optional[str] = None
    excluded_refs: tuple[SourceRef, ...] = Field(default_factory=tuple)


class ReorientationPacket(GeneratedArtifact):
    """Compact read-only context bundle for return-to-work flows.

    A bridge/assembly support artifact (``CONTEXT_ACTIVATION_SEMANTICS.md``): it composes
    references for orientation but is **not** agent memory, **not** canonical knowledge,
    and **not** receipt authority. Memory and receipts are referenced by id only. Read-only
    assembly of the packet contents is #1536.
    """

    artifact_class: Literal["reorientation_packet"] = REORIENTATION_PACKET_CLASS
    # A reorientation packet exists to support re-orientation, so it is orient-capable by
    # default (CONTEXT_ACTIVATION_SEMANTICS.md: ``may_orient=true`` permits re-orientation;
    # leaving it false would strip the one permission the packet needs). Write, promote, and
    # action authority stay disabled and are still refused by the base validator.
    authority_limits: ContextAuthorityLimits = Field(
        default_factory=lambda: ContextAuthorityLimits(may_orient=True)
    )
    summary: Optional[str] = None
    leave_point_ref: Optional[str] = None  # reference only
    memory_handoff_refs: tuple[str, ...] = Field(default_factory=tuple)  # reference-only ids
    stale_after: Optional[datetime] = None
