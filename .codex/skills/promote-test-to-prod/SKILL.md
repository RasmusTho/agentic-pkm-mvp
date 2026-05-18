---
name: promote-test-to-prod
description: "Staged workflow: promote a test-verified candidate commit to prod/stable. Requires a durable test verification receipt from promote-to-test (or an explicit emergency bypass receipt). Orchestrates the standard prepare → execute → verify → (rollback on failure) sequence against the prod channel."
---

# Promote Test to Prod

Use this skill to advance a **test-verified** candidate commit to the prod channel. This is the second and final stage of the normal promotion path.

Read `docs/RELEASE_CHANNELS/README.md` (§Current direction, §Promotion contract, §Channel model) and `docs/ENVIRONMENTS.md` (§Code vs Environment Separation) before running.

Do not use this skill to:
- promote to the test channel (use `promote-to-test` first)
- verify prod health in isolation (use `verify-promotion`)
- roll back a failed prod promotion (use `rollback-promotion`)

## Purpose in the staged workflow

```
candidate commit
  └─► promote-to-test ──► test verification receipt (required)
                               └─► promote-test-to-prod ──► prod stable
```

This skill is a wrapper that gates the standard `prepare-promotion → execute-promotion → verify-promotion` sequence behind a required test evidence check.

## Required evidence before prod promotion

One of two evidence forms must be present before this skill proceeds:

**Normal path — test verification receipt:**
- A PASS receipt from `promote-to-test` for the same candidate SHA, at `ops/test-promotions/YYYY-MM-DD-<short-sha>.md`.
- The receipt must name: candidate SHA, `channel: test`, `outcome: PASS`, and a timestamp.
- The candidate SHA in the receipt must match the SHA being promoted to prod.

**Emergency bypass path — bypass receipt:**
- Operator invokes with `--bypass-test-receipt`.
- Operator supplies a written risk note (stored in `ops/test-promotions/YYYY-MM-DD-<short-sha>-bypass.md`):
  - Why the test stage was skipped.
  - What risk the operator is accepting.
  - Operator sign-off (name or identity token).
- The bypass receipt is permanently attached to the prod promotion plan.
- **Direct dev→prod via bypass is not the default path.** It is reserved for genuine emergencies (critical hotfix, production outage recovery). Every bypass is a permanent audit artifact.

If neither form is present, this skill aborts with:
```
ABORT: no test verification receipt found for candidate <sha>.
Run promote-to-test first, or invoke with --bypass-test-receipt and supply a risk note.
```

## Channel isolation preflight

Before any prod mutation, confirm all four prod bindings are correct:

| Binding | Required value |
| --- | --- |
| Compose file | `docker-compose.yaml:docker-compose.prod.yml` |
| Compose project | `pkm-prod` (not `pkm-test`, not default) |
| `PKM_ENVIRONMENT` | `prod` |
| Vault root | Operator-supplied real vault path (never `vault-test/` or `vault-dev/`) |
| Postgres port | `15432` |
| DB name | `app` |
| Runtime artifacts | `tmp/` |

**Fail-closed rule:** if any binding does not match, abort immediately. Do not proceed on a partial or ambiguous prod channel configuration.

## What this skill does

1. **Evidence check.** Confirm a test verification receipt (or emergency bypass receipt) exists for the candidate SHA. Abort if neither is present.

2. **Channel isolation preflight.** Confirm all prod bindings (above). Abort if any fails.

3. **Prod-scoped prepare.** Invoke `prepare-promotion` for the prod channel:
   - Diffs the candidate commit against the current `stable` ref.
   - Enumerates migrations not yet applied to `app` (prod DB, port 15432).
   - Classifies each migration as reversible or forward-only.
   - Links the test verification receipt (or bypass receipt) in the plan under a `Test evidence` section.
   - Produces the prod promotion plan at `ops/promotions/YYYY-MM-DD-<short-sha>.md`.
   - Pauses for operator review and acknowledgement of forward-only migrations.

4. **Operator acknowledgement.** The operator reviews and ticks all checkboxes in the prod promotion plan. This skill does not auto-proceed past the plan review gate.

5. **Prod-scoped execute.** Invoke `execute-promotion` with the acknowledged plan:
   - Records `stable-prev` before moving anything.
   - Moves the `stable` ref to the candidate SHA.
   - Applies migrations to `app` (port 15432).
   - Restarts the prod process (`make prod-start-full VAULT_ROOT=<path>`).

6. **Prod-scoped verify.** Invoke `verify-promotion` against the prod channel:
   - Confirms `PKM_ENVIRONMENT=prod`, vault=real vault, DB=`app`.
   - Runs all seven checks from `verify-promotion`.
   - On PASS: appends the promotion acceptance receipt to the prod plan.

7. **On FAIL.** Invoke `rollback-promotion`:
   - Reverses reversible migrations on `app`.
   - Restores `stable` to `stable-prev`.
   - Restarts prod.
   - Calls `verify-promotion` again. If still FAIL: escalate to operator, do not loop.

## Evidence handoff

The prod promotion plan (`ops/promotions/YYYY-MM-DD-<short-sha>.md`) links both:
- The test verification receipt (or bypass receipt) as pre-promotion evidence.
- The post-promotion `verify-promotion` receipt as post-promotion acceptance.

This is the capability-level validation evidence referenced by `docs/RELEASE_CHANNELS/README.md §Validation / acceptance path`.

## What prod promotion does NOT do

- Does not rewind the real vault. (See `docs/RELEASE_CHANNELS/README.md §Vault is not release state`.)
- Does not affect the test channel. The test DB (`app_test`) and test vault (`vault-test/`) are untouched.
- Does not reverse forward-only migrations on rollback. These were acknowledged by the operator.
- Does not undo external side-effects.

## Operator steps

```bash
# Normal path — after promote-to-test produced a PASS receipt:
promote-test-to-prod \
  --candidate <sha> \
  --test-receipt ops/test-promotions/YYYY-MM-DD-<short-sha>.md

# Emergency bypass — when test stage cannot be run:
promote-test-to-prod \
  --candidate <sha> \
  --bypass-test-receipt \
  --risk-note "Critical hotfix for <incident>; test stage skipped; operator: <name>"
```

## Key constraints

- Never move `stable` without a test receipt or an explicit bypass receipt.
- Always record `stable-prev` before moving `stable`.
- Always call `verify-promotion` after `execute-promotion` — whether bypass or normal path.
- Never bypass the test stage without a written, stored risk note.
- Never use the test checkout, test DB, or test vault for prod operations.

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/README.md` — channel model, invariants, vault-is-not-release-state
2. `docs/ENVIRONMENTS.md` — environment binding rules
3. `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` — prod promotion plan shape
4. `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` — rollback posture and limits
5. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — migration safety

## Routing

- Requires: `promote-to-test` (PASS receipt) or operator emergency bypass receipt
- Calls: `prepare-promotion → execute-promotion → verify-promotion`
- On verify FAIL: calls `rollback-promotion → verify-promotion`
- On rollback verify FAIL: escalates to operator; does not loop
