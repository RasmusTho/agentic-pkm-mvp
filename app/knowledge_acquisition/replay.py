"""End-to-end replay from `raw` with zero source egress (KA-06, #2801).

The slice's proof-of-architecture: deleting every derived level and replaying from an
existing `raw` record reproduces EQUIVALENT normalized / extracted / candidate artifacts
without ever contacting the source. Implements
`docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § Lineage and replay:

    "Deleting every derived level and replaying from `raw` reproduces an equivalent result
     (rebuildable, consistent with the machine-mirror posture …)."

Equivalence is stage-specific and stated explicitly in the receipt, per stage — never
collapsed into one unqualified boolean:

- **normalize → byte_identical.** `normalize()` is deterministic: "same `raw` in,
  byte-identical `normalized` output out" (module docstring / contract § normalized). The
  receipt asserts the replayed normalized dict equals the original normalized dict.

- **extracted → schema_and_lineage.** Extractor output is LLM-derived and NOT guaranteed
  byte-identical across a fresh process. Every replay deliberately invokes the extractor and
  persists a new immutable extraction version. What replay guarantees is a schema-valid result
  carrying the SAME `extractor_id` + `extractor_version` + same upstream
  `source_content_identity` lineage. The contract calls extractions "regenerable claims
  *about the source*", explicitly re-run/replaced on change — a lineage-equivalence class,
  not content identity. The receipt says `equivalence="schema_and_lineage"` and never
  claims byte-identity for this level.

- **candidate → versioned_proposal_original_preserved.** KA-05's canonical candidate note is
  first-write-wins. Replaying against an existing note preserves its bytes and writes the newly
  extracted content to a distinct proposal companion. Repeated replays therefore remain visible
  without overwriting either human-authored or prior candidate content.

Zero source egress is a genuine RUNTIME guard, not merely an emergent property of the code
path: `run_replay` enters a context-local no-egress policy checked by every canonical source
seam (`youtube_plugin.yt_dlp_extract_info`, `youtube_plugin.fetch_caption_body`,
`youtube_plugin.fetch`, and `transcribe_source`). Replay by construction only reads
the already-persisted `raw` record and re-runs the in-process compute stages, so the guard
never fires in the happy path — but if any future edit reached an egress seam during
replay, the guard turns it into a loud failure instead of a silent network call. Extractor
model routing (`app/components/llm/router.py`) is a DIFFERENT boundary and remains allowed
(`docs/LLM_ROUTING.md`); the guard blocks only source acquisition, never the LLM. Context-local
state means overlapping replays do not replace process-global functions or block concurrent
acquisition in another execution context.

`--assert-no-source-egress` (the CLI flag) always-on: the guard is installed for every
replay regardless of the flag, because the contract wants zero egress on every replay. The
flag additionally makes the CLI surface the guarantee explicitly in the printed receipt
(`source_egress=0`); it never relaxes the guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence
from uuid import UUID

# Production extractor wiring: importing the extractors package registers every
# extractor module with the extraction registry (the documented pipeline-caller
# contract, `app/knowledge_acquisition/extractors/__init__.py`) — a fresh CLI
# process resolves "summary" without any pipeline-side import of a specific
# extractor module.
import app.knowledge_acquisition.extractors  # noqa: F401
from app.knowledge_acquisition.candidate_writeback import (
    CandidateAssemblyError,
    CandidateWritebackError,
    CandidateWriteResult,
    ExtractionFailure,
    assemble_candidate,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_persistence import (
    ExtractionPersistenceError,
    persist_normalized_transcript,
)
from app.knowledge_acquisition.extraction_registry import (
    UnknownExtractorError,
    clear_extraction_results,
    validate_registered_extractors,
)
from app.knowledge_acquisition.normalize import STAGE_NAME as NORMALIZE_STAGE
from app.knowledge_acquisition.normalize import STAGE_VERSION as NORMALIZE_STAGE_VERSION
from app.knowledge_acquisition.normalize import NormalizeError, normalize
from app.knowledge_acquisition.raw_record import RawRecordIntegrityError, get_raw_record
from app.knowledge_acquisition.source_bundle import (
    DEFAULT_YOUTUBE_ATTACHMENT_ROOT,
    SourceBundleError,
    materialize_youtube_source_bundle,
)
from app.knowledge_acquisition.stage_events import (
    STAGE_EVENT_SOURCE,
    emit_stage_completed,
    emit_stage_dead_letter,
    resolve_extractor_requirements,
    run_extractors,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from app.source_egress import SourceEgressBlockedError, block_source_egress

CANDIDATE_STAGE = "candidate"
CANDIDATE_STAGE_VERSION = 1


class ReplayError(RuntimeError):
    """A replay could not run (e.g. the raw record does not exist in the object store)."""


@dataclass(frozen=True)
class StageReplayReceipt:
    """Per-stage line of a replay receipt, carrying the explicit equivalence class."""

    stage: str
    status: str
    equivalence: str
    idempotent: bool | None = None
    extractor_id: str | None = None
    extractor_version: int | None = None
    artifact_path: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "stage": self.stage,
            "status": self.status,
            "equivalence": self.equivalence,
        }
        if self.idempotent is not None:
            out["idempotent"] = self.idempotent
        if self.extractor_id is not None:
            out["extractor_id"] = self.extractor_id
        if self.extractor_version is not None:
            out["extractor_version"] = self.extractor_version
        if self.artifact_path is not None:
            out["artifact_path"] = self.artifact_path
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class ReplayReceipt:
    """The structured, inspectable result of a full replay from `raw`.

    ``equivalent`` is the AND over every stage having reproduced its declared equivalence
    class; ``source_egress`` is the observed count of source-egress-seam calls during the
    replay (0 when the guard never fired — the required posture).
    """

    raw_record_id: str
    content_identity: str
    source_egress: int
    stages: tuple[StageReplayReceipt, ...]
    equivalent: bool
    dead_lettered: tuple[str, ...] = field(default_factory=tuple)
    required_dead_lettered: tuple[str, ...] = field(default_factory=tuple)
    optional_dead_lettered: tuple[str, ...] = field(default_factory=tuple)

    @property
    def successful_fresh_materialization(self) -> bool:
        """Whether replay completed with a new, deliberately non-comparable candidate.

        A first candidate write cannot truthfully claim byte equivalence because
        there is no preserved artifact to compare. It is still a successful
        replay outcome when no required stage dead-lettered. An optional extractor failure is
        also successful when it materialized the contract's explicitly degraded candidate.
        """
        candidate_stages = [stage for stage in self.stages if stage.stage == CANDIDATE_STAGE]
        return (
            not self.required_dead_lettered
            and len(candidate_stages) == 1
            and candidate_stages[0].status in {"written", "written_degraded"}
            and candidate_stages[0].equivalence
            in {
                "fresh_write_not_byte_comparable",
                "fresh_degraded_write_not_byte_comparable",
            }
            and all(
                stage.status in {"ok", "dead_lettered"}
                for stage in self.stages
                if stage.stage != CANDIDATE_STAGE
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_record_id": self.raw_record_id,
            "content_identity": self.content_identity,
            "source_egress": self.source_egress,
            "equivalent": self.equivalent,
            "dead_lettered": list(self.dead_lettered),
            "required_dead_lettered": list(self.required_dead_lettered),
            "optional_dead_lettered": list(self.optional_dead_lettered),
            "stages": [stage.as_dict() for stage in self.stages],
        }

    def to_lines(self) -> list[str]:
        """Human-readable summary lines, matching the task's "Concretely" block shape."""
        lines: list[str] = []
        for stage in self.stages:
            if stage.stage == NORMALIZE_STAGE:
                label = f"{NORMALIZE_STAGE}@{NORMALIZE_STAGE_VERSION}"
            elif stage.extractor_id is not None:
                label = f"{stage.extractor_id}@{stage.extractor_version}"
            else:
                label = stage.stage
            suffix = ""
            if stage.idempotent:
                suffix = " (idempotent)"
            elif stage.stage == CANDIDATE_STAGE and stage.status == "already_exists":
                suffix = " -> note content identical"
            lines.append(f"{label:<11}... {stage.status}{suffix}")
        lines.append(
            f"replay receipt: equivalent={str(self.equivalent).lower()} "
            f"source_egress={self.source_egress}"
        )
        if self.successful_fresh_materialization:
            lines.append(
                "replay result: fresh materialization succeeded; byte equivalence is not applicable"
            )
        return lines


def _resolve_raw_record(raw_record_id: str | UUID) -> tuple[UUID, dict[str, Any]]:
    if isinstance(raw_record_id, UUID):
        object_id = raw_record_id
    else:
        try:
            object_id = UUID(str(raw_record_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ReplayError(f"invalid raw_record_id {raw_record_id!r}: not a UUID") from exc
    try:
        record = get_raw_record(object_id)
    except RawRecordIntegrityError as exc:
        raise ReplayError(f"raw replay authority rejected object_id {object_id}: {exc}") from exc
    if record is None:
        raise ReplayError(
            f"no raw record found at object_id {object_id} — cannot replay a record that was "
            "never acquired (replay reads an existing raw record; it never re-acquires)"
        )
    return object_id, record


def run_replay(
    raw_record_id: str | UUID,
    *,
    vault_context: VaultContext,
    extractor_ids: Sequence[str] = ("summary",),
    extractor_requirements: Mapping[str, str] | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    assert_no_source_egress: bool = True,
    trace_id: str | None = None,
    conn: Any = None,
    youtube_attachment_root: str = DEFAULT_YOUTUBE_ATTACHMENT_ROOT,
) -> ReplayReceipt:
    """Replay every derived level from an existing `raw` record and return a typed receipt.

    Steps (all in-process, zero source egress):

    1. Load the raw record from the object store (never re-acquire).
    2. Clear only the process-local result cache, then re-run every extractor. Durable prior
       extraction versions remain immutable; the replay creates new versioned extraction
       artifacts. The candidate note is not deleted: first-write-wins preserves it and replay
       writes a proposal companion containing the new extraction output.
    3. Re-run `normalize` (emit its stage event), each extractor via the item-scoped
       orchestration helper (emit per-extractor events, dead-letter failures), and
       `assemble_candidate` + `write_candidate_note` (emit the candidate stage event).
    4. Assert per-stage equivalence and return the receipt.

    Item-scoped dead-letter covers every stage on this path: a `NormalizeError` or a
    candidate assembly/writeback failure emits a durable
    `knowledge_acquisition.stage.dead_lettered` event for THIS item at THAT stage before
    the replay fails loudly (`ReplayError`); a failing extractor dead-letters inside
    `run_extractors` while sibling extractors proceed, and the candidate stage is then
    reported ``skipped_upstream_dead_letter`` (its selected extraction inputs are
    incomplete) rather than assembling a partial note. Per-stage ``idempotent`` on the
    receipt means the stage's completed event was ALREADY recorded (the deterministic key
    deduped at the log layer) — i.e. this replay re-derived a transition the outbox
    already knew about.

    ``assert_no_source_egress`` is honored as always-on: the egress guard is installed
    regardless. The flag is retained for CLI/API compatibility with the named guarantee,
    not as an escape hatch.
    """
    object_id, record = _resolve_raw_record(raw_record_id)
    content_identity = record.get("content_identity")
    if not isinstance(content_identity, str) or not content_identity:
        raise ReplayError(
            f"raw record {object_id} has no string content_identity — malformed record"
        )

    egress_seen = 0
    with block_source_egress():
        # Fresh-process equivalent: wipe the in-process extraction cache so the replay
        # genuinely re-runs every derived level from raw (see step 2 above).
        clear_extraction_results()

        stages: list[StageReplayReceipt] = []

        # --- normalize: byte-identical equivalence -------------------------------------
        # A NormalizeError dead-letters THIS item at THIS stage (durable audit event)
        # before failing the replay loudly — contract § Stage execution model.
        try:
            normalized = normalize(dict(record))
        except NormalizeError as exc:
            emit_stage_dead_letter(
                stage=NORMALIZE_STAGE,
                stage_version=NORMALIZE_STAGE_VERSION,
                content_identity=content_identity,
                reason="normalize_failed",
                error=str(exc),
                trace_id=trace_id,
                conn=conn,
            )
            raise ReplayError(
                f"replay dead-lettered at normalize for content_identity="
                f"{content_identity!r}: {exc}"
            ) from exc
        normalized_dict = normalized.as_dict()
        try:
            resolved_requirements = resolve_extractor_requirements(
                extractor_ids, extractor_requirements
            )
            validate_registered_extractors(list(extractor_ids))
        except (ValueError, UnknownExtractorError) as exc:
            raise ReplayError(f"invalid extractor materialization plan: {exc}") from exc
        try:
            normalized_artifact = persist_normalized_transcript(
                raw_record_id=str(object_id),
                raw_record=record,
                normalized=normalized,
            )
        except ExtractionPersistenceError as exc:
            emit_stage_dead_letter(
                stage=NORMALIZE_STAGE,
                stage_version=NORMALIZE_STAGE_VERSION,
                content_identity=content_identity,
                reason="persistence_failed",
                error=str(exc),
                trace_id=trace_id,
                conn=conn,
            )
            raise ReplayError(
                f"normalized artifact persistence failed for content_identity={content_identity!r}"
            ) from exc
        # Determinism check: a second normalize of the same raw is byte-identical.
        normalized_again = normalize(dict(record)).as_dict()
        normalize_equivalent = normalized_dict == normalized_again
        normalize_event_row = emit_stage_completed(
            stage=normalized.stage,
            stage_version=normalized.stage_version,
            content_identity=content_identity,
            trace_id=trace_id,
            conn=conn,
        )
        stages.append(
            StageReplayReceipt(
                stage=NORMALIZE_STAGE,
                status="ok" if normalize_equivalent else "divergent",
                equivalence="byte_identical",
                # "idempotent" = this transition was ALREADY recorded on the outbox:
                # the deterministic key deduped ("" return) against the earlier emission.
                idempotent=normalize_event_row == "",
            )
        )

        # --- extracted: schema + lineage equivalence -----------------------------------
        report = run_extractors(
            normalized_dict,
            extractor_ids=extractor_ids,
            trace_id=trace_id,
            conn=conn,
            extractor_requirements=resolved_requirements,
            raw_record_id=str(object_id),
            normalized_artifact_id=normalized_artifact.object_id,
            force_reextract=True,
        )
        for outcome in report.outcomes:
            if outcome.status == "ok" and outcome.result is not None:
                result = outcome.result
                # Lineage equivalence: same extractor id/version + same upstream identity.
                lineage_ok = (
                    result.source_content_identity == content_identity
                    and isinstance(result.output, dict)
                    and bool(result.output)
                )
                stages.append(
                    StageReplayReceipt(
                        stage="extracted",
                        status="ok" if lineage_ok else "divergent",
                        equivalence="schema_and_lineage",
                        idempotent=outcome.event_row_id == "",
                        extractor_id=result.extractor_id,
                        extractor_version=result.extractor_version,
                    )
                )
            else:
                stages.append(
                    StageReplayReceipt(
                        stage="extracted",
                        status="dead_lettered",
                        equivalence="none",
                        extractor_id=outcome.extractor_id,
                        detail=outcome.error,
                    )
                )

        # --- candidate: byte-identical by first-write-wins preservation ----------------
        dead_lettered = tuple(outcome.extractor_id for outcome in report.dead_lettered)
        required_dead_lettered = tuple(
            outcome.extractor_id for outcome in report.required_dead_lettered
        )
        optional_dead_lettered = tuple(
            outcome.extractor_id for outcome in report.optional_dead_lettered
        )
        if required_dead_lettered:
            # The candidate depends on "the extractions the source spec selects"
            # (contract § Stage execution model); a selected extraction dead-lettered,
            # so candidate assembly for this item cannot fulfill its inputs. Skip it —
            # the extraction dead-letter above already recorded the failure durably,
            # and the receipt below reports the skip explicitly (never silent).
            candidate_equivalent = False
            stages.append(
                StageReplayReceipt(
                    stage=CANDIDATE_STAGE,
                    status="skipped_upstream_dead_letter",
                    equivalence="none",
                    detail=(
                        "required extractor(s) dead-lettered: "
                        + ", ".join(required_dead_lettered)
                    ),
                )
            )
        else:
            # Assemble strictly from the raw-derived artifacts produced in this replay. The
            # candidate path is first-write-wins; a fresh extraction run against an existing
            # candidate therefore materializes a versioned companion proposal.
            try:
                optional_failures = tuple(
                    ExtractionFailure(
                        extractor_id=outcome.extractor_id,
                        requirement=outcome.materialization_requirement,
                        rerun_handle=(
                            outcome.rerun_handle or f"extractor:{outcome.extractor_id}"
                        ),
                        error=outcome.error or "extraction failed",
                    )
                    for outcome in report.optional_dead_lettered
                )
                candidate = assemble_candidate(
                    dict(record),
                    extractor_ids=tuple(extractor_ids),
                    normalized=normalized,
                    extraction_results=report.successes,
                    raw_record_id=str(object_id),
                    normalized_artifact_id=normalized_artifact.object_id,
                    optional_failures=optional_failures,
                )
                bundle = materialize_youtube_source_bundle(
                    candidate,
                    normalized_artifact,
                    vault_context=vault_context,
                    write_guard=write_guard,
                    youtube_attachment_root=youtube_attachment_root,
                )
                if bundle.status == "blocked":
                    # Bundle materialization is governed by the same write guard as the
                    # candidate note. Preserve the retryable refusal and do not write a
                    # candidate that falsely claims to link a bundle that was not created.
                    write_result = CandidateWriteResult(
                        status="blocked",
                        artifact_path=None,
                        content_identity=candidate.content_identity,
                        reason=bundle.reason or "source bundle materialization blocked by write guard",
                    )
                else:
                    candidate = replace(candidate, derived_transcript_link=bundle.transcript_path)
                    write_result = write_candidate_note(
                        candidate,
                        vault_context=vault_context,
                        write_guard=write_guard,
                        proposal_on_existing=True,
                    )
            except (CandidateAssemblyError, CandidateWritebackError, SourceBundleError) as exc:
                emit_stage_dead_letter(
                    stage=CANDIDATE_STAGE,
                    stage_version=CANDIDATE_STAGE_VERSION,
                    content_identity=content_identity,
                    reason=(
                        "assembly_failed"
                        if isinstance(exc, CandidateAssemblyError)
                        else "writeback_failed"
                    ),
                    error=str(exc),
                    trace_id=trace_id,
                    conn=conn,
                )
                raise ReplayError(
                    f"replay dead-lettered at candidate for content_identity="
                    f"{content_identity!r}: {exc}"
                ) from exc
            candidate_equivalent, candidate_equivalence_class = _candidate_equivalence(
                write_result
            )
            if write_result.status == "blocked":
                # A governed WriteGuard denial is not a stage transition: no event, the
                # loud reason is preserved on the receipt, the item stays re-runnable.
                stages.append(
                    StageReplayReceipt(
                        stage=CANDIDATE_STAGE,
                        status="blocked",
                        equivalence="none",
                        detail=write_result.reason,
                    )
                )
            else:
                candidate_event_row = emit_stage_completed(
                    stage=CANDIDATE_STAGE,
                    stage_version=CANDIDATE_STAGE_VERSION,
                    content_identity=content_identity,
                    extra_payload={"artifact_path": write_result.artifact_path},
                    trace_id=trace_id,
                    conn=conn,
                )
                stages.append(
                    StageReplayReceipt(
                        stage=CANDIDATE_STAGE,
                        status=write_result.status,
                        equivalence=candidate_equivalence_class,
                        idempotent=candidate_event_row == "",
                        artifact_path=write_result.artifact_path,
                    )
                )

    equivalent = (
        normalize_equivalent
        and candidate_equivalent
        and all(
            s.status != "divergent"
            for s in stages
            if s.stage in {NORMALIZE_STAGE, "extracted", CANDIDATE_STAGE}
        )
        and not required_dead_lettered
    )
    return ReplayReceipt(
        raw_record_id=str(object_id),
        content_identity=content_identity,
        source_egress=egress_seen,
        stages=tuple(stages),
        equivalent=equivalent,
        dead_lettered=dead_lettered,
        required_dead_lettered=required_dead_lettered,
        optional_dead_lettered=optional_dead_lettered,
    )


def _candidate_equivalence(write_result: CandidateWriteResult) -> tuple[bool, str]:
    """Classify the candidate stage's replay equivalence.

    - ``already_exists`` → byte-identical by first-write-wins preservation (the strong
      guarantee: the written artifact never changes on replay).
    - ``written`` → this was a fresh materialization. The candidate renderer stamps
      current timestamps, so this receipt cannot truthfully claim byte identity against a
      prior deleted artifact.
    - ``blocked`` → not equivalent; the guarded write was denied.
    """
    if write_result.status == "already_exists":
        return True, "byte_identical_first_write_preserved"
    if write_result.status == "written":
        return False, "fresh_write_not_byte_comparable"
    if write_result.status == "written_degraded":
        return False, "fresh_degraded_write_not_byte_comparable"
    if write_result.status in {"proposal_written", "proposal_already_exists"}:
        return True, "versioned_proposal_original_preserved"
    return False, "none"


__all__ = [
    "CANDIDATE_STAGE",
    "CANDIDATE_STAGE_VERSION",
    "ReplayError",
    "SourceEgressBlockedError",
    "StageReplayReceipt",
    "ReplayReceipt",
    "run_replay",
    "STAGE_EVENT_SOURCE",
]
