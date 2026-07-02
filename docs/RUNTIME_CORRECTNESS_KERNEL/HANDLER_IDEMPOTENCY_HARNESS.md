---
name: Handler Idempotency Harness
description: A test harness that dispatches every registered outbox topic twice against a fixture payload and diffs durable state, proving handler idempotency for all topics
task_id: KERNEL-11
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E2"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-02, KERNEL-08]
depends_on: [MANDATORY_OUTBOX_IDEMPOTENCY.md, EVENT_TOPIC_SCHEMA_REGISTRY.md]
can_parallelize_with: []
---

# Handler Idempotency Harness

## Purpose

Outbox delivery is at-least-once (`ack_outbox` is the last durable action; the worker re-processes on
restart). Handler idempotency (`handle_T(e); handle_T(e)` ≡ `handle_T(e)` on durable state) is
asserted only by convention and verified nowhere; the worker's `_EventDedup` cache is in-memory only
(`app/workers/outbox_worker.py`, class `_EventDedup` approx. line 1210, `_EVENT_DEDUP` line 1225),
lost on restart. A retry after a crash can therefore double an effect (audit invariant **I-E2**).

## What This Task Does

- Add a harness that **dynamically enumerates** the worker dispatch table and dispatches every
  registered topic **twice** with a representative fixture payload, then diffs observable durable
  state between the first and second dispatch — asserting no net change on the second call.
- The dispatch table today is the `if/elif topic == ...` chain in
  `app/workers/outbox_worker.py::_dispatch_topic` (approx. lines 253–302), keyed on module-level topic
  constants (`INGEST_OBJECT_CREATED`, `INGEST_VAULT_CHANGED`, `INGEST_OBJECT_DELETED`,
  `PANEL_SCAN_REQUESTED`, `PROMOTE_INTENT_CREATED`, `NOTE_MOVE_WORKBENCH`, `INDEX_EMBEDDING_REQUESTED`).
  "Dynamically enumerate" means the harness derives the topic set from the source of truth, not a
  hardcoded list. If KERNEL-08's topic registry exists, enumerate it; otherwise enumerate the topic
  constants the dispatch table branches on. Either way a **newly registered topic without a fixture
  fails the harness** — no silent cap. State this coupling explicitly in the harness.
- Run against the memory/test backend; "durable state" = store rows (objects/file_state/vector
  index), vault fixture writes, and emitted outbox events. Diff all three between dispatch 1 and 2.
- Define a **fixture-registration pattern**: a `TOPIC_FIXTURES: dict[str, Payload]` mapping in the
  test module. The harness asserts `set(dispatch_topics) == set(TOPIC_FIXTURES)` first — adding a
  topic forces adding its idempotency fixture, or the harness fails loud.

## Concretely

```bash
pytest -q tests/workers/test_handler_idempotency_harness.py
```

The harness composes a fixture payload per topic, dispatches via the real `_dispatch_topic`
entrypoint twice, snapshots durable state after each, and asserts the second snapshot equals the
first for every topic.

## Why This Matters

Replay-soundness requires duplicate emission AND duplicate dispatch to be no-ops on durable state.
KERNEL-02 made emission idempotent at the log layer; this task proves the handler side, closing the
second half of the at-least-once contract. Enumerating dynamically means the guarantee cannot silently
regress when a topic is added — the canonical failure mode this capability removes.

## Acceptance Criteria

- [ ] The harness enumerates the dispatch table dynamically; a registered topic with no fixture
      fails the harness rather than being skipped.
      Verify: `tests/workers/test_handler_idempotency_harness.py::test_every_topic_has_a_fixture` — asserts `set(dispatch_topics) == set(TOPIC_FIXTURES)` derived from the production dispatch source.
- [ ] Dispatching each topic twice yields identical durable state (store rows, vault writes, emitted
      events) after the second call.
      Verify: `tests/workers/test_handler_idempotency_harness.py::test_dispatch_twice_is_idempotent` — drives `app.workers.outbox_worker._dispatch_topic` (the production dispatch entrypoint), not per-handler helpers.
- [ ] The harness runs in the `not pg` PR gate (memory/test backend, no live Postgres required).
      Verify: `pytest -q -m "not pg" tests/workers/test_handler_idempotency_harness.py`

## How to Verify (Pre-Merge)

1. `pytest -q tests/workers/test_handler_idempotency_harness.py`.
2. Full `pytest -q -m "not pg"` (shared worker path).
3. Sanity: temporarily add a dummy topic branch to `_dispatch_topic` and confirm the harness fails
   until a fixture is added; revert.
4. `ruff check app tests`.

## Out of Scope

- Making handlers idempotent that are not already (this is a *verification* harness; a discovered
  non-idempotent handler is a separate bug/issue).
- Idempotency-key emission (KERNEL-02) and topic schema validation (KERNEL-08).
- Refactoring `_dispatch_topic` from if/elif into a registry dict (nice-to-have, not required; the
  harness enumerates whatever the SoT is).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E2`
- `docs/EVENTS.md` (dispatch table + at-least-once contract)
- `docs/testing/invariant-tests.md` (I-E2 registration)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort (test harness with dynamic enumeration + state
diffing; no production behavior change). Escalate only if a handler turns out to be genuinely
non-idempotent, which converts to a separate remediation issue.
