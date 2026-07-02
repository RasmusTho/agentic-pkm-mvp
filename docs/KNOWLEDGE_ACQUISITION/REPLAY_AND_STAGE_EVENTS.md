---
name: Replay and Stage Events
description: Outbox stage events with idempotency keys, item-scoped dead-letters, and the end-to-end replay guarantee without egress
task_id: KA-06
source_anchor: docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Stage execution model; Lineage and replay
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: [KA-05]
depends_on: [CANDIDATE_WRITEBACK.md]
can_parallelize_with: []
---

# Replay and Stage Events

## Purpose

Close the slice: every stage transition emits a standard-envelope outbox event with a
deterministic idempotency key, failures dead-letter loudly and item-scoped, and the whole chain
replays from `raw` without network egress. This is the slice's proof that the architecture holds.

## What This Task Does

- Stage events (`normalize`, extractor runs, `candidate`) on the existing DB outbox with the
  `docs/EVENTS.md` envelope; idempotency keys deterministic per
  (stage, stage version, `content_identity`) — aligned with the correctness-kernel requirements
  (MANDATORY_OUTBOX_IDEMPOTENCY / HANDLER_IDEMPOTENCY_HARNESS; consume their harness if merged,
  do not fork delivery semantics).
- Item-scoped dead-letter on stage failure: other items and other extractors proceed.
- Replay: a command/receipt that deletes all derived levels for an item and reproduces equivalent
  normalized/extracted/candidate artifacts from `raw` with egress blocked.

## Concretely

```
$ python -m app.cli acquire-replay <raw_record_id> --assert-no-egress
normalize@1 … ok (idempotent)
summary@1  … ok (idempotent)
candidate  … ok → note content identical
replay receipt: equivalent=true egress=0
```

## Why This Matters

The Phase 2 acceptance hinges on replayability; without it, extractor improvements mean
re-downloading everything, and event handlers without idempotency keys violate the kernel
invariants the runtime is converging on.

## Acceptance Criteria

- [ ] Every stage transition emits exactly one outbox event with the standard envelope and a
      deterministic idempotency key (asserted at the production emit site).
      Verify: `tests/knowledge_acquisition/test_stage_events.py::test_envelope_and_deterministic_idempotency_key`
- [ ] Duplicate event delivery does not duplicate stage effects.
      Verify: `tests/knowledge_acquisition/test_stage_events.py::test_duplicate_delivery_idempotent`
- [ ] A failing stage dead-letters that item at that stage, loudly; sibling items/extractors are
      unaffected.
      Verify: `tests/knowledge_acquisition/test_stage_events.py::test_item_scoped_dead_letter`
- [ ] Full replay from `raw` reproduces equivalent derived artifacts with zero network egress.
      Verify: `tests/knowledge_acquisition/test_replay.py::test_replay_from_raw_no_egress_equivalent_output`

## How to Verify (Pre-Merge)

- `pytest tests/knowledge_acquisition/test_stage_events.py tests/knowledge_acquisition/test_replay.py -q`
- Touches the outbox/event path (shared/hot-path): run the full `pytest -q -m "not pg"` suite
  before PR; if the integrated-runtime UAT gate applies to the touched surface, also run
  `RUN_INTEGRATED_RUNTIME_UAT=1`.
- `ruff check app tests`

## Out of Scope

Outbox GC/retention (tracked by the kernel/observability lines); scheduling; batch replay;
cross-device replication (explicit SFC non-goal per README §SBS classification).

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` §Stage execution model, §Lineage and replay
- `docs/EVENTS.md`; `docs/RUNTIME_CORRECTNESS_KERNEL/MANDATORY_OUTBOX_IDEMPOTENCY.md`
- `docs/architecture/runtime-semantics.md` (advisory: outbox as replay substrate)

## Related GitHub Issues

One issue; delivers the parent-closure handoff (final child). TCD hint: Sonnet / high
(event/idempotency semantics; full not-pg suite mandatory).
