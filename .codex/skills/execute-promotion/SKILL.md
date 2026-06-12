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

## Stable-branch protection and PR-based advancement

`origin/stable` is a **protected branch** (`enforce_admins: true`; required status checks: `smoke`, `smoke-docker`, `pr-contract`; PR required). Direct pushes and refs-API updates to `stable` are rejected by GitHub.

Every stable-ref advancement therefore proceeds through a **governed PR targeting `stable`**, not a direct push or annotated-tag force-push:

1. Create a PR from the candidate commit branch (or a release-integration branch) targeting `stable`.
2. The PR must pass all three required status checks: `smoke`, `smoke-docker`, `pr-contract`.
3. An operator reviews and merges the PR. The merge commit becomes the new `stable` HEAD.
4. After merge, record the new `stable` SHA in the promotion receipt as the executed ref.

Never introduce a direct protected-branch ref mutation as the normal promotion path.

## Ancestry preflight (fail-closed)

Before any stable-ref movement, verify that the current `stable` is an ancestor of the promotion candidate:

```bash
git fetch origin
git merge-base --is-ancestor origin/stable <candidate-sha>
```

- **If the check passes (exit 0):** proceed with the promotion PR.
- **If the check fails (exit non-zero):** abort immediately. Report:

  ```
  ABORT: origin/stable is not an ancestor of <candidate-sha>.
  stable/main divergence detected. A reconciliation PR is required before promotion can proceed.
  Steps:
    1. Open a PR from stable into main (or an integration branch) to reconcile the divergence.
    2. Have that PR reviewed, checked, and merged.
    3. Re-run execute-promotion after the reconciliation PR has merged.
  Do not proceed until git merge-base --is-ancestor origin/stable origin/main returns exit 0.
  ```

This preflight is **fail-closed**: if stable is not an ancestor of the candidate, no part of execute-promotion continues. The reconciliation PR must be merged and the ancestry check must pass before promotion resumes.

## What this skill does

1. Reads the promotion plan at the path provided by the operator (output of `prepare-promotion`).
2. Validates the plan: every required section from the promotion plan contract present, all operator acknowledgment checkboxes ticked. Abort if validation fails.
3. **Ancestry preflight**: runs `git merge-base --is-ancestor origin/stable <candidate-sha>`. Aborts with reconciliation-PR instruction if it fails.
4. Records the current `stable` ref as `stable-prev` (pointer file in `ops/promotions/`) before moving anything.
5. Opens a governed PR targeting `stable` from the candidate branch. Waits for required status checks (`smoke`, `smoke-docker`, `pr-contract`) to pass and operator to merge. Records the merged PR URL in the promotion receipt.
6. Updates the prod checkout's HEAD to the new `stable` (`git -C <prod-checkout> fetch && git -C <prod-checkout> checkout stable`).
7. Applies reversible migrations to the prod DB (port 15432) in forward order. Applies forward-only migrations only after confirming the operator acknowledged them in the plan. Stops and calls for rollback if any migration fails.
8. Restarts the prod process (`make prod-down && make prod-up` or equivalent).
9. Appends the promotion execution receipt to the plan file: timestamp, operator, merged PR URL, which ref moved, which migrations applied, process restart confirmation.
10. Reports to the operator: "Promotion executed. Run verify-promotion to confirm health."

## Pre-conditions

- A complete promotion plan produced by `prepare-promotion` exists and all operator acknowledgments are ticked.
- `git merge-base --is-ancestor origin/stable <candidate-sha>` passes (ancestry preflight; see above).
- The prod Postgres container is running (`make prod-up` healthy).
- The prod checkout (separate worktree, per `DEFINE_CONCURRENCY_RULE`) is available.
- `origin/stable` resolves to the current prod commit.

## Operator steps

The `execute-promotion ...` and `verify-promotion` commands below are skill invocations, not installed shell binaries — they name the skills' entry contracts and arguments.

```
# After reviewing and ticking all checkboxes in the plan:
execute-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md

# Then verify:
verify-promotion
```

## Failure handling

- If plan validation fails: abort, report the missing section or un-ticked checkbox. Do not open the stable PR.
- If ancestry preflight fails: abort with the reconciliation-PR instruction. Do not open the stable PR.
- If `stable-prev` recording fails: abort. Moving `stable` before recording the previous ref makes rollback ambiguous.
- If the stable PR cannot be opened or its required checks fail: report the check status. Do not proceed to migration or restart.
- If a migration fails: stop immediately, do not apply subsequent migrations. Report which migration failed. Call `rollback-promotion`.
- If process restart fails: the ref has moved and some migrations may be applied. Report the partial state explicitly. Call `rollback-promotion` — the operator must decide whether rollback is safe given any forward-only migrations already applied.

## Key constraints

- Never execute without a complete, operator-acknowledged plan.
- Always run the ancestry preflight (`git merge-base --is-ancestor`) before any stable movement. Fail closed if it does not pass.
- Always record `stable-prev` before opening the stable PR. This is the rollback anchor.
- Never skip a migration that the plan lists. Never apply a migration the plan does not list.
- Never use the dev checkout for prod operations — separate worktrees per `DEFINE_CONCURRENCY_RULE`.
- Never directly push or force-push to `stable`. The governed PR is the only permitted path for advancing the protected branch.

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
