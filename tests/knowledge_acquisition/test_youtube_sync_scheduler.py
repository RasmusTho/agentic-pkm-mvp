"""YSS-06 (#3921) tests for per-source scheduling, lease, backoff and drain.

Everything is driven through the production ``SyncScheduler`` with an injected
clock and in-memory collaborators: no real egress, no database, no sleeping.
The lease uses the real ``MemorySyncStateStore``, so the exclusion assertions
exercise genuine lease semantics rather than a bespoke test double.
"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.knowledge_acquisition.sync_scheduler import (
    BACKOFF_CAP_SECONDS,
    LEASE_KEY,
    LEASE_TTL_SECONDS,
    SyncScheduler,
    backoff_delay_seconds,
    default_holder,
    resolve_cadence_seconds,
)
from app.knowledge_acquisition.sync_state import MemorySyncStateStore
from app.knowledge_acquisition.acquisition_requests import (
    AcquisitionRequests, drain_one, reset_memory_acquisition_requests,
)
from app.knowledge_acquisition.source_registry import SourceRegistry, reset_memory_source_registry
from app.knowledge_acquisition.youtube_api_client import PlaylistItem, PlaylistItemsPage
from tests.knowledge_acquisition._acquisition_requests_contract import FakeOutboxConn


@pytest.fixture
def production_path(monkeypatch):
    from app.knowledge_acquisition import acquisition_requests, source_registry
    from app.services.outbox import write_outbox_event
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_source_registry()
    reset_memory_acquisition_requests()
    clock = _Clock()
    monkeypatch.setattr(source_registry, "_now_iso", lambda: clock.now.isoformat())
    monkeypatch.setattr(acquisition_requests, "_now", lambda now=None: now or clock.now)
    outbox = FakeOutboxConn()
    monkeypatch.setattr(acquisition_requests, "write_outbox_event",
        lambda event, conn=None, *, idempotency_key: write_outbox_event(
            event, conn=outbox, idempotency_key=idempotency_key))
    registry = SourceRegistry.for_runtime()
    account = str(uuid.uuid4())
    binding = registry.register(collection_kind="inbox_playlist", collection_ref="PL_scheduler_fixture",
        account_binding_id=account, title="Scheduler fixture")
    registry.set_inbox(account, binding.binding_id)
    queue = AcquisitionRequests.for_runtime()
    api = _InboxApi()
    yield registry, queue, api, clock, outbox, account, binding
    reset_memory_source_registry()
    reset_memory_acquisition_requests()


class _InboxApi:
    def __init__(self):
        self.videos = []
        self.calls = 0

    def list_playlist_items(self, playlist_id, **kwargs):
        self.calls += 1
        return PlaylistItemsPage(tuple(
            PlaylistItem("pli-" + video, video, i, "2026-09-22T12:00:00Z", "Fixture")
            for i, video in enumerate(self.videos)), None, f'"etag-{self.calls}"', False)

    def quota_status(self):
        return {"spent_today": self.calls, "budget": 10000, "exhausted": False}


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


def test_inbox_poll_discovers_and_enqueues_within_interval(production_path) -> None:
    registry, queue, api, clock, _outbox, _account, binding = production_path
    scheduler = SyncScheduler(registry=registry, requests=queue, state=MemorySyncStateStore(),
        api_client=api, clock=clock)
    scheduler.tick()
    api.videos.append("aaaaaaaaaaa")
    clock.advance(179)
    assert scheduler.tick().skipped[binding.binding_id] == "not_due"
    assert queue.list_all() == ()
    clock.advance(1)
    outcome = scheduler.tick()
    assert outcome.enqueued == 1
    assert [row.item_ref for row in queue.list_all()] == ["aaaaaaaaaaa"]
    assert registry.get(binding.binding_id).cursor


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

    for kind in ("owned_playlist", "public_playlist", "liked_videos"):
        assert resolve_cadence_seconds(_Binding("fallback", collection_kind=kind,
            poll_interval_seconds=0)) == 3600
    assert resolve_cadence_seconds(_Binding("feed", collection_kind="subscription_feed",
        poll_interval_seconds=0)) == 21600

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


def test_offline_then_online_reconciles_without_duplicates(production_path) -> None:
    registry, queue, api, clock, outbox, _account, _binding = production_path
    state = MemorySyncStateStore()
    api.videos.append("aaaaaaaaaaa")
    before = SyncScheduler(registry=registry, requests=queue, state=state, api_client=api, clock=clock)
    before.tick()
    claimed = queue.claim_batch(1, now=clock.now, conn=outbox)[0]
    candidates = {claimed.source_ref: "candidate-a.md"}  # crash after candidate write, before complete
    api.videos.append("bbbbbbbbbbb")  # saved while the node is stopped
    clock.advance(60)
    after = SyncScheduler(registry=registry, requests=queue, state=state, api_client=api, clock=clock)
    assert after.tick().enqueued == 1
    assert queue.get(claimed.request_id).status == "in_progress"  # too recent to reclaim
    clock.advance(3601)
    after.tick()
    assert queue.get(claimed.request_id).status == "pending"

    def pipeline(source_ref, **kwargs):
        exists = source_ref in candidates
        candidates.setdefault(source_ref, f"candidate-{len(candidates)}.md")
        return SimpleNamespace(blocked=False, dead_lettered=(), content_identity=source_ref,
            stages=[SimpleNamespace(stage="candidate", status="already_exists" if exists else "written",
                artifact_path=candidates[source_ref])])

    for row in queue.claim_batch(10, now=clock.now, conn=outbox):
        assert drain_one(row, vault_context=None, queue=queue, acquire_fn=pipeline,
            conn=outbox, now=clock.now).status == "completed"
    restarted = SyncScheduler(registry=registry, requests=queue, state=state, api_client=api, clock=clock)
    assert restarted.tick().enqueued == 0
    assert len(candidates) == len(queue.list_all()) == 2
    assert {row.status for row in queue.list_all()} == {"completed"}


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
    assert outcome.skipped["paused-source"] == "paused_source"


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


@pytest.mark.parametrize("last_attempt", [None, (START - timedelta(days=1)).isoformat()])
def test_raising_poll_still_backs_off(last_attempt) -> None:
    # `poll_source` writes `last_attempt_at` only on its non-raising paths, so a
    # source whose poll raises leaves the registry field NULL. Reading NULL as
    # unconditionally due re-polls a broken source every tick forever and never
    # lets its backoff apply -- reproduced at 6 polls over 6 minutes against a
    # 3600s cadence before this was fixed.
    registry = _Registry(
        [_Binding("playlist-1", collection_kind="playlist", poll_interval_seconds=3600, last_attempt_at=last_attempt)]
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


def test_manual_inbox_sync_shares_scheduler_lease(production_path, monkeypatch) -> None:
    from app.knowledge_acquisition.playlist_discovery import YouTubeInboxSyncV1
    registry, queue, api, clock, _outbox, account, binding = production_path
    state = MemorySyncStateStore()
    from app.knowledge_acquisition import sync_state
    monkeypatch.setattr(sync_state, "for_runtime", lambda: state)
    service = YouTubeInboxSyncV1(account_binding_id=account, registry=registry, requests=queue,
        api_client=api, oauth_status=lambda _: {"status": "connected"})
    # Use real wall-clock ownership: the existing manual entrypoint has no test-only clock.
    assert state.acquire_lease(key=LEASE_KEY, holder=default_holder(), ttl_seconds=600,
        now=datetime.now(timezone.utc))
    result = service.sync_now()
    assert result["reason_code"] == "lease_held"
    assert api.calls == 0
    assert queue.list_all() == ()
    assert registry.get(binding.binding_id).cursor == {}
    state.clear()
    api.videos.append("aaaaaaaaaaa")
    assert service.sync_now()["enqueued"] == 1
    assert state.get("backoff:" + binding.binding_id)["consecutive_failures"] == 0


def test_poll_stops_after_lease_loss_without_state_writes(production_path) -> None:
    registry, queue, api, clock, _outbox, _account, binding = production_path
    state = MemorySyncStateStore()
    original = api.list_playlist_items
    def steal(*args, **kwargs):
        clock.advance(601)
        assert state.acquire_lease(key=LEASE_KEY, holder="replacement", ttl_seconds=600, now=clock.now)
        return original(*args, **kwargs)
    api.videos.append("aaaaaaaaaaa")
    api.list_playlist_items = steal
    scheduler = SyncScheduler(registry=registry, requests=queue, state=state, api_client=api, clock=clock)
    assert scheduler.tick().reason == "lease_lost"
    assert queue.list_all() == ()
    assert registry.get(binding.binding_id).cursor == {}
    assert registry.get(binding.binding_id).last_error is None
    assert state.get("backoff:" + binding.binding_id) is None
    assert state.get("last_tick") is None
    assert state.get(LEASE_KEY)["holder"] == "replacement"


@pytest.mark.parametrize("streaming", [False, True])
def test_poll_deadline_stops_pagination_and_stream_without_cursor(production_path, streaming) -> None:
    import httpx
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiClient, YouTubeQuotaStore
    registry, queue, _api, clock, _outbox, _account, binding = production_path
    elapsed = [0.0]
    calls = []
    class Tokens:
        def get_access_token(self, **kwargs):
            return "fixture-token"
    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b'{"items":', b'[],"nextPageToken":"next"}'):
                elapsed[0] += 25
                clock.advance(25)
                yield chunk
    def transport(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] <= 30 - elapsed[0]
        if streaming:
            return httpx.Response(200, stream=SlowBody())
        elapsed[0] += 10
        clock.advance(10)
        return httpx.Response(200, json={"items": [], "nextPageToken": f"page{len(calls)}"})
    client = YouTubeApiClient(token_provider=Tokens(), quota=YouTubeQuotaStore.for_runtime(),
        http=httpx.Client(transport=httpx.MockTransport(transport)))
    state = MemorySyncStateStore()
    scheduler = SyncScheduler(registry=registry, requests=queue, state=state, api_client=client,
        clock=clock, monotonic=lambda: elapsed[0])
    assert scheduler.tick().reason == "ran"
    assert len(calls) == (1 if streaming else 3)
    assert elapsed[0] == (50 if streaming else 30)
    assert registry.get(binding.binding_id).cursor == {}
    assert registry.get(binding.binding_id).last_error["reason_code"] == "api_unavailable"
    assert queue.list_all() == ()
    assert state.get("backoff:" + binding.binding_id)["consecutive_failures"] == 1


def test_priority_sources_receive_the_tick_budget_first() -> None:
    rows = [_Binding("normal"), _Binding("inbox")]
    rows[0].priority = "normal"
    rows[1].priority = "high"
    elapsed = [0.0]
    polled = []
    def poll(binding, **kwargs):
        polled.append(binding.binding_id)
        elapsed[0] = 31
        return _PollResult()
    scheduler, *_ = _make(registry=_Registry(rows), poll_fn=poll, monotonic=lambda: elapsed[0])
    outcome = scheduler.tick()
    assert polled == ["inbox"]
    assert outcome.skipped["normal"] == "tick_budget_exhausted"
