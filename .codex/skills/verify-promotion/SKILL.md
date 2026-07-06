---
name: verify-promotion
description: "Verify that prod is healthy and functionally correct after a promotion or rollback: run health checks, status checks, and smoke assertions against the running prod channel."
---

# Verify Promotion

> **Status: step 1 below describes the TARGET gated-`stable` model (deferred promotion
> hardening).** Prod currently tracks `main` directly per
> `docs/RELEASE_CHANNELS/README.md §Promotion model` and
> [ADR-0040](../../../docs/adr/ADR-0040-prod-promotion-ref-main-interim.md); `origin/stable` is
> **dormant** and is not an ancestor of `origin/main`. Under the current baseline, do **not**
> assert the running prod ref equals `origin/stable` — that false-FAILs a healthy prod and routes
> to a rollback against a dormant, diverged ref. Compare against the current promotion ref
> (`main`) instead; see step 1.

Use this skill immediately after `execute-promotion` succeeds, and again after `rollback-promotion`. Its sole job is to confirm the running prod channel is healthy and report any failures clearly.

Do not use this skill to:
- produce the promotion plan (use `prepare-promotion`)
- execute the promotion (use `execute-promotion`)
- roll back a failed promotion (use `rollback-promotion`)

## Capability boundary

Read `docs/HEALTH.md` before running — it owns the health contract that this skill exercises. The release-channels validation path in `docs/RELEASE_CHANNELS/README.md` (Validation / acceptance path) defines what "accepted" means at the capability level; this skill covers the runtime verification step.

Verifying a promotion is Builder System boundary work: the verification receipt is a Builder System
governance artifact, while prod's health and behavior are Product/Runtime truth. Use
`docs/architecture/SBS_OPERATING_MODEL.md` to route SBS impact, owner-doc writeback, and
fitness-rule evidence without treating the verification receipt itself as runtime memory or
Product truth.

This skill is **prod-scoped**: it verifies the running prod channel only. Do not run it against
the test channel (`promote-to-test` runs its own test-scoped verification directly — see that
skill's §Test-scoped verify — because this skill's checks assume `PKM_ENVIRONMENT=prod`).

## What this skill does

1. Confirms the running prod process's code ref matches the current **promotion ref** per `docs/RELEASE_CHANNELS/README.md §Promotion model` — today that ref is `main` (interim baseline, [ADR-0040](../../../docs/adr/ADR-0040-prod-promotion-ref-main-interim.md)): `git rev-parse origin/main` == reported version in health endpoint or settings-explain output. Under the future gated model this becomes `origin/stable`. Do not compare against `origin/stable` while it remains dormant — it is not an ancestor of `origin/main` and a match against it is not a meaningful health signal today.
2. Confirms the prod Postgres container is healthy (port 15432 responsive, outbox consumer running, no error state in worker heartbeat).
3. Runs `python -m app.cli status` against the prod channel and confirms all components report healthy.
4. Runs `python -m app.cli settings-explain` against the prod channel and confirms the resolved environment is `prod`, the vault root is the real vault, and the DB resolves to the prod DB.
5. Runs the repo smoke gate (`pytest -q -m "not pg and not alpha_llm"`) against prod config if the environment supports it; records the result.
6. Checks the watcher heartbeat and confirms it is ticking within expected cadence.
7. Reads the latest outbox state and confirms no stuck or errored events from the promotion.
8. Reports a clear PASS / FAIL with the checks run and their results.
9. Appends the verification receipt (timestamp, checks run, outcome) to the promotion plan file at `ops/promotions/YYYY-MM-DD-<short-sha>.md`.

## Pre-conditions

- `execute-promotion` or `rollback-promotion` has completed.
- The prod Postgres container is running (`make prod-up`).
- The prod process is running.

## Operator steps

The `verify-promotion ...` command below is a skill invocation, not an installed shell binary — it names this skill's entry contract and arguments.

```
verify-promotion [--plan ops/promotions/YYYY-MM-DD-<short-sha>.md]
```

If `--plan` is provided, the verification receipt is appended to it. If not, it is written to stdout only.

## What PASS means

All of the following are true:
- Code ref matches the current promotion ref (`main` under the ADR-0040 interim baseline; `origin/stable` under the future gated model — see step 1).
- Status and settings-explain both report env=prod, correct vault, correct DB.
- Postgres healthy, outbox consumer healthy, watcher heartbeat within cadence.
- No stuck or errored events from the promotion window.
- Smoke gate green (or explicitly waived with a reason).

Any single failure is a FAIL. FAIL after `execute-promotion` → call `rollback-promotion`. FAIL after `rollback-promotion` → escalate to the operator for manual triage; do not attempt automated recovery.

## Key constraints

- Never interpret partial health as acceptable. Report FAIL and route to rollback.
- Never mark PASS without checking every check in steps 1-7 of "What this skill does" and every condition under "What PASS means".
- Always append the receipt to the plan file if one is provided — this is the capability-level validation evidence.

## Authority order for decisions

1. `docs/HEALTH.md` — health contract
2. `docs/RELEASE_CHANNELS/README.md` — what constitutes post-promotion acceptance
3. `docs/ENVIRONMENTS.md` — environment contract (settings-explain expected outputs)

## Routing

- Called after: `execute-promotion` or `rollback-promotion`
- On PASS after execute: promotion is accepted; update the parent feature issue with a validation receipt
- On FAIL after execute: call `rollback-promotion`
- On FAIL after rollback: escalate to operator; do not loop
