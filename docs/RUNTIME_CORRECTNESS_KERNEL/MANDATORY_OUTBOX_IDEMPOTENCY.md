---
name: Mandatory Outbox Idempotency
description: Make deterministic idempotency keys required on every outbox insert; migrate all producers in the same change
task_id: KERNEL-02
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E1"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-01]
depends_on: [TRANSACTIONAL_VAULT_SYNC.md]
can_parallelize_with: []
---

# Mandatory Outbox Idempotency

## Purpose

`write_outbox_event()` accepts an optional `idempotency_key` (`app/services/outbox.py`, approx.
line 206); producers that omit it insert duplicates on retry, and the worker's `_EventDedup` cache
is in-memory only (lost on restart). At-least-once delivery without deterministic dedup means replay
multiplies effects (audit invariant **I-E1**).

## What This Task Does

- Change `write_outbox_event(event, conn=None, *, idempotency_key)` to **require** the key (no
  default). The key becomes the row `id` with `ON CONFLICT (id) DO NOTHING` as today.
- Add one shared derivation helper (e.g. `app/services/outbox.py::derive_idempotency_key(topic,
  source_id, content_fingerprint)` → `sha256(topic ‖ source_id ‖ fingerprint)` as UUIDv5/hex) so
  producers do not invent ad-hoc schemes.
- Migrate **every** producer in the same PR (AGENTS.md invariant→producers rule): `vault_sync.py`
  (`insert_object_and_outbox`), `app/outbox/events.py` (emit_index_embedding_*; already passes
  `event_id` — normalize onto the helper), watcher events (`app/watcher/events.py`), panel/worker
  retry + dead-letter emissions, promotion intents.
- Choose per-topic fingerprints deliberately: ingest events key on `(topic, note_path,
  content_hash)`; watcher-run audit events key on `(topic, run window)`; retry/dead-letter events
  key on `(topic, original outbox id, attempt)` so genuine re-emissions are not swallowed.

## Concretely

```bash
pytest -q tests/services/test_outbox_idempotency.py
grep -rn "write_outbox_event(" app/ | grep -v "idempotency_key"   # must return nothing
```

## Why This Matters

Replay-soundness (rebuild derived state from the log) and safe retry both require duplicate emission
to be a no-op at the log layer, not only in a volatile cache. This is the second half of the
transactional-outbox guarantee started in KERNEL-01.

## Acceptance Criteria

- [ ] `write_outbox_event` has no optional-key path; a keyless call is a `TypeError` at the
      signature level.
      Verify: `tests/services/test_outbox_idempotency.py::test_key_is_required`
- [ ] Duplicate emission with the same derived key yields exactly one outbox row.
      Verify: `tests/services/test_outbox_idempotency.py::test_duplicate_emit_single_row`
- [ ] All producers use the shared derivation helper; a repo-wide grep gate asserts no callsite
      omits the key.
      Verify: `tests/architecture/test_outbox_producer_idempotency.py::test_no_keyless_callsites`
- [ ] Intentional re-emissions (retry/dead-letter audit events) still produce distinct rows
      (attempt-scoped keys).
      Verify: `tests/services/test_outbox_idempotency.py::test_retry_events_not_swallowed`

## How to Verify (Pre-Merge)

1. `pytest -q tests/services/test_outbox_idempotency.py tests/architecture/test_outbox_producer_idempotency.py`
2. Full `pytest -q -m "not pg"` + `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m uat_integrated_runtime`
   (hot-path producer change).
3. `ruff check app tests`.

## Out of Scope

- Handler-side idempotency verification (KERNEL-11).
- Topic payload schemas (KERNEL-08).
- Removing `_EventDedup` (it may stay as a fast-path cache; it is no longer load-bearing).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E1`
- `docs/EVENTS.md :: Idempotency` (producers SHOULD use deterministic event ids — this task
  upgrades SHOULD to MUST; update the doc section in the same PR)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort (mechanical signature + producer sweep with a
clear grep gate). Escalate only if a producer's natural fingerprint is genuinely ambiguous.
