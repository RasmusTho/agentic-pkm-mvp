---
name: promote-to-test
description: "Staged workflow: move a candidate commit into the isolated test channel, run test-scoped prepare → execute → verify, and produce a durable test verification receipt. Required before promote-test-to-prod."
---

# Promote to Test

Use this skill to advance a candidate commit into the **test channel** before considering prod promotion. This is the mandatory first stage of the normal promotion path.

Read `docs/RELEASE_CHANNELS/README.md` (§Current direction: prod baseline before promotion hardening and §Channel model) and `docs/ENVIRONMENTS.md` (§Code vs Environment Separation) before running. Those docs define the channel model this skill consumes.

Do not use this skill to:
- promote directly to prod (use `promote-test-to-prod` after this skill succeeds)
- verify prod health (use `verify-promotion` on the prod channel)
- roll back a failed prod promotion (use `rollback-promotion`)

## Purpose in the staged workflow

```
candidate commit
  └─► promote-to-test ──► test verification receipt
                               └─► promote-test-to-prod ──► prod stable
```

`promote-to-test` is the gate that produces the evidence `promote-test-to-prod` requires. No test receipt → no prod promotion (except the explicit emergency bypass; see §Emergency bypass).

## Channel identity for the test promotion

Before executing any step, confirm all four bindings are correct:

| Binding | Required value |
| --- | --- |
| Compose file | `docker-compose.yaml:docker-compose.test.yml` |
| Compose project | `pkm-test` (not `pkm-prod`, not default) |
| `PKM_ENVIRONMENT` | `test` |
| Vault root | `TEST_VAULT_ROOT` (never the real prod vault path) |
| Postgres port | `15434` |
| DB name | `app_test` |
| Runtime artifacts | `tmp-test/` |

**Fail-closed rule:** if any binding does not match, abort immediately with a clear error. Do not proceed on a partial or ambiguous channel configuration.

## What this skill does

1. **Channel isolation preflight.** Confirm the compose project is `pkm-test`, `PKM_ENVIRONMENT` resolves to `test`, the vault root is not the prod vault, and the DB is `app_test` (port 15434). Abort if any check fails.

2. **Candidate ref confirmation.** Confirm the candidate commit is resolvable and is the intended ref for test promotion. Record it as `test-candidate` in the receipt.

3. **Test checkout.** Verify the test promotion is running from a worktree or checkout pinned to the candidate ref, not the prod checkout. The prod process must not be affected.

4. **Test-scoped prepare.** Run the equivalent of `prepare-promotion` scoped to the test channel:
   - Diff the candidate commit against the current test baseline (last test-promoted commit or `main~1` as appropriate).
   - Enumerate migrations not yet applied to `app_test`.
   - Classify each migration as reversible or forward-only (per `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`).
   - Produce a test promotion plan at `ops/test-promotions/YYYY-MM-DD-<short-sha>.md`.

5. **Test-scoped execute.** Apply migrations to `app_test` (port 15434). Restart the test compose stack (`make test-down && make test-up`). Before restarting, confirm `docker-compose.test.yml` declares `PKM_ENVIRONMENT: test` for all services (api, worker, watcher) — this is enforced by `tests/ops/test_release_channel_isolation.py::test_test_compose_does_not_declare_prod_environment`. If the compose file declares `prod` instead, abort and fix the compose contract before proceeding. Record the test execution receipt in the plan file.

6. **Test-scoped verify.** Verify directly against the test channel — do NOT call the `verify-promotion` skill, which is prod-scoped and will fail or produce a wrong result when run against a `PKM_ENVIRONMENT=test` stack:
   - Confirm `PKM_ENVIRONMENT=test` is active in the running containers (`docker compose -p pkm-test exec api env | grep PKM_ENVIRONMENT`).
   - Confirm vault root is `TEST_VAULT_ROOT`, not the prod vault path.
   - Confirm Postgres test container is healthy on port 15434 (`app_test` DB).
   - Run `python -m app.cli status` against the test API base URL (e.g. `http://localhost:18002`).
   - Run the repo smoke gate with test-channel environment variables.
   - Confirm watcher heartbeat in test artifacts (`tmp-test/`).

7. **Durable test verification receipt.** On PASS, append a receipt to the plan file:
   ```
   Test verification receipt:
     candidate: <sha>
     channel: test (pkm-test, app_test, PKM_ENVIRONMENT=test)
     vault: <TEST_VAULT_ROOT>
     timestamp: <ISO-8601>
     checks: [channel-isolation, migrations, status, smoke, watcher-heartbeat]
     outcome: PASS
   ```
   This receipt is the required input to `promote-test-to-prod`.

8. **On FAIL.** Reverse applied reversible migrations against `app_test`. Restart test stack to a clean state. Do not produce a PASS receipt. Report the failing check clearly.

## CI/UAT as substitute for a live test run

CI and scripted UAT can satisfy the verification function of this skill **only when**:
- They ran against an isolated `test`-equivalent runtime (separate DB, separate vault, `PKM_ENVIRONMENT=test`).
- They produced a durable machine-readable receipt that names the candidate SHA, the channel config, and the passing check suite.
- The receipt is co-located with, or linked from, `ops/test-promotions/`.

If these conditions are met, step 6 may be replaced by referencing the CI/UAT receipt instead of re-running verification locally. The receipt must still be committed and linked in the test promotion plan.

## Emergency bypass (direct dev→prod)

Direct dev→prod is **not the default path** and must not be used for normal promotions.

If an emergency or hotfix requires bypassing the test stage, the operator must:
1. Explicitly invoke `promote-test-to-prod` with `--bypass-test-receipt`.
2. Provide a written risk note explaining why the test stage was skipped.
3. Acknowledge that the promotion is unverified in test.
4. The bypass produces a **risk receipt** (not a verification receipt) that is permanently attached to the prod promotion plan.

The bypass receipt does not grant immunity from rollback requirements. If verify-promotion fails after a bypassed promotion, rollback is still mandatory.

## Pre-conditions

- `docs/RELEASE_CHANNELS/README.md` is current on the branch being promoted.
- The test compose stack is not running a separate unrelated test job (check for lease conflicts).
- The candidate commit resolves cleanly.

## Operator steps

```bash
# From a test-scoped worktree (not the prod checkout):
promote-to-test --candidate <sha-or-ref>

# On PASS, the receipt is at:
#   ops/test-promotions/YYYY-MM-DD-<short-sha>.md
# Hand that path to promote-test-to-prod.
```

## Key constraints

- Never run against the prod vault, prod DB, or prod compose project.
- Never produce a PASS receipt if any verification step failed.
- Never promote a ref to test and prod in a single step; these are always two separate operations.
- The test channel rollback follows the same rules as prod rollback but targets `app_test` only. The real vault is never touched regardless of channel.

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/README.md` — channel model and invariants
2. `docs/ENVIRONMENTS.md` — environment binding rules
3. `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` — plan shape
4. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — migration safety
5. `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` — rollback posture

## Routing

- Precedes: `promote-test-to-prod` (pass it the plan path with the test verification receipt)
- On FAIL: reverse test migrations, do not produce PASS receipt, report failure
- Does not call `rollback-promotion` (that skill is prod-scoped); reverse test migrations directly
