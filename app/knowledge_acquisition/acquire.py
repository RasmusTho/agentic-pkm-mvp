"""Runtime acquisition entrypoint (KA acquire, #3106): fetch a NEW source item end-to-end.

Closes the gap left after Phase 2 (#2795): every KA stage function shipped and was proven —
`fetch` (KA-01/02), `normalize` (KA-03), extraction registry + `summary` (KA-04),
`candidate-writeback` (KA-05), stage events + replay (KA-06) — but nothing wired a genuinely
NEW source item through them. The only live command was `acquire-replay`
(`app/knowledge_acquisition/replay.py`), which re-derives an EXISTING `raw` record and never
calls a plugin's `fetch`. This module is the missing front door: given an explicit source
ref (a YouTube URL today), it resolves the plugin, calls `fetch` (real egress), persists the
raw record, then runs the same derived-stage sequence `run_replay` proved
(`normalize -> extractors -> assemble_candidate -> write_candidate_note`), emitting one KA-06
stage event per transition.

Explicit-URL only (no discovery/continuous sync — out of scope per the issue). Idempotent on
the raw record's `content_identity`: `youtube_plugin.fetch` itself resolves dedup before
persisting (caption path dedups via `persist_raw_record`; ASR path pre-checks via
`find_raw_record` so a known item never re-pays download + transcription), and the derived
stages inherit KA-05's first-write-wins candidate note. Re-running a known URL is therefore a
traced no-op end-to-end, never a byte-different candidate.

Stage execution model (`docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § Stage
execution model): a stage failure is loud and item-scoped — no fabricated raw record, no
partial candidate. `fetch` itself already returns a traced `ok=False` `FetchOutcome` instead
of raising on an ASR failure (`youtube_plugin.py :: fetch`); this module raises
`AcquisitionError` for that case (and reuses `run_replay`'s own dead-letter-then-raise shape
for the normalize/candidate stages) so a CLI caller gets a single exception family and a
nonzero exit, matching `acquire-replay`'s existing failure contract.

DB-required guard: stage-event emission is a Postgres outbox write
(`app.services.outbox.write_outbox_event`). Per the issue's explicit constraint, this
entrypoint must fail loud when no runtime DB is configured rather than silently skipping
events — `resolve_runtime_database_url` synthesizes a default DSN even when
`DATABASE_URL`/`DB_DSN` are unset (dev/test/prod host/db defaults), so it cannot be used as
the guard by itself; `require_configured_database_url` below checks the two env vars
directly, the same two names the outbox module itself documents as the override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

# Production extractor wiring: importing the extractors package registers every extractor
# module with the extraction registry (see `replay.py`'s identical import for the same
# reason) so a fresh process resolves "summary" without a pipeline-side import of a specific
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
from app.knowledge_acquisition.normalize import STAGE_NAME as NORMALIZE_STAGE
from app.knowledge_acquisition.normalize import STAGE_VERSION as NORMALIZE_STAGE_VERSION
from app.knowledge_acquisition.normalize import NormalizeError, has_usable_transcript, normalize
from app.knowledge_acquisition.replay import CANDIDATE_STAGE, CANDIDATE_STAGE_VERSION
from app.knowledge_acquisition.stage_events import (
    ExtractionRunReport,
    emit_stage_completed,
    emit_stage_dead_letter,
    run_extractors,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

YOUTUBE_SOURCE_KIND = youtube_plugin.SOURCE_KIND


class AcquisitionError(RuntimeError):
    """A new-item acquisition could not complete (item-scoped, loud, traced)."""


class RetryableSourceAcquisitionError(AcquisitionError):
    """Expected source-access failure with a safe queue failure classification."""

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _caption_failure_for_queue(exc: youtube_plugin.CaptionAcquisitionError) -> RetryableSourceAcquisitionError:
    """Classify the plugin's expected access failures without persisting provider text.

    ``CaptionAcquisitionError`` is the plugin boundary's explicit operational
    failure type.  Its detail can include a provider response or a source URL,
    neither of which belongs in a durable queue row or outbox event.
    """
    detail = str(exc).casefold()
    inaccessible_markers = (
        "private",
        "not found",
        "does not exist",
        "has been removed",
        "http error 404",
    )
    if any(marker in detail for marker in inaccessible_markers):
        return RetryableSourceAcquisitionError(
            reason_code="source_gone", message="YouTube source is inaccessible"
        )
    return RetryableSourceAcquisitionError(
        reason_code="network_error", message="YouTube source fetch failed"
    )


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when the acquisition entrypoint runs without a configured runtime DB.

    Stage-event emission is a Postgres outbox write; silently skipping it would produce an
    acquisition with no lineage trail. The entrypoint fails loud instead (issue #3106's
    explicit DB-required constraint).
    """


def require_configured_database_url(env: Mapping[str, str] | None = None) -> str:
    """Fail loud when neither `DATABASE_URL` nor `DB_DSN` is set.

    Deliberately independent of `app.config.database.resolve_runtime_database_url`: that
    helper synthesizes a same-host default DSN (`app_dev`/`app_test`/`app` + `db:5432`
    defaults) even when both env vars are unset, so it cannot detect "no runtime DB
    configured" — it always returns *something*. This entrypoint needs the narrower check:
    an explicit DSN must be present, matching the two env var names
    `app/services/outbox.py::_open_conn` itself falls back to.
    """
    source = env if env is not None else os.environ
    url = (source.get("DATABASE_URL") or source.get("DB_DSN") or "").strip()
    if not url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL or DB_DSN is not set. The acquisition entrypoint requires a "
            "configured runtime Postgres outbox for KA stage-event emission (KA-06) — set "
            "one of these env vars to a reachable Postgres DSN before running `acquire`."
        )
    return url


@dataclass(frozen=True)
class AcquireStageReceipt:
    """Per-stage line of an acquisition receipt (same shape as replay's, plus `fetch`/`raw`)."""

    stage: str
    status: str
    idempotent: bool | None = None
    extractor_id: str | None = None
    extractor_version: int | None = None
    artifact_path: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"stage": self.stage, "status": self.status}
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
class AcquisitionReceipt:
    """Structured, inspectable result of one `acquire_youtube` call."""

    source_kind: str
    item_ref: str
    raw_record_id: str
    content_identity: str
    is_new_raw: bool
    acquisition_method: str
    stages: tuple[AcquireStageReceipt, ...]
    dead_lettered: tuple[str, ...] = ()
    blocked: bool = False

    @property
    def ok(self) -> bool:
        # A governed WriteGuard denial (``blocked``) is NOT a stage dead-letter, but it is
        # still a non-ok acquisition: no candidate note was written. Mirrors
        # ``replay.run_replay``, which folds a blocked candidate write into ``equivalent=False``
        # via ``_candidate_equivalence`` returning ``(False, "none")`` so ``acquire-replay``
        # exits nonzero. A blocked write must never read as success.
        return not self.dead_lettered and not self.blocked

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "item_ref": self.item_ref,
            "raw_record_id": self.raw_record_id,
            "content_identity": self.content_identity,
            "is_new_raw": self.is_new_raw,
            "acquisition_method": self.acquisition_method,
            "ok": self.ok,
            "dead_lettered": list(self.dead_lettered),
            "blocked": self.blocked,
            "stages": [s.as_dict() for s in self.stages],
        }

    def to_lines(self) -> list[str]:
        lines: list[str] = []
        for stage in self.stages:
            if stage.stage == NORMALIZE_STAGE:
                label = f"{NORMALIZE_STAGE}@{NORMALIZE_STAGE_VERSION}"
            elif stage.extractor_id is not None:
                label = f"{stage.extractor_id}@{stage.extractor_version}"
            else:
                label = stage.stage
            suffix = " (idempotent)" if stage.idempotent else ""
            lines.append(f"{label:<11}... {stage.status}{suffix}")
        lines.append(
            f"acquire receipt: ok={str(self.ok).lower()} "
            f"content_identity={self.content_identity}"
        )
        return lines


def acquire_youtube(
    url_or_id: str,
    *,
    vault_context: VaultContext,
    extractor_ids: Sequence[str] = ("summary",),
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    trace_id: str | None = None,
    conn: Any = None,
    env: Mapping[str, str] | None = None,
    fetch_fn: Callable[[str], youtube_plugin.FetchOutcome] | None = None,
) -> AcquisitionReceipt:
    """Acquire a NEW YouTube URL end-to-end: fetch -> persist raw -> normalize -> extract ->
    assemble_candidate -> write_candidate_note, emitting one KA-06 stage event per transition.

    Mirrors `app.knowledge_acquisition.replay.run_replay`'s derived-stage sequencing exactly
    (normalize -> extractors -> candidate), but starts one stage earlier: `fetch` performs the
    real source egress and persists the raw record (`replay.run_replay` instead reads an
    EXISTING raw record and blocks egress entirely). `fetch_fn` defaults to
    `youtube_plugin.fetch`; tests inject a stub there to avoid real network/ASR egress.

    Raises `DatabaseNotConfiguredError` before touching the source at all when no runtime DB
    is configured (loud DB-required guard — see `require_configured_database_url`).

    Raises `AcquisitionError` on any item-scoped stage failure: the ASR/fetch chain failing
    (`FetchOutcome.ok is False`), a `NormalizeError`, or a candidate assembly/writeback
    failure. Each failure dead-letters that item at that stage (durable audit event) before
    raising — no fabricated raw record, no partial candidate note, matching
    `REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model and `run_replay`'s own shape.
    """
    require_configured_database_url(env)

    fetch = fetch_fn or youtube_plugin.fetch
    video_id = youtube_plugin.extract_video_id(url_or_id)

    try:
        outcome = fetch(url_or_id)
    except youtube_plugin.CaptionAcquisitionError as exc:
        raise _caption_failure_for_queue(exc) from exc
    if not outcome.ok:
        # No raw record was fabricated (youtube_plugin.fetch returns object_id=None on this
        # path) — nothing to dead-letter at a KA-06 stage because there is no raw/content
        # identity slot occupied yet; the failure is already traced by the plugin's own
        # `knowledge_acquisition.asr.fallback_failed` log. Fail loud to the caller.
        raise AcquisitionError(
            f"fetch failed for {url_or_id!r} (content_identity={outcome.content_identity!r}): "
            f"{outcome.failure}"
        )

    content_identity = outcome.content_identity
    raw_record: dict[str, Any] = dict(outcome.record) if outcome.record else _reload_raw(
        source_kind=YOUTUBE_SOURCE_KIND, item_ref=video_id, content_identity=content_identity
    )

    stages: list[AcquireStageReceipt] = [
        AcquireStageReceipt(
            stage="raw",
            status="persisted" if outcome.is_new else "dedup_noop",
            idempotent=not outcome.is_new,
        )
    ]

    # --- normalize -------------------------------------------------------------------
    try:
        normalized = normalize(dict(raw_record))
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
        raise AcquisitionError(
            f"acquisition dead-lettered at normalize for content_identity="
            f"{content_identity!r}: {exc}"
        ) from exc

    normalized_dict = normalized.as_dict()
    normalize_event_row = emit_stage_completed(
        stage=normalized.stage,
        stage_version=normalized.stage_version,
        content_identity=content_identity,
        trace_id=trace_id,
        conn=conn,
    )
    stages.append(
        AcquireStageReceipt(
            stage=NORMALIZE_STAGE,
            status="ok",
            idempotent=normalize_event_row == "",
        )
    )

    # --- extracted -------------------------------------------------------------------
    report = (
        run_extractors(
            normalized_dict, extractor_ids=extractor_ids, trace_id=trace_id, conn=conn
        )
        if has_usable_transcript(normalized)
        else ExtractionRunReport(successes=(), outcomes=())
    )
    for out in report.outcomes:
        if out.status == "ok" and out.result is not None:
            stages.append(
                AcquireStageReceipt(
                    stage="extracted",
                    status="ok",
                    idempotent=out.event_row_id == "",
                    extractor_id=out.result.extractor_id,
                    extractor_version=out.result.extractor_version,
                )
            )
        else:
            stages.append(
                AcquireStageReceipt(
                    stage="extracted",
                    status="dead_lettered",
                    extractor_id=out.extractor_id,
                    detail=out.error,
                )
            )

    dead_lettered = tuple(o.extractor_id for o in report.dead_lettered)
    if dead_lettered:
        # A selected extraction dead-lettered — candidate assembly cannot fulfill its inputs.
        # The extraction dead-letter above already recorded the failure durably; report the
        # skip explicitly (never silent, never a partial candidate note).
        stages.append(
            AcquireStageReceipt(
                stage=CANDIDATE_STAGE,
                status="skipped_upstream_dead_letter",
                detail=f"extractor(s) dead-lettered: {', '.join(dead_lettered)}",
            )
        )
        return AcquisitionReceipt(
            source_kind=YOUTUBE_SOURCE_KIND,
            item_ref=video_id,
            raw_record_id=str(outcome.object_id),
            content_identity=content_identity,
            is_new_raw=outcome.is_new,
            acquisition_method=outcome.acquisition_method,
            stages=tuple(stages),
            dead_lettered=dead_lettered,
        )

    # --- candidate ---------------------------------------------------------------------
    try:
        candidate = assemble_candidate(raw_record, extractor_ids=tuple(extractor_ids))
        write_result: CandidateWriteResult = write_candidate_note(
            candidate, vault_context=vault_context, write_guard=write_guard
        )
    except (CandidateAssemblyError, CandidateWritebackError) as exc:
        emit_stage_dead_letter(
            stage=CANDIDATE_STAGE,
            stage_version=CANDIDATE_STAGE_VERSION,
            content_identity=content_identity,
            reason=(
                "assembly_failed" if isinstance(exc, CandidateAssemblyError) else "writeback_failed"
            ),
            error=str(exc),
            trace_id=trace_id,
            conn=conn,
        )
        raise AcquisitionError(
            f"acquisition dead-lettered at candidate for content_identity="
            f"{content_identity!r}: {exc}"
        ) from exc

    candidate_blocked = write_result.status == "blocked"
    if candidate_blocked:
        # A governed WriteGuard denial is not a stage transition: no stage.completed event,
        # no dead-letter (the write was refused, not a compute failure — the item stays
        # cleanly re-runnable on the next attempt). But it IS a non-ok acquisition: no
        # candidate note was written, so `receipt.ok` must be False and the CLI must exit
        # nonzero. Mirrors run_replay, which folds "blocked" into equivalent=False with no
        # event and no dead-letter.
        stages.append(
            AcquireStageReceipt(
                stage=CANDIDATE_STAGE, status="blocked", detail=write_result.reason
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
            AcquireStageReceipt(
                stage=CANDIDATE_STAGE,
                status=write_result.status,
                idempotent=candidate_event_row == "",
                artifact_path=write_result.artifact_path,
            )
        )

    return AcquisitionReceipt(
        source_kind=YOUTUBE_SOURCE_KIND,
        item_ref=video_id,
        raw_record_id=str(outcome.object_id),
        content_identity=content_identity,
        is_new_raw=outcome.is_new,
        acquisition_method=outcome.acquisition_method,
        stages=tuple(stages),
        blocked=candidate_blocked,
    )


def _reload_raw(*, source_kind: str, item_ref: str, content_identity: str) -> dict[str, Any]:
    """Fallback raw-record reload for a dedup-hit `FetchOutcome` with an empty `record` field.

    `youtube_plugin.fetch`'s caption-path dedup always returns the persisted record via
    `persist_raw_record`; this only guards a shape where `record` came back empty despite
    `object_id` being set (defensive — not expected on the shipped plugin).
    """
    from app.knowledge_acquisition.raw_record import get_raw_record, raw_record_object_id

    object_id = raw_record_object_id(
        source_kind=source_kind, item_ref=item_ref, content_identity=content_identity
    )
    record = get_raw_record(object_id)
    if record is None:
        raise AcquisitionError(
            f"raw record not found after fetch for content_identity={content_identity!r}"
        )
    return record


__all__ = [
    "YOUTUBE_SOURCE_KIND",
    "AcquisitionError",
    "RetryableSourceAcquisitionError",
    "DatabaseNotConfiguredError",
    "AcquireStageReceipt",
    "AcquisitionReceipt",
    "require_configured_database_url",
    "acquire_youtube",
]
