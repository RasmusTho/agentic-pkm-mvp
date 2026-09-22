"""YSS-06 (#3921) tests for per-source scheduling, lease, backoff and drain.

Everything is driven through the production ``SyncScheduler`` with an injected
clock and in-memory collaborators: no real egress, no database, no sleeping.
The lease uses the real ``MemorySyncStateStore``, so the exclusion assertions
exercise genuine lease semantics rather than a bespoke test double.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.knowledge_acquisition.sync_scheduler import (
    BACKOFF_CAP_SECONDS,
    DEFAULT_CADENCE_SECONDS,
    LEASE_KEY,
    LEASE_TTL_SECONDS,
    SyncScheduler,
    backoff_delay_seconds,
    default_holder,
    resolve_cadence_seconds,
)
from app.knowledge_acquisition.sync_state import MemorySyncStateStore

pytestmark = pytest.mark.not_pg

START = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class _Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@dataclass
class _Binding:
    binding_id: str
    collection_kind: str = "inbox_playlist"
    enabled: bool = True
    poll_interval_seconds: int = 180
    last_attempt_at: str | None = None


@dataclass
class _Registry:
    rows: list[_Binding] = field(default_factory=list)

    def list_all(self) -> tuple[_Binding, ...]:
        return tuple(self.rows)

    def mark_attempted(self, binding_id: str, at: datetime) -> None:
        self.rows = [
            replace(row, last_attempt_at=at.isoformat()) if row.binding_id == binding_id else row
            for row in self.rows
        ]


@dataclass
class _Row:
    request_id: str
    status: str = "in_progress"


class _Queue:
    """Stands in for AcquisitionRequests: hands out one claimed row per call."""

    def __init__(self, rows: list[_Row] | None = None) -> None:
        self.pending = list(rows or [])
        self.claims = 0
        self.stale_resets = 0
        self._lock = threading.Lock()

    def claim_batch(self, limit: int, **kwargs: Any) -> list[_Row]:
        with self._lock:
            self.claims += 1
            if not self.pending:
                return []
            return [self.pending.pop(0)]

    def reset_stale_in_progress(self, **kwargs: Any) -> int:
        self.stale_resets += 1
        return 0


@dataclass
class _PollResult:
    discovered: int = 0
    enqueued: int = 0
    deduped: int = 0
    reason_code: str | None = None


def _make(
    *,
    registry: _Registry,
    queue: _Queue | None = None,
    state: MemorySyncStateStore | None = None,
    clock: _Clock | None = None,
    poll_fn: Any = None,
    **kwargs: Any,
) -> tuple[SyncScheduler, _Clock, MemorySyncStateStore, _Queue]:
    clock = clock or _Clock()
    state = state or MemorySyncStateStore()
    queue = queue if queue is not None else _Queue()
    sched = SyncScheduler(
        registry=registry,
        requests=queue,
        state=state,
        clock=clock,
        poll_fn=poll_fn or (lambda binding, **kw: _PollResult()),
        **kwargs,
    )
    return sched, clock, state, queue


def test_inbox_poll_discovers_and_enqueues_within_interval() -> None:
    registry = _Registry([_Binding("inbox", last_attempt_at=START.isoformat())])
    polled: list[str] = []

    def poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        polled.append(binding.binding_id)
        registry.mark_attempted(binding.binding_id, clock.now)
        return _PollResult(discovered=1, enqueued=1)

    sched, clock, _state, _queue = _make(registry=registry, poll_fn=poll)

    # The first tick after start is the catch-up pass: every enabled source is
    # due regardless of cadence, because the node may have been off for days.
    catch_up = sched.tick()
    assert catch_up.reason == "ran"
    assert polled == ["inbox"]

    # From then on cadence governs: nothing is polled before the interval.
    polled.clear()
    clock.advance(DEFAULT_CADENCE_SECONDS["inbox_playlist"] - 1)
    early = sched.tick()
    assert polled == []
    assert early.skipped["inbox"] == "not_due"

    # Within one inbox interval the item is discovered and enqueued, through
    # the production tick -> poll -> enqueue path.
    clock.advance(1)
    second = sched.tick()

    assert polled == ["inbox"]
    assert second.discovered == 1
    assert second.enqueued == 1


def test_default_cadences_and_overrides() -> None:
    assert resolve_cadence_seconds(_Binding("a", collection_kind="inbox_playlist")) == 180
    assert (
        resolve_cadence_seconds(
            _Binding("b", collection_kind="playlist", poll_interval_seconds=3600)
        )
        == 3600
    )
    assert (
        resolve_cadence_seconds(
            _Binding("c", collection_kind="subscriptions", poll_interval_seconds=21600)
        )
        == 21600
    )

    # A per-source override wins when usable.
    assert (
        resolve_cadence_seconds(
            _Binding("d", collection_kind="playlist", poll_interval_seconds=900)
        )
        == 900
    )

    # Invalid overrides fall back to the kind default rather than polling at an
    # unintended rate. `True` is checked explicitly: bool is an int subclass.
    for bad in (0, -1, True, "600", None):
        binding = _Binding("e", collection_kind="playlist")
        binding.poll_interval_seconds = bad  # type: ignore[assignment]
        assert resolve_cadence_seconds(binding) == 3600

    # An unknown kind is polled conservatively, not aggressively. The override
    # is cleared so the kind default is what answers.
    unknown = _Binding("f", collection_kind="whatever")
    unknown.poll_interval_seconds = None  # type: ignore[assignment]
    assert resolve_cadence_seconds(unknown) == 21600


def test_overlapping_runs_excluded_by_lease_at_call_site() -> None:
    # Enforcement: exclusion must hold at the production call site, so both
    # schedulers are real and share one real lease store.
    registry = _Registry([_Binding("inbox")])
    state = MemorySyncStateStore()
    clock = _Clock()
    polls: list[str] = []

    def poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        polls.append(binding.binding_id)
        return _PollResult()

    # Both runners derive identity exactly as production does. An earlier
    # revision of this test hand-picked two distinct strings, which is the one
    # configuration that works: every production site passed the same constant,
    # so two runners both acquired the lease.
    first, _c, _s, _q = _make(registry=registry, state=state, clock=clock, poll_fn=poll)
    second, _c2, _s2, _q2 = _make(registry=registry, state=state, clock=clock, poll_fn=poll)

    # A third runner, also with a derived identity, holds the lease first.
    assert state.acquire_lease(
        key=LEASE_KEY,
        holder=default_holder(),
        ttl_seconds=LEASE_TTL_SECONDS,
        now=clock.now,
    )
    assert first.tick().reason == "lease_held"
    assert second.sync_now().reason == "lease_held"
    assert polls == []

    # A stale lease is taken over rather than honoured forever: the previous
    # holder may simply have been killed.
    clock.advance(LEASE_TTL_SECONDS + 1)
    assert first.tick().reason == "ran"
    assert polls == ["inbox"]

    # Two independently constructed schedulers must never both hold it, which
    # is only true when their identities actually differ.
    assert default_holder() != default_holder()
    held_by_first = state.acquire_lease(
        key=LEASE_KEY, holder=first._holder, ttl_seconds=LEASE_TTL_SECONDS, now=clock.now
    )
    also_held_by_second = state.acquire_lease(
        key=LEASE_KEY, holder=second._holder, ttl_seconds=LEASE_TTL_SECONDS, now=clock.now
    )
    assert held_by_first is True
    assert also_held_by_second is False, "a second runner must not be granted a live lease"


def test_offline_then_online_reconciles_without_duplicates() -> None:
    # Stop -> videos accumulate -> restart. The first tick after start treats
    # every enabled source as due and resets stale in-progress rows, so nothing
    # is lost and nothing is enqueued twice.
    registry = _Registry(
        [_Binding("inbox", last_attempt_at=(START - timedelta(days=3)).isoformat())]
    )
    seen: list[str] = []

    def poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        seen.append(binding.binding_id)
        registry.mark_attempted(binding.binding_id, clock.now)
        # Re-discovery of an already-known item converges as a dedup, not a
        # second request (INV-YSS-2 lives in the queue, asserted here as the
        # scheduler faithfully reporting it).
        return _PollResult(discovered=2, enqueued=1, deduped=1)

    sched, clock, _state, queue = _make(registry=registry, poll_fn=poll)

    outcome = sched.tick()

    assert queue.stale_resets == 1, "restart must reset rows stranded in_progress"
    assert seen == ["inbox"]
    assert outcome.enqueued == 1
    assert outcome.deduped == 1

    # The catch-up is once, not every tick: the second tick respects cadence.
    seen.clear()
    sched.tick()
    assert seen == []


def test_backoff_and_manual_sync_now() -> None:
    assert backoff_delay_seconds(0) == 0
    assert backoff_delay_seconds(1) == 60
    assert backoff_delay_seconds(2) == 240
    assert backoff_delay_seconds(20) == BACKOFF_CAP_SECONDS, "backoff must be capped"

    registry = _Registry([_Binding("inbox", last_attempt_at=START.isoformat())])
    attempts: list[str] = []

    def failing_poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        attempts.append("poll")
        registry.mark_attempted(binding.binding_id, clock.now)
        return _PollResult(reason_code="network_error")

    sched, clock, state, _queue = _make(registry=registry, poll_fn=failing_poll)

    clock.advance(180)
    sched.tick()
    assert len(attempts) == 1

    # One failure adds 60s on top of the 180s cadence, so the source is not due
    # again at 180s.
    clock.advance(180)
    sched.tick()
    assert len(attempts) == 1, "a failed source must back off, not retry at cadence"

    clock.advance(61)
    sched.tick()
    assert len(attempts) == 2

    # "Sync now" runs immediately regardless of backoff...
    sched.sync_now("inbox")
    assert len(attempts) == 3

    # ...but a failed manual attempt does not reset the backoff, or an operator
    # retry would become a way to escape the cap.
    backoff = state.get("backoff:inbox") or {}
    assert backoff["consecutive_failures"] >= 2


def test_pause_semantics() -> None:
    registry = _Registry([_Binding("inbox"), _Binding("paused-source", enabled=False)])
    polls: list[str] = []

    def poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        polls.append(binding.binding_id)
        return _PollResult()

    paused = {"value": True}
    state = MemorySyncStateStore()
    sched, _clock, _state, _queue = _make(
        registry=registry,
        state=state,
        poll_fn=poll,
        paused=lambda: paused["value"],
    )

    # Global pause short-circuits before the lease: a paused runner must not
    # churn the lease away from an unpaused one.
    assert sched.tick().reason == "paused_global"
    assert polls == []
    assert state.get(LEASE_KEY) is None, "paused tick must not touch the lease"

    paused["value"] = False
    outcome = sched.tick()
    # Per-source pause is the registry's `enabled` flag; the disabled source is
    # not polled and is not reported as merely 'not due'.
    assert polls == ["inbox"]
    assert "paused-source" not in outcome.skipped


def test_tick_never_performs_acquisition() -> None:
    # The watcher cycle holds a shared ingress flock while this tick runs, so a
    # multi-minute media download here stalls vault watching and blocks a
    # foreground rebind. An earlier revision drained the queue inside the tick
    # and an independent review reproduced a 3.01s tick against a 0.5s budget.
    # Discovery only: the queue must be left entirely alone.
    queue = _Queue([_Row(f"req-{index}") for index in range(5)])
    registry = _Registry([_Binding("inbox")])
    sched, _clock, _state, _q = _make(
        registry=registry,
        queue=queue,
        poll_fn=lambda binding, **kw: _PollResult(discovered=3, enqueued=3),
    )

    outcome = sched.tick()

    assert outcome.reason == "ran"
    assert outcome.enqueued == 3
    assert queue.claims == 0, "the tick must not claim acquisition work"
    assert len(queue.pending) == 5, "queued rows stay for the operator-invoked drain"
    assert not hasattr(outcome, "drained"), "a discovery-only tick reports no drain counters"

    # The scheduler must carry no drain collaborator at all, so a future edit
    # cannot quietly reintroduce acquisition into the watcher cycle.
    assert not hasattr(sched, "_drain_fn")
    assert not hasattr(sched, "_drain")


def test_raising_poll_still_backs_off() -> None:
    # `poll_source` writes `last_attempt_at` only on its non-raising paths, so a
    # source whose poll raises leaves the registry field NULL. Reading NULL as
    # unconditionally due re-polls a broken source every tick forever and never
    # lets its backoff apply -- reproduced at 6 polls over 6 minutes against a
    # 3600s cadence before this was fixed.
    registry = _Registry(
        [_Binding("playlist-1", collection_kind="playlist", poll_interval_seconds=3600)]
    )
    attempts: list[str] = []

    def raising_poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        attempts.append("poll")
        raise RuntimeError("provider unreachable")

    sched, clock, state, _queue = _make(registry=registry, poll_fn=raising_poll)

    sched.tick()  # catch-up pass; the poll raises and records its own attempt
    assert len(attempts) == 1

    for _ in range(5):
        clock.advance(60)
        sched.tick()

    assert len(attempts) == 1, f"a raising poll must back off, not retry every tick: {attempts}"
    assert (state.get("backoff:playlist-1") or {}).get("consecutive_failures") == 1


def test_benign_reason_codes_do_not_accumulate_backoff() -> None:
    # `poll_source` reports benign dispositions through the same `reason_code`
    # field as transient failures. Backing off on those would keep a source
    # un-polled for hours after the operator fixed nothing.
    registry = _Registry([_Binding("inbox", last_attempt_at=START.isoformat())])
    attempts: list[str] = []

    def benign_poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        attempts.append("poll")
        registry.mark_attempted(binding.binding_id, clock.now)
        return _PollResult(reason_code="paused_source")

    sched, clock, state, _queue = _make(registry=registry, poll_fn=benign_poll)

    sched.tick()  # catch-up pass
    clock.advance(180)
    sched.tick()

    assert len(attempts) == 2, "a benign disposition must not delay the next poll"
    assert (state.get("backoff:inbox") or {}).get("consecutive_failures") == 0


def test_reconciled_marker_survives_per_tick_construction() -> None:
    # Production rebuilds the scheduler every tick so it sees current settings.
    # The catch-up marker must therefore be carried in, or every tick re-runs
    # the catch-up pass and no per-source cadence ever applies.
    registry = _Registry([_Binding("inbox", last_attempt_at=START.isoformat())])
    state = MemorySyncStateStore()
    clock = _Clock()
    polls: list[str] = []

    def poll(binding: _Binding, **kwargs: Any) -> _PollResult:
        polls.append(binding.binding_id)
        registry.mark_attempted(binding.binding_id, clock.now)
        return _PollResult()

    reconciled = False
    for _ in range(3):
        sched = SyncScheduler(
            registry=registry,
            requests=_Queue(),
            state=state,
            clock=clock,
            poll_fn=poll,
            reconciled=reconciled,
        )
        sched.tick()
        reconciled = sched.reconciled
        clock.advance(60)

    # One catch-up poll, then cadence: 60s and 120s later the inbox is not due.
    assert polls == ["inbox"], f"cadence was defeated by per-tick construction: {polls}"
