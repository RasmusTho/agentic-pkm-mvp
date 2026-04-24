---
name: rollback-promotion
description: "Roll prod back to the previous stable ref: restore the stable pointer, reverse reversible migrations on the prod DB, and restart the prod process. Call verify-promotion after completion."
---

# Rollback Promotion

Use this skill when `execute-promotion` fails or when `verify-promotion` returns FAIL after a promotion. Its job is to return prod to the last known-good state as defined by the rollback contract.

Do not use this skill to:
- produce the promotion plan (use `prepare-promotion`)
- execute a new promotion (use `execute-promotion`)
- verify health after rollback (use `verify-promotion` — always call it after rollback)

## Capability boundary

Read `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` before running. That document is the authority for what rollback restores and what it cannot restore. Key limits stated there:

- **Vault is not rewound.** The real vault is never touched by rollback.
- **Forward-only migrations are not reversed.** If the promotion applied forward-only migrations and they succeeded, the DB schema may not return to its pre-promotion shape. This was acknowledged by the operator at promotion time.
- **External side-effects are not reversed.** Anything triggered outside the channel boundary is out of scope.

## What this skill does

1. Reads the promotion plan (`ops/promotions/YYYY-MM-DD-<short-sha>.md`) to determine: the previous `stable` ref (`stable-prev`), the migration delta, and which migrations were applied before the failure.
2. Confirms `stable-prev` is resolvable and is different from the current `stable`. Abort if not — the rollback anchor is missing and operator intervention is required.
3. Reverses applied reversible migrations against the prod DB (port 15432) in reverse order. Skips forward-only migrations with an explicit log entry: "forward-only migration X was applied; reversal not available per classification."
4. Moves `stable` back to `stable-prev`.
5. Updates the prod checkout's HEAD to `stable-prev`.
6. Restarts the prod process (`make prod-down && make prod-up`).
7. Appends the rollback receipt to the promotion plan file: timestamp, which ref was restored, which migrations were reversed, which were skipped (forward-only), process restart confirmation.
8. Reports to the operator: "Rollback complete. Run verify-promotion."

## Pre-conditions

- A promotion plan file exists with a recorded `stable-prev` and migration delta.
- `stable-prev` resolves to a valid commit.
- The prod Postgres container is running or can be started.

## Operator steps

```
rollback-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md

# Always verify after rollback:
verify-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md
```

## Failure handling

- If `stable-prev` is missing or ambiguous: **abort and escalate to the operator**. Do not guess at a rollback target. The operator must identify the correct previous ref manually.
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

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` — what rollback restores and what it does not
2. The promotion plan file — which migrations were applied and in what order
3. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — which migrations can be reversed
4. `docs/RELEASE_CHANNELS/README.md` — invariants

## Routing

- Called after: `execute-promotion` failure, or `verify-promotion` FAIL post-promotion
- After completion → always call `verify-promotion`
- If verify fails after rollback → escalate to operator; do not loop
