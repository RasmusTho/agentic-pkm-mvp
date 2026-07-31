"""Stage events + item-scoped dead-letter for the KA refinement pipeline (KA-06, #2801).

Closes the Knowledge Acquisition Phase 2 slice: every refinement stage transition
(`normalize`, each extractor run, `candidate`) emits exactly one standard-envelope
outbox event (`docs/EVENTS.md`) with a **deterministic** idempotency key, and a stage
failure dead-letters that one item at that one stage — loudly and item-scoped — without
blocking sibling items or sibling extractors. Implements
`docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model
("Each stage transition emits an event on the existing outbox … A stage failure is loud
and item-scoped: it dead-letters that item at that stage without blocking other items or
other extractors").

Design decisions (binding for this slice):

- **Existing DB outbox, no forked delivery.** Emission routes through
  `app.services.outbox.write_outbox_event` (KERNEL-02: mandatory idempotency key, row
  `id = key`, `ON CONFLICT (id) DO NOTHING`) with keys derived through the ONE shared
  helper `derive_idempotency_key`. No parallel event path, no `app.outbox.events` JSONL
  append (that seam is non-idempotent, #2881), no worker `_dispatch_topic` branch.

- **These topics are lineage/audit, not commands mutating pipeline state.** They record
  that a stage transition happened, per the contract's lineage/replay model. KA-07 (#3107)
  added the first CONSUMER for both topics in `outbox_worker._dispatch_topic`
  (`handle_knowledge_acquisition_stage_completed` /
  `handle_knowledge_acquisition_stage_dead_lettered`), but that consumer's downstream
  action is deliberately bounded and minimal (a durable observability signal — candidate
  ready-for-triage / dead-letter surfaced) — never the full triage engine, and it never
  mutates a `raw`/`normalized`/`candidate` artifact this module produced. See
  `docs/EVENTS.md` § these two topics for the consumer contract.

  Because they are now dispatched, KA-07 also registered their KERNEL-08 topic schemas
  (`schemas/events/knowledge_acquisition.stage.{completed,dead_lettered}.v1.schema.json`),
  so the `write_outbox_event` calls in `emit_stage_completed` / `emit_stage_dead_letter`
  below now hard-validate the payload against the registered schema and stamp
  `meta.payload_schema` at write time. A payload-shape change to these emitters must stay
  within the registered schema (or bump it) or it will raise `TopicSchemaViolation` at the
  producer — the `stage`/`stage_version`/`content_identity` fields (plus `reason`/`error`
  for the dead-letter topic) are required by the schema.

- **Deterministic keys stable across replay, distinct across stage-version bumps.** The
  completion key for a stage transition is derived from
  `(stage, stage_version, content_identity)` — plus `extractor_id` for extractor runs so
  two extractors over the same content never collide. Re-running an unchanged stage at an
  unchanged version re-derives the SAME key (idempotent no-op: exactly one row). Bumping
  the stage/extractor version derives a DISTINCT key, so a stage improvement that re-runs
  the stage is a genuinely new lineage event and is never swallowed against the old
  version's row (contract § Lineage and replay: "Improving a stage re-runs that stage …").

- **Dead-letter mechanics: design (a) — a KA-local helper.** On a stage failure this
  module writes a `knowledge_acquisition.stage.dead_lettered` outbox event carrying
  `{content_identity, stage, stage_version, extractor_id?, reason, error}` via the same
  `write_outbox_event` / `derive_idempotency_key` primitives, then surfaces the failure
  loudly to the immediate caller (a structured `StageOutcome(status="dead_lettered")` from
  `run_extractors`, or the raised exception when the caller drives a single stage). It does
  NOT reuse `outbox_worker._dead_letter_outbox_message`: that function is the WORKER's
  DB-row dispatch-poison path (attempts exhausted on a queued row), a different concern —
  these stage failures are in-process compute failures, never a queued row the worker is
  dispatching. Keeping the helper local also avoids `app.knowledge_acquisition` (memory
  layer) importing `app.workers` (execution layer). The dead-letter key is
  content-scoped (`{stage}:{stage_version}:dead_letter` fingerprint) so a duplicate
  delivery of the same failure dedups to one audit row, exactly like the success path.

- **Emission is atomic with the stage effect in the only sense these stages need.** These
  stages are pure in-process compute (`normalize()` is a pure transform; `run_extractor`
  caches its own result; `write_candidate_note` is first-write-wins). There is no
  DB-row-mutation-paired-with-an-event to make transactional (unlike vault_sync's
  `insert_object_and_outbox`, which pairs a durable object row with its event in one
  connection). The event is written synchronously in the same Python call stack
  immediately after the stage effect succeeds; because the key is deterministic and the
  underlying effect is itself idempotent, a crash between effect and emit is self-healing
  on replay — the re-run reproduces the effect (idempotently) and re-derives the same key
  (deduping the event). We do NOT claim a cross-process transaction the compute shape does
  not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.events.models import new_event
from app.events.types import (
    KNOWLEDGE_ACQUISITION_STAGE_COMPLETED,
    KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED,
)
from app.knowledge_acquisition.extraction_registry import (
    STAGE_NAME as EXTRACTED_STAGE_NAME,
    ExtractionError,
    ExtractionResult,
    run_extractor,
)
from app.services.outbox import derive_idempotency_key, write_outbox_event

STAGE_COMPLETED_TOPIC = KNOWLEDGE_ACQUISITION_STAGE_COMPLETED
STAGE_DEAD_LETTERED_TOPIC = KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED

# Stable attribution label for the envelope `source` field (docs/EVENTS.md § envelope).
STAGE_EVENT_SOURCE = "knowledge_acquisition.pipeline"


def _stage_scope(*, stage: str, extractor_id: str | None) -> str:
    """The identity segment that distinguishes an extractor run from a bare stage.

    Two extractors over the same normalized content are different lineage events, so the
    extractor id is folded into the key's fingerprint scope. A stage with no extractor
    (`normalize`, `candidate`) uses the stage name alone.
    """
    return f"{stage}:{extractor_id}" if extractor_id else stage


def stage_completed_key(
    *, stage: str, stage_version: int, content_identity: str, extractor_id: str | None = None
) -> str:
    """Deterministic idempotency key for a stage-completed event.

    Stable across replay (same stage+version+content+extractor → same key ⇒ one row),
    distinct across a version bump (a stage improvement re-runs and is a new lineage event,
    never swallowed against the old row). Derived through the single shared KERNEL-02
    helper — no ad-hoc scheme.
    """
    scope = _stage_scope(stage=stage, extractor_id=extractor_id)
    return derive_idempotency_key(
        STAGE_COMPLETED_TOPIC,
        content_identity,
        f"{scope}:{stage_version}",
    )


def stage_dead_letter_key(
    *, stage: str, stage_version: int, content_identity: str, extractor_id: str | None = None
) -> str:
    """Deterministic idempotency key for a stage dead-letter audit event.

    Content-scoped (not attempt-scoped): a duplicate delivery of the same stage failure
    dedups to one audit row, mirroring the success path. A version bump derives a distinct
    key, so a re-run of an improved-but-still-failing stage is a genuinely new dead-letter.
    """
    scope = _stage_scope(stage=stage, extractor_id=extractor_id)
    return derive_idempotency_key(
        STAGE_DEAD_LETTERED_TOPIC,
        content_identity,
        f"{scope}:{stage_version}:dead_letter",
    )


def emit_stage_completed(
    *,
    stage: str,
    stage_version: int,
    content_identity: str,
    extractor_id: str | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
    conn: Any = None,
) -> str:
    """Emit exactly one `knowledge_acquisition.stage.completed` outbox event.

    Returns the inserted row id (the deterministic key) on first emission, or ``""`` when
    the row already existed (duplicate delivery deduped by `ON CONFLICT (id) DO NOTHING`).
    Idempotent by construction: re-emitting the same stage transition is a no-op.
    """
    payload: dict[str, Any] = {
        "stage": stage,
        "stage_version": stage_version,
        "content_identity": content_identity,
    }
    if extractor_id is not None:
        payload["extractor_id"] = extractor_id
    if extra_payload:
        for key, value in extra_payload.items():
            payload.setdefault(key, value)

    key = stage_completed_key(
        stage=stage,
        stage_version=stage_version,
        content_identity=content_identity,
        extractor_id=extractor_id,
    )
    event = new_event(
        event_type=STAGE_COMPLETED_TOPIC,
        payload=payload,
        trace_id=trace_id,
        source=STAGE_EVENT_SOURCE,
    )
    # required_db=True (#4214): `conn` is an OPTIONAL parameter here and the
    # acquisition entrypoints forward their own `conn=None` default, so this is a
    # self-owned write at runtime. Left unclassified, an explicit memory backend
    # skipped it and returned "" — which `acquire.py`/`replay.py` read as
    # `idempotent=True`, i.e. a receipt asserting the transition was ALREADY
    # durably recorded, for a stage event that never existed. This module's own
    # contract forbids that: `acquire.py` calls require_configured_database_url()
    # precisely so an acquisition cannot land without a lineage trail. A supplied
    # connection still bypasses the policy and owns its transaction.
    return write_outbox_event(event, conn=conn, idempotency_key=key, required_db=True)


def emit_stage_dead_letter(
    *,
    stage: str,
    stage_version: int,
    content_identity: str,
    reason: str,
    error: str,
    extractor_id: str | None = None,
    trace_id: str | None = None,
    conn: Any = None,
) -> str:
    """Emit exactly one `knowledge_acquisition.stage.dead_lettered` outbox event.

    The loud, durable record that THIS item failed at THIS stage. Returns the inserted row
    id on first emission, or ``""`` when a duplicate delivery of the same failure deduped.
    """
    payload: dict[str, Any] = {
        "stage": stage,
        "stage_version": stage_version,
        "content_identity": content_identity,
        "reason": reason,
        "error": error,
    }
    if extractor_id is not None:
        payload["extractor_id"] = extractor_id

    key = stage_dead_letter_key(
        stage=stage,
        stage_version=stage_version,
        content_identity=content_identity,
        extractor_id=extractor_id,
    )
    event = new_event(
        event_type=STAGE_DEAD_LETTERED_TOPIC,
        payload=payload,
        trace_id=trace_id,
        source=STAGE_EVENT_SOURCE,
    )
    # required_db=True (#4214): `conn` is an OPTIONAL parameter here and the
    # acquisition entrypoints forward their own `conn=None` default, so this is a
    # self-owned write at runtime. Left unclassified, an explicit memory backend
    # skipped it and returned "" — which `acquire.py`/`replay.py` read as
    # `idempotent=True`, i.e. a receipt asserting the transition was ALREADY
    # durably recorded, for a stage event that never existed. This module's own
    # contract forbids that: `acquire.py` calls require_configured_database_url()
    # precisely so an acquisition cannot land without a lineage trail. A supplied
    # connection still bypasses the policy and owns its transaction.
    return write_outbox_event(event, conn=conn, idempotency_key=key, required_db=True)


@dataclass(frozen=True)
class StageOutcome:
    """Item-scoped result of running one stage (here: one extractor) over one item.

    ``status`` is ``"ok"`` (the stage succeeded; ``result`` is populated and a
    `stage.completed` event was emitted) or ``"dead_lettered"`` (the stage failed;
    ``error`` is populated and a `stage.dead_lettered` event was emitted). A dead-lettered
    outcome is never silent — the caller gets an unambiguous structured failure it can log,
    surface, or count — but it does not raise, so a loop over sibling extractors continues.

    ``event_row_id`` (success only) is `write_outbox_event`'s return for the stage.completed
    emission: the inserted row id on first emission, ``""`` when the deterministic key
    already existed (log-layer dedup) — replay reads ``""`` as "this transition was already
    recorded", i.e. an idempotent re-emission.
    """

    extractor_id: str
    status: str  # "ok" | "dead_lettered"
    result: ExtractionResult | None = None
    error: str | None = None
    event_row_id: str | None = None


@dataclass(frozen=True)
class ExtractionRunReport:
    """The outcome set of running a fan-out of extractors over one normalized artifact."""

    successes: tuple[ExtractionResult, ...]
    outcomes: tuple[StageOutcome, ...]

    @property
    def dead_lettered(self) -> tuple[StageOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "dead_lettered")


def run_extractors(
    normalized: Mapping[str, Any],
    *,
    extractor_ids: Sequence[str],
    trace_id: str | None = None,
    conn: Any = None,
) -> ExtractionRunReport:
    """Run a set of extractors over one normalized artifact, item-scoped per extractor.

    Extractors "are mutually independent and may run in parallel or not at all"
    (`REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model), so one extractor raising
    `ExtractionError` must NOT stop sibling extractors on the same item. Each extractor is
    run independently:

    - success → emit one `stage.completed` event, record an ``ok`` `StageOutcome`;
    - `ExtractionError` → dead-letter THIS extractor at the `extracted` stage (loud,
      durable audit event) and record a ``dead_lettered`` `StageOutcome`, then continue to
      the next extractor.

    This is the multi-extractor orchestration point the contract implies; it is additive
    (it wraps the existing single-call-site `run_extractor` without changing its
    semantics). ``successes`` are exactly the extractions a caller should bundle into a
    candidate; ``dead_lettered`` names the extractors that failed for this item.

    `UnknownExtractorError` deliberately propagates un-caught: an extractor id that was
    never registered is a caller/configuration error for the whole run, not an item-scoped
    stage failure — dead-lettering it per item would bury a wiring bug in per-item audit
    rows instead of failing the run loudly.
    """
    content_identity = normalized.get("source_content_identity")
    if not isinstance(content_identity, str) or not content_identity:
        # The normalized artifact is malformed for the whole item — not an extractor-scoped
        # failure. Fail loud to the caller rather than fabricating per-extractor outcomes.
        raise ValueError(
            "run_extractors requires a normalized artifact with a string source_content_identity"
        )

    successes: list[ExtractionResult] = []
    outcomes: list[StageOutcome] = []
    for extractor_id in extractor_ids:
        try:
            result = run_extractor(extractor_id, normalized)
        except ExtractionError as exc:
            emit_stage_dead_letter(
                stage=EXTRACTED_STAGE_NAME,
                stage_version=exc.version,
                content_identity=content_identity,
                extractor_id=extractor_id,
                reason="extraction_failed",
                error=str(exc),
                trace_id=trace_id,
                conn=conn,
            )
            outcomes.append(
                StageOutcome(extractor_id=extractor_id, status="dead_lettered", error=str(exc))
            )
            continue
        event_row_id = emit_stage_completed(
            stage=result.stage,
            stage_version=result.extractor_version,
            content_identity=content_identity,
            extractor_id=extractor_id,
            extra_payload={"model_identity": dict(result.model_identity)},
            trace_id=trace_id,
            conn=conn,
        )
        successes.append(result)
        outcomes.append(
            StageOutcome(
                extractor_id=extractor_id,
                status="ok",
                result=result,
                event_row_id=event_row_id,
            )
        )

    return ExtractionRunReport(successes=tuple(successes), outcomes=tuple(outcomes))


__all__ = [
    "STAGE_COMPLETED_TOPIC",
    "STAGE_DEAD_LETTERED_TOPIC",
    "STAGE_EVENT_SOURCE",
    "StageOutcome",
    "ExtractionRunReport",
    "stage_completed_key",
    "stage_dead_letter_key",
    "emit_stage_completed",
    "emit_stage_dead_letter",
    "run_extractors",
]
