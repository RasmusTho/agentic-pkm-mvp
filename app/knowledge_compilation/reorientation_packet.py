"""Assemble read-only ReorientationPacket supports from orientation context bundles.

Slice #1536 under parent feature #1533. This module stays pure-domain: it consumes
already-approved orientation/context-bundle inputs and returns a non-canonical
``ReorientationPacket`` without storage, API, event emission, or mutation behavior.
"""

from __future__ import annotations

from datetime import datetime

from app.context_bundles.schema import ContextBundle, ExcludedItem, IncludedItem
from app.knowledge_compilation.runtime_artifacts import (
    AGENT_MEMORY_CLASS,
    ReorientationPacket,
    SourceRef,
)
from app.orientation.bundle_consumer import build_orientation_frame_from_bundle


class PacketAssemblyError(ValueError):
    """Raised when packet assembly would cross the read-only orientation boundary."""


_MUTATION_SOURCE_ROLES = {
    "action",
    "apply",
    "mutation",
    "mutation_intent",
    "write",
    "write_intent",
    "write_proposal",
}


def _bounded(text: str, limit: int) -> str:
    if limit < 1:
        raise PacketAssemblyError("max_summary_chars must be positive")
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."


def _source_ref_from_included(item: IncludedItem) -> SourceRef:
    provenance = item.provenance
    return SourceRef(
        artifact_id=item.artifact_id,
        note_path=item.path,
        role=item.source_role or "orientation_context",
        review_state=item.review_state,
        retrieval_score=item.retrieval_score,
        derived_by=provenance.transformed_by if provenance else None,
    )


def _source_ref_from_excluded(item: ExcludedItem) -> SourceRef:
    provenance = item.provenance
    return SourceRef(
        artifact_id=item.artifact_id,
        role="excluded",
        review_state=item.review_state,
        derived_by=provenance.transformed_by if provenance else None,
    )


def _reject_mutation_inputs(bundle: ContextBundle) -> None:
    for item in bundle.included:
        role = (item.source_role or "").lower()
        trust = (item.trust_state or "").upper()
        if role in _MUTATION_SOURCE_ROLES:
            raise PacketAssemblyError(
                f"cannot assemble reorientation packet from mutation-scoped item {item.artifact_id}"
            )
        if trust == "APPLY":
            raise PacketAssemblyError(
                f"cannot assemble reorientation packet from APPLY-scoped item {item.artifact_id}"
            )


def _memory_handoff_refs(
    included: list[IncludedItem],
    *,
    max_memory_handoff_refs: int,
) -> tuple[str, ...]:
    if max_memory_handoff_refs < 0:
        raise PacketAssemblyError("max_memory_handoff_refs must be non-negative")
    refs: list[str] = []
    for item in included:
        role = (item.source_role or "").lower()
        if role == "memory_handoff" or item.artifact_id.startswith(f"{AGENT_MEMORY_CLASS}:"):
            refs.append(item.artifact_id)
        if len(refs) >= max_memory_handoff_refs:
            break
    return tuple(refs)


def _summary(
    bundle: ContextBundle,
    *,
    fact_count: int,
    inference_count: int,
    candidate_count: int,
    excluded_count: int,
    stale: bool,
    max_summary_chars: int,
) -> str:
    text = (
        f"bundle={bundle.id}; facts={fact_count}; inferences={inference_count}; "
        f"candidate_refs={candidate_count}; exclusions={excluded_count}; stale={stale}"
    )
    return _bounded(text, max_summary_chars)


def assemble_reorientation_packet_from_bundle(
    bundle: ContextBundle,
    *,
    trace_ref: str,
    now: datetime | None = None,
    leave_point_ref: str | None = None,
    max_source_refs: int = 12,
    max_memory_handoff_refs: int = 8,
    max_summary_chars: int = 240,
) -> ReorientationPacket:
    """Create a reference-only packet for return-to-work orientation.

    The existing orientation bundle consumer performs the main authority checks:
    ``may_orient`` must be true, ``may_write`` must be false, and the bundle must be
    scoped for ``orient`` use. This assembly layer adds packet-specific refusal of
    mutation/APPLY inputs, caps copied references, and keeps memory handoff hints as
    identifiers only.
    """

    if not trace_ref.strip():
        raise PacketAssemblyError("trace_ref is required for packet assembly")
    if max_source_refs < 1:
        raise PacketAssemblyError("max_source_refs must be positive")

    frame = build_orientation_frame_from_bundle(bundle, now=now)
    _reject_mutation_inputs(bundle)

    source_refs = tuple(
        _source_ref_from_included(item) for item in bundle.included[:max_source_refs]
    )
    excluded_refs = tuple(_source_ref_from_excluded(item) for item in bundle.excluded)
    exclusion_reasons = tuple(item.reason for item in bundle.excluded)

    return ReorientationPacket(
        summary=_summary(
            bundle,
            fact_count=len(frame.facts),
            inference_count=len(frame.inferences),
            candidate_count=len(frame.candidate_actions),
            excluded_count=len(frame.exclusions),
            stale=frame.stale,
            max_summary_chars=max_summary_chars,
        ),
        source_refs=source_refs,
        trace_ref=trace_ref,
        generated_by="knowledge_compilation.reorientation_packet",
        leave_point_ref=leave_point_ref,
        memory_handoff_refs=_memory_handoff_refs(
            bundle.included,
            max_memory_handoff_refs=max_memory_handoff_refs,
        ),
        stale_after=bundle.expiry.stale_after,
        stale_reason=frame.stale_reason,
        excluded_refs=excluded_refs,
        exclusion_reasons=exclusion_reasons,
    )


__all__ = [
    "PacketAssemblyError",
    "assemble_reorientation_packet_from_bundle",
]
