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

- **Promotion target** — exact current green TEST source C and its immutable digest D, and the current protected `stable` baseline S being replaced.
- **Code delta** — ordered list of PRs included, each annotated with: PR title, PR link, AC status (satisfied / partial / unverified), verification receipt pointer, and any known-regression notes.
- **Migration delta** — schema and data migrations from S to C to apply to prod's active (`app` DB, compose project `pkm-prod`), each classified as **reversible** or **forward-only** per `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION`. Physical execution retains this boundary and every acknowledgment gate.
- **Config / settings delta** — settings changes that take effect in prod after promotion (watcher policies, env vars, operator-visible defaults).
- **Risk notes** — explicit list of risks the operator should consider, including forward-only migrations, any PR lacking full AC verification, and any cross-channel touchpoints.
- **Rollback path** — the previous `stable` ref and the migration-reversal sequence (per `DEFINE_ROLLBACK_CONTRACT`).
- **Operator acknowledgments** — explicit checkboxes the operator ticks before execution (e.g. "I accept forward-only migration X", "I have run verify-promotion in a dry context").

The plan is written as a single markdown file in a known location (e.g. `ops/promotions/YYYY-MM-DD-<sha>.md`). After `execute-promotion` completes, the plan is retained as the promotion receipt.

## Current TEST and protected stable evidence

Issue #6228 adopts this plan as the existing durable carrier for production admission; it introduces
no additional registry. The seven reviewed sections remain required. `Test evidence` adds one
`<!-- stable-promotion -->` JSON block with these closed fields:

- `candidate`: `sha` C, `digest` D, and positive `run_id`, `run_attempt`, `artifact_id` for the existing
  build-once main-image producer. C must equal the exact current controller-owned `test` ref and
  retain trusted green DEV and TEST evidence. A prior PASS candidate is insufficient.
- `stable_baseline`: S, freshly read from the protected canonical stable ref before its PR; S must
  be an ancestor of C. Divergence requires separately authorized reconciliation and a fresh TEST
  qualification, never a force push or tree-only equivalence.
- `deployment_model`: the actual `pinned-image` model, backed by the existing prod deployment
  receipt's fleet-model fitness PASS. Normal checkout promotion refuses generated merge identity
  before the stable PR. A plan cannot declare a cutover into existence.
- `functional_evidence`: `receipt`, `registry`, `context`, `check_report`, `rendered`, `manifest` paths (absolute on the
  execution host, or relative to the plan), and `receipt_id`. The signed STARTUP-04 v2 functional
  PASS must bind C/D and S, match the retained report/context and existing trust registry, and pass
  freshness, revocation, signature, config/test/vault/schema and migration checks. Deploy/PG smoke
  alone cannot substitute for functional observations. The retained P2 render and ChannelManifest
  must reconstruct the report's candidate identity for exact C/D; a valid signed receipt for
  another source or another approved receipt cannot use this plan's baseline transition.
- `approval`: a human `operator` identity and `plan_digest`. The read-only admission command's
  `--approval-digest` hashes the entire reviewed narrative and the four input fields above. The
  human records this digest and ticks all acknowledgments after review; the renderer never grants
  approval. Editing reviewed code/config/migration/risk narrative or inputs invalidates approval.
- `execution`: initially empty; after protected PR merge records only `pull_request` (number) and
  `stable_sha` M. The consumer independently checks same repository, stable base, C head, merge M,
  M's parents exactly `[S, C]`, unchanged tree, required protection and unchanged TEST/stable refs.
  This output is excluded from the approval digest because it cannot change the approved inputs.

M authorizes the protected stable transition only. The physical deployment remains source C and
qualified digest D; no M image or runtime version is implicitly tested. The existing deploy script,
Make producer and native host adapter forward the same plan and fail before secrets/effects when
admission is absent. After merge, the STARTUP validator may retain signed S only by re-authenticating
this exact approved S→M transition and immutable local Git objects. The caller cannot select S.
The v2 receipt shape, signature and trust strength do not change.

Append observed execution, verification and recovery narrative after one
`<!-- promotion-outcomes -->` marker. This output area is excluded from approval and grants no
admission authority. All required sections and the unique evidence block must precede it.
The execution fields remain independently checked even when outcome text is present.

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
