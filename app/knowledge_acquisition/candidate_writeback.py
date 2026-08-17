"""Candidate assembly + governed `youtube_source_note` writeback (KA-05).

The pipeline's terminal stage. Implements
`docs/KNOWLEDGE_ACQUISITION/CANDIDATE_WRITEBACK.md` and
`docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § `candidate`:
bundle selected extractions into the artifact shape the ingestion/triage
policy specifies, then write the `youtube_source_note` companion artifact
into the vault through the governed vault-write path
(`app.write_guard.WriteGuard`) — the only place this platform touches
human-visible surfaces.

Design decisions (per the coordinator's already-made calls, not relitigated
here):

- **Assembly accepts explicit durable lineage.** The acquisition/replay orchestrators pass the
  raw-derived normalized and extraction artifacts they just resolved. Direct callers may still
  re-derive in-process for compatibility, but persisted candidates carry raw, normalized, and
  extraction artifact ids.
- **No outbox/stage-event emission.** That is KA-06 (#2801). This module
  never touches `app.outbox.events` (tracked non-idempotent per #2881) or any
  other event-emission seam; the vault write flows into the existing
  watcher/vault-sync pipeline on its own.
- **Idempotent note write, new-note-per-item.** The vault path is derived
  deterministically from the candidate's `content_identity` (never a random
  uuid), so re-running the same candidate always targets the same path. If a
  note already exists at that path, it is never overwritten. A fresh re-extraction instead writes
  a versioned `.meta.md` proposal companion through the same atomic governed-write seam.

What this module MUST NOT do (`REFINEMENT_PIPELINE_CONTRACT.md` §"What the
pipeline MUST NOT do"):

- Advance triage state beyond `captured`, or mutate any *existing* artifact's
  governance-bearing metadata. Stamping the mandated initial posture on the
  candidate note this module itself creates is the sole exception.
- Promote anything into `evergreen_note` / `synthesis_note` / `decision_record`.
- Perform any filesystem write outside the governed `WriteGuard` call site —
  the write call site in `write_candidate_note()` is the only place this
  module touches the filesystem, and it always calls
  `write_guard.assert_writes_allowed(...)` immediately before the write.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from app.knowledge.write_ops import (
    candidate_note_exists_durable,
    create_candidate_note_once,
)
from app.knowledge_acquisition.extraction_registry import ExtractionResult, run_extractor
from app.knowledge_acquisition.note_renderer import (
    NoteRenderError,
    ProposalSection,
    render_review_required_note,
)
from app.knowledge_acquisition.normalize import has_usable_transcript, normalize
from app.knowledge_acquisition.normalize import NormalizedTranscript
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

CANDIDATE_WRITE_ACTION = "knowledge_acquisition.candidate_writeback"
ARTIFACT_CLASS = "youtube_source_note"
TRIAGE_STATE_CAPTURED = "captured"
DEFAULT_SOURCES_DIR = "Sources"

# Mandated non-authoritative posture markers (INGESTION_AND_TRIAGE_POLICY.md §3;
# token mapping per the #2793 owner decision, 2026-07-02, cited in
# YOUTUBE_SOURCE_SPEC.md § Writeback). These are the only values this module is
# permitted to stamp — never `reviewed`/`protected`/etc.
REVIEW_STATE_DRAFT = "draft"


class CandidateAssemblyError(RuntimeError):
    """Raised when a candidate cannot be assembled from a `raw` record."""


class CandidateWritebackError(RuntimeError):
    """Raised when a note write fails for a reason other than a governed block.

    Item-scoped: the candidate itself is untouched and remains re-runnable.
    """


@dataclass(frozen=True)
class Candidate:
    """A `candidate`-level artifact: selected extractions bundled for triage.

    Carries everything `write_candidate_note` needs to render the vault note
    and derive its deterministic path, without depending on the `raw` record
    shape again.
    """

    content_identity: str
    source_kind: str
    item_ref: str
    url: str
    title: str
    creator: str | None
    published: str | None
    acquisition_method: str
    transcript_available: bool
    extractions: tuple[ExtractionResult, ...]
    transcript_segment_count: int = 0
    raw_record_id: str | None = None
    normalized_artifact_id: str | None = None
    extraction_artifact_ids: tuple[str, ...] = ()
    optional_failures: tuple["ExtractionFailure", ...] = ()
    derived_transcript_link: str | None = None

    def summary_text(self) -> str | None:
        for extraction in self.extractions:
            if extraction.extractor_id == "summary":
                return extraction.output.get("summary")
        return None

    def summary_confidence(self) -> float | None:
        for extraction in self.extractions:
            if extraction.extractor_id != "summary":
                continue
            value = extraction.output.get("confidence")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                return float(value)
        return None


@dataclass(frozen=True)
class CandidateWriteResult:
    status: str
    artifact_path: str | None
    content_identity: str
    reason: str | None = None


@dataclass(frozen=True)
class ExtractionFailure:
    extractor_id: str
    requirement: str
    rerun_handle: str
    error: str


def assemble_candidate(
    raw_record: Mapping[str, Any],
    *,
    extractor_ids: Sequence[str] = ("summary",),
    normalized: NormalizedTranscript | None = None,
    extraction_results: Sequence[ExtractionResult] | None = None,
    raw_record_id: str | None = None,
    normalized_artifact_id: str | None = None,
    optional_failures: Sequence[ExtractionFailure] = (),
) -> Candidate:
    """Assemble a `candidate` from a `raw` record and explicit derived lineage when supplied.

    Raises `CandidateAssemblyError` if the raw record is missing required
    fields, wrapping the item-scoped failure a stage would otherwise raise
    (`NormalizeError` / `ExtractionError` / `UnknownExtractorError`) so a
    caller iterating many candidates gets one exception family at this
    boundary. Nothing here mutates the `raw_record` argument.
    """
    content_identity = raw_record.get("content_identity")
    if not content_identity or not isinstance(content_identity, str):
        raise CandidateAssemblyError("raw_record.content_identity is required and must be a string")
    source_kind = raw_record.get("source_kind")
    item_ref = raw_record.get("item_ref")
    if not source_kind or not item_ref:
        raise CandidateAssemblyError("raw_record.source_kind and item_ref are required")

    metadata = raw_record.get("metadata") or {}
    provenance = raw_record.get("provenance") or {}

    try:
        normalized_result = normalized or normalize(dict(raw_record))
    except Exception as exc:  # noqa: BLE001 - re-raised as the assembly-scoped error below
        raise CandidateAssemblyError(
            f"normalize() failed for content_identity={content_identity!r}: {exc}"
        ) from exc

    normalized_dict = normalized_result.as_dict()
    transcript_segment_count = len(normalized_result.segments)
    transcript_available = has_usable_transcript(normalized_result)
    extractions: list[ExtractionResult] = []
    if extraction_results is not None:
        extractions.extend(extraction_results)
    elif transcript_available:
        for extractor_id in extractor_ids:
            try:
                extractions.append(run_extractor(extractor_id, normalized_dict))
            except Exception as exc:  # noqa: BLE001 - re-raised as the assembly-scoped error below
                raise CandidateAssemblyError(
                    f"extractor {extractor_id!r} failed for "
                    f"content_identity={content_identity!r}: {exc}"
                ) from exc

    return Candidate(
        content_identity=content_identity,
        source_kind=str(source_kind),
        item_ref=str(item_ref),
        url=str(raw_record.get("url") or provenance.get("url") or ""),
        title=str(metadata.get("title") or item_ref),
        creator=metadata.get("channel") or provenance.get("creator"),
        published=metadata.get("publish_date") or provenance.get("published"),
        acquisition_method=str(raw_record.get("acquisition_method") or ""),
        transcript_available=transcript_available,
        extractions=tuple(extractions),
        transcript_segment_count=transcript_segment_count,
        raw_record_id=raw_record_id,
        normalized_artifact_id=normalized_artifact_id,
        extraction_artifact_ids=tuple(
            result.artifact_id for result in extractions if result.artifact_id is not None
        ),
        optional_failures=tuple(optional_failures),
    )


def candidate_note_path(candidate: Candidate, *, sources_dir: str = DEFAULT_SOURCES_DIR) -> str:
    """Deterministic vault-relative path for a candidate's note.

    Derived from `content_identity` (never a random id), so re-running the
    same candidate always targets the same path — the idempotency the spec's
    Restart/Durability posture requires ("same note path, same content
    identity").

    The identity's scheme prefix (e.g. ``sha256:``) is stripped before the
    16-char window is taken, so all 16 characters are hash payload. Slugging
    the full ``sha256:<hex>`` string would spend 7 of the 16 characters on
    the constant ``sha256-`` prefix, leaving only ~9 hex chars of
    discriminating entropy — two identities differing after the 16th
    character of the full string would collide onto the same path (opus
    review round 1 finding on #2800).
    """
    safe_dir = _safe_rel_path(sources_dir)
    slug = _slug(candidate.title)
    identity_payload = candidate.content_identity.split(":", 1)[-1]
    short_identity = _slug(identity_payload)[:16] or "item"
    return (PurePosixPath(safe_dir) / f"{slug}-{short_identity}.md").as_posix()


def render_candidate_note(candidate: Candidate) -> str:
    """Compose the candidate into explicit owner/proposal/evidence bands."""
    now = _iso(datetime.now(timezone.utc))
    frontmatter: dict[str, Any] = {
        "artifact_class": ARTIFACT_CLASS,
        "lifecycle": "active",
        "work_relation": "learn",
        "provenance": {
            "source_kind": candidate.source_kind,
            "url": candidate.url,
            "creator": candidate.creator,
            "published": candidate.published,
            "content_identity": candidate.content_identity,
            "acquisition_method": candidate.acquisition_method,
        },
        "watched_status": "queued",
        "transcript_available": candidate.transcript_available,
        "authority": {
            "source_authoritative": False,
            "ai_generated": True,
            # Mandated posture markers (INGESTION_AND_TRIAGE_POLICY.md §3;
            # #2793 token mapping) — the template extension this slice ships.
            "requires_review": True,
        },
        "review_state": REVIEW_STATE_DRAFT,
        "triage_state": TRIAGE_STATE_CAPTURED,
        "created": now,
        "updated": now,
    }
    if candidate.raw_record_id is not None:
        frontmatter["raw_record_id"] = candidate.raw_record_id
    if candidate.normalized_artifact_id is not None:
        frontmatter["normalized_artifact_id"] = candidate.normalized_artifact_id
    if candidate.extraction_artifact_ids:
        frontmatter["extraction_artifact_ids"] = list(candidate.extraction_artifact_ids)
    if candidate.optional_failures:
        frontmatter["degraded"] = True
        frontmatter["unavailable_optional_extractors"] = [
            failure.extractor_id for failure in candidate.optional_failures
        ]

    proposal_sections = _candidate_proposal_sections(candidate)
    coverage = (
        f"{candidate.transcript_segment_count}/{candidate.transcript_segment_count} "
        "normalized segments (100%; complete transcript)"
        if candidate.transcript_available and candidate.transcript_segment_count > 0
        else "0 normalized segments; no transcript evidence"
    )
    return render_review_required_note(
        frontmatter=frontmatter,
        proposal_sections=proposal_sections,
        evidence=(
            ("Title", candidate.title),
            ("Source URL", candidate.url),
            ("Content identity", candidate.content_identity),
            ("Acquisition method", candidate.acquisition_method),
            (
                "Transcript",
                (
                    f"available; {candidate.transcript_segment_count} normalized segments"
                    if candidate.transcript_available
                    else "unavailable"
                ),
            ),
            ("Coverage", coverage),
            (
                "Durable lineage",
                (
                    f"raw={candidate.raw_record_id or 'legacy'}; "
                    f"normalized={candidate.normalized_artifact_id or 'legacy'}; "
                    f"extractions={','.join(candidate.extraction_artifact_ids) or 'none'}"
                ),
            ),
            ("Derived transcript", candidate.derived_transcript_link or "not materialized"),
            (
                "Materialization status",
                (
                    "degraded; optional failures: "
                    + ", ".join(failure.extractor_id for failure in candidate.optional_failures)
                    if candidate.optional_failures
                    else "complete"
                ),
            ),
        ),
    )


def _candidate_proposal_sections(candidate: Candidate) -> tuple[ProposalSection, ...]:
    """Render reviewable extraction outputs without assigning them authority."""
    summary = candidate.summary_text()
    confidence = candidate.summary_confidence()
    sections: list[ProposalSection] = []
    if summary is not None and confidence is not None and candidate.transcript_segment_count > 0:
        sections.append(
            ProposalSection(
                module_id="summary",
                title="Summary",
                content=(
                    f"**Model confidence (non-authoritative):** {confidence:g}\n" "\n" f"{summary}"
                ),
            )
        )
    if candidate.optional_failures:
        sections.append(
            ProposalSection(
                module_id="extraction-gaps",
                title="Degraded extraction status",
                content="\n".join(
                    (
                        f"- Optional extractor `{failure.extractor_id}` is unavailable. "
                        f"Rerun handle: `{failure.rerun_handle}`."
                    )
                    for failure in candidate.optional_failures
                ),
            )
        )
    if candidate.derived_transcript_link:
        sections.append(
            ProposalSection(
                module_id="derived-transcript",
                title="Derived transcript",
                content=(
                    "Derived transcript reference (never replay input): "
                    f"[[{candidate.derived_transcript_link}]]"
                ),
            )
        )
    return tuple(sections)


def write_candidate_note(
    candidate: Candidate,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    sources_dir: str = DEFAULT_SOURCES_DIR,
    proposal_on_existing: bool = False,
) -> CandidateWriteResult:
    """The governed vault-write call site: the only place this module touches
    the filesystem.

    The existing-target probe runs before render and WriteGuard, and mutates
    nothing. For a missing target, the candidate-only knowledge helper asserts
    `write_guard.assert_writes_allowed(CANDIDATE_WRITE_ACTION)` before parent
    preparation or stage creation. Long acquisition and render work therefore
    owns no publication resource.

    A `WritesBlockedError` is caught here and returned as an item-scoped
    `status="blocked"` result: loud (the reason is preserved), never silent,
    and the candidate is untouched — nothing durable was written, so it
    remains re-runnable on the very next attempt (not terminal).

    If a note already exists at the deterministic path for this `content_identity`, it is never
    overwritten. Ordinary acquisition is a traced no-op; `proposal_on_existing=True` creates a
    versioned proposal companion for a fresh extraction.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = candidate_note_path(candidate, sources_dir=sources_dir)

    try:
        target_exists = candidate_note_exists_durable(
            artifact_path,
            vault_root=vault_root,
        )
    except Exception as exc:  # noqa: BLE001 - re-raised as the item-scoped error below
        raise CandidateWritebackError(
            f"candidate note probe failed for content_identity="
            f"{candidate.content_identity!r} at {artifact_path!r}: {exc}"
        ) from exc

    if target_exists:
        if proposal_on_existing and candidate.extraction_artifact_ids:
            return _write_versioned_proposal(
                candidate,
                predecessor_path=artifact_path,
                vault_root=vault_root,
                write_guard=write_guard,
            )
        return CandidateWriteResult(
            status="already_exists",
            artifact_path=artifact_path,
            content_identity=candidate.content_identity,
        )

    try:
        content = render_candidate_note(candidate)
    except NoteRenderError as exc:
        raise CandidateWritebackError(
            f"candidate note render failed for content_identity="
            f"{candidate.content_identity!r}: {exc}"
        ) from exc

    try:
        status = create_candidate_note_once(
            artifact_path,
            content,
            vault_root=vault_root,
            action=CANDIDATE_WRITE_ACTION,
            write_guard=write_guard,
        )
    except WritesBlockedError as exc:
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            content_identity=candidate.content_identity,
            reason=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - re-raised as the item-scoped error below
        raise CandidateWritebackError(
            f"candidate note write failed for content_identity="
            f"{candidate.content_identity!r} at {artifact_path!r}: {exc}"
        ) from exc

    if status == "already_exists" and proposal_on_existing and candidate.extraction_artifact_ids:
        # Another replay won candidate first-materialization after our initial durable probe.
        # Reconcile the losing fresh extraction into its own proposal instead of dropping it.
        return _write_versioned_proposal(
            candidate,
            predecessor_path=artifact_path,
            vault_root=vault_root,
            write_guard=write_guard,
        )
    return CandidateWriteResult(
        status=(
            "written_degraded"
            if status == "written" and candidate.optional_failures
            else status
        ),
        artifact_path=artifact_path,
        content_identity=candidate.content_identity,
    )


def _write_versioned_proposal(
    candidate: Candidate,
    *,
    predecessor_path: str,
    vault_root: Path,
    write_guard: WriteGuard,
) -> CandidateWriteResult:
    """Atomically create one D5 proposal companion without touching predecessor bytes."""
    identity_material = "\n".join(candidate.extraction_artifact_ids)
    proposal_reference = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()[:20]
    predecessor = PurePosixPath(predecessor_path)
    max_version = max((item.extractor_version for item in candidate.extractions), default=0)
    proposal_name = (
        f"{predecessor.stem}-proposal-extracted-v{max_version}-"
        f"{proposal_reference}.meta.md"
    )
    proposal_path = predecessor.with_name(proposal_name).as_posix()
    now = _iso(datetime.now(timezone.utc))
    content = render_review_required_note(
        frontmatter={
            "artifact_class": "youtube_source_note_proposal",
            "authority": {"ai_generated": True, "requires_review": True},
            "review_state": REVIEW_STATE_DRAFT,
            "content_identity": candidate.content_identity,
            "predecessor_ref": predecessor_path,
            "proposal_reference": proposal_reference,
            "raw_record_id": candidate.raw_record_id,
            "normalized_artifact_id": candidate.normalized_artifact_id,
            "extraction_artifact_ids": list(candidate.extraction_artifact_ids),
            "write_receipt": f"create-once:{proposal_path}",
            "created": now,
            "updated": now,
        },
        proposal_sections=(
            ProposalSection(
                module_id="reextraction",
                title="Re-extraction proposal",
                content=(
                    "This versioned companion proposes newly extracted material for human "
                    "review. It does not alter the predecessor candidate."
                ),
            ),
            *_candidate_proposal_sections(candidate),
        ),
        evidence=(
            ("Content identity", candidate.content_identity),
            ("Predecessor", predecessor_path),
            ("Proposal reference", proposal_reference),
            ("Raw record", candidate.raw_record_id or "unknown"),
            ("Normalized artifact", candidate.normalized_artifact_id or "unknown"),
            ("Extraction artifacts", ",".join(candidate.extraction_artifact_ids)),
            ("Write receipt", f"create-once:{proposal_path}"),
        ),
    )
    try:
        status = create_candidate_note_once(
            proposal_path,
            content,
            vault_root=vault_root,
            action=CANDIDATE_WRITE_ACTION,
            write_guard=write_guard,
        )
    except WritesBlockedError as exc:
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            content_identity=candidate.content_identity,
            reason=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - item-scoped writeback error
        raise CandidateWritebackError(
            f"versioned proposal write failed for content_identity="
            f"{candidate.content_identity!r} at {proposal_path!r}: {exc}"
        ) from exc
    return CandidateWriteResult(
        status="proposal_written" if status == "written" else "proposal_already_exists",
        artifact_path=proposal_path,
        content_identity=candidate.content_identity,
        reason=f"write_receipt=create-once:{status}:{proposal_path}",
    )


def _vault_root(context: VaultContext) -> Path:
    if not context.active_vault_path:
        raise CandidateWritebackError("vault_context.active_vault_path is required")
    return Path(context.active_vault_path).expanduser().resolve()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "item"


def _safe_rel_path(value: str) -> str:
    path = PurePosixPath(value)
    if value.startswith("/") or ".." in path.parts:
        raise CandidateWritebackError("sources_dir must stay vault-relative")
    return path.as_posix()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ARTIFACT_CLASS",
    "CANDIDATE_WRITE_ACTION",
    "REVIEW_STATE_DRAFT",
    "TRIAGE_STATE_CAPTURED",
    "Candidate",
    "CandidateAssemblyError",
    "CandidateWriteResult",
    "CandidateWritebackError",
    "ExtractionFailure",
    "assemble_candidate",
    "candidate_note_path",
    "render_candidate_note",
    "write_candidate_note",
]
