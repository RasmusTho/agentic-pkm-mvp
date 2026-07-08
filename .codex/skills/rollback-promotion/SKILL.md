---
name: rollback-promotion
description: "Roll prod back: in checkout mode merge the governed rollback PR, update prod to the merged origin/stable head, reverse reversible migrations, and restart; in pinned-image mode bump back to the previous-good pin through scripts/deploy_channel.sh. Call verify-promotion after completion."
---

# Rollback Promotion

> **Status: describes the TARGET gated-`stable` model (deferred promotion hardening).** Prod
> currently tracks `main` directly per `docs/RELEASE_CHANNELS/README.md §Promotion model` and
> [ADR-0040](../../../docs/adr/ADR-0040-prod-promotion-ref-main-interim.md); `origin/stable` is
> **dormant** and is not an ancestor of `origin/main`. A revert PR against dormant `stable` is not
> meaningful under the current baseline — confirm with the operator before invoking.

Use this skill when `execute-promotion` fails or when `verify-promotion` returns FAIL after a promotion. Its job is to return prod to the last known-good state as defined by the rollback contract.

Do not use this skill to:
- produce the promotion plan (use `prepare-promotion`)
- execute a new promotion (use `execute-promotion`)
- verify health after rollback (use `verify-promotion` — always call it after rollback)

## Capability boundary

Read `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` before running. That document is the authority for what rollback restores and what it cannot restore. Key limits stated there:
Rollback execution is Builder System boundary work. Rollback PRs and receipts are Builder System
governance artifacts; runtime refs, migrations, and channel state are Product/Runtime effects. Route
owner-doc, SBS, transition-debt, and fitness-rule consequences through
`docs/architecture/SBS_OPERATING_MODEL.md`, and do not treat rollback evidence as runtime/user memory.

- **Vault is not rewound.** The real vault is never touched by rollback.
- **Forward-only migrations are not reversed.** If the promotion applied forward-only migrations and they succeeded, the DB schema may not return to its pre-promotion shape. This was acknowledged by the operator at promotion time.
- **External side-effects are not reversed.** Anything triggered outside the channel boundary is out of scope.

## Stable-branch protection and PR-based rollback

`origin/stable` is a **protected branch** (`enforce_admins: true`; required status checks: `smoke`, `smoke-docker`, `pr-contract`; PR required). Direct pushes and refs-API updates to `stable` are rejected by GitHub.

Rolling back therefore follows the same governed-PR path as a promotion:

1. Create a revert PR from the promotion commit's parent (or a rollback branch pinned to `stable-prev`) targeting `stable`.
2. The revert PR must pass all three required status checks: `smoke`, `smoke-docker`, `pr-contract`.
3. An operator reviews and merges the revert PR. The merge creates the protected rollback head on `origin/stable`.
4. Keep the prod checkout on the failed promotion commit while reversible migration
   downgrades run, so the migration files added by that promotion remain available
   from `app/alembic`. Do not check out the merged rollback commit before reversal.
5. After reversible migration downgrades complete, fetch `origin/stable` and update the
   prod checkout to the merged rollback commit before process restart.
6. Record both `stable-prev` (the rollback target/anchor), the failed promotion checkout
   used for migration reversal, and the merged `origin/stable` SHA in the rollback receipt.

**This skill never directly writes to the protected `stable` branch.** A direct push or force-push to `stable` is not permitted and is not the rollback path.

## Deployment model

Before rollback, resolve the prod channel's deployment model:

- **Checkout model (interim / no-dead-window):** the channel remains on the checkout model until a
  cutover receipt exists for prod: a fleet-model fitness PASS recorded at
  `ops/deployments/prod-latest.json`. In this mode, keep the existing governed rollback PR,
  migration reversal from the failed promotion checkout, checkout update, and `make prod-start-full`
  restart procedure.
- **Pinned-image model (post-cutover):** once the cutover receipt exists, rollback physical
  execution is a pin bump to the previous-good image tag plus recreate. Use the previous-good tag
  recorded in the promotion plan or deploy receipt and run:

  ```bash
  scripts/deploy_channel.sh prod <previous-good-sha>
  ```

  The script owns the pin bump, recreate, health gates, UI smoke, and rollback/deploy receipt per
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md §Rollback procedure`. No rebuild is performed.
  Forward-only migration caveats remain unchanged and must stay visible to the operator.

## What this skill does

1. Reads the promotion plan (`ops/promotions/YYYY-MM-DD-<short-sha>.md`) to determine: the previous `stable` ref (`stable-prev`), the promotion PR or merge commit, the migration delta, and which migrations were applied before the failure.
2. Resolves the deployment model for `prod` using the rule above and records it in the rollback receipt.

**Checkout model (interim / no-dead-window):**

3. Confirms `stable-prev` is resolvable and is different from the current `stable`. Abort if not — the rollback anchor is missing and operator intervention is required.
4. Opens a revert PR targeting `stable` (reverting the promotion merge commit, or targeting `stable-prev` via a rollback branch). Records the revert PR URL. Waits for required status checks to pass per `_shared/CI_WAIT_CONTRACT.md`, then waits for the operator to merge.
5. Fetches `origin/stable` after the revert PR merges and records the merged rollback
   commit SHA, but keeps the prod checkout on the failed promotion commit while
   migration reversal runs.
6. Reverses applied reversible migrations against the prod DB (port 15432) in
   reverse order from the failed promotion checkout, where the authored migration
   files and reverse steps still exist. Skips forward-only migrations with an
   explicit log entry: "forward-only migration X was applied; reversal not
   available per classification."
7. Updates the prod checkout to the merged rollback `origin/stable` head after
   reversible migration reversal completes. `stable-prev` remains the rollback
   target/anchor; it is not the final detached prod checkout when branch protection
   creates a merge commit.
8. Restarts the prod process with `make prod-start-full` — the canonical prod startup that enforces all four prod runtime-binding elements (compose overlay, `pkm-prod` project namespace, `PKM_ENVIRONMENT=prod`, and the `.env.prod.local`-resolved vault root) per `docs/RELEASE_CHANNELS/README.md §Prod runtime binding`. Do not use separate down/up Make targets — a bare up target alone does not enforce the full binding.

**Pinned-image model (post-cutover):**

9. Confirms the previous-good SHA/tag from the promotion plan or deploy receipt is resolvable and is different from the failed deployed SHA.
10. Applies only reversible migration reversal that the rollback contract allows; forward-only migrations remain an explicit operator caveat.
11. Runs `scripts/deploy_channel.sh prod <previous-good-sha>` to bump the prod pin back and recreate the channel. This script is the only physical rollback deploy step in pinned-image mode.
12. Reads and records the resulting receipt at `ops/deployments/prod-latest.json`.

13. Appends the rollback receipt to the promotion plan file: timestamp, deployment model, revert PR
   URL, `stable-prev` rollback target, failed promotion checkout used for migration
   reversal when applicable, merged `origin/stable` rollback commit or deploy receipt path, which migrations were reversed,
   which were skipped (forward-only), process restart confirmation.
14. Reports to the operator: "Rollback complete. Run verify-promotion."

## Pre-conditions

- A promotion plan file exists with a recorded `stable-prev` and migration delta.
- `stable-prev` resolves to a valid commit.
- The prod Postgres container is running or can be started.

## Operator steps

The `rollback-promotion ...` and `verify-promotion` commands below are skill invocations, not installed shell binaries — they name the skills' entry contracts and arguments.

```
rollback-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md

# Always verify after rollback:
verify-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md
```

## Failure handling

- If `stable-prev` is missing or ambiguous: **abort and escalate to the operator**. Do not guess at a rollback target. The operator must identify the correct previous ref manually.
- If the revert PR cannot be opened, its required checks fail, or the merged rollback commit cannot be fetched from `origin/stable`: report the check/status/ref state and escalate. Do not proceed to migration reversal or restart until the protected rollback head is known.
- If a reversible migration reversal fails: stop, report which step failed and the current DB state. Do not continue reversing subsequent migrations. Escalate to the operator for manual DB triage.
- If process restart fails after rollback: report the state explicitly — ref is restored, migrations are (partially) reversed, process is not running. Operator must start it manually.
- If `verify-promotion` returns FAIL after rollback: do **not** attempt a second automated rollback. Escalate immediately.

## What rollback does NOT do

Per `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`:

- Does not rewind the real vault (authored content is never touched).
- Does not reverse forward-only migrations (acknowledged at promotion time).
- Does not undo external side-effects (emails sent, external API calls, etc.).
- Does not restore runtime artifacts to a pre-promotion snapshot (`tmp/` is regenerated, not restored).

The operator must have acknowledged these limits at promotion time via the operator acknowledgment checkboxes in the plan.

## Key constraints

- Always call `verify-promotion` after rollback completes — rollback is not accepted until verification passes.
- Always append the rollback receipt to the promotion plan file — it is evidence for the parent feature issue.
- Never attempt to reverse a forward-only migration. Log it and move on.
- Never roll back without a resolved `stable-prev` anchor.
- Never reverse prod migrations before the protected rollback PR has merged and the merged `origin/stable` rollback commit has been fetched and recorded.
- Never update the prod checkout to the merged rollback commit before reversible migration reversal runs; the reversal uses the failed promotion checkout so newly added migration files remain available.
- Never directly push or force-push to `stable`. The governed revert PR is the only permitted path for restoring the protected branch.
- In pinned-image mode, never use checkout update/restart as the physical rollback. Roll back the
  channel by running `scripts/deploy_channel.sh` against the previous-good SHA/tag.

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` — what rollback restores and what it does not
2. The promotion plan file — which migrations were applied and in what order
3. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — which migrations can be reversed
4. `docs/RELEASE_CHANNELS/README.md` — invariants

## Routing

- Called after: `execute-promotion` failure, or `verify-promotion` FAIL post-promotion
- After completion → always call `verify-promotion`
- If verify fails after rollback → escalate to operator; do not loop
