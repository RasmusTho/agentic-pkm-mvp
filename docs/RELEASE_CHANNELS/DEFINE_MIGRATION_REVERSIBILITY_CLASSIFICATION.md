---
name: Define Migration Reversibility Classification
description: Specify how schema and data migrations are classified as reversible or forward-only, where the classification is declared, and how it is consumed by the promotion plan.
task_id: RELEASE_CHANNELS-04
source_anchor: docs/RELEASE_CHANNELS/README.md :: Rollback posture
parent_capability: RELEASE_CHANNELS
prerequisites: [RELEASE_CHANNELS-01, RELEASE_CHANNELS-02]
depends_on: [DEFINE_CHANNEL_IDENTITY.md, SPLIT_POSTGRES_PER_CHANNEL.md]
can_parallelize_with: [DEFINE_PROMOTION_PLAN_CONTRACT, DEFINE_CONCURRENCY_RULE, DEFINE_ROLLBACK_CONTRACT]
---

# Define Migration Reversibility Classification

## Purpose

Make rollback safety legible before promotion, not after. Every migration either restores cleanly when `stable` rolls back or it does not; today there is no contract that forces that question to be answered explicitly. This task specifies the classification and the surface where it is declared, so the promotion plan can honestly state "this migration can / cannot be rolled back" and the operator can choose knowingly.

## What This Task Does

This task produces the migration-reversibility contract as a docs artifact under `docs/RELEASE_CHANNELS/`. It:

- Defines two classifications: **reversible** and **forward-only**.
- Specifies the declaration surface: every migration carries an explicit reversibility marker at authoring time (not inferred at promotion time).
- States the rule that forward-only migrations require explicit operator acknowledgment in the promotion plan.
- States the rule that reversible migrations carry a machine-readable reversal step (or reference to one).
- Declares what data-side changes are considered migrations for this purpose (schema changes, destructive data rewrites, index creation/deletion).
- States that the classification is not a guarantee the migration will succeed; it is a statement about whether the reversal path exists and has been authored.

## Concretely

- **Reversible migration**: the migration has an authored reverse step that restores the prior schema/data shape when executed. The reverse step is versioned alongside the forward step and runs as part of `rollback-promotion` if invoked.
- **Forward-only migration**: the migration does not have a reverse step, either because reversal is impossible (e.g. dropped data) or because reversal is not worth authoring. Forward-only migrations are allowed but must be flagged.
- **Declaration surface**: the reversibility marker lives in the migration file itself (frontmatter, comment, or tool-native metadata, as the migration tool allows). It is mandatory; a migration with no marker fails a pre-promotion check.
- **Consumption**: `prepare-promotion` reads the markers across the migration delta and emits them into the promotion plan's migration-delta section.
- **Operator acknowledgment**: forward-only migrations require a distinct operator acknowledgment in the plan. Reversible migrations do not.
- **Scope**: applies to migrations that run against `pkm_prod`. Dev-side migrations run against `pkm_dev` and are not bound by this contract during development; the contract engages at promotion time.

## Why This Matters

Without this classification, rollback is a guess. The operator discovers at rollback time that the migration can't reverse, and now prod is in a half-returned state with no audit trail. The classification shifts that failure mode to promotion time, where it is a deliberate choice instead of an incident. It also forces developers to think about reversibility when they author a migration, not when the operator is trying to recover from a bad release.

## Acceptance Criteria

- [ ] The contract defines exactly two classifications: reversible and forward-only.
  Verify: `rg -n "reversible|forward-only" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] The contract specifies the declaration surface lives in the migration file itself and is mandatory.
  Verify: `rg -n "declaration surface|migration file|mandatory" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] The contract specifies that forward-only migrations require an explicit operator acknowledgment in the promotion plan.
  Verify: `rg -n "operator acknowledgment|forward-only" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] The contract specifies that reversible migrations carry a machine-readable reversal step.
  Verify: `rg -n "reversal step|machine-readable" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] The contract scopes its applicability to migrations running against `pkm_prod`.
  Verify: `rg -n "pkm_prod|at promotion time|applicability" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] The contract states that classification is about reversal-path existence, not about migration success.
  Verify: `rg -n "not a guarantee|success|reversal path" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] The contract does not prescribe a specific migration tool.
  Verify: doc review; no tool-specific syntax mandated.

## How to Verify (Pre-Merge)

- Confirm the spec does not attempt to define migration authoring tooling or CI enforcement — those belong in follow-up implementation issues.
- Confirm the scope boundary with dev-side migrations is explicit: dev is unconstrained; the contract engages at promotion.
- Confirm the spec cross-references `DEFINE_PROMOTION_PLAN_CONTRACT` for how the classification is surfaced to the operator.

## Out of Scope

- Implementing the pre-promotion check that enforces the marker.
- Choosing the migration tool.
- Reversibility enforcement in CI for dev-side migrations.
- Data-restoration strategies beyond "run the authored reverse step."

## Related Docs

- [docs/RELEASE_CHANNELS/README.md](README.md) :: Rollback posture
- [docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md](DEFINE_PROMOTION_PLAN_CONTRACT.md)
- [docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md](DEFINE_ROLLBACK_CONTRACT.md)
- [docs/DB_SCHEMA.md](../DB_SCHEMA.md)

## Related GitHub Issues

When promoted: "Implements RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION." Follow-up issue: author the pre-promotion check that fails when a migration lacks a marker.
