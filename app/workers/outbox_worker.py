from __future__ import annotations

import errno
import hashlib
import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from app.agents.panel.filters import strip_ai_panels
from app.agents.panel.writeback import strip_ai_status_block
from app.agents.panel_agent.execution import refresh_panel_note_object, run_panel_note_execution
from app.components.concurrency import EventDedupStore, OptimisticWriteGuard, VersionMismatch
from app.events.sync import SyncChainCorrelationData, SyncLatencySummaryEvent
from app.events.types import (
    INGEST_OBJECT_CREATED,
    INGEST_OBJECT_DELETED,
    INGEST_VAULT_CHANGED,
    KNOWLEDGE_ACQUISITION_STAGE_COMPLETED,
    KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED,
    NOTE_MOVE_WORKBENCH,
    PANEL_SCAN_REQUESTED,
    PROMOTE_INTENT_CREATED,
)
from app.events.schema import make_outbox_event
from app.events.topic_schema_registry import (
    TopicSchemaViolation,
    is_registered_topic,
    resolve_payload_schema_version,
    validate_topic_payload,
)
from app.indexer.consumer import process_event as process_indexer_event
from app.knowledge.write_ops import read_note_text_with_version
from app.objects import resolve_canonical_object_id
from app.outbox.events import INDEX_EMBEDDING_REQUESTED
from app.observability.logging_setup import configure_json_logging
from app.observability.tracer import start_span
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path, write_worker_heartbeat
from app.workers.metrics import (
    WORKER_LAST_TICK_TIMESTAMP,
    WORKER_PROCESSED,
    maybe_start_worker_metrics_server,
)
from app.services.indexer import (
    handle_ingest_object_created,
    purge_object_vectors,
    resolve_event_object_id,
)
from app.services.companion_note import CompanionNote, scan_attachments, write_companion
from app.settings.runtime import get_settings_bundle
from app.services.note_uuid import ensure_note_uuid
from app.services.outbox import (
    ack_outbox,
    append_jsonl_outbox_event,
    bootstrap,
    bump_outbox_attempts,
    derive_idempotency_key,
    open_outbox_txn_conn,
    payload_fingerprint,
    poll_outbox_one,
    write_outbox_event,
)
from app.vault.paths import NoVaultSelectedError, get_vault_inbox_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD
from app.events.models import new_event
from scripts.yaml_roundtrip import load_frontmatter

logger = logging.getLogger(__name__)
_WRITE_GUARD = OptimisticWriteGuard()

_UNKNOWN_INSTANCE = "unknown"
OUTBOX_EVENT_DEAD_LETTERED = "outbox.event.dead_lettered"

# KA-07 (#3107): observability signals emitted by the stage-event consumer
# route below. Distinct from the KA-06 producer topics
# (`knowledge_acquisition.stage.completed` / `...dead_lettered`, which this
# worker now dispatches) -- these are the WORKER's own audit trail of having
# handled one of those events, mirroring `OUTBOX_EVENT_DEAD_LETTERED` above
# (the worker's dispatch-poison signal) rather than reusing the KA producer's
# topic name for a different concern.
KA_CANDIDATE_READY_FOR_TRIAGE = "knowledge_acquisition.candidate.ready_for_triage"
KA_STAGE_DEAD_LETTER_SURFACED = "knowledge_acquisition.stage.dead_letter_surfaced"

# In-process redelivery-window guard for the two KA consumer signals' JSONL
# audit append, mirroring `app.outbox.events._AUDIT_EMISSION_DEDUP` and this
# module's own `_PANEL_LATENCY_SUMMARY_DEDUP`: a fast-path window, not the
# durable idempotency source of truth (that is the DB-outbox row's
# deterministic `id` + `ON CONFLICT DO NOTHING` when the DB outbox is
# enabled). Without this gate the JSONL sink (unlike the DB outbox) has no
# dedup of its own and would grow one line per redelivery even though the
# durable DB row still converges to one.
_KA_CONSUMER_SIGNAL_DEDUP = EventDedupStore()

# In-process dedup for the `sync.latency.summary` audit emission in
# `handle_panel_scan_requested` (#2881). This JSONL append is unconditional
# per dispatch with a fresh random `event_id`, so a redelivered
# `panel.scan.requested` row previously appended a second summary line for
# the SAME observation. Keyed on `(note_uuid, scan_requested_ts,
# file_detection_ts)` -- the observation's own stable timestamps threaded
# through the payload/event envelope on every dispatch of the same outbox
# row -- deliberately excluding `runtime_start_ts`/`runtime_complete_ts`
# (wall-clock at dispatch time, always fresh) from the key.
_PANEL_LATENCY_SUMMARY_DEDUP = EventDedupStore()

# Dead-letter reason for a dispatch-time schema violation (KERNEL-08, #2770).
SCHEMA_VIOLATION_REASON = "schema_violation"
INVALID_NOTE_UUID_REASON = "invalid_note_uuid"


class SchemaViolationDispatchError(RuntimeError):
    """A registered-schema payload failed validation at dispatch.

    Raised by :func:`_dispatch_topic` before the real handler runs, so an
    invalid payload never partially processes. Marked so the `run()` consume
    loop dead-letters it immediately with reason ``schema_violation`` instead
    of spending the poison-retry budget (which exists for handler failures on
    otherwise-valid payloads, not for structurally invalid ones) or the
    transient-retry path (a schema violation is never transient).
    """

    def __init__(self, violation: TopicSchemaViolation) -> None:
        super().__init__(str(violation))
        self.violation = violation


class InvalidPanelNoteUUIDDispatchError(ValueError):
    """A stored panel-note UUID is malformed and cannot be dispatched safely.

    This is deliberately distinct from a transient handler error. The source note
    and its queued event are durable evidence, but retrying the same immutable
    malformed UUID only crash-loops the worker. The consume loop dead-letters
    this one row immediately and continues with later events.
    """

    def __init__(self, value: str) -> None:
        super().__init__(f"invalid panel note uuid: {value}")


def _resolve_instance_id() -> str:
    try:
        bundle = get_settings_bundle()
        instance = getattr(bundle, "instance", None)
        if instance is None:
            return _UNKNOWN_INSTANCE
        raw = getattr(instance, "id", None)
        if raw is None:
            return _UNKNOWN_INSTANCE
        resolved = str(raw).strip()
        return resolved if resolved else _UNKNOWN_INSTANCE
    except Exception:
        return _UNKNOWN_INSTANCE
_MAX_TRANSIENT_RETRY_ATTEMPTS = 3

# Upper bound on how many times the worker will crash-and-retry a single outbox row
# whose handler raises before that row is dead-lettered (acked + audited) so it can
# no longer block the head of the queue. A row that genuinely needs more than this
# many attempts is treated as poison rather than transient, which prevents the
# `processed_total=0` head-of-line stall observed on dev+prod (#2252).
_MAX_DISPATCH_ATTEMPTS = 5
_TRANSIENT_OS_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EHOSTDOWN,
    errno.EHOSTUNREACH,
    errno.ENETDOWN,
    errno.ENETRESET,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
}
_TRANSIENT_DB_ERROR_NAMES = {
    "AdminShutdown",
    "CannotConnectNow",
    "ConnectionDoesNotExist",
    "ConnectionException",
    "ConnectionFailure",
    "CrashShutdown",
    "DatabaseDropped",
    "InterfaceError",
    "OperationalError",
    "ProtocolViolation",
    "QueryCanceled",
    "SQLClientUnableToEstablishSQLConnection",
    "SQLServerRejectedEstablishmentOfSQLConnection",
    "TransactionResolutionUnknown",
}
_TRANSIENT_NETWORK_ERROR_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "ConnectionError",
    "MaxRetryError",
    "NetworkError",
    "NewConnectionError",
    "PoolTimeout",
    "ProxyError",
    "ReadError",
    "ReadTimeout",
    "Timeout",
    "TimeoutException",
    "TransportError",
    "WriteError",
}
_TRANSIENT_NETWORK_MODULE_PREFIXES = ("httpx", "requests", "urllib3")
_TRANSIENT_HTTP_STATUS_CODES = {408, 429}


def _resolve_max_dispatch_attempts() -> int:
    raw = os.getenv("WORKER_MAX_DISPATCH_ATTEMPTS")
    if raw is None:
        return _MAX_DISPATCH_ATTEMPTS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _MAX_DISPATCH_ATTEMPTS
    return value if value >= 1 else _MAX_DISPATCH_ATTEMPTS


def _iter_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _matches_error_name(
    exc: BaseException,
    *,
    module_prefixes: tuple[str, ...],
    names: set[str],
) -> bool:
    for cls in type(exc).__mro__:
        module = getattr(cls, "__module__", "")
        name = getattr(cls, "__name__", "")
        if name in names and module.startswith(module_prefixes):
            return True
    return False


def _http_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    raw_status = getattr(response, "status_code", None)
    if raw_status is None:
        return None
    try:
        return int(raw_status)
    except (TypeError, ValueError):
        return None


def _is_transient_dispatch_error(exc: BaseException) -> bool:
    """Return true for retryable infra outages that must not spend poison budget."""
    for current in _iter_exception_chain(exc):
        # App-local transient errors mark themselves with `is_transient = True`:
        # provider adapters (e.g. GeminiTransientError for HTTP 429/5xx, re-raised
        # from the consumer path with dead_letter_on_exhaustion=False) and
        # app.db.errors.StoreSchemaMissingError (KERNEL-04 #2766: store migrations
        # not applied yet on a fresh stack — boot-ordering, crash-retry under
        # supervision, never dead-letter). These carry no httpx response/chain, so
        # without this the worker would poison-count and dead-letter a transient
        # outage instead of keeping the row pending for retry (at-least-once
        # durability). The marker protocol (not isinstance) keeps the worker free
        # of app.db/app.stores imports, which layering guards forbid
        # (tests/guard/test_no_direct_db_imports.py,
        # tests/architecture/test_deprecated_store_callers.py).
        if getattr(current, "is_transient", None) is True:
            return True
        if isinstance(current, TransientRetryEnqueueError):
            return True
        if isinstance(current, (ConnectionError, TimeoutError)):
            return True
        if isinstance(current, OSError) and current.errno in _TRANSIENT_OS_ERRNOS:
            return True
        if _matches_error_name(
            current,
            module_prefixes=("psycopg",),
            names=_TRANSIENT_DB_ERROR_NAMES,
        ):
            return True
        if _matches_error_name(
            current,
            module_prefixes=_TRANSIENT_NETWORK_MODULE_PREFIXES,
            names=_TRANSIENT_NETWORK_ERROR_NAMES,
        ):
            return True
        status_code = _http_status_code(current)
        is_network_module = type(current).__module__.startswith(_TRANSIENT_NETWORK_MODULE_PREFIXES)
        if status_code is not None and is_network_module:
            if status_code >= 500 or status_code in _TRANSIENT_HTTP_STATUS_CODES:
                return True
    return False


class TransientRetryEnqueueError(RuntimeError):
    """Raised when a transient retry cannot be persisted safely."""


@dataclass
class WorkerIngestSummary:
    ingested: int


@dataclass
class WorkerPanelSummary:
    emitted: int
    deferred: bool = False


@dataclass
class WorkerTickResult:
    """Outcome of a single worker tick.

    ``state`` is ``"no_vault"`` when no vault is selected and the worker idled
    without touching the filesystem, ``"idle"`` when a vault is bound but the
    outbox had nothing to process, and ``"processed"`` when a message was
    dispatched.
    """

    state: str
    processed: int = 0


def run_once(
    *,
    vault_root: Path | None = None,
) -> WorkerTickResult:
    """Run a single worker tick, idling honestly when no vault is selected.

    With no vault bound (``VAULT_ROOT`` unset, no explicit ``vault_root``) the
    worker reports a ``"no_vault"`` state and performs no outbox poll or
    filesystem access, so it never synthesizes a CWD-relative ``./vault`` (#2384).
    A set-but-missing ``VAULT_ROOT`` still raises through the strict resolver,
    preserving the loud misconfiguration contract.
    """
    if _resolve_optional_vault_root(vault_root) is None:
        logger.debug("outbox worker tick idled: no vault selected")
        return WorkerTickResult(state="no_vault", processed=0)

    message = poll_outbox_one()
    if not message:
        return WorkerTickResult(state="idle", processed=0)

    topic = message.get("topic")
    payload = message.get("payload") or {}
    trace_id = (
        payload.get("trace_id")
        or message.get("trace_id")
        or _trace_id_from_envelope(message.get("event"))
        or "-"
    )
    event_id = _event_id_from_message(message)
    try:
        _dispatch_topic(topic, payload, trace_id=trace_id, message=message, event_id=event_id)
    except InvalidPanelNoteUUIDDispatchError as uuid_exc:
        logger.warning(
            "worker dead-lettered malformed panel note uuid topic=%s id=%s",
            topic,
            message.get("id"),
        )
        _dead_letter_and_ack(
            message["id"],
            topic=topic,
            payload=payload,
            reason=INVALID_NOTE_UUID_REASON,
            attempts=0,
            trace_id=None if trace_id == "-" else trace_id,
            error=str(uuid_exc),
        )
        return WorkerTickResult(state="processed", processed=1)
    except SchemaViolationDispatchError as schema_exc:
        # Immediate dead-letter (KERNEL-08, #2770): see the matching branch in
        # run()'s consume loop for the invariant (never transient, no retry budget).
        logger.warning(
            "worker dead-lettered schema violation topic=%s id=%s reason=%s",
            topic,
            message.get("id"),
            schema_exc.violation.reason,
        )
        _dead_letter_and_ack(
            message["id"],
            topic=topic,
            payload=payload,
            reason=SCHEMA_VIOLATION_REASON,
            attempts=0,
            trace_id=None if trace_id == "-" else trace_id,
            error=str(schema_exc),
        )
        return WorkerTickResult(state="processed", processed=1)
    ack_outbox(message["id"])
    return WorkerTickResult(state="processed", processed=1)


def _message_meta(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
    envelope = message.get("event")
    meta = getattr(envelope, "meta", None)
    return meta if isinstance(meta, Mapping) else None


def _validate_dispatch_payload(topic: str | None, payload: Mapping[str, Any], *, message: Mapping[str, Any]) -> None:
    """Validate ``payload`` at dispatch against its registered topic schema.

    Grandfathering (cross-task invariant #1, ``docs/RUNTIME_CORRECTNESS_KERNEL/README.md``):
    a row with no ``meta.payload_schema``/``meta.schema_version`` tag predates
    the registry ("v0") and is validated log-only — a violation is logged, never
    dead-lettered. A row carrying the tag is hard-validated: a violation raises
    :class:`SchemaViolationDispatchError` so the caller dead-letters immediately
    with reason ``schema_violation`` instead of running the handler on a payload
    known to violate its own contract (no partial processing).
    """
    if topic is None or not is_registered_topic(topic):
        return
    version = resolve_payload_schema_version(_message_meta(message))
    try:
        validate_topic_payload(topic, payload)
    except TopicSchemaViolation as violation:
        if version.is_grandfathered:
            logger.warning(
                "worker schema violation on grandfathered (pre-registry) row topic=%s reason=%s",
                topic,
                violation.reason,
            )
            return
        raise SchemaViolationDispatchError(violation) from violation


def _dispatch_topic(
    topic: str | None,
    payload: Mapping[str, Any],
    *,
    trace_id: str,
    message: Mapping[str, Any],
    event_id: str = "",
) -> None:
    """Dispatch one outbox message to its real topic handler.

    This is the single shared dispatch table used by both ``run_once`` and the
    production daemon ``run()`` loop. Keeping one table prevents the two paths
    from diverging, which is how a supported topic (e.g. ``promote.intent.created``
    or ``index.embedding.requested``) could be acked as "unsupported" via
    ``run_once`` while ``run()`` actually handled it (#2407).

    Schema validation (KERNEL-08, #2770) runs first, before any handler: an
    invalid payload against a registered schema must never partially process.
    """
    _validate_dispatch_payload(topic, payload, message=message)
    if topic == INGEST_OBJECT_CREATED:
        handle_ingest_object_created(_indexer_payload(payload))
    elif topic == INGEST_VAULT_CHANGED:
        handle_ingest_vault_changed(payload, trace_id=trace_id)
    elif topic == INGEST_OBJECT_DELETED:
        handle_ingest_object_deleted(payload)
    elif topic == PANEL_SCAN_REQUESTED:
        event_timestamp = message.get("timestamp") or payload.get("timestamp")
        handle_panel_scan_requested(
            payload,
            trace_id=trace_id,
            scan_requested_ts=event_timestamp,
        )
    elif topic == PROMOTE_INTENT_CREATED:
        from app.promotion.consumer import consume_promotion_intent_payload

        consume_promotion_intent_payload(
            payload,
            trace_id=trace_id,
            event_id=event_id,
        )
    elif topic == NOTE_MOVE_WORKBENCH:
        handle_note_move_workbench(payload, trace_id=trace_id)
    elif topic == INDEX_EMBEDDING_REQUESTED:
        process_indexer_event(
            {
                "event": INDEX_EMBEDDING_REQUESTED,
                "payload": dict(payload),
                "trace_id": trace_id,
            }
        )
    elif topic == KNOWLEDGE_ACQUISITION_STAGE_COMPLETED:
        handle_knowledge_acquisition_stage_completed(payload, trace_id=trace_id)
    elif topic == KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED:
        handle_knowledge_acquisition_stage_dead_lettered(payload, trace_id=trace_id)
    else:
        logger.debug("worker skipping unsupported topic=%s trace_id=%s", topic, trace_id)


def _indexer_payload(payload: Mapping[str, Any]) -> dict[str, object]:
    return dict(payload)


def _trace_id_from_envelope(envelope: object) -> str | None:
    if isinstance(envelope, dict):
        raw = envelope.get("trace_id")
        return str(raw) if raw else None
    raw = getattr(envelope, "trace_id", None)
    return str(raw) if raw else None


def handle_ingest_object_deleted(payload: Mapping[str, Any]) -> None:
    """Purge the deleted object's vectors from the durable index (T-delete).

    The purge itself is delegated to
    ``app.services.indexer.purge_object_vectors`` -- the established indexer
    seam onto the vector index (this worker must not import the transitional
    ``app.stores`` layer directly; ``tests/architecture/
    test_deprecated_store_callers.py`` forbids new callers). This handler
    owns only the event-side contract: payload parsing, logging, and
    never-crash degradation.

    D-2 tombstone semantics are preserved: only ``store_vector_index`` rows
    are removed (all views for the object, since neither store backend's
    ``purge_vectors`` filters by view -- see ``app/stores/memory.py``/
    ``app/stores/pg.py``); the ``store_objects`` row is never touched and
    stays as a ``path=NULL`` tombstone per
    ``tests/properties/test_tombstone_lineage.py`` (D-2, pinned by PR #2943).

    Idempotent under at-least-once redelivery: purging an object with no
    vector rows (already purged by a prior delivery, or never indexed) is a
    documented no-op on both store backends (``purge_vectors`` returns 0
    instead of raising) -- see KERNEL-11's harness registration for this
    topic in ``tests/workers/test_handler_idempotency_harness.py``.

    In-process cache coherence for the retrieval hybrid store
    (``app/retrieval/hybrid.py``) is handled by the existing rebuild seam,
    not here: per KERNEL-05 (``docs/RUNTIME_CORRECTNESS_KERNEL/
    RETRIEVAL_READS_DURABLE_INDEX.md``), the in-process cache is a
    cache-through of the durable index rebuilt via
    ``rebuild_from_durable_index()`` at process warm / explicit rebuild and
    kept fresh by the serving path's generation check (G1res-1, #2981:
    ``_revalidate_cache_generation()`` compares the durable store-generation
    token at most once per min-check interval and rebuilds on mismatch), the
    same seam ``handle_ingest_object_created`` and the indexer consumer rely
    on for their own purge+upsert writes -- this handler does not need its
    own bespoke cache-eviction path to stay consistent with that contract.
    """
    raw_uuid = resolve_event_object_id(dict(payload))
    object_id: UUID | None = None
    if raw_uuid:
        try:
            object_id = UUID(str(raw_uuid))
        except (ValueError, AttributeError, TypeError):
            object_id = None

    purged = 0
    if object_id is not None:
        purged = purge_object_vectors(object_id)
    else:
        logger.warning(
            "ingest delete event missing a resolvable uuid; skipping vector purge path=%s",
            payload.get("path"),
        )

    logger.info(
        "handled ingest delete event uuid=%s path=%s deleted=%s purged_vectors=%s",
        payload.get("uuid"),
        payload.get("path"),
        payload.get("deleted"),
        purged,
    )


# KA stage-scope this candidate's terminal artifact is written at (`REFINEMENT_
# PIPELINE_CONTRACT.md` § Stage execution model): `stage.completed` events fire
# for `normalize` and every extractor run too, but only a `candidate`-stage
# completion means a candidate note now exists and is eligible to advance
# toward triage. Intermediate stages are traced (dispatched, logged) but their
# bounded downstream action is a deliberate no-op -- there is no candidate yet
# to mark ready.
_KA_CANDIDATE_STAGE = "candidate"


def _ka_stage_scope(payload: Mapping[str, Any]) -> str:
    """The same identity segment KA-06's producer folds into its idempotency key.

    Mirrors ``app.knowledge_acquisition.stage_events._stage_scope``: an
    extractor run is scoped by ``{stage}:{extractor_id}``, a bare stage
    (``normalize``, ``candidate``) by the stage name alone. Recomputing it here
    (rather than importing the KA-layer private helper) keeps this worker-side
    consumer decoupled from the KA producer module's internals while deriving
    an identical scope string from the same payload fields the producer put on
    the wire.
    """
    stage = str(payload.get("stage") or "")
    extractor_id = payload.get("extractor_id")
    return f"{stage}:{extractor_id}" if extractor_id else stage


def _emit_ka_consumer_signal(
    event_type: str,
    *,
    content_identity: str,
    fingerprint: str,
    payload: Mapping[str, Any],
    trace_id: str | None,
) -> None:
    """Durable, item-scoped observability signal for a handled KA stage event.

    Mirrors ``_dead_letter_outbox_message``'s dual-write shape (JSONL audit
    sink always; DB outbox additionally when enabled) rather than an
    in-process cache: KERNEL-02/11 treat an in-memory dedup set as a fast-path
    only, never the idempotency source of truth (it is lost on restart). The
    idempotency key is derived through the single shared KERNEL-02 helper
    (``derive_idempotency_key``) from the SAME ``(topic, content_identity,
    stage-scope:stage_version)`` fingerprint the KA-06 producer already used
    to key its own emission -- so redelivery of the identical producer event
    reproduces the identical consumer-signal key and dedups to one row via
    ``ON CONFLICT (id) DO NOTHING``, without this worker needing its own
    ad-hoc scheme or a volatile cache.
    """
    key = derive_idempotency_key(event_type, content_identity, fingerprint)
    if _KA_CONSUMER_SIGNAL_DEDUP.seen(key):
        logger.debug(
            "KA consumer signal skipped (duplicate delivery) event_type=%s content_identity=%s",
            event_type,
            content_identity,
        )
        return

    event = make_outbox_event(
        event_type,
        source="worker",
        trace_id=trace_id,
        payload=dict(payload),
    )
    try:
        append_jsonl_outbox_event(_outbox_audit_path(), event, default_source="worker")
        if _use_db_outbox():
            write_outbox_event(event, idempotency_key=key)
    except Exception:
        # Best-effort observability signal: a failure here must never re-block
        # the outbox poll loop or fail the dispatch of the KA stage event
        # itself (these are audit-only side effects).
        logger.exception(
            "worker failed to record KA consumer signal event_type=%s content_identity=%s",
            event_type,
            content_identity,
        )


def handle_knowledge_acquisition_stage_completed(
    payload: Mapping[str, Any], *, trace_id: str | None = None
) -> None:
    """Consume ``knowledge_acquisition.stage.completed`` (KA-06 → KA-07, #3107).

    Bounded, minimal downstream action -- NOT the triage engine
    (`INGESTION_AND_TRIAGE_POLICY.md`/`CONTEXTUALIZATION_LAYER` own that,
    docs-only target state; out of scope here per the Issue). Only the
    ``candidate`` stage (the pipeline's terminal stage, where a candidate note
    now exists per `CANDIDATE_WRITEBACK.md`) has a concrete action: emit a
    durable, item-scoped ``knowledge_acquisition.candidate.ready_for_triage``
    observability signal marking the candidate eligible for triage pickup.
    Every other stage (`normalize`, each extractor run) is a traced no-op --
    dispatched and logged, no signal emitted -- because there is no candidate
    yet to mark ready.

    Idempotent: the emitted signal's key is derived from the same
    ``(content_identity, stage-scope, stage_version)`` fingerprint the
    producer used, so redelivery of the same stage-completed event converges
    on the durable DB-outbox row (when enabled) via ``ON CONFLICT DO NOTHING``
    -- no duplicate signal for a duplicate delivery.
    """
    stage = str(payload.get("stage") or "")
    content_identity = payload.get("content_identity")
    if not isinstance(content_identity, str) or not content_identity:
        logger.warning(
            "knowledge_acquisition.stage.completed missing content_identity; skipping stage=%s",
            stage,
        )
        return

    if stage != _KA_CANDIDATE_STAGE:
        logger.debug(
            "knowledge_acquisition.stage.completed traced, no downstream action "
            "(non-terminal stage) stage=%s content_identity=%s trace_id=%s",
            stage,
            content_identity,
            trace_id,
        )
        return

    stage_version = payload.get("stage_version")
    fingerprint = f"{_ka_stage_scope(payload)}:{stage_version}"
    _emit_ka_consumer_signal(
        KA_CANDIDATE_READY_FOR_TRIAGE,
        content_identity=content_identity,
        fingerprint=fingerprint,
        payload={
            "content_identity": content_identity,
            "stage": stage,
            "stage_version": stage_version,
            "artifact_path": payload.get("artifact_path"),
        },
        trace_id=trace_id,
    )
    logger.info(
        "knowledge_acquisition candidate ready for triage content_identity=%s trace_id=%s",
        content_identity,
        trace_id,
    )


def handle_knowledge_acquisition_stage_dead_lettered(
    payload: Mapping[str, Any], *, trace_id: str | None = None
) -> None:
    """Consume ``knowledge_acquisition.stage.dead_lettered`` (KA-06 → KA-07, #3107).

    Item-scoped surfacing only: this handler never raises, so a dead-lettered
    stage failure for one item never blocks dispatch of sibling items' events
    (`REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model: "loud and
    item-scoped ... without blocking other items or other extractors" --
    the same invariant KA-06's producer upholds at emission time; this
    consumer preserves it at dispatch time too). Surfaces a durable,
    observable ``knowledge_acquisition.stage.dead_letter_surfaced`` signal
    (JSONL audit sink + DB outbox when enabled) distinct from the worker's own
    dispatch-poison signal (``OUTBOX_EVENT_DEAD_LETTERED``) -- this is a KA
    stage COMPUTE failure the producer already recorded, never a queued
    outbox row exhausting dispatch attempts.

    Idempotent by the same content-derived key scheme as the completed-event
    handler above: redelivery of the same dead-letter event reproduces the
    same key and dedups.
    """
    stage = str(payload.get("stage") or "")
    content_identity = payload.get("content_identity")
    if not isinstance(content_identity, str) or not content_identity:
        logger.warning(
            "knowledge_acquisition.stage.dead_lettered missing content_identity; "
            "surfacing degraded, stage=%s",
            stage,
        )
        content_identity = ""

    stage_version = payload.get("stage_version")
    fingerprint = f"{_ka_stage_scope(payload)}:{stage_version}:dead_letter_surfaced"
    _emit_ka_consumer_signal(
        KA_STAGE_DEAD_LETTER_SURFACED,
        content_identity=content_identity or "unknown",
        fingerprint=fingerprint,
        payload={
            "content_identity": content_identity,
            "stage": stage,
            "stage_version": stage_version,
            "extractor_id": payload.get("extractor_id"),
            "reason": payload.get("reason"),
            "error": payload.get("error"),
        },
        trace_id=trace_id,
    )
    logger.warning(
        "knowledge_acquisition stage dead-letter surfaced content_identity=%s stage=%s "
        "reason=%s trace_id=%s",
        content_identity,
        stage,
        payload.get("reason"),
        trace_id,
    )


def _ensure_logging_configured() -> None:
    """Install the shared process-level JSON formatter (structured logging #3895).

    Root-logger wiring via ``configure_json_logging`` keeps every
    ``logging.getLogger(__name__)`` call site untouched and renders each
    worker log line as one JSON object on stdout with the span-schema field
    conventions (trace_id, status, extra) from
    ``docs/OBSERVABILITY.md :: JSON log and span schema``. Re-invocation
    rebinds the handler to the current stdout so pytest's capsys-replaced
    streams stay aligned (same contract the previous local stderr setup had).
    """
    configure_json_logging()
    # Records must reach the root JSON handler; the pre-#3895 local handler
    # setup switched this off.
    logger.propagate = True


def _resolve_optional_vault_root(vault_root: Path | None = None) -> Path | None:
    """Resolve the worker's vault root, or ``None`` when no vault is selected.

    Precedence: explicit ``vault_root`` -> existing ``WATCHER_VAULT_PATH`` ->
    existing ``VAULT_ROOT`` -> existing legacy ``/app/vault`` mount. The legacy
    ``/app/vault`` mount check is intentionally kept here; its removal is Slice
    05D (#2386) and out of scope for this slice. The silent CWD-relative
    ``Path("vault")`` fallback is removed (#2384): with no vault selected this
    returns ``None`` so the worker idles instead of synthesizing ``./vault``.
    """
    if vault_root is not None:
        return vault_root.expanduser().resolve()
    watcher_root = os.getenv("WATCHER_VAULT_PATH")
    if watcher_root:
        watcher_path = Path(watcher_root).expanduser()
        if watcher_path.exists():
            return watcher_path.resolve()
    env_root = os.getenv("VAULT_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser()
        if env_path.exists():
            return env_path.resolve()
    mounted_root = Path("/app/vault")  # legacy mount, removed in slice 05D (#2386)
    if mounted_root.exists():
        return mounted_root.resolve()
    return None


def _resolve_vault_root(vault_root: Path | None = None) -> Path:
    """Resolve the worker vault root, raising when no vault is selected.

    Event handlers require a vault root to locate note files; they call this
    strict variant. The no-vault idle decision is made earlier (see
    :func:`run_once`) so handlers are only reached once a vault is bound.
    """
    resolved = _resolve_optional_vault_root(vault_root)
    if resolved is None:
        raise NoVaultSelectedError(
            "outbox worker requires a selected vault to process events; "
            "VAULT_ROOT is unset"
        )
    return resolved


def _note_path_from_payload(payload: Mapping[str, Any], *, vault_root: Path) -> Path:
    rel_value = payload.get("relative_path")
    raw = payload.get("vault_path")

    if raw:
        candidate = Path(str(raw)).expanduser()
        try:
            resolved_candidate = candidate.resolve()
            resolved_root = vault_root.resolve()
            resolved_candidate.relative_to(resolved_root)
            return resolved_candidate
        except Exception:
            pass

    if not rel_value:
        raise ValueError("missing relative_path in ingest payload")

    note_path = vault_root / Path(str(rel_value))
    return note_path.expanduser().resolve()


def _normalize_uuid_value(raw: str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        if not raw:
            return ""
        return _normalize_uuid_value(raw[0])
    value = str(raw).strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    return value


def _event_id_from_message(message: Mapping[str, Any]) -> str:
    evt = message.get("event")
    if hasattr(evt, "event_id"):
        return str(getattr(evt, "event_id") or "")
    payload = message.get("payload")
    if isinstance(payload, Mapping):
        event_id = payload.get("event_id")
        if event_id:
            return str(event_id)
    return ""


_WARNED_ONCE: set[str] = set()


def _warn_once(key: str, message: str, *args: object) -> None:
    if key in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(key)
    logger.warning(message, *args)


def _maybe_heal_uuid(note_path: Path, vault_root: Path) -> str:
    try:
        rel_path = note_path.relative_to(vault_root)
    except Exception:
        return ""

    inbox_rel = Path(get_vault_inbox_dir_rel(vault_root))
    try:
        rel_path.relative_to(inbox_rel)
    except Exception:
        return ""

    # iCloud File Provider paths can transiently deny writes (EPERM/EACCES) even when
    # the file later becomes writable; retry briefly to avoid leaving inbox notes uuid-less.
    max_attempts = 5
    base_sleep = 0.2

    for attempt in range(max_attempts):
        try:
            healed = ensure_note_uuid(note_path, vault_root=vault_root)
            if healed:
                logger.info("healed uuid for inbox note note_path=%s", note_path)
            return healed
        except OSError as exc:
            if exc.errno in {errno.EPERM, errno.EACCES, errno.EROFS}:
                if attempt + 1 < max_attempts:
                    time.sleep(base_sleep * (2**attempt))
                    continue
                _warn_once(
                    f"uuid_heal_perm:{note_path}",
                    "uuid heal skipped (permission) note_path=%s errno=%s",
                    note_path,
                    exc.errno,
                )
                return ""
            logger.warning("failed to ensure uuid for %s: %s", note_path, exc)
            return ""
        except Exception as exc:
            logger.warning("failed to ensure uuid for %s: %s", note_path, exc)
            return ""

    return ""


def _ensure_uuid_with_backoff(note_path: Path, *, vault_root: Path) -> str:
    max_attempts = 5
    base_sleep = 0.2

    for attempt in range(max_attempts):
        try:
            healed = ensure_note_uuid(note_path, vault_root=vault_root)
            if healed:
                logger.info("ensured uuid for note note_path=%s", note_path)
            return healed
        except OSError as exc:
            if exc.errno in {errno.EPERM, errno.EACCES, errno.EROFS}:
                if attempt + 1 < max_attempts:
                    time.sleep(base_sleep * (2**attempt))
                    continue
                _warn_once(
                    f"uuid_ensure_perm:{note_path}",
                    "uuid ensure skipped (permission) note_path=%s errno=%s",
                    note_path,
                    exc.errno,
                )
                return ""
            logger.warning("failed to ensure uuid for %s: %s", note_path, exc)
            return ""
        except Exception as exc:
            logger.warning("failed to ensure uuid for %s: %s", note_path, exc)
            return ""

    return ""
def _write_markdown_if_changed(note_path: Path, original: str, updated: str) -> bool:
    if original == updated:
        return False
    current, expected_version = read_note_text_with_version(note_path)
    if current != original:
        return False
    DEFAULT_WRITE_GUARD.assert_writes_allowed("panel worker update")
    try:
        _WRITE_GUARD.write_if_unchanged(note_path, expected_version, updated)
        return True
    except VersionMismatch:
        return False


def _stabilized_note_text(note_path: Path, *, attempts: int = 6, base_sleep: float = 0.25) -> str | None:
    previous_signature: tuple[float, int, str] | None = None
    for attempt in range(attempts):
        try:
            before = note_path.stat()
            raw_text, raw_version = read_note_text_with_version(note_path)
            after = note_path.stat()
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.EPERM, errno.EACCES, errno.EROFS}:
                if attempt + 1 < attempts:
                    time.sleep(base_sleep * (2**attempt))
                    continue
                return None
            raise
        signature = (
            float(after.st_mtime),
            int(after.st_size),
            raw_version,
        )
        if before.st_mtime == after.st_mtime and before.st_size == after.st_size:
            if signature == previous_signature:
                return raw_text
            previous_signature = signature
        if attempt + 1 < attempts:
            time.sleep(base_sleep * (2**attempt))
    return None


def _outbox_audit_path() -> Path:
    return Path(os.getenv("INDEX_OUTBOX_PATH", "/app/tmp/index-outbox.jsonl")).expanduser()


def _payload_retry_count(payload: Mapping[str, Any]) -> int:
    raw = payload.get("_worker_retry_count")
    if raw is None:
        return 0
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0


def _retry_exhausted(payload: Mapping[str, Any]) -> bool:
    return _payload_retry_count(payload) >= _MAX_TRANSIENT_RETRY_ATTEMPTS


def _original_event_id(payload: Mapping[str, Any], explicit_event_id: str | None) -> str:
    if explicit_event_id:
        return explicit_event_id
    raw = payload.get("event_id") or payload.get("original_event_id")
    return str(raw) if raw else ""


def _emit_retry_dead_letter(
    topic: str,
    payload: Mapping[str, Any],
    *,
    note_path: Path,
    reason: str,
    retry_count: int,
    trace_id: str | None,
    original_event_id: str | None,
) -> None:
    event = make_outbox_event(
        OUTBOX_EVENT_DEAD_LETTERED,
        source="worker",
        trace_id=trace_id or str(payload.get("trace_id") or "") or None,
        payload={
            "original_topic": topic,
            "original_event_id": _original_event_id(payload, original_event_id),
            "note_path": str(note_path),
            "reason": reason,
            "retry_count": retry_count,
        },
    )
    append_jsonl_outbox_event(_outbox_audit_path(), event, default_source="worker")
    if _use_db_outbox():
        # Attempt-scoped key (topic, original event id/path, retry count) so a
        # retried audit write dedups but a later genuine re-exhaustion at a new
        # attempt count is NOT swallowed (I-E1).
        write_outbox_event(
            event,
            idempotency_key=derive_idempotency_key(
                OUTBOX_EVENT_DEAD_LETTERED,
                _original_event_id(payload, original_event_id) or str(note_path),
                f"retry-exhausted:{reason}:{retry_count}",
            ),
        )


def _dead_letter_outbox_message(
    topic: str | None,
    payload: Mapping[str, Any],
    *,
    message_id: str,
    reason: str,
    attempts: int,
    trace_id: str | None,
    error: str,
    conn: Any = None,
) -> None:
    """Audit a poison outbox row that exceeded the dispatch-attempt budget.

    Writes an ``outbox.event.dead_lettered`` record to the JSONL audit sink (and the
    DB outbox when enabled) so the drop is observable. Best-effort: a failure here must
    not re-block the queue, so exceptions are swallowed after logging.

    ``conn`` (#3930): when the caller shares its manual-commit connection so the
    audit row commits atomically with the surrounding bookkeeping, the DB write
    runs inside a savepoint (``conn.transaction()``) — its failure rolls back
    only the audit insert, never the caller's transaction, preserving the
    best-effort contract (the ack must still commit).
    """
    try:
        event = make_outbox_event(
            OUTBOX_EVENT_DEAD_LETTERED,
            source="worker",
            trace_id=trace_id or str(payload.get("trace_id") or "") or None,
            payload={
                "original_topic": topic,
                "original_event_id": _original_event_id(payload, None),
                "outbox_id": message_id,
                "reason": reason,
                "attempts": attempts,
                "error": error,
            },
        )
        append_jsonl_outbox_event(_outbox_audit_path(), event, default_source="worker")
        if _use_db_outbox():
            # Keyed on (topic, poisoned outbox row id, attempts): duplicate
            # audit emission for the same drop dedups; a later re-poisoning at
            # a different attempt count produces a distinct row (I-E1).
            key = derive_idempotency_key(
                OUTBOX_EVENT_DEAD_LETTERED,
                str(message_id),
                f"poison:{attempts}",
            )
            if conn is not None:
                with conn.transaction():
                    write_outbox_event(event, conn=conn, idempotency_key=key)
            else:
                write_outbox_event(event, idempotency_key=key)
        logger.warning(
            "worker dead-lettered poison outbox row topic=%s id=%s reason=%s attempts=%s",
            topic,
            message_id,
            reason,
            attempts,
        )
    except Exception:
        logger.exception(
            "worker dead-letter audit failed topic=%s id=%s reason=%s",
            topic,
            message_id,
            reason,
        )
    _draft_schema_violation_case(
        topic=topic,
        reason=reason,
        event_id=_original_event_id(payload, None) or message_id,
        payload=payload,
        trace_id=trace_id,
    )


def _dead_letter_and_ack(
    message_id: Any,
    *,
    topic: str | None,
    payload: Mapping[str, Any],
    reason: str,
    attempts: int,
    trace_id: str | None,
    error: str,
) -> None:
    """Write the dead-letter audit row and ack the poisoned row atomically (#3930).

    One canonical manual-commit connection carries both statements so a crash
    between them cannot strand an audited-but-unacked row (which would re-poll
    and duplicate work on restart). When the canonical connection is
    unavailable, degrade to the historical per-call autocommit sequence —
    at-least-once semantics hold either way (the attempt-scoped idempotency
    key dedups the audit row on a same-attempt retry).
    """
    conn = open_outbox_txn_conn()
    if conn is None:
        _dead_letter_outbox_message(
            topic,
            payload,
            message_id=str(message_id or ""),
            reason=reason,
            attempts=attempts,
            trace_id=trace_id,
            error=error,
        )
        ack_outbox(message_id)
        return
    try:
        # Outermost transaction block: the connection is fresh/idle here, so
        # this BEGINs and commits both statements on clean exit. Without it,
        # the dead-letter helper's own savepoint block would be the outermost
        # transaction on this connection and psycopg3 would commit the audit
        # insert on block exit — before the ack, i.e. two transactions again.
        with conn.transaction():
            _dead_letter_outbox_message(
                topic,
                payload,
                message_id=str(message_id or ""),
                reason=reason,
                attempts=attempts,
                trace_id=trace_id,
                error=error,
                conn=conn,
            )
            ack_outbox(conn, message_id)
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - close is best-effort
            pass


def _record_failed_dispatch(
    message_id: Any,
    *,
    topic: str | None,
    payload: Mapping[str, Any],
    trace_id: str | None,
    error: BaseException,
) -> bool:
    """Record one failed dispatch: bump the poison budget, dead-letter at the cap.

    Returns True when the row was dead-lettered and acked (the caller moves on
    to the next row) and False when the row stays pending (the caller re-raises
    so the supervised worker crash-retries; at-least-once).

    On the canonical connection all bookkeeping for this failure commits as ONE
    transaction (#3930): below the cap the attempts bump commits alone, making
    the poison budget durable across the crash-retry (#2252); at the cap bump +
    dead-letter audit + ack commit together, so a crash between the statements
    rolls the whole cycle back instead of stranding partial state (a row
    durably ``attempts == max`` yet undelivered, then a duplicate dead-letter
    audit row under ``poison:<n+1>`` on the next cycle). When the canonical
    connection is unavailable, degrade to the historical per-call autocommit
    sequence.
    """
    reason = f"dispatch_failed:{type(error).__name__}"
    conn = open_outbox_txn_conn()
    if conn is None:
        attempts = 0
        try:
            attempts = bump_outbox_attempts(message_id)
        except Exception:
            logger.exception(
                "worker failed to record dispatch attempt topic=%s id=%s",
                topic,
                message_id,
            )
        if attempts and attempts >= _resolve_max_dispatch_attempts():
            _dead_letter_outbox_message(
                topic,
                payload,
                message_id=str(message_id or ""),
                reason=reason,
                attempts=attempts,
                trace_id=trace_id,
                error=str(error),
            )
            ack_outbox(message_id)
            return True
        return False
    try:
        attempts = 0
        try:
            attempts = bump_outbox_attempts(conn, message_id)
        except Exception:
            logger.exception(
                "worker failed to record dispatch attempt topic=%s id=%s",
                topic,
                message_id,
            )
            try:
                conn.rollback()
            except Exception:  # pragma: no cover - rollback is best-effort
                pass
        if attempts and attempts >= _resolve_max_dispatch_attempts():
            _dead_letter_outbox_message(
                topic,
                payload,
                message_id=str(message_id or ""),
                reason=reason,
                attempts=attempts,
                trace_id=trace_id,
                error=str(error),
                conn=conn,
            )
            # Ack and commit share one guard: either can raise on the same
            # broken-connection fault that would make the other fail too, and
            # nothing durable happens on this connection unless both succeed
            # (the ack itself rolls back with the rest of the transaction if
            # only commit fails) — fall through to the same "not resolved"
            # signal the below-cap path returns: the caller re-raises the
            # original dispatch error for crash-retry, instead of a new
            # ack/commit-failure exception masking it.
            return _ack_and_commit_or_log(conn, message_id=message_id, topic=topic)
        _commit_or_log(conn, topic=topic, message_id=message_id)
        return False
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - close is best-effort
            pass


def _commit_or_log(conn: Any, *, topic: str | None, message_id: Any) -> bool:
    """Commit ``conn``, logging (not raising) on failure.

    A raise here would replace the caller's own dispatch-failure exception
    with an unrelated commit-failure exception by the time it reaches the
    `except Exception as handler_exc: ... raise` re-raise in `run()` (#3930
    review) — the row stays safely pending either way (nothing committed), so
    the caller only needs a bool to decide whether bookkeeping is durable.
    """
    try:
        conn.commit()
    except Exception:
        logger.exception(
            "worker failed to commit dispatch-failure bookkeeping topic=%s id=%s",
            topic,
            message_id,
        )
        return False
    return True


def _ack_and_commit_or_log(conn: Any, *, message_id: Any, topic: str | None) -> bool:
    """Ack ``message_id`` and commit ``conn``, logging (not raising) on failure.

    Same rationale as :func:`_commit_or_log`, extended to the ack call: a bare
    `ack_outbox(conn, message_id)` before the commit shares the identical
    broken-connection failure surface as `conn.commit()` and can equally raise
    and mask the caller's original dispatch error (#3930 round-2 review) —
    both statements are guarded by the same try so either failure degrades to
    the same "not resolved" bool instead of propagating.
    """
    try:
        ack_outbox(conn, message_id)
        conn.commit()
    except Exception:
        logger.exception(
            "worker failed to ack/commit dispatch-failure bookkeeping topic=%s id=%s",
            topic,
            message_id,
        )
        return False
    return True


def _draft_schema_violation_case(
    *,
    topic: str | None,
    reason: str,
    event_id: str,
    payload: Mapping[str, Any],
    trace_id: str | None,
) -> None:
    """Draft a schema-violation dead-letter as an eval-case candidate (KERNEL-15, #2777).

    Best-effort and additive to the dead-letter audit above: a failure here
    (including no vault selected, or WriteGuard blocking writes) must never
    re-block the queue or mask the underlying dead-letter, so every exception
    is caught and logged, never re-raised.
    """
    try:
        from app.eval.failure_capture import draft_dead_letter_case, is_schema_violation_reason

        if not is_schema_violation_reason(reason):
            return
        vault_root = _resolve_optional_vault_root(None)
        if vault_root is None:
            return
        draft_dead_letter_case(
            vault_root=vault_root,
            topic=topic or "",
            reason=reason,
            event_id=event_id,
            payload=payload,
            trace_id=trace_id,
        )
    except Exception:
        logger.exception(
            "worker failure-to-eval draft failed topic=%s reason=%s",
            topic,
            reason,
        )


def _queue_transient_retry(
    topic: str,
    payload: Mapping[str, Any],
    *,
    note_path: Path,
    reason: str,
    trace_id: str | None = None,
    original_event_id: str | None = None,
) -> bool:
    retry_count = _payload_retry_count(payload)
    if retry_count >= _MAX_TRANSIENT_RETRY_ATTEMPTS:
        try:
            _emit_retry_dead_letter(
                topic,
                payload,
                note_path=note_path,
                reason=reason,
                retry_count=retry_count,
                trace_id=trace_id,
                original_event_id=original_event_id,
            )
        except Exception:
            logger.exception(
                "worker retry dead-letter emit failed topic=%s note_path=%s reason=%s retry_count=%s",
                topic,
                note_path,
                reason,
                retry_count,
            )
        logger.warning(
            "worker retry exhausted topic=%s note_path=%s reason=%s retry_count=%s",
            topic,
            note_path,
            reason,
            retry_count,
        )
        return False

    retry_payload = dict(payload)
    retry_payload["_worker_retry_count"] = retry_count + 1
    retry_payload["_worker_retry_reason"] = reason
    retry_payload["_worker_retry_enqueued_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    retry_event = new_event(
        event_type=topic,
        payload=retry_payload,
        trace_id=trace_id or str(payload.get("trace_id") or "") or None,
        source="worker",
    )

    try:
        if _use_db_outbox():
            # Attempt-scoped key (topic, original event id/path, retry:<n>) so
            # each retry attempt is a distinct row (intentional re-emission),
            # while a duplicate enqueue of the same attempt dedups (I-E1).
            write_outbox_event(
                retry_event,
                idempotency_key=derive_idempotency_key(
                    topic,
                    _original_event_id(payload, original_event_id) or str(note_path),
                    f"retry:{retry_count + 1}:{reason}",
                ),
            )
        else:
            append_jsonl_outbox_event(_outbox_audit_path(), retry_event, default_source="worker")
    except Exception:
        logger.exception(
            "worker retry enqueue failed topic=%s note_path=%s reason=%s retry_count=%s",
            topic,
            note_path,
            reason,
            retry_count + 1,
        )
        return False

    logger.info(
        "worker retry queued topic=%s note_path=%s reason=%s retry_count=%s",
        topic,
        note_path,
        reason,
        retry_count + 1,
    )
    return True



def handle_panel_scan_requested(
    payload: Mapping[str, Any],
    *,
    vault_root: Path | None = None,
    trace_id: str | None = None,
    scan_requested_ts: str | None = None,
) -> WorkerPanelSummary:
    resolved_root = _resolve_vault_root(vault_root)
    note_path = _note_path_from_payload(payload, vault_root=resolved_root)

    # Capture runtime start timestamp for latency tracking
    runtime_start_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    trace_id = trace_id or str(payload.get("trace_id") or "") or None

    raw_text = _stabilized_note_text(note_path)
    if raw_text is None:
        if not _queue_transient_retry(
            PANEL_SCAN_REQUESTED,
            payload,
            note_path=note_path,
            reason="file_unstable",
            trace_id=trace_id,
        ):
            if _retry_exhausted(payload):
                logger.warning("panel scan dropped after exhausted retries (file unstable) note_path=%s", note_path)
                return WorkerPanelSummary(emitted=0, deferred=False)
            raise TransientRetryEnqueueError(f"failed to queue retry for unstable panel note: {note_path}")
        logger.info("panel scan deferred (file unstable) note_path=%s", note_path)
        return WorkerPanelSummary(emitted=0, deferred=True)

    frontmatter, _ = load_frontmatter(raw_text)
    note_uuid = _normalize_uuid_value(frontmatter.get("uuid") if isinstance(frontmatter, dict) else None)
    healed_uuid = ""
    if not note_uuid:
        healed_uuid = _maybe_heal_uuid(note_path, resolved_root)
        raw_text = _stabilized_note_text(note_path) or raw_text
        frontmatter, _ = load_frontmatter(raw_text)
        note_uuid = _normalize_uuid_value(frontmatter.get("uuid") if isinstance(frontmatter, dict) else None) or healed_uuid

    if not note_uuid:
        if not _queue_transient_retry(
            PANEL_SCAN_REQUESTED,
            payload,
            note_path=note_path,
            reason="missing_uuid",
            trace_id=trace_id,
        ):
            if _retry_exhausted(payload):
                logger.warning("panel scan dropped after exhausted retries (missing uuid) note_path=%s", note_path)
                return WorkerPanelSummary(emitted=0, deferred=False)
            raise TransientRetryEnqueueError(f"failed to queue retry for missing panel note uuid: {note_path}")
        logger.info("panel scan skipped (missing uuid) note_path=%s", note_path)
        return WorkerPanelSummary(emitted=0, deferred=True)

    try:
        UUID(note_uuid)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidPanelNoteUUIDDispatchError(note_uuid) from exc

    # The scan event carries the retained vault UUID. Historical rows may map
    # it to a different canonical objects.id; all ObjectStore-facing refresh,
    # intent, and writeback work must use that canonical key.
    canonical_note_id = resolve_canonical_object_id(note_uuid)

    refresh_panel_note_object(
        note_uuid=canonical_note_id,
        note_path=note_path,
        raw_text=raw_text,
        trace_id=trace_id or "",
    )

    execution = run_panel_note_execution(
        canonical_note_id,
        trace_id=trace_id,
        outbox_path=_outbox_audit_path(),
        vault_root=resolved_root,
        vault_uuid=note_uuid,
        persist_created_to_db=_use_db_outbox(),
    )
    emitted = execution.emitted_count

    # Emit latency summary for this sync-chain event
    try:
        runtime_complete_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        # scan_requested_ts from event envelope, file_detection_ts from payload.mtime_iso
        scan_requested_ts = scan_requested_ts or str(payload.get("timestamp", ""))
        file_detection_ts = str(payload.get("mtime_iso") or "")

        # If mtime_iso is not available, try to derive from timestamp as fallback
        if not file_detection_ts:
            file_detection_ts = scan_requested_ts

        if trace_id and file_detection_ts and scan_requested_ts:
            # Content-derived dedup (#2881): keyed on the observation's own
            # stable timestamps (same across a redelivered dispatch of the
            # same outbox row), never the wall-clock runtime_start/complete
            # timestamps computed fresh on every dispatch.
            summary_key = derive_idempotency_key(
                "sync.latency.summary",
                note_uuid,
                payload_fingerprint(
                    {
                        "scan_requested_ts": scan_requested_ts,
                        "file_detection_ts": file_detection_ts,
                    }
                ),
            )
            if _PANEL_LATENCY_SUMMARY_DEDUP.seen(summary_key):
                logger.debug(
                    "latency summary skipped (duplicate observation) trace_id=%s note_uuid=%s",
                    trace_id,
                    note_uuid,
                )
            else:
                correlation = SyncChainCorrelationData(
                    trace_id=trace_id,
                    note_uuid=note_uuid,
                    note_path=str(note_path.relative_to(resolved_root)),
                    file_detection_ts=file_detection_ts,
                    scan_requested_ts=scan_requested_ts,
                    runtime_start_ts=runtime_start_ts,
                )
                latency_payload = correlation.complete(completion_ts=runtime_complete_ts)
                latency_event = SyncLatencySummaryEvent(
                    trace_id=trace_id,
                    payload=latency_payload,
                )
                outbox_path_obj = _outbox_audit_path()
                outbox_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with outbox_path_obj.open("a", encoding="utf-8") as f:
                    f.write(latency_event.model_dump_json())
                    f.write("\n")
                logger.info(
                    "latency summary emitted trace_id=%s note_uuid=%s end_to_end_ms=%s",
                    trace_id,
                    note_uuid,
                    latency_payload.end_to_end_ms,
                )
    except Exception as exc:
        logger.warning("failed to emit latency summary: %s", exc)

    if emitted:
        logger.info("panel scan handled note_path=%s note_uuid=%s emitted=%s", note_path, note_uuid, emitted)
    else:
        logger.info("panel scan produced no events note_path=%s note_uuid=%s", note_path, note_uuid)
    return WorkerPanelSummary(emitted=emitted)


def _use_db_outbox() -> bool:
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    return backend == "pg" or bool(os.getenv("DATABASE_URL") or os.getenv("DB_DSN"))

def handle_ingest_vault_changed(
    payload: Mapping[str, Any],
    *,
    vault_root: Path | None = None,
    trace_id: str | None = None,
) -> WorkerIngestSummary:
    resolved_root = _resolve_vault_root(vault_root)
    note_path = _note_path_from_payload(payload, vault_root=resolved_root)

    healed_uuid = _maybe_heal_uuid(note_path, resolved_root)

    raw_text = _stabilized_note_text(note_path)
    if raw_text is None:
        if not _queue_transient_retry(
            INGEST_VAULT_CHANGED,
            payload,
            note_path=note_path,
            reason="missing_or_unstable_note",
            trace_id=trace_id,
        ):
            if _retry_exhausted(payload):
                logger.warning("ingest dropped after exhausted retries note_path=%s", note_path)
                return WorkerIngestSummary(ingested=0)
            raise TransientRetryEnqueueError(f"failed to queue retry for missing or unstable note: {note_path}")
        logger.warning("ingest skipped (missing note) note_path=%s", note_path)
        return WorkerIngestSummary(ingested=0)

    frontmatter, body = load_frontmatter(raw_text)
    # Canonicalize on the AI-panel-stripped body (KERNEL-06, #2768 fix): the panel
    # agent writes both the `%% AI:Start/End %%` fence contents and a separate
    # `> [!info]- AI status` receipt callout back into the note body on disk (see
    # app/agents/panel_agent/runtime.py write_text / app/agents/panel/writeback.py
    # write_receipts). The receipt callout carries a per-run timestamp, so the raw
    # body mutates between first ingest and a later reingest of the same source
    # content even when nothing the human wrote changed. Hashing the raw body made
    # `provenance.content_hash` (and the companion content_hash) non-deterministic
    # across reruns, breaking registry-chain rerun idempotence. Stripping both
    # panel artifacts here — once, before `content` fans out to the store_objects
    # payload, the vector-index content_hash stamp, and the companion hash — keeps
    # all three consumers looking at the same canonical source body.
    content = strip_ai_status_block(strip_ai_panels(body or raw_text)).strip()

    note_uuid = _normalize_uuid_value(frontmatter.get("uuid") or frontmatter.get("id"))
    if not note_uuid and healed_uuid:
        note_uuid = healed_uuid
    if not note_uuid:
        note_uuid = _ensure_uuid_with_backoff(note_path, vault_root=resolved_root)
        if note_uuid:
            raw_text = _stabilized_note_text(note_path) or raw_text
            frontmatter, body = load_frontmatter(raw_text)

    if not note_uuid:
        logger.debug("note missing uuid after heal attempt note_path=%s", note_path)
    else:
        try:
            rel_path = note_path.relative_to(resolved_root)
            text_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            write_companion(
                resolved_root,
                CompanionNote(
                    uuid=note_uuid,
                    source_ref=str(rel_path),
                    title=str(frontmatter.get("title") or note_path.stem),
                    content_hash=text_sha256,
                    ingest_state="tracked",
                    last_ingested=datetime.now(timezone.utc).isoformat(),
                    created_by_instance=_resolve_instance_id(),
                    attachments=scan_attachments(content),
                ),
            )
        except OSError as exc:
            if exc.errno in {errno.EPERM, errno.EACCES, errno.EROFS}:
                _warn_once(
                    f"companion_write_perm:{note_path}",
                    "companion write skipped (permission) note_path=%s errno=%s",
                    note_path,
                    exc.errno,
                )
            else:
                raise

    ingest_obj: dict[str, Any] = {
        "uuid": note_uuid,
        "content": content,
        "title": frontmatter.get("title") or note_path.stem,
        "review_state": frontmatter.get("review_state"),
        "maturity": frontmatter.get("maturity") or None,
        "trace_id": payload.get("trace_id"),
        "payload": {
            "frontmatter": frontmatter,
            "raw_text": raw_text,
            "hash": payload.get("hash"),
            "watcher": payload.get("watcher"),
        },
        "source_ref": str(note_path),
        "kind": "note",
    }

    handle_ingest_object_created(ingest_obj)
    return WorkerIngestSummary(ingested=1)


def handle_note_move_workbench(
    payload: Mapping[str, Any],
    *,
    vault_root: Path | None = None,
    trace_id: str | None = None,
) -> None:
    """Handle a note.move.workbench event from the panel agent.

    Delegates to the Vault Action Layer (app.vault.actions.move_note_to_zone).
    This is the first Tier-2 vault action handler; see app/vault/actions.py for
    the full governed mutation chain and the long-term artifact model.
    """
    from app.vault.actions import move_note_to_zone
    from app.vault.layout import load_layout

    note_path_str = payload.get("note_path")
    if not note_path_str:
        logger.warning(
            "handle_note_move_workbench: missing note_path in payload trace_id=%s",
            trace_id or "-",
        )
        return

    resolved_root = _resolve_vault_root(vault_root)
    try:
        layout = load_layout(resolved_root)
    except Exception as exc:
        logger.warning(
            "handle_note_move_workbench: cannot load vault layout vault_root=%s error=%s trace_id=%s",
            resolved_root,
            exc,
            trace_id or "-",
        )
        return

    params = payload.get("params") or {}
    destination_zone = params.get("destination_zone") or "workbench"
    intent_id = payload.get("action_id") or payload.get("intent_id")
    note_path = Path(str(note_path_str))

    result = move_note_to_zone(
        note_path=note_path,
        destination_zone=destination_zone,
        vault_root=resolved_root,
        layout=layout,
        actor="panel_agent",
        intent_id=str(intent_id) if intent_id else None,
        trace_id=trace_id,
    )

    if result.skipped:
        logger.info(
            "handle_note_move_workbench: skipped reason=%s note_path=%s trace_id=%s",
            result.reason,
            note_path,
            trace_id or "-",
        )
    elif result.mutation_applied:
        logger.info(
            "handle_note_move_workbench: moved from=%s to=%s receipt_written=%s trace_id=%s",
            result.source_path,
            result.destination_path,
            result.receipt_written,
            trace_id or "-",
        )
    else:
        logger.warning(
            "handle_note_move_workbench: move failed reason=%s trace_id=%s",
            result.reason,
            trace_id or "-",
        )


def run(
    interval: float = 0.2,
    startup_retries: int = 30,
    retry_delay: float = 1.0,
    heartbeat_interval: float | None = None,
    log_heartbeat_interval: float | None = None,
    stop_after_ticks: int | None = None,
) -> None:
    _ensure_logging_configured()

    # Opt-in Prometheus endpoint (builder-ops-stability Issue 6): no-op unless
    # WORKER_METRICS_PORT is set to a positive port.
    maybe_start_worker_metrics_server()

    for attempt in range(startup_retries):
        try:
            bootstrap()
            break
        except Exception as exc:
            if attempt + 1 == startup_retries:
                logger.exception("worker bootstrap failed after %s attempts", startup_retries)
                raise
            logger.warning(
                "worker bootstrap failed (attempt %s/%s): %s",
                attempt + 1,
                startup_retries,
                exc,
            )
            time.sleep(retry_delay)

    # Resolve vault-authored settings at worker startup (SETTINGS-01 / F1): without
    # this the worker's LLM routing / embeddings run on pydantic code defaults.
    # Invalid sources degrade loudly on health rather than crashing the worker.
    try:
        from app.settings.ingestion import ingest_settings

        ingest_settings(reason="worker_startup")
    except Exception as exc:  # pragma: no cover - defensive; ingest already degrades
        logger.warning("Settings ingestion at worker startup failed: %s", exc)

    heartbeat_interval = heartbeat_interval if heartbeat_interval is not None else float(
        os.getenv("WORKER_HEARTBEAT_INTERVAL", "1")
    )
    heartbeat_path = resolve_worker_heartbeat_path()
    outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "/app/tmp/index-outbox.jsonl")).expanduser()

    if log_heartbeat_interval is None:
        raw_log_interval = os.getenv("WORKER_LOG_HEARTBEAT_SECONDS", "60")
        try:
            log_heartbeat_interval = float(raw_log_interval)
        except ValueError:
            log_heartbeat_interval = 60.0
    if log_heartbeat_interval is not None and log_heartbeat_interval <= 0:
        log_heartbeat_interval = None

    processed_by_event: dict[str, int] = {}
    last_processed: dict[str, float] = {}

    logger.info(
        "worker starting interval=%s heartbeat_interval=%s heartbeat_path=%s outbox_path=%s",
        interval,
        heartbeat_interval,
        heartbeat_path,
        outbox_path,
    )
    last_log = time.time()

    ticks_total = 0
    processed_total = 0
    errors_total = 0
    last_heartbeat = 0.0

    # The loop polls/dispatches only while a vault is selected. When no vault is
    # bound, ``no_vault_idle`` short-circuits the poll/dispatch body for that tick
    # (heartbeats, logging, sleep, and stop-after-ticks below still run).
    while True:
        ticks_total += 1
        WORKER_LAST_TICK_TIMESTAMP.set(time.time())
        no_vault_idle = _resolve_optional_vault_root(None) is None
        if no_vault_idle:
            # No-vault idle guard (#2407): match run_once's runtime decision. With
            # no vault selected the production loop must not poll/dispatch
            # vault-bound rows, since their handlers raise NoVaultSelectedError —
            # a non-transient error that would poison-count and dead-letter the
            # row instead of leaving it queued until a vault is selected.
            logger.debug("worker tick idled: no vault selected")
        try:
            message = None if no_vault_idle else poll_outbox_one()
            if message:
                processed_total += 1
                WORKER_PROCESSED.inc()
                topic = message.get("topic")
                event_ts = time.time()
                if topic:
                    processed_by_event[topic] = processed_by_event.get(topic, 0) + 1
                    last_processed[topic] = event_ts

                event_id = _event_id_from_message(message)
                if event_id and _EVENT_DEDUP.seen(event_id):
                    # Known-duplicate no-op (#2963): this event_id was already
                    # dispatched earlier in this process lifetime. Ack the row so it advances
                    # instead of leaving it queued. poll_outbox_one always returns
                    # the oldest un-acked row, so an un-acked known-duplicate would
                    # be re-polled every tick, .seen() would keep returning True,
                    # and the loop would `continue` forever on it -- a silent
                    # head-of-line stall (a softer echo of the #2252 stall) that
                    # also starves every downstream row. The row IS handled here
                    # (a deduplicated no-op), so acking it is the receipt.
                    ack_outbox(message["id"])
                    continue

                payload = message.get("payload") or {}
                if event_id and isinstance(payload, Mapping) and not payload.get("event_id"):
                    payload = dict(payload)
                    payload["event_id"] = event_id
                trace_id = (
                    payload.get("trace_id")
                    or message.get("trace_id")
                    or _trace_id_from_envelope(message.get("event"))
                    or "-"
                )

                handler_note_path: str | None = None
                if topic == INGEST_VAULT_CHANGED:
                    try:
                        resolved_root = _resolve_vault_root(None)
                        handler_note_path = str(_note_path_from_payload(payload, vault_root=resolved_root))
                    except Exception:
                        handler_note_path = None

                with start_span("worker.consume", trace_id, {"topic": topic}):
                    try:
                        # Dispatch through the single shared table so run() and
                        # run_once cannot diverge on which topics are supported (#2407).
                        _dispatch_topic(
                            topic,
                            payload,
                            trace_id=trace_id,
                            message=message,
                            event_id=event_id,
                        )
                    except InvalidPanelNoteUUIDDispatchError as uuid_exc:
                        errors_total += 1
                        logger.warning(
                            "worker dead-lettered malformed panel note uuid topic=%s id=%s",
                            topic,
                            message.get("id"),
                        )
                        _dead_letter_and_ack(
                            message["id"],
                            topic=topic,
                            payload=payload,
                            reason=INVALID_NOTE_UUID_REASON,
                            attempts=0,
                            trace_id=None if trace_id == "-" else trace_id,
                            error=str(uuid_exc),
                        )
                        continue
                    except SchemaViolationDispatchError as schema_exc:
                        # Immediate dead-letter (KERNEL-08, #2770): a registered-schema
                        # violation is never transient and never worth a retry budget —
                        # the payload is structurally invalid, not intermittently
                        # unavailable, so dispatch never partially processes it.
                        errors_total += 1
                        logger.warning(
                            "worker dead-lettered schema violation topic=%s id=%s reason=%s",
                            topic,
                            message.get("id"),
                            schema_exc.violation.reason,
                        )
                        _dead_letter_and_ack(
                            message["id"],
                            topic=topic,
                            payload=payload,
                            reason=SCHEMA_VIOLATION_REASON,
                            attempts=0,
                            trace_id=None if trace_id == "-" else trace_id,
                            error=str(schema_exc),
                        )
                        continue
                    except Exception as handler_exc:
                        logger.exception(
                            "worker handler failed topic=%s trace_id=%s note_path=%s",
                            topic,
                            trace_id,
                            handler_note_path or "-",
                        )
                        if _is_transient_dispatch_error(handler_exc):
                            logger.warning(
                                "worker transient handler failure; keeping outbox row pending "
                                "topic=%s id=%s error=%s",
                                topic,
                                message.get("id"),
                                type(handler_exc).__name__,
                            )
                            raise
                        # Bound retries per row so a single un-handleable (poison) event
                        # cannot crash-loop the worker at the head of the queue and
                        # block every following row (the processed_total=0 stall, #2252).
                        # The bump, dead-letter audit, and ack commit as one
                        # transaction on one connection (#3930).
                        if _record_failed_dispatch(
                            message["id"],
                            topic=topic,
                            payload=payload,
                            trace_id=None if trace_id == "-" else trace_id,
                            error=handler_exc,
                        ):
                            errors_total += 1
                            continue
                        # Below the poison threshold: treat as transient and re-raise so
                        # the supervised worker restarts and retries (at-least-once).
                        raise

                ack_outbox(message["id"])
        except Exception:
            errors_total += 1
            logger.exception("worker loop failed")
            raise

        now = time.time()
        if now - last_heartbeat >= heartbeat_interval:
            write_worker_heartbeat(
                path=heartbeat_path,
                ticks_total=ticks_total,
                errors_total=errors_total,
                processed_total=processed_total,
                processed_by_event=processed_by_event,
                last_processed=last_processed,
                outbox_path=outbox_path,
                now=now,
            )
            last_heartbeat = now

        if log_heartbeat_interval is not None and now - last_log >= log_heartbeat_interval:
            logger.info(
                "worker heartbeat ticks_total=%s processed_total=%s errors_total=%s",
                ticks_total,
                processed_total,
                errors_total,
            )
            last_log = now

        if stop_after_ticks is not None and ticks_total >= stop_after_ticks:
            break

        time.sleep(interval)


class _EventDedup:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, event_id: str) -> bool:
        if not event_id:
            return False
        if event_id in self._seen:
            return True
        self._seen.add(event_id)
        if len(self._seen) > 2048:
            self._seen = set(list(self._seen)[-1024:])
        return False


_EVENT_DEDUP = _EventDedup()


if __name__ == "__main__":
    run()
