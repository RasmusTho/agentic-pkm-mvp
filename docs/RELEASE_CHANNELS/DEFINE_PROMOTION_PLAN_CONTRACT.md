---
name: Define Promotion Plan Contract
description: Specify the shape of the promotion plan produced by prepare-promotion and consumed by execute-promotion, including required sections, risk classification, and acceptance-criteria checks.
task_id: RELEASE_CHANNELS-03
source_anchor: docs/RELEASE_CHANNELS/README.md :: Promotion contract
parent_capability: RELEASE_CHANNELS
prerequisites: [RELEASE_CHANNELS-01]
depends_on: [DEFINE_CHANNEL_IDENTITY.md]
can_parallelize_with: [SPLIT_POSTGRES_PER_CHANNEL, DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION, DEFINE_CONCURRENCY_RULE, DEFINE_ROLLBACK_CONTRACT]
---

# Define Promotion Plan Contract

## Purpose

Make promotion an explicit, reviewable artifact rather than a series of commands the operator types into a terminal. Before any `stable` ref moves, the operator must be able to read a single document that describes exactly what is changing, what the risks are, and what the rollback path looks like. This task specifies the shape of that document.

## What This Task Does

This task produces the promotion-plan contract as a docs artifact under `docs/RELEASE_CHANNELS/`. It:

- Specifies the required sections of a promotion plan.
- States that the plan is produced by the `prepare-promotion` skill and consumed by `execute-promotion`.
- Specifies the risk-classification shape: every included PR is annotated with its acceptance-criteria status, known regressions, and any forward-only migration flag.
- States the operator's role: the plan is reviewed before execution; promotion never proceeds on an unreviewed plan.
- Specifies that the plan is preserved as a promotion receipt after execution.

## Concretely

A promotion plan has these required sections:

- **Promotion target** — the commit on `main` being promoted, and the current `stable` commit being replaced.
- **Code delta** — ordered list of PRs included, each annotated with: PR title, PR link, AC status (satisfied / partial / unverified), verification receipt pointer, and any known-regression notes.
- **Migration delta** — schema and data migrations to apply to `pkm_prod`, each classified as **reversible** or **forward-only** per `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION`.
- **Config / settings delta** — settings changes that take effect in prod after promotion (watcher policies, env vars, operator-visible defaults).
- **Risk notes** — explicit list of risks the operator should consider, including forward-only migrations, any PR lacking full AC verification, and any cross-channel touchpoints.
- **Rollback path** — the previous `stable` ref and the migration-reversal sequence (per `DEFINE_ROLLBACK_CONTRACT`).
- **Operator acknowledgments** — explicit checkboxes the operator ticks before execution (e.g. "I accept forward-only migration X", "I have run verify-promotion in a dry context").

The plan is written as a single markdown file in a known location (e.g. `ops/promotions/YYYY-MM-DD-<sha>.md`). After `execute-promotion` completes, the plan is retained as the promotion receipt.

## Why This Matters

Without a plan contract, every promotion is a verbal "I think this is fine" event that leaves no audit trail and no shared understanding of what just changed in prod. The plan shape also forces `prepare-promotion` to surface risks explicitly instead of letting them hide in unread commits. It is the artifact that makes promotion reviewable and rollback grounded.

## Acceptance Criteria

- [ ] The contract specifies all seven required sections of a promotion plan.
  Verify: `rg -n "Promotion target|Code delta|Migration delta|Config|Risk notes|Rollback path|Operator acknowledgments" docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`.
- [ ] The contract states that the plan is produced by `prepare-promotion` and consumed by `execute-promotion`.
  Verify: `rg -n "prepare-promotion|execute-promotion" docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`.
- [ ] The contract requires per-PR AC status annotation in the code delta.
  Verify: `rg -n "AC status|acceptance-criteria status|verification receipt" docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`.
- [ ] The contract requires per-migration reversibility classification, deferring the classification rules to `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION`.
  Verify: `rg -n "reversible|forward-only|DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION" docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`.
- [ ] The contract requires operator acknowledgments before execution.
  Verify: `rg -n "Operator acknowledgments|checkbox|before execution" docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`.
- [ ] The contract states the plan is retained as a promotion receipt.
  Verify: `rg -n "promotion receipt|retained|audit trail" docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`.
- [ ] The contract does not prescribe tooling used to produce or apply the plan.
  Verify: doc review; the spec names required sections and behavior, not a specific runner, file format beyond "markdown", or migration tool.

## How to Verify (Pre-Merge)

- Confirm the plan section list is complete and every section is load-bearing (no ceremonial sections).
- Confirm the spec does not duplicate the rules owned by `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION` or `DEFINE_ROLLBACK_CONTRACT`.
- Confirm the spec is docs-only and does not imply any runtime implementation.

## Out of Scope

- Writing the `prepare-promotion` or `execute-promotion` skills (governance-lane follow-up).
- Defining the migration-reversibility rules (owned by `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION`).
- Defining rollback mechanics (owned by `DEFINE_ROLLBACK_CONTRACT`).
- Hosted CI/CD-triggered promotion.

## Related Docs

- [docs/RELEASE_CHANNELS/README.md](README.md) :: Promotion contract
- [docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md](DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md)
- [docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md](DEFINE_ROLLBACK_CONTRACT.md)

## Related GitHub Issues

When promoted: "Implements RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT." Downstream: a separate issue authors the `prepare-promotion` skill that actually produces this plan; that is governance-lane work.
