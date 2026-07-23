"""Coordinated Karakeep producer/consumer scheduling (KMA-05, #3377).

Turns the two proven one-shot halves -- the Heimdal producer
(``app.heimdal.karakeep_ingest.KarakeepAdapter`` gated by
``app.heimdal.karakeep_service.assert_fetch_ready``) and the Mimer consumer
(``app.heimdal.candidate_projection.project_pending_candidates``) -- into
bounded, unattended acquisition WITHOUT merging their ownership.

Coordination happens only through the durable published-evidence handoff
(KMA-INV-4): this module never makes an in-process cross-constituent call or a
shared transaction, and it holds no shared execution lock. Each constituent has:

- its own bounded run entrypoint (:func:`run_producer` / :func:`run_consumer`);
- its own independent lease (:data:`PRODUCER_LEASE` / :data:`CONSUMER_LEASE`),
  so a run only excludes another run of the *same* side, never the other side;
- its own durable cursor (Heimdal's producer cursor; Mimer's consumer cursor),
  which schedule state can never substitute for;
- a truthful, secret-safe receipt.

Karakeep health gates ONLY the Heimdal fetch; the Mimer consumer may drain the
durable handoff while Karakeep is down (KMA-INV-5). Either half may fail, lag, or
overlap without falsifying the other half's durable success -- the combined
:class:`BoundaryReceipt` reports each side independently.

Secret containment (KMA-INV-6): receipts carry counts, a status class, and a
secret-free gate reason code only -- never an endpoint, token, or raw provider
output.

Bounding (timeout/backoff): each run is a single bounded pass -- the producer's
page budget and the consumer's read batch bound the work per run, and the lease
TTL bounds how long a crashed holder can hold its side before the lease expires
and the next run may proceed. Inter-run backoff and the poll interval belong to
the driving loop (shaped like ``app.heimdal.capture_runtime.run_forever``), not
to these bounded one-shot entrypoints; wiring a live driver is deferred to the
acceptance slice (KMA-06).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from app.heimdal.karakeep_service import (
    KarakeepServiceConfigError,
    KarakeepServiceUnhealthyError,
    assert_fetch_ready,
)

logger = logging.getLogger(__name__)

PRODUCER_LEASE = "karakeep.producer"
CONSUMER_LEASE = "karakeep.consumer"

DEFAULT_LEASE_TTL_SECONDS = 900.0

# A monotonic clock is the default; tests inject a deterministic one.
_MONOTONIC = time.monotonic


# ---------------------------------------------------------------------------
# Independent per-constituent leases (no shared execution lock)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lease:
    key: str
    holder: str
    expires_at: float


class LeaseStore:
    """In-process leases keyed per constituent. Acquiring one key never blocks a
    different key, so the producer and consumer sides are independent; a second
    acquire of the *same* live key by a different holder is refused, preventing
    same-side overlap without a cross-side lock. Process-durable and injectable;
    a real deployment wires a cross-process backing through the same surface."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, Lease] = {}

    def acquire(self, key: str, holder: str, *, ttl_seconds: float, now: float) -> Optional[Lease]:
        with self._lock:
            existing = self._leases.get(key)
            if existing is not None and existing.expires_at > now and existing.holder != holder:
                return None
            lease = Lease(key=key, holder=holder, expires_at=now + ttl_seconds)
            self._leases[key] = lease
            return lease

    def release(self, key: str, holder: str) -> None:
        with self._lock:
            existing = self._leases.get(key)
            if existing is not None and existing.holder == holder:
                del self._leases[key]

    def clear(self) -> None:
        with self._lock:
            self._leases.clear()


_DEFAULT_LEASE_STORE = LeaseStore()


def default_lease_store() -> LeaseStore:
    return _DEFAULT_LEASE_STORE


def reset_lease_store() -> None:
    """Test-only reset hook, mirroring the other Heimdal memory-store resets."""
    _DEFAULT_LEASE_STORE.clear()


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProducerReceipt:
    """Heimdal producer outcome. Secret-free (counts + status class + reason code)."""

    ran: bool
    lease_conflict: bool
    gated: bool
    gate_reason: Optional[str]
    fetched: int
    published: int
    noops: int
    item_errors: int
    stopped_early: bool
    failed: bool
    producer_cursor: Optional[str]
    constituent: str = "heimdal"


@dataclass(frozen=True)
class ConsumerReceipt:
    """Mimer consumer outcome. Independent of the producer's success."""

    ran: bool
    lease_conflict: bool
    consumed: int
    written: int
    already_exists: int
    blocked: int
    failed: bool
    consumer_cursor: Optional[int]
    constituent: str = "mimer"


@dataclass(frozen=True)
class BoundaryReceipt:
    """The combined operator receipt: each constituent reported truthfully and
    independently. A failed/gated producer never falsifies the consumer half."""

    producer: ProducerReceipt
    consumer: ConsumerReceipt


# ---------------------------------------------------------------------------
# Health gate (wraps the KMA-02 fetch-readiness gate into the scheduler contract)
# ---------------------------------------------------------------------------


def source_health_gate(
    env: Optional[Any] = None, *, http: Optional[Any] = None
) -> Optional[str]:
    """The real Heimdal-fetch health gate: ``None`` when fetch-ready, else a
    secret-safe reason code. Delegates to
    ``app.heimdal.karakeep_service.assert_fetch_ready`` -- config absence and red
    health both refuse the fetch, and neither the endpoint nor the token appears
    in the returned code (KMA-INV-6)."""
    try:
        assert_fetch_ready(env=env, http=http)
        return None
    except KarakeepServiceConfigError:
        return "config_absent"
    except KarakeepServiceUnhealthyError:
        return "source_unhealthy"


# ---------------------------------------------------------------------------
# Bounded runs
# ---------------------------------------------------------------------------


def run_producer(
    *,
    holder: str,
    health_gate: Callable[[], Optional[str]],
    acquire: Callable[[], Any],
    read_producer_cursor: Callable[[], Optional[str]],
    lease_store: Optional[LeaseStore] = None,
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    clock: Callable[[], float] = _MONOTONIC,
) -> ProducerReceipt:
    """One bounded Heimdal producer run under the producer lease.

    ``health_gate`` returns ``None`` when the source is fetch-ready, else a
    secret-safe reason code (e.g. ``"config_absent"`` / ``"source_unhealthy"``);
    when gated, no fetch runs and the producer cursor is untouched. ``acquire``
    is a bounded fetch/publish pass returning an
    ``app.heimdal.karakeep_ingest.AcquisitionResult``; its failure is isolated so
    the schedule survives, and because Heimdal's cursor only advances on durable
    publication (KMA-INV-3), a failed or gated run cannot regress it.
    """
    store = lease_store or default_lease_store()
    now = clock()
    lease = store.acquire(PRODUCER_LEASE, holder, ttl_seconds=ttl_seconds, now=now)
    if lease is None:
        logger.info("Karakeep producer run skipped: producer lease held by another runner")
        return _producer_conflict(read_producer_cursor)

    try:
        reason = health_gate()
        if reason is not None:
            logger.info("Karakeep producer fetch gated (reason=%s); Mimer replay is unaffected", reason)
            return ProducerReceipt(
                ran=True,
                lease_conflict=False,
                gated=True,
                gate_reason=reason,
                fetched=0,
                published=0,
                noops=0,
                item_errors=0,
                stopped_early=False,
                failed=False,
                producer_cursor=_safe_cursor(read_producer_cursor),
            )
        try:
            result = acquire()
        except Exception as exc:  # noqa: BLE001 -- one bad run must not kill the schedule
            logger.error("Karakeep producer run failed: %s", type(exc).__name__)
            return ProducerReceipt(
                ran=True,
                lease_conflict=False,
                gated=False,
                gate_reason=None,
                fetched=0,
                published=0,
                noops=0,
                item_errors=0,
                stopped_early=True,
                failed=True,
                producer_cursor=_safe_cursor(read_producer_cursor),
            )
        return ProducerReceipt(
            ran=True,
            lease_conflict=False,
            gated=False,
            gate_reason=None,
            fetched=int(getattr(result, "fetched", 0)),
            published=len(getattr(result, "published", ()) or ()),
            noops=int(getattr(result, "noops", 0)),
            item_errors=len(getattr(result, "item_errors", ()) or ()),
            stopped_early=bool(getattr(result, "stopped_early", False)),
            failed=False,
            producer_cursor=_safe_cursor(read_producer_cursor),
        )
    finally:
        store.release(PRODUCER_LEASE, holder)


def run_consumer(
    *,
    holder: str,
    project: Callable[[], list[Any]],
    read_consumer_cursor: Callable[[], int],
    lease_store: Optional[LeaseStore] = None,
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    clock: Callable[[], float] = _MONOTONIC,
) -> ConsumerReceipt:
    """One bounded Mimer consumer run under the consumer lease.

    No health gate: the consumer drains the durable handoff regardless of
    Karakeep availability (KMA-INV-4). ``project`` is a bounded materialization
    pass returning ``app.heimdal.candidate_projection.CandidateWriteResult``
    rows; its failure is isolated and Mimer's consumer cursor only advances
    across a contiguous durable prefix, so a failure preserves it (KMA-INV-3).
    """
    store = lease_store or default_lease_store()
    now = clock()
    lease = store.acquire(CONSUMER_LEASE, holder, ttl_seconds=ttl_seconds, now=now)
    if lease is None:
        logger.info("Karakeep consumer run skipped: consumer lease held by another runner")
        return _consumer_conflict(read_consumer_cursor)

    try:
        try:
            results = project()
        except Exception as exc:  # noqa: BLE001 -- one bad run must not kill the schedule
            logger.error("Karakeep consumer run failed: %s", type(exc).__name__)
            return ConsumerReceipt(
                ran=True,
                lease_conflict=False,
                consumed=0,
                written=0,
                already_exists=0,
                blocked=0,
                failed=True,
                consumer_cursor=_safe_int_cursor(read_consumer_cursor),
            )
        statuses = [getattr(r, "status", "") for r in results]
        return ConsumerReceipt(
            ran=True,
            lease_conflict=False,
            consumed=len(results),
            written=statuses.count("written"),
            already_exists=statuses.count("already_exists"),
            blocked=statuses.count("blocked"),
            failed=False,
            consumer_cursor=_safe_int_cursor(read_consumer_cursor),
        )
    finally:
        store.release(CONSUMER_LEASE, holder)


def run_boundary_cycle(
    *,
    holder: str,
    health_gate: Callable[[], Optional[str]],
    acquire: Callable[[], Any],
    read_producer_cursor: Callable[[], Optional[str]],
    project: Callable[[], list[Any]],
    read_consumer_cursor: Callable[[], int],
    lease_store: Optional[LeaseStore] = None,
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    clock: Callable[[], float] = _MONOTONIC,
) -> BoundaryReceipt:
    """Run one bounded producer pass and one bounded consumer pass.

    The consumer runs regardless of the producer's outcome (gated, failed, or
    overlapping), because it consumes only the already-durable handoff. The two
    sides never share a lock and never call each other in process.
    """
    store = lease_store or default_lease_store()
    producer = run_producer(
        holder=holder,
        health_gate=health_gate,
        acquire=acquire,
        read_producer_cursor=read_producer_cursor,
        lease_store=store,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )
    consumer = run_consumer(
        holder=holder,
        project=project,
        read_consumer_cursor=read_consumer_cursor,
        lease_store=store,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )
    return BoundaryReceipt(producer=producer, consumer=consumer)


def _producer_conflict(read_producer_cursor: Callable[[], Optional[str]]) -> ProducerReceipt:
    return ProducerReceipt(
        ran=False,
        lease_conflict=True,
        gated=False,
        gate_reason=None,
        fetched=0,
        published=0,
        noops=0,
        item_errors=0,
        stopped_early=False,
        failed=False,
        producer_cursor=_safe_cursor(read_producer_cursor),
    )


def _consumer_conflict(read_consumer_cursor: Callable[[], int]) -> ConsumerReceipt:
    return ConsumerReceipt(
        ran=False,
        lease_conflict=True,
        consumed=0,
        written=0,
        already_exists=0,
        blocked=0,
        failed=False,
        consumer_cursor=_safe_int_cursor(read_consumer_cursor),
    )


def _safe_cursor(read: Callable[[], Optional[str]]) -> Optional[str]:
    try:
        return read()
    except Exception:  # noqa: BLE001 -- a cursor read failure must not break the receipt
        return None


def _safe_int_cursor(read: Callable[[], int]) -> Optional[int]:
    try:
        return read()
    except Exception:  # noqa: BLE001 -- a cursor read failure must not break the receipt
        return None


__all__ = [
    "CONSUMER_LEASE",
    "DEFAULT_LEASE_TTL_SECONDS",
    "PRODUCER_LEASE",
    "BoundaryReceipt",
    "ConsumerReceipt",
    "Lease",
    "LeaseStore",
    "ProducerReceipt",
    "default_lease_store",
    "reset_lease_store",
    "run_boundary_cycle",
    "run_consumer",
    "run_producer",
    "source_health_gate",
]
