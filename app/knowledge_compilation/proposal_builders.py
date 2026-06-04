"""Deterministic, provider-free proposal builders for v6.x Knowledge Compilation.

Child slice #1535 under parent feature #1533. Builds ``CompilationDraft`` and
``CurationCandidate`` proposals (the runtime contracts from #1534) out of explicitly
supplied, *approved* context — preserving provenance, uncertainty, exclusions, rationale,
trust posture, and trace ids, and refusing to launder hidden authority from unreviewed
memory, embeddings, retrieval ranking, generated summaries, stale inputs, or
write-authorizing bundles.

Authority posture follows ``docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`` (SUGGEST / no
laundering) and ``docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md`` (activation
rights / hidden-authority guard).

This module is pure, deterministic domain code: no LLM/provider call, no events, no vault
writes, no database/object-store/port writes, no API/UI wiring.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge_compilation.runtime_artifacts import (
    CompilationDraft,
    ContextAuthorityLimits,
    CurationCandidate,
    SourceRef,
)

# ``derived_by`` values that mark machine-derived material which must not be laundered into a
# proposal's authority (it is a ranking/synthesis signal, not approved human authority).
_MACHINE_DERIVATIONS: frozenset[str] = frozenset(
    {"embedding", "generated_summary", "summary", "retrieval", "rerank"}
)
_APPROVED_REVIEW_STATES: frozenset[str] = frozenset({"reviewed", "accepted", "protected"})


class ProposalContext(BaseModel):
    """Explicitly supplied, approved context for deterministic proposal building.

    The context is the builder's only input — there is no provider call or retrieval inside
    the builder. ``authority_limits`` records the posture of the supplying bundle; a
    write/promote/action-authorizing bundle is refused rather than laundered into a proposal.
    """

    model_config = ConfigDict(frozen=True)

    source_refs: tuple[SourceRef, ...] = Field(default_factory=tuple)
    authority_limits: ContextAuthorityLimits = Field(default_factory=ContextAuthorityLimits)
    stale: bool = False
    content: Optional[str] = None
    uncertainty_notes: Optional[str] = None
    rationale: Optional[str] = None
    excluded_refs: tuple[SourceRef, ...] = Field(default_factory=tuple)
    generated_by: Optional[str] = None
    trace_ref: Optional[str] = None


def _reject_hidden_authority(context: ProposalContext) -> None:
    """Refuse context that would launder hidden authority into a generated proposal.

    Raises ``ValueError`` rather than silently degrading the input, so a builder never turns
    unreviewed/ranked/derived/stale/write-authorizing material into proposal authority.
    """

    if not context.source_refs:
        raise ValueError("proposal context requires provenance: at least one source_ref")
    if context.stale:
        raise ValueError("proposal context is stale; refusing to build a proposal from stale input")
    limits = context.authority_limits
    if limits.may_write or limits.may_promote or limits.may_authorize_action:
        raise ValueError(
            "proposal context is write-authorizing; refusing to launder action authority "
            "into a non-canonical proposal"
        )
    for ref in context.source_refs:
        review_state = (ref.review_state or "").strip().lower()
        if review_state and review_state not in _APPROVED_REVIEW_STATES:
            raise ValueError(
                f"source {ref.artifact_id!r} has non-approved review_state {ref.review_state!r}; "
                f"only reviewed, accepted, or protected sources can be laundered into a proposal"
            )
        if ref.retrieval_score is not None:
            raise ValueError(
                f"retrieval-ranked source {ref.artifact_id!r} is a ranking signal, not approved "
                f"authority"
            )
        if (ref.derived_by or "").strip().lower() in _MACHINE_DERIVATIONS:
            raise ValueError(
                f"machine-derived source {ref.artifact_id!r} ({ref.derived_by}) is not approved "
                f"authority"
            )


def build_compilation_draft(context: ProposalContext, *, title: str) -> CompilationDraft:
    """Build a non-canonical ``CompilationDraft`` from approved context.

    Preserves source refs, body content, uncertainty posture, and trace id. The output's
    non-canonical / SUGGEST / pending-review posture is guaranteed by the #1534 contract.
    """

    _reject_hidden_authority(context)
    return CompilationDraft(
        title=title,
        source_refs=context.source_refs,
        body=context.content,
        uncertainty_notes=context.uncertainty_notes,
        generated_by=context.generated_by,
        trace_ref=context.trace_ref,
    )


def build_curation_candidate(context: ProposalContext, *, title: str) -> CurationCandidate:
    """Build a non-canonical ``CurationCandidate`` from approved context.

    Preserves retained-material rationale, source links, and the excluded refs (which carry
    their exclusion reason on the ref), without dropping or downgrading provenance.
    """

    _reject_hidden_authority(context)
    return CurationCandidate(
        title=title,
        source_refs=context.source_refs,
        rationale=context.rationale,
        excluded_refs=context.excluded_refs,
        generated_by=context.generated_by,
        trace_ref=context.trace_ref,
    )
