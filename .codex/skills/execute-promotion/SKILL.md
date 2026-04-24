---
name: execute-promotion
description: "Execute a reviewed promotion plan: move the stable ref, apply migrations to the prod DB, and restart the prod process from the updated checkout. Requires a complete, operator-acknowledged promotion plan from prepare-promotion."
---

# Execute Promotion

Use this skill only after `prepare-promotion` has produced a complete plan and the operator has reviewed and ticked all acknowledgment checkboxes.

Do not use this skill to:
- produce the promotion plan (use `prepare-promotion`)
- verify that prod is healthy after execution (use `verify-promotion`)
- roll back a failed promotion (use `rollback-promotion`)

## Capability boundary

Read `docs/RELEASE_CHANNELS/README.md` (Promotion contract) and `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` before running. The plan is the contract. If the plan is incomplete or has un-ticked acknowledgment checkboxes, abort.

## What this skill does

1. Reads the promotion plan at the path provided by the operator (output of `prepare-promotion`).
2. Validates the plan: all seven required sections present, all operator acknowledgment checkboxes ticked. Abort if validation fails.
3. Records the current `stable` ref as `stable-prev` (annotated tag or pointer file in `ops/promotions/`) before moving anything.
4. Moves the `stable` ref to the promotion target commit (`git tag -f stable <target-sha>` or equivalent).
5. Updates the prod checkout's HEAD to the new `stable` (`git -C <prod-checkout> fetch && git -C <prod-checkout> checkout stable`).
6. Applies reversible migrations to the prod DB (port 15432) in forward order. Applies forward-only migrations only after confirming the operator acknowledged them in the plan. Stops and calls for rollback if any migration fails.
7. Restarts the prod process (`make prod-down && make prod-up` or equivalent).
8. Appends the promotion execution receipt to the plan file: timestamp, operator, which ref moved, which migrations applied, process restart confirmation.
9. Reports to the operator: "Promotion executed. Run verify-promotion to confirm health."

## Pre-conditions

- A complete promotion plan produced by `prepare-promotion` exists and all operator acknowledgments are ticked.
- The prod Postgres container is running (`make prod-up` healthy).
- The prod checkout (separate worktree, per `DEFINE_CONCURRENCY_RULE`) is available.
- `git tag stable` resolves to the current prod commit.

## Operator steps

```
# After reviewing and ticking all checkboxes in the plan:
execute-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md

# Then verify:
verify-promotion
```

## Failure handling

- If plan validation fails: abort, report the missing section or un-ticked checkbox. Do not move `stable`.
- If `stable-prev` recording fails: abort. Moving `stable` before recording the previous ref makes rollback ambiguous.
- If a migration fails: stop immediately, do not apply subsequent migrations. Report which migration failed. Call `rollback-promotion`.
- If process restart fails: the ref has moved and some migrations may be applied. Report the partial state explicitly. Call `rollback-promotion` — the operator must decide whether rollback is safe given any forward-only migrations already applied.

## Key constraints

- Never execute without a complete, operator-acknowledged plan.
- Always record `stable-prev` before moving `stable`. This is the rollback anchor.
- Never skip a migration that the plan lists. Never apply a migration the plan does not list.
- Never use the dev checkout for prod operations — separate worktrees per `DEFINE_CONCURRENCY_RULE`.

## Authority order for decisions

1. The promotion plan produced by `prepare-promotion` — the immediate contract
2. `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` — plan shape
3. `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` — failure and rollback posture
4. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — migration safety
5. `docs/RELEASE_CHANNELS/README.md` — invariants

## Routing

- Produced by: `prepare-promotion`
- On success → `verify-promotion`
- On failure → `rollback-promotion`
