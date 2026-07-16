---
name: Schedule and Operate Continuous Sync
description: Per-source due-time scheduling inside the existing watcher registry loop (sparse-cadence sub-tick), DB lease with TTL+heartbeat, bounded drain, pause/resume, backoff, offline/restart reconciliation, safe shutdown.
task_id: YSS-06
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Retry and backoff"
parent_capability: YouTube Source Sync
prerequisites: [YSS-04, YSS-05]
depends_on: [ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md, DISCOVER_PLAYLIST_ITEMS_CONTINUOUSLY.md]
can_parallelize_with: []
---

# Schedule and Operate Continuous Sync

## Purpose

Turn one-shot discovery and drain into unattended continuous sync — inbox every 180 s — without
building a new scheduler or a new long-running process. The existing watcher registry loop is the
tick host; this task adds a sparse-cadence sub-tick beside the Daily Briefing precedent.

## What This Task Does

1. **Tick host (reuse, not new):** clone the `BriefingTickCadence` / `_run_briefing_tick` pattern
   in `app/watcher/registry.py` (`run_registry_forever`) into a `SyncTickCadence` +
   `_run_youtube_sync_tick()` invoked once per registry cycle, firing at most every
   `SYNC_TICK_INTERVAL_SECONDS` (60 s tick; per-source due-times decide actual polls). The
   sub-tick is exception-isolated like the relevance tick — a sync failure can never break vault
   watching. Gated by `youtubeSync.enabled` (vault-shared) AND `youtubeSync.runnerEnabled`
   (vault-local, machine binding): both false ⇒ zero work, zero egress.
2. **Scheduler core** `app/knowledge_acquisition/sync_scheduler.py` (pure logic, injectable clock):
   - computes per-source `next_due` from `last_attempt_at` + effective interval (priority sources
     first), honoring per-source backoff state after failures (contract §Retry and backoff);
   - runs due discovery polls (YSS-05 `poll_source`) within a per-tick time budget;
   - drains the request queue through a bounded in-process executor
     (`youtubeSync.maxConcurrentAcquisitions`, default 2) so slow egress (ASR fallback) never
     blocks the tick; the executor is fed/reaped per tick, never unbounded;
   - global pause and per-source pause (registry `enabled=false`) short-circuit with
     `paused_global`/`paused_source` reasons;
   - **safe shutdown:** in-flight drains finish or are abandoned to durable retryable state; no
     new work is claimed after stop is requested.
3. **Single-run lease (INV-YSS-6):** a durable lease row (key `lease:youtube_sync`, TTL 10 min,
   heartbeat each tick) in a generic sync-state table (the `episode_engine_state` key/value
   pattern; forward-only migration). The watcher sub-tick and any CLI-invoked run claim the same
   lease; a live lease blocks overlap, a stale lease is taken over after expiry. "Sync now"
   (CLI/UI) performs one lease-guarded immediate attempt regardless of backoff.
4. **Offline/restart reconciliation:** on first tick after start, reset stale `in_progress`
   requests, then treat every enabled source as due (cursor + queue are durable; missed time is
   simply caught up). Saved videos accumulated while the node was off are discovered on the first
   poll — no separate reconciliation machinery.
5. **Heartbeat/observability seam:** writes `last_tick_at` + per-tick counters
   (discovered/enqueued/acquired/deduped/retried/dead_lettered/quota) into the sync-state table
   for YSS-09 to surface; `runner_offline` is *derived* from `last_tick_at` staleness by
   consumers, never self-reported.

## Concretely

```python
sched = SyncScheduler(registry=reg, requests=q, clock=fake_clock, lease=lease_store)
sched.tick()                       # inbox due -> poll + enqueue; drains ≤2 acquisitions
fake_clock.advance(120); sched.tick()   # inbox not due (180s) -> no poll
fake_clock.advance(60);  sched.tick()   # due again
```

In runtime the same `tick()` is called by the watcher sub-tick; tests never need the loop.

## Why This Matters

Overlapping polls double-enqueue and double-spend quota; an unbounded drain inside the watcher
starves file-watching; a scheduler that self-reports "up to date" while offline lies to the user.
The lease, the budgeted tick, and derived staleness kill those classes.

## Acceptance Criteria

- [ ] A video appearing in the inbox fixture is discovered and enqueued within one 180 s inbox
      interval of scheduler time (injectable clock), driven through the production
      tick → poll_source → enqueue path.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_inbox_poll_discovers_and_enqueues_within_interval`
- [ ] Default cadences: inbox 180 s, other playlists 3600 s, subscription feeds 21600 s — all
      overridable per source; invalid overrides fall back loudly.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_default_cadences_and_overrides`
- [ ] Two concurrent tick attempts (simulated second runner / CLI overlap) are excluded by the
      lease; a stale lease is taken over after TTL expiry — asserted at the production lease
      call site.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_overlapping_runs_excluded_by_lease_at_call_site`
- [ ] Stop → add videos → restart converges: no lost items, no duplicate candidates, stale
      `in_progress` reset (INV-YSS-3 end-to-end with stubbed pipeline).
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_offline_then_online_reconciles_without_duplicates`
- [ ] Failure backoff is exponential with cap and reason-coded; manual "Sync now" performs one
      immediate lease-guarded attempt without resetting backoff on failure.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_backoff_and_manual_sync_now`
- [ ] Global pause and per-source pause stop polling with the correct reason codes and stop
      claiming new drains; in-flight work lands durably (safe shutdown).
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_pause_and_safe_shutdown_semantics`
- [ ] Drain concurrency never exceeds `maxConcurrentAcquisitions`, and a slow drain does not
      delay the next discovery tick beyond its budget.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_bounded_concurrency_and_tick_budget`
- [ ] The watcher sub-tick wiring is exception-isolated and both-flags-gated (no egress, no lease
      churn when disabled) — asserted at the registry-loop production call site.
      Verify: `tests/watcher/test_registry_youtube_sync_tick.py::test_sub_tick_gated_and_exception_isolated`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_youtube_sync_scheduler.py tests/watcher/test_registry_youtube_sync_tick.py`
- `pytest -q -m "not pg"` (watcher loop is hot-path; full default suite mandatory)
- `ruff check app tests && mypy app`

## Out of Scope

New compose services or daemons (explicitly none — the watcher hosts the tick; if the tick host
ever proves too tight, a dedicated service reusing the worker-loop pattern is the documented
fallback, decided then, not now), UI/CLI surfaces (YSS-10/11), backfill cadence (YSS-08 plugs its
weekly reconcile into this scheduler's due-time model).

## Restart / Durability Posture

Everything the scheduler needs to resume — cursors, queue, backoff, lease, `last_tick_at` — is
durable in the channel DB. The in-process executor's in-flight work is the only volatile state;
its loss on crash re-runs items idempotently. The user experience after downtime is "it catches
up on the next tick", never "it lost my saves" and never "it claims up-to-date while stale".

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Retry and backoff / Reason codes / Settings model`
- `docs/KARAKEEP_MIMER_ACQUISITION/SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION.md` (sibling scheduling precedent — leases/cursors/receipts shape)
- `docs/ENVIRONMENTS.md :: Allowed Variation by Environment`

## Related GitHub Issues

One issue. TCD hint: Opus / high — concurrency, lease semantics, restart convergence, and
watcher-loop integration; highest defect blast radius in the set after YSS-02.
