"""Acquisition-time wiring of key moments and default frame capture into candidates (#5746).

Connects the delivered YSNV2-09 moment projection (``key_moments.derive_key_moments``) and the
YSNV2-11 bounded frame-capture stage (``source_frames.capture_source_frames``) to the candidate
the acquisition/replay orchestrators are about to render.  Rendering itself stays in
``candidate_writeback`` under the shared proposals wrapper.

Failure posture:

* a moment-derivation failure omits the moments section and records a visible
  ``unavailable`` status; it never fails the candidate;
* capture degradation (unavailable media, exceeded bound, extraction failure, write-guard
  block) leaves timestamps-only moments and a visible frames status, with no placeholder;
* ``SourceFramesError`` (inconsistent lineage, unprovable temporary-media cleanup, failed
  vault/ObjectStore write) propagates so the caller dead-letters it visibly;
* ``capture=False`` (replay, text-only re-rendering) never invokes media capture and performs
  no source egress; it only re-references frames an earlier capture already retained.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from app.knowledge_acquisition.candidate_writeback import Candidate
from app.knowledge_acquisition.extraction_persistence import (
    ExtractionPersistenceError,
    PersistedExtraction,
    PersistedTranscript,
    load_extraction_artifact,
)
from app.knowledge_acquisition.extraction_registry import ExtractionResult
from app.knowledge_acquisition.key_moments import KeyMomentsError, derive_key_moments
from app.knowledge_acquisition.source_frames import (
    SourceMediaCapture,
    capture_source_frames,
    retained_frames,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard


def attach_key_moments(
    candidate: Candidate,
    *,
    transcript: PersistedTranscript,
    extractions: Sequence[ExtractionResult],
    vault_context: VaultContext,
    capture: bool,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    youtube_attachment_root: str | None = None,
    media_capture: SourceMediaCapture | None = None,
) -> Candidate:
    """Return ``candidate`` carrying persisted moments and, when retained, their frames."""

    if not candidate.transcript_available:
        return candidate
    try:
        moments = derive_key_moments(
            transcript=transcript,
            item_ref=candidate.item_ref,
            claims_extraction=_claims_extraction(extractions),
        )
    except (KeyMomentsError, ExtractionPersistenceError) as exc:
        return replace(candidate, moments_status=f"unavailable (key moment derivation failed: {exc})")

    candidate = replace(
        candidate,
        key_moments=moments.moments,
        key_moments_artifact_id=moments.object_id,
        moments_status=moments.status,
    )
    if not moments.moments:
        return candidate

    def _retained() -> tuple[dict[str, Any], ...]:
        return retained_frames(
            key_moments=moments,
            transcript=transcript,
            item_ref=candidate.item_ref,
            vault_context=vault_context,
            youtube_attachment_root=youtube_attachment_root,
        )

    if not capture:
        frames = _retained()
        status = "previously retained (not recaptured)" if frames else "timestamps-only (not recaptured)"
        return replace(candidate, moment_frames=frames, frames_status=status)

    result = capture_source_frames(
        key_moments=moments,
        transcript=transcript,
        item_ref=candidate.item_ref,
        vault_context=vault_context,
        write_guard=write_guard,
        youtube_attachment_root=youtube_attachment_root,
        media_capture=media_capture,
    )
    if result.status == "frames_retained":
        return replace(
            candidate,
            moment_frames=result.frames,
            frames_status=f"frames_retained; {len(result.frames)} retained; manifest={result.manifest_path}",
        )
    if result.status == "already_captured":
        frames = _retained()
        return replace(
            candidate,
            moment_frames=frames,
            frames_status=f"already_captured; manifest={result.manifest_path}",
        )
    return replace(candidate, frames_status=f"timestamps-only ({result.degraded_reason or result.status})")


def _claims_extraction(extractions: Sequence[ExtractionResult]) -> PersistedExtraction | None:
    result = next((item for item in extractions if item.extractor_id == "claims"), None)
    if result is None or result.artifact_id is None:
        return None
    return load_extraction_artifact(result.artifact_id)


__all__ = ["attach_key_moments"]
