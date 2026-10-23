---
name: promote-to-test
description: "Staged workflow: move a candidate commit into the isolated test channel, run test-scoped prepare → execute → verify, and produce a durable test verification receipt. Required before promote-test-to-prod."
---

# Promote to Test

> **Status: current source promotion policy (ADR-0068 D4, Issue #6228).**
> `stable` is the production promotion authority. Normal advancement requires the exact current
> `test` candidate C, trusted green TEST evidence, a durable functional PASS, and explicit approval
> of the concrete plan. Protected merge M records stable authority; it does not qualify a new
> source version or image. Production deploys the tested source C and immutable digest D.
> Repository support does not establish a running-prod observation or physical cutover. Current
> infrastructure observations belong to `RasmusTho/yggdrasil-infra/CURRENT_STATUS.md`.

Use this skill to advance a candidate commit into the **test channel** before considering prod promotion. This is the mandatory first stage of the normal promotion path.

Read `docs/RELEASE_CHANNELS/README.md` (§Promotion model and §Channel model) and `docs/ENVIRONMENTS.md` (§Code vs Environment Separation) before running. Those docs define the channel model this skill consumes.
This is Builder System boundary work: the skill and receipts are Builder System artifacts, while the
candidate commit may affect Product/Runtime truth. Use
`docs/architecture/SBS_OPERATING_MODEL.md` to keep release evidence, owner-doc writeback, and runtime
authority separate.

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

`promote-to-test` is the gate that produces the evidence `promote-test-to-prod` requires. A green deploy verdict alone does not qualify production; durable functional PASS and exact current TEST eligibility are both required.

## Deployment model

Before executing the test promotion, resolve the test channel's deployment model:

- **Checkout model (interim / no-dead-window):** the channel remains on the checkout model until a
  cutover receipt exists for test: a fleet-model fitness PASS recorded in
  `ops/deployments/test-latest.json`. In this mode, keep the existing test checkout, test-scoped
  migration, and `make test-down && make test-up` execution path. A checkout-only result does not
  qualify immutable image D for production; that image must be the one functionally observed.
- **Pinned-image model (post-cutover):** once the test cutover receipt exists, keep the same
  evidence and test-verification requirements, but route physical execution through
  `scripts/deploy_channel.sh deploy test <candidate-sha> --image-digest <tested-digest>` per
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`. The script owns the pin bump, migration gate,
  recreate, health gates, UI smoke, and deploy receipt. The candidate SHA still comes from the
  governed promotion workflow; the deployment model only changes how the test channel is updated.

## Channel identity for the test promotion

Before executing any step, confirm every binding in the table below is correct:

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

1. **Channel isolation preflight.** Before any stack mutation, invoke the shipped read-only guard against the test checkout's own compose file (never a dev-tree copy — pass the full path, do not rely on cwd):
   ```bash
   python -m app.release_channels.channel_isolation_preflight <test-checkout>/docker-compose.test.yml test
   ```
   This fail-closes when the compose overlay's effective env bindings (`PKM_ENVIRONMENT`, `DATABASE_URL`, `DB_DSN`) do not resolve to the test channel (`docs/RELEASE_CHANNELS/README.md §Compose/env binding invariant`). In addition, confirm the compose project is `pkm-test`, the vault root is not the prod vault, and the DB is `app_test` (port 15434). Abort if the guard or any manual check fails.

2. **Candidate ref confirmation.** Resolve the current controller-owned `test` ref and its trusted green DEV/TEST artifacts. C must equal that exact current ref and retain its build-once immutable image D. This skill performs functional validation; it must not independently overwrite the controller-owned test ref. Record C/D and the producer run/attempt/artifact provenance.

3. **Test checkout.** Verify the test promotion is running from a worktree or checkout pinned to the candidate ref, not the prod checkout. The prod process must not be affected.

4. **Test-scoped prepare.** Run the equivalent of `prepare-promotion` scoped to the test channel:
   - Diff the candidate commit against the current test baseline, resolved in this order: (1) the candidate SHA recorded in the latest receipt under `ops/test-promotions/`, if one exists; (2) an operator-supplied baseline ref; (3) the candidate's merge-base with `main` (`git merge-base <candidate> main`) if neither of the above is available.
   - Enumerate migrations not yet applied to `app_test`.
   - Classify each migration as reversible or forward-only (per `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`).
   - Produce a test promotion plan at `ops/test-promotions/YYYY-MM-DD-<short-sha>.md`.

5. **Test-scoped execute.** In checkout model, apply migrations to `app_test` (port 15434) and restart the test compose stack (`make test-down && make test-up`). Before restarting, confirm `docker-compose.test.yml` declares `PKM_ENVIRONMENT: test` for all services (api, worker, watcher) — this is enforced by `tests/ops/test_release_channel_isolation.py::test_test_compose_does_not_declare_prod_environment`. If the compose file declares `prod` instead, abort and fix the compose contract before proceeding. In pinned-image model, run `scripts/deploy_channel.sh deploy test <candidate-sha> --image-digest <tested-digest>` instead of checkout restart and record the deploy receipt at `ops/deployments/test-latest.json`. Record the test execution receipt in the plan file. Do not rebuild or substitute an image with the same source tree.

6. **Test-scoped verify.** Verify directly against the test channel — do NOT call the `verify-promotion` skill, which is prod-scoped and will fail or produce a wrong result when run against a `PKM_ENVIRONMENT=test` stack:
   - Confirm `PKM_ENVIRONMENT=test` is active in the running containers (`docker compose -p pkm-test exec api env | grep PKM_ENVIRONMENT`).
   - Confirm vault root is `TEST_VAULT_ROOT`, not the prod vault path.
   - Confirm `/version` reports C and the running immutable image is D from the retained build provenance and deploy receipt.
   - Confirm Postgres test container is healthy on port 15434 (`app_test` DB).
   - Run `python -m app.cli status` against the test API base URL (e.g. `http://localhost:18002`).
   - Run the repo smoke gate with test-channel environment variables.
   - Confirm watcher heartbeat in test artifacts (`tmp-test/`).

7. **Durable signed test verification receipt.** Bind the actual isolated functional observations
   through the existing STARTUP-04 check-report and terminal-receipt producers described below.
   Retain the signed v2 PASS, exact receipt id, P2 render/ChannelManifest, report, admission context
   with fresh canonical stable S, and existing trust registry outside resettable test roots. Link
   these machine-readable inputs from the test plan and production plan. Append a human summary:
   ```
   Test verification receipt:
     candidate: <sha>
     immutable_image_digest: <D>
     signed_receipt: <path and receipt id>
     channel: test (pkm-test, app_test, PKM_ENVIRONMENT=test)
     vault: <TEST_VAULT_ROOT>
     timestamp: <ISO-8601>
     checks: [channel-isolation, migrations, status, smoke, watcher-heartbeat]
     outcome: PASS
   ```
   The signed evidence is required by `promote-test-to-prod`; this Markdown summary alone is insufficient.

8. **On FAIL.** Do not produce a PASS receipt. Preserve the actual failure evidence and use the documented test roll-forward/rebuild policy. Do not automatically roll back database migrations or move the controller-owned ref.

## CI/UAT as substitute for a live test run

CI and scripted UAT can satisfy the verification function of this skill **only when**:
- They ran against an isolated `test`-equivalent runtime (separate DB, separate vault, `PKM_ENVIRONMENT=test`).
- They produced the signed STARTUP-04 receipt and retained inputs above, naming exact C/D, the channel config, and the passing functional check suite.
- The receipt is co-located with, or linked from, `ops/test-promotions/`.

If these conditions are met, step 6 may be replaced by referencing the CI/UAT receipt instead of re-running verification locally. The receipt must still be stored under `ops/test-promotions/` (local ops storage — the directory is gitignored per the #2081 receipts-are-local policy, so a repo-committed receipt is not expected) and linked in the test promotion plan.

The signed STARTUP-04 producer is `app.release_channels.promotion_receipt`:
`build_promotion_test_check_report` binds observed checks to immutable C and the fresh canonical
stable baseline S; `write_promotion_test_terminal_receipt` (CLI `python -m app.release_channels.promotion_receipt promotion-test-verify`) produces the
existing v2 signed receipt. Retain its P2 render and ChannelManifest, check report, admission context, receipt id and existing trust
registry alongside the test plan and link them from the production plan. Preserve signature,
issuer trust, revocation and freshness requirements. Do not print or copy issuer keys.

A written Markdown PASS, fixtures, native PG checks or trusted green TEST deploy alone do not
substitute for actual isolated functional observations. Source support does not assert that such a
live receipt already exists. Baseline S is read from canonical protected stable by the producer;
a caller cannot select an arbitrary migration baseline. Emergency recovery needs separate explicit
operator authority; the normal promotion guard contains no test-evidence bypass.

## Pre-conditions

- `docs/RELEASE_CHANNELS/README.md` is current on the branch being promoted.
- The test compose stack is not running a separate unrelated test job (check for lease conflicts).
- The candidate commit resolves cleanly.

## Operator steps

The `promote-to-test ...` command below is a skill invocation, not an installed shell binary — it names this skill's entry contract and arguments.

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
- Test failures follow roll-forward/rebuild. Never automatically reverse database migrations or use the real vault for recovery.
- In pinned-image mode, never treat updating a test checkout as deployment; physical execution runs
  through `scripts/deploy_channel.sh deploy test <candidate-sha>`.

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/README.md` — channel model and invariants
2. `docs/ENVIRONMENTS.md` — environment binding rules
3. `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` — plan shape
4. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — migration safety
5. `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md` — rollback posture

## Routing

- Precedes: `promote-test-to-prod` (pass it the plan path with the test verification receipt)
- On FAIL: retain failure evidence and use test-scoped roll-forward/rebuild; do not produce PASS.
- Does not call `rollback-promotion` (that skill is prod-scoped).

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. After PASS, return the durable test
receipt to the calling workflow. Invoke `promote-test-to-prod` only when production promotion is
already authorized and the live release-channel contract permits that route; test-only scope ends
with test verification. On FAIL, complete test-scoped recovery as specified here and preserve its
failure evidence.
