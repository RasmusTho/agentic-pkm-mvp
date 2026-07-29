---
name: Guarantee Globally Unique Split Complements
description: Give each merge redirect and target-side complement one globally unique identity, then recover repeated splits from stable identities instead of source/target shape.
task_id: EROJ-03
source_anchor: "docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md :: Cross-task partial-failure matrix"
parent_capability: Entity-Review Operation Journal
prerequisites:
  - EROJ-02 accepted parent receipt
depends_on:
  - PRESERVE_TARGET_EVOLUTION_LINEAGE.md
can_parallelize_with: []
---

# Guarantee Globally Unique Split Complements

## Purpose

Close the final recovery ambiguity: a source redirect and the target's `merged_from` membership must
be one uniquely identified relation. Repeated split attempts must resume from that identity and may
not create a second complement or certify completion from matching source/target ids alone.

## What This Task Does

- Add one stable `complement_id` for each merge relation. The source redirect records that id; the
  target records a structured complement containing the same id, `from_id`, original `into_id`, and
  governing operation id when available. Keep `merged_from` only as a compatibility projection
  derived from structured complements, not as recovery proof.
- Derive entity-review complement ids deterministically from the immutable operation identity and
  relation pair. Enforce uniqueness across every register note under the existing governed
  register-write/locking boundary before any split effect is accepted.
- Extend the narrow journal with the exact split plan and per-complement checkpoints needed by
  `EntityRegister.split`; preallocate successor entity ids and complement transitions before the
  first split note write. Retry reuses those ids and writes only missing effects.
- Make split validation require the same complement id on both sides and the journal checkpoint.
  Matching labels, aliases, `merged_into`, or `merged_from` membership cannot certify completion.
- Add deterministic compatibility for existing unambiguous source redirect + target `merged_from`
  pairs. Backfill a stable legacy complement id under the register lock, update both producers, and
  fail before mutation on duplicates, missing opposite sides, multiple candidate targets, or cycles.
- Update every merge/split producer, note parser/renderer, fixture, and owner contract in the same PR.
  Do not leave a new required complement field without migrated producers.

## Concretely

For merge operation `op`, source `S` and original target `T` share complement `c`. A split plan names
`c` and preallocates each successor id. If a process stops after writing the first successor and
repointing `S`, retry sees the same plan and `c`, verifies that completed effect, and writes only the
remaining effects. A later second split cannot mint a new `c` for the old relation or treat a
duplicate `merged_from: [S]` entry elsewhere as success.

Legacy notes are eligible for deterministic backfill only when exactly one source redirect and one
target membership form an unambiguous pair. Anything else is repair-required evidence, not input to
an automatic guess.

## Why This Matters

Source/target ids are not a globally unique relation identity after repeated splits and re-merges.
Two notes can look structurally plausible while representing duplicate or contradictory complements.
Stable relation identity plus a persisted split plan turns crash recovery into exact completion of
known effects rather than graph-shape certification.

## Acceptance Criteria

- [ ] Every merge producer writes one complement id on source and target, and the same id cannot
      appear as two relations anywhere in the active register.
      Verify: `tests/heimdal/test_entity_register.py::test_split_complement_ids_are_globally_unique_across_repeated_splits`
- [ ] A crash during the second split resumes the preallocated plan and produces no duplicate target
      complement, successor entity, or split event.
      Verify: `tests/heimdal/test_entity_register.py::test_second_split_crash_recovers_without_duplicate_complements`
- [ ] A matching source/target shape with a duplicate, missing, or mismatched complement id fails
      before journal completion or queue clear.
      Verify: `tests/heimdal/test_entity_register.py::test_duplicate_complement_preflight_fails_before_pending_clear`
- [ ] Existing unambiguous redirect/`merged_from` pairs receive deterministic two-sided complement
      ids, while ambiguous or contradictory legacy notes fail loud without mutation.
      Verify: `tests/heimdal/test_entity_register.py::test_legacy_complement_backfill_is_deterministic_and_fail_loud`
- [ ] Split retries reuse preallocated successor ids and per-complement checkpoints from the narrow
      operation journal.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_split_retry_reuses_preallocated_successors_and_checkpoints`
- [ ] The entity-review queue remains pending until fresh committed event visibility, lineage proof,
      and unique split-complement recovery all hold together.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_pending_clear_waits_for_unique_split_recovery`
- [ ] Every note producer/parser/renderer and fixture is migrated in the same change, with a preflight
      that rejects unresolved duplicate complement ids before writes.
      Verify: `tests/heimdal/test_entity_register.py::test_all_relation_producers_supply_unique_complement_identity`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/heimdal/test_entity_review_operation_journal.py tests/heimdal/test_entity_register.py tests/heimdal/test_entity_confirm.py`
- `python3 -m pytest -q -m "not pg" tests/heimdal tests/migrations`
- `ruff check app tests`
- `mypy app`
- Run focused crash injection before/after each successor write in first and second split plans.
- Run the compatibility preflight against unambiguous, duplicate, missing-opposite, and cyclic legacy
  fixtures.
- Full Tier-3 independent review, current-SHA CI, and terminal parent recovery-matrix replay.

## Out of Scope

- A general relationship id system for non-entity data, a graph database, or a generic transaction
  coordinator.
- Guessing repair for ambiguous legacy notes.
- Changing human merge/split intent or compacting/deleting historical entity notes.
- Parallel split execution or a background repair worker.

## Restart / Durability Posture

The committed split plan is the retry anchor. Preallocated successor ids and complement checkpoints
make each note effect idempotent. A restart scans only the plan's named entities and then performs the
global complement uniqueness preflight before continuing. Any mismatch leaves the operation
non-terminal and `pending` unchanged; no cleanup deletes evidence automatically.

## TCD Capability Guidance

Use Codex Sol / xhigh reasoning. This slice combines data compatibility, globally enforced identity,
multi-note crash recovery, migration of every producer, and the exact repeated-split defect that
exhausted #4253. Prove the mechanism with crash injection and legacy preflight fixtures before the
broader suite. Apply the mechanism-level convergence gate if one review reports multiple blockers.
Do not fan out implementation.

## Related Docs

- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`
- `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/CONCURRENCY.md`
- `docs/RUNTIME_CORRECTNESS_KERNEL/TRANSACTIONAL_VAULT_SYNC.md`
- `docs/EVENTS.md`

## Related GitHub Issues

Filed as [#4352](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4352), the third serial child of
parent validation hub [#4349](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4349). It remains
`agent:blocked` pending an accepted EROJ-02/#4351 parent receipt.
