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

- **Assembly re-derives from `raw` in-process.** `assemble_candidate()` calls
  `normalize()` and `run_extractor()` itself rather than accepting a durable
  extraction-results handoff — KA-04's process-local idempotency cache is an
  optimization, not a durable store, per the spec's Restart/Durability
  posture ("Candidate assembly state is derived and re-runnable from raw").
- **No outbox/stage-event emission.** That is KA-06 (#2801). This module
  never touches `app.outbox.events` (tracked non-idempotent per #2881) or any
  other event-emission seam; the vault write flows into the existing
  watcher/vault-sync pipeline on its own.
- **Idempotent note write, new-note-per-item.** The vault path is derived
  deterministically from the candidate's `content_identity` (never a random
  uuid), so re-running the same candidate always targets the same path. If a
  note already exists at that path, the write is a traced no-op — this slice
  never overwrites an existing artifact (note UPDATES on re-acquisition are
  out of scope per the spec).

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

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml

from app.knowledge.write_ops import write_note_relative
from app.knowledge_acquisition.extraction_registry import ExtractionResult, run_extractor
from app.knowledge_acquisition.normalize import normalize
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
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None


@dataclass(frozen=True)
class CandidateWriteResult:
    status: str  # "written" | "already_exists" | "blocked"
    artifact_path: str | None
    content_identity: str
    reason: str | None = None


def assemble_candidate(
    raw_record: Mapping[str, Any],
    *,
    extractor_ids: Sequence[str] = ("summary",),
) -> Candidate:
    """Assemble a `candidate` from a `raw` record, re-deriving `normalized` and
    every requested extraction in-process (no durable extraction-results
    handoff; see module docstring).

    Raises `CandidateAssemblyError` if the raw record is missing required
    fields, wrapping the item-scoped failure a stage would otherwise raise
    (`NormalizeError` / `ExtractionError` / `UnknownExtractorError`) so a
    caller iterating many candidates gets one exception family at this
    boundary. Nothing here mutates the `raw_record` argument.
    """
    content_identity = raw_record.get("content_identity")
    if not content_identity or not isinstance(content_identity, str):
        raise CandidateAssemblyError(
            "raw_record.content_identity is required and must be a string"
        )
    source_kind = raw_record.get("source_kind")
    item_ref = raw_record.get("item_ref")
    if not source_kind or not item_ref:
        raise CandidateAssemblyError(
            "raw_record.source_kind and item_ref are required"
        )

    metadata = raw_record.get("metadata") or {}
    provenance = raw_record.get("provenance") or {}

    try:
        normalized = normalize(dict(raw_record))
    except Exception as exc:  # noqa: BLE001 - re-raised as the assembly-scoped error below
        raise CandidateAssemblyError(
            f"normalize() failed for content_identity={content_identity!r}: {exc}"
        ) from exc

    normalized_dict = normalized.as_dict()
    transcript_segment_count = len(normalized.segments)
    transcript_available = transcript_segment_count > 0
    extractions: list[ExtractionResult] = []
    if transcript_available:
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
    """Render the candidate note per the shipped template shape (Concretely block):
    About / AI summary (non-authoritative) / Human takeaways (empty).
    """
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
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    summary = candidate.summary_text()
    confidence = candidate.summary_confidence()
    if summary is not None and confidence is not None and candidate.transcript_segment_count > 0:
        segment_count = candidate.transcript_segment_count
        summary_section = (
            f"> **Model confidence (non-authoritative):** {confidence:g}\n"
            f"> **Coverage:** {segment_count}/{segment_count} normalized segments "
            "(100%; complete transcript)\n"
            ">\n"
            f"> {summary}"
        )
    else:
        summary_section = "> _AI summary goes here if generated. This is not human knowledge._"

    body = f"""
## About

{candidate.title}

## AI summary

<!-- [AI-suggested summary — non-authoritative. Do not promote into knowledge without review.] -->

{summary_section}

## Human takeaways

<!-- Add your own notes here as you watch. These are the first human-authored content in this note. -->

---

_The YouTube video URL is the authoritative source. The AI summary above is non-authoritative.
Promotion into durable knowledge (evergreen or synthesis notes) requires human review and creates
a distinct artifact; this source note is retained as provenance._
"""
    return f"---\n{yaml_block}\n---\n{body}"


def write_candidate_note(
    candidate: Candidate,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    sources_dir: str = DEFAULT_SOURCES_DIR,
) -> CandidateWriteResult:
    """The governed vault-write call site: the only place this module touches
    the filesystem.

    `write_guard.assert_writes_allowed(CANDIDATE_WRITE_ACTION)` runs
    immediately before the write via `write_note_relative` (the same
    `KnowledgePort`-backed helper `materialize_moment` /
    `materialize_promoted_memory` use) — WriteGuard is independently
    authoritative and this stage has no other path to disk.

    A `WritesBlockedError` is caught here and returned as an item-scoped
    `status="blocked"` result: loud (the reason is preserved), never silent,
    and the candidate is untouched — nothing durable was written, so it
    remains re-runnable on the very next attempt (not terminal).

    If a note already exists at the deterministic path for this
    `content_identity`, the write is a traced no-op (`status="already_exists"`)
    — this slice never overwrites an existing artifact.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = candidate_note_path(candidate, sources_dir=sources_dir)

    if (vault_root / artifact_path).exists():
        return CandidateWriteResult(
            status="already_exists",
            artifact_path=artifact_path,
            content_identity=candidate.content_identity,
        )

    content = render_candidate_note(candidate)

    try:
        write_guard.assert_writes_allowed(CANDIDATE_WRITE_ACTION)
    except WritesBlockedError as exc:
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            content_identity=candidate.content_identity,
            reason=str(exc),
        )

    try:
        write_note_relative(artifact_path, content, vault_root=vault_root)
    except Exception as exc:  # noqa: BLE001 - re-raised as the item-scoped error below
        raise CandidateWritebackError(
            f"candidate note write failed for content_identity="
            f"{candidate.content_identity!r} at {artifact_path!r}: {exc}"
        ) from exc

    return CandidateWriteResult(
        status="written",
        artifact_path=artifact_path,
        content_identity=candidate.content_identity,
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
    "assemble_candidate",
    "candidate_note_path",
    "render_candidate_note",
    "write_candidate_note",
]
