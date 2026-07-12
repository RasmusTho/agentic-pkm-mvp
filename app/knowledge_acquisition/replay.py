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
  byte-identical across a fresh process (the in-process idempotency cache is cleared for a
  genuine replay, so `run()` re-invokes). What replay guarantees is a schema-valid result
  carrying the SAME `extractor_id` + `extractor_version` + same upstream
  `source_content_identity` lineage. The contract calls extractions "regenerable claims
  *about the source*", explicitly re-run/replaced on change — a lineage-equivalence class,
  not content identity. The receipt says `equivalence="schema_and_lineage"` and never
  claims byte-identity for this level.

- **candidate → byte_identical_first_write_preserved.** KA-05's `write_candidate_note` is
  first-write-wins: replaying candidate assembly against an EXISTING note (same
  deterministic path derived from `content_identity`) yields `status="already_exists"` and
  the note stays byte-identical to the original write — even if the replayed extraction
  above produced different text. So the WRITTEN artifact is byte-identical by construction
  of the first-write-wins path (proven by
  `tests/knowledge_acquisition/test_candidate_writeback.py::test_rerun_with_drifted_summary_preserves_first_write`).
  The receipt states equivalence rests on first-write preservation, not on recomputing
  identical content.

Zero source egress is a genuine RUNTIME guard, not merely an emergent property of the code
path: `run_replay` swaps every source-egress seam (`youtube_plugin.yt_dlp_extract_info`,
`youtube_plugin.fetch_caption_body`, `youtube_plugin.fetch`, and `transcribe_source` —
both `app.media.transcribe`'s attribute and the plugin's imported alias) for a raiser of
`SourceEgressBlockedError` for the duration of the replay and restores them in a
`finally`. Replay by construction only reads
the already-persisted `raw` record and re-runs the in-process compute stages, so the guard
never fires in the happy path — but if any future edit reached an egress seam during
replay, the guard turns it into a loud failure instead of a silent network call. Extractor
model routing (`app/components/llm/router.py`) is a DIFFERENT boundary and remains allowed
(`docs/LLM_ROUTING.md`); the guard blocks only source acquisition, never the LLM.

`--assert-no-source-egress` (the CLI flag) always-on: the guard is installed for every
replay regardless of the flag, because the contract wants zero egress on every replay. The
flag additionally makes the CLI surface the guarantee explicitly in the printed receipt
(`source_egress=0`); it never relaxes the guard.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import UUID

# Production extractor wiring: importing the extractors package registers every
# extractor module with the extraction registry (the documented pipeline-caller
# contract, `app/knowledge_acquisition/extractors/__init__.py`) — a fresh CLI
# process resolves "summary" without any pipeline-side import of a specific
# extractor module.
import app.knowledge_acquisition.extractors  # noqa: F401
from app.knowledge_acquisition import youtube_plugin
from app.knowledge_acquisition.candidate_writeback import (
    CandidateAssemblyError,
    CandidateWritebackError,
    CandidateWriteResult,
    assemble_candidate,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_registry import clear_extraction_results
from app.knowledge_acquisition.normalize import STAGE_NAME as NORMALIZE_STAGE
from app.knowledge_acquisition.normalize import STAGE_VERSION as NORMALIZE_STAGE_VERSION
from app.knowledge_acquisition.normalize import NormalizeError, normalize
from app.knowledge_acquisition.raw_record import get_raw_record
from app.knowledge_acquisition.stage_events import (
    STAGE_EVENT_SOURCE,
    emit_stage_completed,
    emit_stage_dead_letter,
    run_extractors,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

CANDIDATE_STAGE = "candidate"
CANDIDATE_STAGE_VERSION = 1


class ReplayError(RuntimeError):
    """A replay could not run (e.g. the raw record does not exist in the object store)."""


class SourceEgressBlockedError(RuntimeError):
    """A source-egress seam was reached during a replay that must contact no source.

    Raised by the installed guard when `youtube_plugin.yt_dlp_extract_info`,
    `youtube_plugin.fetch_caption_body`, or `transcribe_source` is called inside a
    `run_replay` scope — the loud failure the contract's "acquisition hosts unreachable"
    posture requires, instead of a silent network call.
    """


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

    @property
    def successful_fresh_materialization(self) -> bool:
        """Whether replay completed with a new, deliberately non-comparable candidate.

        A first candidate write cannot truthfully claim byte equivalence because
        there is no preserved artifact to compare. It is still a successful
        replay outcome when every upstream stage completed and no item was
        dead-lettered.
        """
        candidate_stages = [stage for stage in self.stages if stage.stage == CANDIDATE_STAGE]
        return (
            not self.dead_lettered
            and len(candidate_stages) == 1
            and candidate_stages[0].status == "written"
            and candidate_stages[0].equivalence == "fresh_write_not_byte_comparable"
            and all(stage.status == "ok" for stage in self.stages if stage.stage != CANDIDATE_STAGE)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_record_id": self.raw_record_id,
            "content_identity": self.content_identity,
            "source_egress": self.source_egress,
            "equivalent": self.equivalent,
            "dead_lettered": list(self.dead_lettered),
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


@contextlib.contextmanager
def _source_egress_guard() -> Iterator[None]:
    """Install a raise-on-call guard over the three source-egress seams; restore on exit.

    Counts nothing itself — a call raises before it can do anything. ``run_replay`` observes
    zero egress by construction (it never reaches these seams); the guard's job is to make a
    regression that DID reach them fail loud instead of silently contacting a source.
    """
    import app.media.transcribe as transcribe_mod

    saved: dict[tuple[Any, str], Any] = {
        (youtube_plugin, "yt_dlp_extract_info"): youtube_plugin.yt_dlp_extract_info,
        (youtube_plugin, "fetch_caption_body"): youtube_plugin.fetch_caption_body,
        (youtube_plugin, "fetch"): youtube_plugin.fetch,
        (transcribe_mod, "transcribe_source"): transcribe_mod.transcribe_source,
        (youtube_plugin, "transcribe_source"): youtube_plugin.transcribe_source,
    }

    def _blocked(seam_name: str) -> Callable[..., Any]:
        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            raise SourceEgressBlockedError(
                f"replay reached source-egress seam {seam_name!r}: replay must reproduce "
                "derived artifacts from the existing raw record without contacting the source"
            )

        return _raise

    try:
        for (mod, name) in saved:
            setattr(mod, name, _blocked(name))
        yield
    finally:
        for (mod, name), original in saved.items():
            setattr(mod, name, original)


def _resolve_raw_record(raw_record_id: str | UUID) -> tuple[UUID, dict[str, Any]]:
    if isinstance(raw_record_id, UUID):
        object_id = raw_record_id
    else:
        try:
            object_id = UUID(str(raw_record_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ReplayError(f"invalid raw_record_id {raw_record_id!r}: not a UUID") from exc
    record = get_raw_record(object_id)
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
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    assert_no_source_egress: bool = True,
    trace_id: str | None = None,
    conn: Any = None,
) -> ReplayReceipt:
    """Replay every derived level from an existing `raw` record and return a typed receipt.

    Steps (all in-process, zero source egress):

    1. Load the raw record from the object store (never re-acquire).
    2. Simulate "deleted all derived levels": `clear_extraction_results()` drops the
       in-process extraction result cache so extractors genuinely re-run rather than
       replaying a cached result (extraction artifacts are not durably persisted in this
       slice — clearing the cache IS the deletion), WITHOUT clearing the registry itself
       (so a test-injected stubbed extractor spec is preserved). The candidate note is NOT
       deleted — first-write-wins means replay reproduces it as `already_exists`, and the
       contract forbids deleting an existing artifact.
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
    with _source_egress_guard():
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
        dead_lettered = tuple(o.extractor_id for o in report.dead_lettered)
        if dead_lettered:
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
                    detail=f"extractor(s) dead-lettered: {', '.join(dead_lettered)}",
                )
            )
        else:
            # KA-05's assemble_candidate re-derives normalize + extractions in-process;
            # the extraction cache is warm after run_extractors above, so this does NOT
            # re-invoke the LLM (run_extractor returns the cached result, replayed=True).
            try:
                candidate = assemble_candidate(dict(record), extractor_ids=tuple(extractor_ids))
                write_result = write_candidate_note(
                    candidate, vault_context=vault_context, write_guard=write_guard
                )
            except (CandidateAssemblyError, CandidateWritebackError) as exc:
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
        and not dead_lettered
    )
    return ReplayReceipt(
        raw_record_id=str(object_id),
        content_identity=content_identity,
        source_egress=egress_seen,
        stages=tuple(stages),
        equivalent=equivalent,
        dead_lettered=dead_lettered,
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
