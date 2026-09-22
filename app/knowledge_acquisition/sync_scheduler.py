"""YSS-06 (#3921): per-source scheduling, lease, pause and drain for source sync.

Implements `docs/YOUTUBE_SOURCE_SYNC/SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md`.
This module is the *when*: it decides which sources are due, bounds how much
acquisition runs per tick, and keeps two runners from doing the same work. The
*what* already exists and is not reimplemented here — discovery is YSS-05's
``poll_source`` and each queue row runs through YSS-04's ``drain_one``.

Deliberately pure logic with injected collaborators (clock, registry, queue,
state store, poll/drain callables). The tick is driven by the existing watcher
registry loop rather than a new long-running process, so everything here must
be callable synchronously from that loop and must never raise into it.

Two facts shape the design:

- **The tick host is shared.** A slow acquisition cannot be allowed to stall
  vault watching, so discovery and drain both run inside a per-tick time budget
  and the drain executor is bounded by ``maxConcurrentAcquisitions``.
- **Missed time is not lost work.** Cursors and queue rows are durable, so a
  node that was off simply finds every enabled source due on its first tick and
  catches up. There is no separate reconciliation machinery, and none is needed.

Backoff state lives in this module's own state store rather than in the
registry row's ``last_error``: that field is YSS-01's contract shape, and
scheduler bookkeeping has no business widening it.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol

logger = logging.getLogger(__name__)

# --- Cadence contract --------------------------------------------------------

#: Default poll cadence per collection kind, per the task spec. A source may
#: override its own interval; an invalid override falls back to these loudly
#: rather than silently polling at an unintended rate.
DEFAULT_CADENCE_SECONDS: Mapping[str, int] = {
    "inbox_playlist": 180,
    "playlist": 3600,
    "subscriptions": 21600,
}

#: Fallback for a kind this scheduler does not know yet. Conservative on
#: purpose: an unknown source should poll rarely, not aggressively.
UNKNOWN_KIND_CADENCE_SECONDS = 21600

#: Source-level failure backoff (the queue keeps its own per-item backoff).
BACKOFF_BASE_SECONDS = 60
BACKOFF_FACTOR = 4
BACKOFF_CAP_SECONDS = 6 * 60 * 60

#: How long a tick may spend before it stops starting new work. The tick runs
#: inside the shared watcher loop, so the budget is what keeps file watching
#: responsive while an acquisition is slow.
DEFAULT_TICK_BUDGET_SECONDS = 30.0

#: Lease identity and lifetime (INV-YSS-6). The TTL outlives a normal tick by a
#: wide margin so an ordinary slow drain never looks abandoned.
LEASE_KEY = "lease:youtube_sync"
LEASE_TTL_SECONDS = 600

#: Rows stuck ``in_progress`` longer than this are reset on the first tick.
STALE_IN_PROGRESS_SECONDS = 3600

DEFAULT_MAX_CONCURRENT_ACQUISITIONS = 2

_BACKOFF_KEY_PREFIX = "backoff:"
LAST_TICK_KEY = "last_tick"


class SyncStateStore(Protocol):
    """Durable key/value state plus the single-runner lease."""

    def acquire_lease(self, *, key: str, holder: str, ttl_seconds: int, now: datetime) -> bool: ...

    def heartbeat_lease(self, *, key: str, holder: str, ttl_seconds: int, now: datetime) -> bool: ...

    def release_lease(self, *, key: str, holder: str) -> None: ...

    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True)
class TickOutcome:
    """One tick's observable result. Also the shape YSS-09 will project."""

    reason: str
    polled: tuple[str, ...] = ()
    discovered: int = 0
    enqueued: int = 0
    deduped: int = 0
    drained: int = 0
    drain_outcomes: Mapping[str, int] = field(default_factory=dict)
    skipped: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "polled": list(self.polled),
            "discovered": self.discovered,
            "enqueued": self.enqueued,
            "deduped": self.deduped,
            "drained": self.drained,
            "drain_outcomes": dict(self.drain_outcomes),
            "skipped": dict(self.skipped),
        }


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value))
    except ValueError:
        # A corrupt timestamp must not wedge the source forever: treat it as
        # never attempted so the next tick re-polls and rewrites it.
        logger.warning("unparseable last_attempt_at on a source row; treating as due")
        return None


def resolve_cadence_seconds(binding: Any) -> int:
    """The effective poll interval for one source.

    A per-source override wins when it is a usable positive integer. Anything
    else — zero, negative, a bool, a string — is a configuration error, so the
    kind default is used and the fallback is logged rather than silently
    accepted at an unintended rate.
    """
    default = DEFAULT_CADENCE_SECONDS.get(
        getattr(binding, "collection_kind", ""), UNKNOWN_KIND_CADENCE_SECONDS
    )
    override = getattr(binding, "poll_interval_seconds", None)
    if isinstance(override, bool) or not isinstance(override, int) or override <= 0:
        if override is not None:
            logger.warning(
                "invalid poll_interval_seconds on source %s; falling back to the %s default",
                getattr(binding, "binding_id", "<unknown>"),
                getattr(binding, "collection_kind", "<unknown>"),
            )
        return default
    return override


def backoff_delay_seconds(consecutive_failures: int) -> int:
    """Exponential source-level backoff with a hard cap."""
    if consecutive_failures <= 0:
        return 0
    delay = BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR ** (consecutive_failures - 1))
    return int(min(delay, BACKOFF_CAP_SECONDS))


class SyncScheduler:
    """Decides what runs this tick, and bounds how much of it runs."""

    def __init__(
        self,
        *,
        registry: Any,
        requests: Any,
        state: SyncStateStore,
        vault_context: Any,
        api_client: Any = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        poll_fn: Callable[..., Any] | None = None,
        drain_fn: Callable[..., Any] | None = None,
        holder: str = "watcher",
        max_concurrent: int = DEFAULT_MAX_CONCURRENT_ACQUISITIONS,
        tick_budget_seconds: float = DEFAULT_TICK_BUDGET_SECONDS,
        paused: Callable[[], bool] = lambda: False,
    ) -> None:
        self._registry = registry
        self._requests = requests
        self._state = state
        self._vault_context = vault_context
        self._api_client = api_client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._poll_fn = poll_fn
        self._drain_fn = drain_fn
        self._holder = holder
        self._max_concurrent = max(1, int(max_concurrent))
        self._tick_budget_seconds = float(tick_budget_seconds)
        self._paused = paused
        self._reconciled = False
        self._stopping = False

    # -- lifecycle ------------------------------------------------------------

    def request_stop(self) -> None:
        """Safe shutdown: claim no new work; let in-flight drains land durably."""
        self._stopping = True

    # -- public entrypoints ---------------------------------------------------

    def tick(self) -> TickOutcome:
        """One scheduled pass: poll what is due, then drain within budget."""
        if self._paused():
            # Deliberately before the lease: a paused runner must not churn the
            # lease, or it would keep taking it away from an unpaused one.
            return TickOutcome(reason="paused_global")
        return self._run(due_only=True, only_binding_id=None)

    def sync_now(self, binding_id: str | None = None) -> TickOutcome:
        """Operator-invoked immediate attempt, regardless of due time or backoff.

        Still lease-guarded, because "sync now" overlapping a scheduled tick is
        exactly the double-enqueue the lease exists to prevent. A failure here
        does not reset the source's backoff: an operator retry should not be a
        way to escape the cap.
        """
        if self._paused():
            return TickOutcome(reason="paused_global")
        return self._run(due_only=False, only_binding_id=binding_id)

    # -- internals ------------------------------------------------------------

    def _run(self, *, due_only: bool, only_binding_id: str | None) -> TickOutcome:
        now = _utc(self._clock())
        assert now is not None
        if not self._state.acquire_lease(
            key=LEASE_KEY, holder=self._holder, ttl_seconds=LEASE_TTL_SECONDS, now=now
        ):
            return TickOutcome(reason="lease_held")

        try:
            return self._run_locked(now=now, due_only=due_only, only_binding_id=only_binding_id)
        finally:
            self._state.release_lease(key=LEASE_KEY, holder=self._holder)

    def _run_locked(
        self, *, now: datetime, due_only: bool, only_binding_id: str | None
    ) -> TickOutcome:
        started = self._monotonic()
        skipped: dict[str, str] = {}

        if not self._reconciled:
            # First tick after start. Rows left `in_progress` by a killed
            # process would otherwise stay claimed until their own stale
            # threshold; resetting here is what makes restart converge.
            try:
                self._requests.reset_stale_in_progress(
                    older_than_seconds=STALE_IN_PROGRESS_SECONDS, now=now
                )
            except Exception:
                logger.exception("stale in-progress reset failed; continuing this tick")
            self._reconciled = True
            due_only = False  # everything enabled is due after an outage

        polled: list[str] = []
        discovered = enqueued = deduped = 0

        for binding in self._enabled_sources(only_binding_id):
            if self._stopping:
                skipped[binding.binding_id] = "stopping"
                continue
            if self._monotonic() - started >= self._tick_budget_seconds:
                skipped[binding.binding_id] = "tick_budget_exhausted"
                continue
            if due_only and not self._is_due(binding, now=now):
                skipped[binding.binding_id] = "not_due"
                continue

            result = self._poll_one(binding)
            polled.append(binding.binding_id)
            if result is None:
                continue
            discovered += int(getattr(result, "discovered", 0) or 0)
            enqueued += int(getattr(result, "enqueued", 0) or 0)
            deduped += int(getattr(result, "deduped", 0) or 0)

        drained, drain_outcomes = self._drain(started=started)

        self._state.set(
            LAST_TICK_KEY,
            {
                "at": now.isoformat(),
                "polled": len(polled),
                "discovered": discovered,
                "enqueued": enqueued,
                "deduped": deduped,
                "drained": drained,
                "outcomes": dict(drain_outcomes),
            },
        )

        return TickOutcome(
            reason="ran",
            polled=tuple(polled),
            discovered=discovered,
            enqueued=enqueued,
            deduped=deduped,
            drained=drained,
            drain_outcomes=drain_outcomes,
            skipped=skipped,
        )

    def _enabled_sources(self, only_binding_id: str | None) -> Iterable[Any]:
        rows = self._registry.list_all()
        for row in rows:
            if only_binding_id is not None and row.binding_id != only_binding_id:
                continue
            if not getattr(row, "enabled", False):
                # Per-source pause is the registry's `enabled` flag; there is no
                # second pause concept to keep in sync.
                continue
            yield row

    def _is_due(self, binding: Any, *, now: datetime) -> bool:
        last_attempt = _parse_iso(getattr(binding, "last_attempt_at", None))
        if last_attempt is None:
            return True
        interval = resolve_cadence_seconds(binding)
        failures = self._consecutive_failures(binding.binding_id)
        delay = interval + backoff_delay_seconds(failures)
        return now >= last_attempt + timedelta(seconds=delay)

    def _consecutive_failures(self, binding_id: str) -> int:
        row = self._state.get(f"{_BACKOFF_KEY_PREFIX}{binding_id}") or {}
        value = row.get("consecutive_failures")
        return value if isinstance(value, int) and value > 0 else 0

    def _record_poll_result(self, binding_id: str, *, failed: bool) -> None:
        key = f"{_BACKOFF_KEY_PREFIX}{binding_id}"
        if not failed:
            self._state.set(key, {"consecutive_failures": 0})
            return
        self._state.set(
            key, {"consecutive_failures": self._consecutive_failures(binding_id) + 1}
        )

    def _resolve_poll_fn(self) -> Callable[..., Any]:
        if self._poll_fn is not None:
            return self._poll_fn
        from app.knowledge_acquisition.playlist_discovery import poll_source

        return poll_source

    def _resolve_drain_fn(self) -> Callable[..., Any]:
        if self._drain_fn is not None:
            return self._drain_fn
        from app.knowledge_acquisition.acquisition_requests import drain_one

        return drain_one

    def _poll_one(self, binding: Any) -> Any:
        poll_fn = self._resolve_poll_fn()
        try:
            result = poll_fn(
                binding,
                api_client=self._api_client,
                requests=self._requests,
                registry=self._registry,
            )
        except Exception:
            # One unreachable source must never end the tick for the others.
            logger.exception("source poll failed for %s", binding.binding_id)
            self._record_poll_result(binding.binding_id, failed=True)
            return None
        self._record_poll_result(
            binding.binding_id, failed=bool(getattr(result, "reason_code", None))
        )
        return result

    def _drain(self, *, started: float) -> tuple[int, dict[str, int]]:
        """Run queued acquisitions, bounded by concurrency and the tick budget."""
        drain_fn = self._resolve_drain_fn()

        outcomes: dict[str, int] = {}
        drained = 0
        if self._stopping:
            return drained, outcomes

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as pool:
            pending: set[Future[Any]] = set()
            while True:
                if self._stopping:
                    break
                if self._monotonic() - started >= self._tick_budget_seconds:
                    break
                if len(pending) >= self._max_concurrent:
                    pending = self._reap(pending, outcomes, block=True)
                    drained = sum(outcomes.values())
                    continue
                claimed = self._claim_one()
                if not claimed:
                    break
                pending.add(pool.submit(self._drain_one_row, drain_fn, claimed))

            # Let whatever is already running finish: abandoning it would leave
            # rows `in_progress` with no owner until the stale reset.
            while pending:
                pending = self._reap(pending, outcomes, block=True)
            drained = sum(outcomes.values())
        return drained, outcomes

    def _claim_one(self) -> Any:
        try:
            batch = self._requests.claim_batch(1)
        except Exception:
            logger.exception("claiming an acquisition request failed")
            return None
        return batch[0] if batch else None

    def _drain_one_row(self, drain_fn: Callable[..., Any], row: Any) -> str:
        try:
            result = drain_fn(
                row,
                vault_context=self._vault_context,
                queue=self._requests,
            )
        except Exception:
            logger.exception("drain failed for request %s", getattr(row, "request_id", "?"))
            return "error"
        return str(getattr(result, "status", "unknown"))

    @staticmethod
    def _reap(
        pending: set[Future[Any]], outcomes: dict[str, int], *, block: bool
    ) -> set[Future[Any]]:
        still: set[Future[Any]] = set()
        for future in pending:
            if not block and not future.done():
                still.add(future)
                continue
            status = future.result()
            outcomes[status] = outcomes.get(status, 0) + 1
        return still


__all__ = [
    "BACKOFF_CAP_SECONDS",
    "DEFAULT_CADENCE_SECONDS",
    "DEFAULT_MAX_CONCURRENT_ACQUISITIONS",
    "LEASE_KEY",
    "LEASE_TTL_SECONDS",
    "STALE_IN_PROGRESS_SECONDS",
    "SyncScheduler",
    "SyncStateStore",
    "TickOutcome",
    "backoff_delay_seconds",
    "resolve_cadence_seconds",
]
