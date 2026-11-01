"""MVR-05D production outbox producer registry and binding/context envelope.

Every production DB-outbox call site (``write_outbox_event`` /
``insert_object_and_outbox`` under ``app/``) names exactly one registered
producer here through the ``producer=`` keyword. The registry is the closed
inventory the architecture guard
``tests/architecture/test_multi_vault_context_boundaries.py::test_vault_bound_outbox_producers_cannot_emit_legacy_envelopes``
compares against the AST-discovered call sites: an unregistered call site, a
call site naming another location's producer, or a stale registry entry fails
that gate.

The registry also declares each producer's routing class:

- ``vault_bound``: the emission belongs to exactly one stable vault binding.
  It is stamped by the outbox choke point with the binding, its GOV/revision/
  root facts, the captured producer context, and both idempotency keys.
- ``global``: definitionally vault-independent work. It resolves to the
  explicit ``explicitly-global`` binding and never borrows a vault binding.
- ``inherited``: worker re-emissions (retry, dead-letter, consumer signal)
  that inherit the stored binding of their source row, so their routing class
  is the source row's.

The envelope written at the choke point is :data:`OUTBOX_ENVELOPE_VERSION`.
A row carrying it is the only vault-bound shape the worker may dispatch.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

OUTBOX_ENVELOPE_VERSION = "mvr05.outbox-envelope.v1"

RoutingClass = Literal["vault_bound", "global"]
DeclaredRouting = Literal["vault_bound", "global", "inherited"]
ProducerFamily = Literal["watcher", "api", "ingest", "capture", "heimdal", "shared", "worker"]

ROUTING_VAULT_BOUND: RoutingClass = "vault_bound"
ROUTING_GLOBAL: RoutingClass = "global"

# Producer-context kinds stamped into ``meta.producer_context.kind``.
CONTEXT_ACTIVE = "active_context"
CONTEXT_BINDING_RUNTIME = "binding_runtime"
CONTEXT_NO_BINDING_RUNTIME = "no_binding_runtime"
CONTEXT_GLOBAL = "global"

#: Context kinds the worker accepts for a dispatchable vault-bound row. A
#: ``no_binding_runtime`` row was emitted by a process without instance
#: binding authority, so a binding-gated worker can never validate it.
DISPATCHABLE_VAULT_BOUND_CONTEXT_KINDS = (CONTEXT_ACTIVE, CONTEXT_BINDING_RUNTIME)


class UnregisteredOutboxProducerError(ValueError):
    """A DB-outbox emission named a producer absent from the closed registry."""


class OutboxProducerRoutingError(ValueError):
    """An emission resolved to a binding its registered routing class forbids."""


@dataclass(frozen=True)
class OutboxProducer:
    producer_id: str
    module: str
    function: str
    family: ProducerFamily
    routing: DeclaredRouting


def _p(
    producer_id: str,
    module: str,
    function: str,
    family: ProducerFamily,
    routing: DeclaredRouting = "vault_bound",
) -> OutboxProducer:
    return OutboxProducer(producer_id, module, function, family, routing)


#: The closed production inventory. Keyed by producer id; ``module`` and
#: ``function`` name the enclosing (qualified) function of the call site.
PRODUCERS: tuple[OutboxProducer, ...] = (
    # Watcher lifecycles.
    _p("watcher.registry.panel_note_events", "app/watcher/registry.py", "_process_panel_note", "watcher"),
    _p("watcher.registry.panel_scan_requested", "app/watcher/registry.py", "_emit_watch_event", "watcher"),
    _p("watcher.registry.watch_event", "app/watcher/registry.py", "_emit_watch_event", "watcher"),
    _p("watcher.vault.delete_tombstone", "app/watcher/vault_watcher.py", "_emit_watcher_delete_event", "watcher"),
    # API routes.
    _p("api.ingest.object_created", "app/api/routes/ingest.py", "ingest", "api"),
    # Ingest pipelines.
    _p("ingest.cli.pipe", "app/cli/__init__.py", "pipe", "ingest"),
    _p("ingest.object_store.save", "app/objects/__init__.py", "ObjectStore.save_object", "ingest"),
    _p("ingest.vault_sync", "app/services/vault_sync.py", "_enqueue", "ingest"),
    _p(
        "ingest.knowledge_acquisition.request",
        "app/knowledge_acquisition/acquisition_requests.py",
        "AcquisitionRequests._emit",
        "ingest",
    ),
    _p(
        "ingest.knowledge_acquisition.rss_sync",
        "app/knowledge_acquisition/channel_rss_discovery.py",
        "_write_sync_event",
        "ingest",
    ),
    _p(
        "ingest.knowledge_acquisition.stage_completed",
        "app/knowledge_acquisition/stage_events.py",
        "emit_stage_completed",
        "ingest",
    ),
    _p(
        "ingest.knowledge_acquisition.stage_dead_letter",
        "app/knowledge_acquisition/stage_events.py",
        "emit_stage_dead_letter",
        "ingest",
    ),
    # Governed capture.
    _p("capture.appended", "app/api/routes/capture.py", "_emit_capture_event", "capture"),
    # Heimdal.
    _p("heimdal.meeting.user_note", "app/api/routes/heimdal_meeting.py", "_emit_user_note_event", "heimdal"),
    _p("heimdal.entity_register", "app/heimdal/entity_register.py", "EntityRegister._emit", "heimdal"),
    _p(
        "heimdal.entity_review.merge",
        "app/heimdal/entity_review_operation_journal.py",
        "EntityReviewOperationJournal.commit_merge_event",
        "heimdal",
    ),
    _p(
        "heimdal.entity_review.split",
        "app/heimdal/entity_review_operation_journal.py",
        "EntityRegisterSplitJournal.finish_split",
        "heimdal",
    ),
    _p(
        "heimdal.media.admitted",
        "app/heimdal/media_ingress.py",
        "_emit_admission_event",
        "heimdal",
        "global",
    ),
    _p("heimdal.meeting.finalized", "app/heimdal/meeting_finalization.py", "_emit_finalized_event", "heimdal"),
    _p("heimdal.meeting.late_admitted", "app/heimdal/meeting_ledger.py", "_emit_late_admitted_event", "heimdal"),
    # Shared services.
    _p("shared.panel_agent.execution", "app/agents/panel_agent/execution.py", "run_panel_note_execution", "shared"),
    _p("shared.panel_agent.runtime", "app/agents/panel_agent/runtime.py", "_write_db_outbox_events", "shared"),
    _p("shared.panel.confirmation", "app/panel/confirmation.py", "_emit_projection_event", "shared"),
    _p("shared.promotion.consumer", "app/promotion/consumer.py", "_emit_db_event", "shared"),
    _p("shared.settings.write_receipt", "app/receipts/settings_write.py", "emit_settings_write_receipt", "shared"),
    _p("shared.index.embedding_requested", "app/outbox/events.py", "emit_index_embedding_requested", "shared"),
    _p("shared.episodes.closed", "app/episodes/closure.py", "close_episode", "shared"),
    _p("shared.episode_debrief.trigger", "app/episode_debrief/trigger.py", "_reconcile", "shared"),
    _p(
        "shared.eval.disposition_receipt",
        "app/eval/failure_capture.py",
        "_persist_disposition_authority_receipt",
        "shared",
    ),
    _p(
        "shared.instance.default_vault",
        "app/instance/default_vault.py",
        "_emit_default_mutation_event",
        "shared",
        "global",
    ),
    _p(
        "shared.instance.vault_dimensions",
        "app/instance/vault_dimensions.py",
        "emit_dimension_mutation_event",
        "shared",
        "global",
    ),
    # Worker re-emissions inherit their source row's stored binding.
    _p("worker.ka_consumer_signal", "app/workers/outbox_worker.py", "_emit_ka_consumer_signal", "worker", "inherited"),
    _p("worker.retry_dead_letter", "app/workers/outbox_worker.py", "_emit_retry_dead_letter", "worker", "inherited"),
    _p(
        "worker.dead_letter",
        "app/workers/outbox_worker.py",
        "_dead_letter_outbox_message",
        "worker",
        "inherited",
    ),
    _p("worker.transient_retry", "app/workers/outbox_worker.py", "_queue_transient_retry", "worker", "inherited"),
)

PRODUCER_REGISTRY: Mapping[str, OutboxProducer] = MappingProxyType(
    {producer.producer_id: producer for producer in PRODUCERS}
)

if len(PRODUCER_REGISTRY) != len(PRODUCERS):  # pragma: no cover - import-time invariant
    raise RuntimeError("outbox producer ids must be unique")


def require_registered_producer(producer_id: str) -> OutboxProducer:
    """Return the registered producer or fail loud; there is no default producer."""

    if not isinstance(producer_id, str) or not producer_id.strip():
        raise UnregisteredOutboxProducerError(
            f"outbox producer id must be a non-empty string, got {producer_id!r}"
        )
    producer = PRODUCER_REGISTRY.get(producer_id)
    if producer is None:
        raise UnregisteredOutboxProducerError(
            f"outbox producer {producer_id!r} is not in the MVR-05D production registry"
        )
    return producer


def vault_bound_producers() -> tuple[OutboxProducer, ...]:
    return tuple(producer for producer in PRODUCERS if producer.routing == "vault_bound")


@dataclass(frozen=True)
class EmissionContext:
    """Immutable request context captured for emissions inside a governed write."""

    context_id: str
    context_generation: int
    target_binding_id: str


_EMISSION_CONTEXT: ContextVar[EmissionContext | None] = ContextVar(
    "mvr05d_outbox_emission_context", default=None
)


@contextmanager
def active_context_emission(
    *, context_id: str, context_generation: int, target_binding_id: str
) -> Iterator[EmissionContext]:
    """Capture the request ActiveContextSet identity for nested outbox emissions."""

    captured = EmissionContext(
        context_id=context_id,
        context_generation=int(context_generation),
        target_binding_id=target_binding_id,
    )
    token = _EMISSION_CONTEXT.set(captured)
    try:
        yield captured
    finally:
        _EMISSION_CONTEXT.reset(token)


def current_emission_context() -> EmissionContext | None:
    return _EMISSION_CONTEXT.get()


__all__ = [
    "CONTEXT_ACTIVE",
    "CONTEXT_BINDING_RUNTIME",
    "CONTEXT_GLOBAL",
    "CONTEXT_NO_BINDING_RUNTIME",
    "DISPATCHABLE_VAULT_BOUND_CONTEXT_KINDS",
    "EmissionContext",
    "OUTBOX_ENVELOPE_VERSION",
    "OutboxProducer",
    "OutboxProducerRoutingError",
    "PRODUCERS",
    "PRODUCER_REGISTRY",
    "ROUTING_GLOBAL",
    "ROUTING_VAULT_BOUND",
    "UnregisteredOutboxProducerError",
    "active_context_emission",
    "current_emission_context",
    "require_registered_producer",
    "vault_bound_producers",
]
