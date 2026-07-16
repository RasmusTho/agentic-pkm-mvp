---
name: Establish Durable Acquisition Requests
description: Source-agnostic durable request queue (table + memory backend) with deterministic idempotency, multi-trigger provenance, retries, item-scoped dead letters, and the drain seam into acquire_youtube.
task_id: YSS-04
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: AcquisitionRequest"
parent_capability: YouTube Source Sync
prerequisites: [YSS-01]
depends_on: [ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md]
can_parallelize_with: [BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md]
---

# Establish Durable Acquisition Requests

## Purpose

Discovery must never fetch, and fetch must never depend on discovery being alive. The durable
request row is the seam: discovery enqueues cheaply; a bounded drain acquires later; restarts,
retries, and dedup converge on the row. This is deliberately a migration-owned table, not outbox
rows — the queue needs status queries, trigger-append provenance, priority, and per-item backoff
that append-only events cannot carry, and its slow drain must not ride the shared outbox worker's
fast dispatch loop.

## What This Task Does

1. New module `app/knowledge_acquisition/acquisition_requests.py` implementing
   `SOURCE_SYNC_CONTRACT.md :: AcquisitionRequest` exactly: deterministic
   `request_id = uuid5("{source_kind}:{item_ref}:{policy_version}")`, Postgres backend (new table
   `acquisition_requests`, forward-only Alembic migration with the `reversibility` marker,
   modeled on the `a1b2c3d4e5f6` template) + memory backend for `not_pg` tests (the
   `app/heimdal/cursor_store.py` dual-backend shape, incl. fail-loud
   `AcquisitionRequestsSchemaMissingError` preflight and `STORE_SCHEMA_AUTOCREATE` test-only
   autocreate).
2. `enqueue(...)`: idempotent insert; on conflict appends the new discovery trigger to
   `discovery_triggers` and touches nothing else. Emits `acquisition.requested` (first insert
   only) and `youtube.source.discovered` per contract via
   `app/services/outbox.py::write_outbox_event` + `derive_idempotency_key`.
3. `claim_batch(limit)` / `complete(...)` / `fail(...)`: drain order `(priority, requested_at)`;
   attempts + reason-coded backoff per contract §Retry and backoff; stale `in_progress` reset;
   explicit `dead_letter(...)` for terminal item outcomes. Emits
   `acquisition.started/completed/failed` with `(request_id, attempt)` keys.
4. Drain adapter `drain_one(request, *, vault_context, write_guard=...)` that invokes the existing
   `acquire_youtube` (`app/knowledge_acquisition/acquire.py`) with the request's policy snapshot
   and trace id, then maps the `AcquisitionReceipt` per INV-YSS-3: `ok` → `completed`
   (+`content_identity`/`artifact_path`); `blocked` → retryable `writeguard_blocked`; stage
   dead-letter → `pipeline_dead_letter` (terminal, item-scoped); raised
   transient/`AcquisitionError` → retryable with reason. The scheduler slice (YSS-06) owns *when*
   this runs; this slice owns *what happens* when it runs.
5. Register the four `acquisition.*` topic schemas + `youtube.source.discovered` under
   `schemas/events/` and constants in `app/events/types.py` (lineage posture — no
   `_dispatch_topic` branch).

## Concretely

```python
q = AcquisitionRequests.for_runtime()
r1 = q.enqueue(source_kind="youtube_url", item_ref="dQw4w9WgXcQ", trigger=Trigger(binding_id=b1, ...))
r2 = q.enqueue(source_kind="youtube_url", item_ref="dQw4w9WgXcQ", trigger=Trigger(binding_id=b2, ...))
assert r1.request_id == r2.request_id and len(r2.discovery_triggers) == 2   # INV-YSS-2
outcome = drain_one(q.claim_batch(1)[0], vault_context=ctx)                  # runs existing pipeline
```

## Why This Matters

Without INV-YSS-2/3 at this seam, the same video saved in two lists becomes two candidates, a
WriteGuard block reads as success, or a crash between pipeline success and status update loses
work. Every one of those converges here or nowhere.

## Acceptance Criteria

- [ ] Same `(source_kind, item_ref, policy_version)` from two sources yields one request with both
      triggers preserved, exactly one `acquisition.requested` event, and — driven end-to-end
      through a stubbed pipeline — exactly one candidate.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_same_video_two_sources_single_request_merged_provenance`
- [ ] A request becomes durable (visible after simulated restart) before any completion state; a
      crash between enqueue and drain re-converges without duplicate pipeline effects.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_request_durable_before_drain_and_restart_converges`
- [ ] WriteGuard-blocked writeback leaves the request retryable with `writeguard_blocked`, emits
      `acquisition.failed` with `terminal: false`, and a later drain completes it — asserted
      through the production `drain_one` → `acquire_youtube` call site.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_writeguard_block_reported_and_retryable_at_call_site`
- [ ] KA stage dead-letter maps to explicit item-scoped `dead_lettered` without affecting sibling
      requests; attempts-exhaustion dead-letters with `terminal: true`.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_dead_letter_item_scoped_and_attempts_exhaustion`
- [ ] Retry backoff sets `next_attempt_at` per contract and `claim_batch` respects it; priority
      orders inbox-discovered items first.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_backoff_gate_and_priority_order`
- [ ] Event emissions carry contract idempotency keys: re-emission of the same attempt dedups;
      a new attempt is a distinct event.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_event_idempotency_keys_per_attempt`
- [ ] Pg backend passes the same behavioral suite; migration is forward-only with the
      reversibility marker.
      Verify: `tests/knowledge_acquisition/test_acquisition_requests_pg.py::test_pg_backend_contract` (marked `pg`)

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_acquisition_requests.py`
- `pytest -q -m "not pg"` (queue + outbox emission are hot-path; full default suite)
- `ruff check app tests && mypy app`

## Out of Scope

Discovery adapters (YSS-05/07), scheduling/lease (YSS-06), any YouTube egress (the drain calls the
existing entrypoint; tests stub it), UI/CLI surfaces.

## Restart / Durability Posture

Requests, attempts, backoff state, and dead letters are durable rows in the channel database;
nothing queue-shaped is process memory. A restart may re-run an `in_progress` item; KA idempotency
plus the deterministic request id make the re-run converge — the user never sees a duplicate
candidate, only (at worst) repeated work.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: AcquisitionRequest / Event topics / Retry and backoff`
- `docs/EVENTS.md :: Event Idempotency (normative) / Event Topic Schema Registry`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Stage execution model`

## Related GitHub Issues

One issue. TCD hint: Opus / high — concurrency, idempotency, and partial-failure semantics
dominate; a hidden defect here silently loses or duplicates knowledge intake.
