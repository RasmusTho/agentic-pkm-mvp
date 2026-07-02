---
name: Event Topic Schema Registry
description: Versioned per-topic payload schema registry validated at write and dispatch; invalid payload at dispatch dead-letters with reason schema_violation; pre-registry rows grandfathered as v0
task_id: KERNEL-08
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E5, CW-4"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-02]
depends_on: [MANDATORY_OUTBOX_IDEMPOTENCY.md]
can_parallelize_with: [TRANSFORM_PROVENANCE_STAMP]
---

# Event Topic Schema Registry

## Purpose

`OutboxEvent.payload` is `Dict[str, Any]` and `meta` defaults to `{"version": "1.0"}`
(`app/events/schema.py :: _default_meta`, lines 15–16). No per-topic payload schema exists;
consumers parse raw dicts. The runtime has a correct formal model in `yggdrasil_runtime/` and
`tests/`, but the live pipeline speaks untyped dicts — drift is structural (audit **I-E5**, CW-4).

## What This Task Does

- Add a versioned per-topic schema registry: `schemas/events/<topic>.v1.schema.json` for every topic
  in the worker dispatch table (`app/workers/outbox_worker.py :: _dispatch_topic`, approx. lines
  253–301 at audit time). The topics currently dispatched are: `ingest.object.created`,
  `ingest.vault.changed`, `ingest.object.deleted`, `panel.scan.requested`, `promote.intent.created`,
  `note.move.workbench`, `index.embedding.requested` (constants in `app/events/types.py`).
- Validate at **write** (`app/services/outbox.py :: write_outbox_event`, approx. lines 192–222) and
  at **dispatch** (`_dispatch_topic`). Invalid payload at dispatch → immediate dead-letter with
  reason `schema_violation` via the existing `_dead_letter_outbox_message` path
  (`app/workers/outbox_worker.py`, approx. line 608), **never** partial processing.
- `OutboxEvent.meta` gains `payload_schema: "<topic>.v<N>"` (replacing the bare `version: "1.0"`
  convention in `_default_meta`/`_build_meta`).
- **Grandfathering (cross-task invariant #1):** rows written before the registry exists — i.e.
  `meta.payload_schema` / `schema_version` absent — are treated as `v0` and validated **log-only** at
  dispatch, never dead-lettered retroactively. Only rows carrying a registered schema version are
  hard-validated.
- Registry coverage is enforced **dynamically**: a test enumerates the dispatch table at runtime and
  fails if any dispatched topic lacks a `schemas/events/<topic>.v1.schema.json` — no hardcoded topic
  list that can silently cap coverage.

## Concretely

```bash
pytest -q tests/events/test_topic_schema_registry.py
pytest -q tests/workers/test_outbox_worker.py
```

## Why This Matters

At-least-once delivery over untyped payloads means one producer's malformed dict becomes a
consumer's crash or silent mis-handling. A registry with validate-at-write catches drift early and
validate-at-dispatch converts a poison payload into a loud dead-letter instead of partial state.

## Acceptance Criteria

- [ ] Registry coverage: every topic dispatched by `_dispatch_topic` has a
      `schemas/events/<topic>.v1.schema.json`; the coverage test enumerates the dispatch table (no
      hardcoded cap) and fails on any gap.
      Verify: `tests/events/test_topic_schema_registry.py::test_every_dispatched_topic_has_schema`
- [ ] Validation at write: `write_outbox_event` rejects a payload that violates its registered
      schema; `OutboxEvent.meta.payload_schema` is set to `<topic>.v<N>`.
      Verify: `tests/events/test_topic_schema_registry.py::test_write_validates_and_stamps_schema`
- [ ] Enforcement AC: an invalid payload dead-letters at dispatch with reason `schema_violation` and
      never partially processes — the test drives the production dispatch entrypoint
      (`_dispatch_topic` via the worker consume loop), asserting the dead-letter call fires.
      Verify: `tests/workers/test_outbox_worker.py::test_schema_violation_dead_letters_at_dispatch`
- [ ] Grandfathering: a row with `payload_schema`/`schema_version` absent is validated log-only and
      is never dead-lettered.
      Verify: `tests/events/test_topic_schema_registry.py::test_pre_registry_rows_grandfathered_v0`

## How to Verify (Pre-Merge)

1. `pytest -q tests/events/test_topic_schema_registry.py tests/workers/test_outbox_worker.py`
2. Full `pytest -q -m "not pg"` (touches the outbox write + worker dispatch paths); `ruff check app tests`.

## Out of Scope

- Idempotency-key requirement on `write_outbox_event` (KERNEL-02, prerequisite).
- Plan schema validation (KERNEL-09); handler idempotency harness (KERNEL-11).
- Migrating payloads to closed value types beyond JSON-schema validation.

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-E5, CW-4`
- `docs/EVENTS.md` (topic contract; update at promotion), `schemas/` (existing schema conventions)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort (mechanical once the first topic schema +
validate-at-write/dispatch pattern is set; the coverage test guarantees completeness).
