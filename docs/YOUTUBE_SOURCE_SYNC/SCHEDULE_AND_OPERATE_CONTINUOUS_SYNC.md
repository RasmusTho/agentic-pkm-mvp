---
name: Schedule and Operate Continuous Sync
description: Discovery scheduling inside the existing watcher registry loop, durable lease, pause, backoff, restart reconciliation, and tick observations. Acquisition draining remains operator-invoked.
task_id: YSS-06
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Retry and backoff"
parent_capability: YouTube Source Sync
prerequisites: [YSS-04, YSS-05]
depends_on: [ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md, DISCOVER_PLAYLIST_ITEMS_CONTINUOUSLY.md]
can_parallelize_with: []
---

# Schedule and Operate Continuous Sync

State: Repository implementation for #3921 / PR #5616, narrowed by the owner continuation on
2026-09-22 to discovery scheduling for the supported one-account Inbox. Background acquisition
and siblings #3922-#3926 remain deferred; live capability acceptance is separate.

## Purpose

Turn one-shot Inbox discovery into scheduled discovery — default inbox cadence 180 s — without
building a new scheduler or a new long-running process. The existing watcher registry loop is the
tick host; this task adds a sparse-cadence sub-tick beside the Daily Briefing precedent.

## What This Task Does

1. **Tick host (reuse, not new):** clone the `BriefingTickCadence` / `_run_briefing_tick` pattern
   in `app/watcher/registry.py` (`run_registry_forever`) into a `SyncTickCadence` +
   `_run_youtube_sync_tick()` invoked once per registry cycle, firing at most every
   `SYNC_TICK_INTERVAL_SECONDS` (60 s tick; per-source due-times decide actual polls). The
   sub-tick is exception-isolated like the relevance tick — a sync failure can never break vault
   watching. Gated by `youtubeSync.enabled` (vault-shared) AND `youtubeSync.runnerEnabled`
   (vault-local, machine binding): either gate false means no scheduler work, egress, or lease churn.
2. **Scheduler core** `app/knowledge_acquisition/sync_scheduler.py` (pure logic, injectable clock):
   - computes per-source due-time from `last_attempt_at` + effective interval, honoring
     per-source backoff state after failures (contract §Retry and backoff);
   - admits due discovery polls (YSS-05 `poll_source`) within a per-tick start budget, with
     cooperative deadline/lease checks through the client and before durable result publication.
     HTTP timeouts, page caps, and bounded response reads limit I/O; an in-flight synchronous
     I/O operation can still wait for its transport timeout. This is not a hard real-time deadline;
   - **does not drain.** Narrowed 2026-09-22 (#3921): acquisition egress cannot run inside the
     watcher cycle, which holds a shared ingress flock, so a multi-minute download there stalls
     vault watching and blocks a foreground rebind. Draining stays the operator-invoked
     `youtube-inbox-dev drain` command (#5613); a bounded background drain is its own slice;
   - global pause and per-source pause (registry `enabled=false`) short-circuit with
     `paused_global`/`paused_source` reasons;
   - **acquisition shutdown is outside this slice.** No acquisition request is claimed by the
     tick. Discovery cooperatively checks the deadline and active lease; a future background
     drain needs its own stop and durable retry protocol.
3. **Single-run lease (INV-YSS-6):** a durable lease row (key `lease:youtube_sync`, TTL 10 min)
   in the migration-owned `youtube_sync_state` table. Scheduler instances derive distinct
   holder identities; a live lease blocks another holder, a stale lease may be taken over after
   expiry, and renewal/release check the acquiring holder. Existing manual Inbox sync uses the
   same scheduler lease and backoff state for one immediate attempt. Polling renews/checks
   ownership at cooperative boundaries and refuses durable publication after ownership loss.
   This adds no new CLI/UI surface.
4. **Offline/restart reconciliation:** active ticks retry stale `in_progress` recovery; failure
   does not mark recovery complete. The first catch-up pass makes enabled sources due, while
   later ticks honor cadence/backoff. Durable cursors and requests preserve idempotency; only
   items still visible in the bounded discovery window can be found without deferred backfill.
5. **Tick observability seam:** writes the `last_tick` row with `at`, `polled`, `discovered`,
   `enqueued`, and `deduped` into the sync-state table. These are discovery observations, not
   acquisition counters. Lease renewal is separate from this observation. YSS-09 status/health
   projection remains deferred;
   any later `runner_offline` status must derive from observation staleness.

## Concretely

```python
sched = SyncScheduler(registry=reg, requests=q, clock=fake_clock, lease=lease_store)
sched.tick()                       # inbox due -> poll + enqueue (no acquisition here)
fake_clock.advance(120); sched.tick()   # inbox not due (180s) -> no poll
fake_clock.advance(60);  sched.tick()   # due again
```

In runtime the same `tick()` is called by the watcher sub-tick; tests never need the loop.

## Why This Matters

Overlapping polls double-enqueue and double-spend quota; an unbounded drain inside the watcher
starves file-watching; a scheduler that self-reports "up to date" while offline lies to the user.
The lease and discovery-only tick bound overlap and avoid media acquisition inside the watcher.
Cooperative deadline checks do not establish a hard real-time poll deadline; status projection
remains later work.

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
- [ ] Global pause and per-source pause stop polling with the correct reason codes, and a paused
      runner does not touch the lease.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_pause_semantics`
- [ ] The tick performs discovery only and never acquisition, so it cannot block the watcher cycle
      on external media egress.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_scheduler.py::test_tick_never_performs_acquisition`
- [ ] The durable state store reads its own rows against real Postgres, so a row-shape mistake
      cannot leave the whole capability inert behind a memory-backed test suite.
      Verify: `tests/knowledge_acquisition/test_youtube_sync_state_pg.py::test_pg_state_store_reads_its_own_rows`
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

Cursors, queue rows, backoff, lease, and the `last_tick` observation are durable in the channel
DB. The catch-up marker is process-local: the first catch-up pass makes enabled sources due,
while stale-request recovery is retried on active ticks independently of that marker. Discovery
remains subject to the client's bounded newest-first window; this is not historical backfill or
an unlimited offline-recovery guarantee. Acquiring queued items still requires the operator drain.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Retry and backoff / Reason codes / Settings model`
- `docs/KARAKEEP_MIMER_ACQUISITION/SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION.md` (sibling scheduling precedent — leases/cursors/receipts shape)
- `docs/ENVIRONMENTS.md :: Allowed Variation by Environment`

## Related GitHub Issues

One issue. TCD hint: Opus / high — concurrency, lease semantics, restart convergence, and
watcher-loop integration; highest defect blast radius in the set after YSS-02.
