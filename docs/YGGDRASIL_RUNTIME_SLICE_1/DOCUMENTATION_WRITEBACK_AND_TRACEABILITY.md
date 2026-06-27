---
name: Documentation Writeback and Traceability
description: Update the invariant registry and traceability matrix to reflect runtime enforcement; close the parent epic
task_id: YRS1-08
source_anchor: docs/architecture/traceability-matrix.md :: rows 1-7
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-07]
depends_on: [CONVERT_INVARIANT_XFAILS_TO_PASSING.md]
can_parallelize_with: []
---

# Documentation Writeback and Traceability

## Purpose

Promote the durable truth: the architecture docs must now say the converted invariants are enforced
at runtime, not merely pinned by an xfail skeleton. This is the only task that updates owner docs, and
it carries the parent-epic closure handoff.

## What This Task Does

- Updates `docs/testing/invariant-tests.md` Coverage map: the eight converted invariants move from
  "xfail runtime skeleton" to runtime-enforced (keeping their schema/static posture noted).
- Updates `docs/architecture/traceability-matrix.md` rows for principles 1–7 where a test moved from
  `future_runtime` to runtime/static.
- Updates any runtime contract doc to record the implemented slice (notably the architecture context
  packet's "first runtime vertical slice" status, and a one-line pointer to the `yggdrasil_runtime`
  package).
- Posts the final validation receipt to the parent epic and closes it, reconciling the README
  `State:` line and the parent-issue local surface.
- Introduces no architecture contradiction (the docs must stay internally consistent — derived
  representations still rebuildable, similarity still not permission, etc.).

## Concretely

- Registry diff: `capture_stamps_scope`, `provenance_survives_derivation`, `retrieve_scope_prefilter`,
  `similarity_not_permission`, `cross_scope_only_via_flow`, `private_not_in_work_results`,
  `rpg_not_confused_with_software`, `retrieval_cannot_upgrade_intrinsic_non_evidence` (runtime part)
  → marked runtime-enforced with their test pointers.
- Matrix diff: enforcement posture column updated for the corresponding rows.

## Why This Matters

If the registry and matrix keep claiming these are future-runtime skeletons after the runtime lands,
the docs lie about what the system enforces — and the next agent re-plans already-delivered work.
Bundling the owner-doc update into this PR (not a follow-up) keeps the claimed truth aligned with the
delivered truth.

## Acceptance Criteria

- [ ] `docs/testing/invariant-tests.md` Coverage map reflects the eight converted invariants as
  runtime-enforced.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: Coverage map`
- [ ] `docs/architecture/traceability-matrix.md` enforcement posture updated for the affected rows.
  - Verify: doc writeback at `docs/architecture/traceability-matrix.md :: rows 1-7`
- [ ] The architecture context packet records the first runtime vertical slice as delivered, with a
  pointer to `yggdrasil_runtime`.
  - Verify: doc writeback at `docs/foundation/yggdrasil-architecture-context-packet.md :: runtime slice status`
- [ ] No architecture contradiction is introduced.
  - Verify: `pytest -q tests/invariants tests/evals` stays green (the static doc-consistency probes,
    e.g. `test_oef_charter_states_observability_not_policy`, stay green).
- [ ] Parent epic closed with a final validation receipt; README `State:` and
  `PARENT_FEATURE_ISSUE` surface reconciled.
  - Verify: doc writeback at `docs/YGGDRASIL_RUNTIME_SLICE_1/README.md :: State`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants tests/evals` stays green.
- Review: the registry/matrix diffs match the converted-invariant list exactly (no over-claiming an
  invariant that is still xfail).

## Out of Scope

- Any new runtime behavior or test conversion (done in YRS1-02..07).
- Promoting "left for later" invariants in the docs.

## Related Docs

- `docs/testing/invariant-tests.md`, `docs/architecture/traceability-matrix.md`,
  `docs/foundation/yggdrasil-architecture-context-packet.md`
- Boundaries: OEF (records visibility), GOV (gives normative meaning)

## Related GitHub Issues

One issue, `agent:ready` once YRS1-07 merges. Final child — carries parent-epic closure.
