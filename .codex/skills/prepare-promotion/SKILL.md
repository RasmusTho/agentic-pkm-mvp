---
name: prepare-promotion
description: "Produce a promotion plan that diffs the current TEST-qualified candidate against stable, enumerates code delta, migration delta, config delta, and risk notes, and surfaces every forward-only migration for operator acknowledgment before execution."
---

# Prepare Promotion

> **Status: current source promotion policy (ADR-0068 D4, Issue #6228).**
> `stable` is the production promotion authority. Normal advancement requires the exact current
> `test` candidate C, trusted green TEST evidence, a durable functional PASS, and explicit approval
> of the concrete plan. Protected merge M records stable authority; it does not qualify a new
> source version or image. Production deploys the tested source C and immutable digest D.
> Repository support does not establish a running-prod observation or physical cutover. Current
> infrastructure observations belong to `RasmusTho/yggdrasil-infra/CURRENT_STATUS.md`.

Use this skill before any `execute-promotion` run. Its sole job is to produce a reviewable promotion plan. It does not move any ref, apply any migration, or restart any process.

Do not use this skill to:
- execute the promotion (use `execute-promotion`)
- verify that prod came up cleanly after promotion (use `verify-promotion`)
- roll back a failed promotion (use `rollback-promotion`)

## Capability boundary

The release-channels capability spec lives at `docs/RELEASE_CHANNELS/`. Read `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` before running this skill — it is the authoritative contract for what a promotion plan must contain.
Promotion planning is Builder System boundary work. The plan is a Builder System governance artifact;
the code, migrations, settings, and runtime preconditions it summarizes may be Product/Runtime
changes. Use `docs/architecture/SBS_OPERATING_MODEL.md` to route SBS impact, owner-doc writeback,
transition debt, and fitness-rule evidence without treating the promotion plan itself as runtime
memory or Product truth.

## Deployment model

Before planning, resolve the target channel's deployment model:

- **Checkout model (interim / no-dead-window):** the channel remains on the checkout model until a
  cutover receipt exists for that channel: a fleet-model fitness PASS recorded in
  `ops/deployments/<channel>-latest.json`. In this mode, keep the existing promotion-plan diff:
  current promotion ref / `stable` baseline, target commit, migration delta, config delta, rollback
  path, and operator acknowledgments. Normal forward execution refuses the generated merge SHA
  before a stable PR because checkout M is not the TEST-qualified source C. A physical model
  transition requires its own authority and observed receipt.
- **Pinned-image model (post-cutover):** once that channel's cutover receipt exists, the plan still
  uses `docs/RELEASE_CHANNELS/README.md` to decide which SHA is authorized, but physical deployment
  will be executed by `scripts/deploy_channel.sh deploy <channel> <tested-sha> --image-digest <digest> --promotion-plan <path>` per
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`. The plan must record the deployment model,
  channel, authorized SHA, image-tag availability check, migration-gate posture, previous-good pin
  for rollback, and the expected deploy receipt path `ops/deployments/<channel>-latest.json`.

## What this skill does

1. Resolves the current protected `stable` baseline S; reads running-prod identity separately.
2. Resolves the exact current `test` candidate C and its trusted green TEST and build-once image D evidence. An older test-passed candidate or arbitrary `main` HEAD is ineligible.
3. Diffs the two refs and enumerates every PR merged since `stable`.
4. For each included PR: extracts title, link, and any associated GitHub Issue; checks whether ACs are marked satisfied on the Issue; notes any open verification gaps.
5. Enumerates migration files committed since `stable` that have not yet been applied to the prod DB (`app` DB, compose project `pkm-prod`, port 15432). For each migration: reads its reversibility marker (per `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`) and flags forward-only ones explicitly.
6. Diffs settings/env defaults between the two refs and notes any operator-visible config changes.
7. Assembles risk notes: forward-only migrations, PRs without full AC verification, any cross-channel touchpoints visible in the diff, and a **vault-settings preflight** of the prod vault (`app.vault.promotion_preflight.vault_settings_preflight`, or `python -m app.cli vault preflight --path <prod vault>`). If the vault is `uninitialized` (predates the vault-settings foundation), record a required `python -m app.cli vault init --path <prod vault>` step as a **blocking** risk — otherwise the watcher fail-exits on startup (the #1991 prod failure mode).
8. Writes the promotion plan to `ops/promotions/YYYY-MM-DD-<short-sha>.md` using the required sections from `DEFINE_PROMOTION_PLAN_CONTRACT`.
9. Prints a summary to the operator: plan path, number of PRs, number of migrations (N reversible, M forward-only), and any blocking risks.

The skill does not execute a promotion without the required operator review. Return the plan for
preparation-only scope; otherwise execute the next authorized step once its acknowledgments hold,
without asking again for review already recorded against this exact plan.

## Required sections in the output plan

Per `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`:

1. **Promotion target** — from-commit, to-commit, and timestamp.
2. **Code delta** — ordered PR list with AC status and verification receipt links.
3. **Migration delta** — each migration with reversibility classification.
4. **Config / settings delta** — operator-visible changes.
5. **Risk notes** — forward-only migrations, AC gaps, cross-channel concerns.
6. **Rollback path** — previous `stable` ref and migration reversal sequence.
7. **Operator acknowledgments** — checkboxes for forward-only migrations and any AC gaps.

The same plan adds `Test evidence` using the closed evidence shape in the plan contract: C/D and
its CI provenance, S, the deployment model, signed functional receipt/report/context/registry paths,
and the receipt identity. Preserve the previous-good pin and all migration risks. The renderer does
not perform the code/migration/config investigation or grant approval.

Compute the reviewed plan digest with `python -m app.release_channels.stable_promotion --plan <path>
--approval-digest`. The human records their identity and this digest in `approval`, and ticks every
acknowledgment. Editing the reviewed narrative or inputs invalidates approval. Execution output
records the independently verified protected PR and M; it cannot change C/D or S.

## Pre-conditions

- `docs/RELEASE_CHANNELS/` is present on `main` (docs capability PR merged; originally PR #602). If those docs are not on `main`, do not run this skill.
- `make prod-up` is running and the prod Postgres container is healthy on port 15432.
- The protected `origin/stable` ref resolves without ambiguity (`git rev-parse origin/stable` succeeds).
- The target is the exact current green `test` candidate; no default to `main` or `HEAD`.
- A signed functional PASS from `promote-to-test`, its check report and trust registry, and a production admission context bind C/D to S. PG smoke or a green deployment verdict alone is insufficient.
- The selected prod vault is initialized for the vault-settings foundation (`python -m app.cli vault preflight --path <prod vault>` reports `initialized`). If it reports `uninitialized`, the plan must carry a `python -m app.cli vault init --path <prod vault>` step before execute (idempotent; reviews the scaffolded `paths.md`/`companion-ui.md` against the real vault).

## Operator steps

The `prepare-promotion ...` command below is a skill invocation, not an installed shell binary — it names this skill's entry contract and arguments.

```
# From the prod checkout (not the dev checkout — separate worktree per docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md)
prepare-promotion [--target <sha-or-ref>]

# Review the produced plan at ops/promotions/YYYY-MM-DD-<short-sha>.md
# Tick all operator-acknowledgment checkboxes
# With execution authority and required acknowledgments, invoke execute-promotion
```

## Output

A single markdown file at `ops/promotions/YYYY-MM-DD-<short-sha>.md` satisfying the promotion plan contract. Also printed to stdout as a human-readable summary.

## Key constraints

- Never move the `stable` ref. That is `execute-promotion`'s job.
- Never apply migrations. Plan only.
- Never restart any process.
- If the `stable` ref is ambiguous or missing, abort and report — do not guess.
- If a migration lacks a reversibility marker, flag it as a blocking risk in the plan and do not classify it silently.
- Never let the deployment-model switch move promotion authority: ADR-0068 D4 and
  `docs/RELEASE_CHANNELS/README.md §Promotion model` decide the authorized C/D and stable authority; the deployment
  model only decides whether physical execution is checkout update/restart or
  `scripts/deploy_channel.sh`.

## Invariant → producers rule (issue #1997 F4)

When a change adds a **runtime precondition** — a new invariant the runtime
fails-exits without (the #1991 vault-settings init is the canonical example) —
that change is incomplete until it also updates **every producer of the thing
the invariant guards** AND adds a fail-loud preflight, in the **same change**.

A "producer" is anything that creates or brings up the guarded resource:

- init / bootstrap scripts (e.g. `scripts/init_test_vault.sh`,
  `scripts/bootstrap_test_channel.sh`);
- existing-resource migration (e.g. a `vault init` step for a vault that
  predates the invariant — for prod this is the blocking risk recorded in step 7
  above; for the test channel it is baked into the bootstrap);
- test fixtures that stand up the resource in-process (e.g. the IR-v1 UAT vault
  fixture);
- the matching preflight that refuses to run on a violation
  (`app.vault.promotion_preflight` for the vault, `app.ops.channel_preflight`
  for the whole test channel).

Why: the 2026-06-14 v6.1 Wave 1 promotion was almost entirely harness pain
because #1991 made vault-init a hard precondition but its producers
(`init_test_vault.sh`, the existing prod vault) were never migrated — the
invariant shipped half-applied and was discovered as a prod startup failure.
A precondition without migrated producers + a preflight is a latent outage.

Enforcement: the test channel is held to this by `app.ops.channel_preflight`
(refuses inconsistent config) and the harness-selfverify CI gate (runs the
IR-v1 UAT + the bootstrap smoke + a fault-injection proof). When you add a
runtime precondition, add it to that gate's coverage too.

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` — plan shape
2. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — migration classification
3. `docs/RELEASE_CHANNELS/README.md` — invariants
4. `docs/ENVIRONMENTS.md` — environment model

## Routing

- To execute: `execute-promotion` (pass it the plan path produced here)
- To roll back after a failed execute: `rollback-promotion`
- To verify post-execution: `verify-promotion`

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. Once the plan is complete and the
required operator acknowledgments and execution authority already exist, invoke `execute-promotion`
with that plan. Preparation-only scope returns the reviewable plan. Missing acknowledgments remain
an explicit gate; continuation does not authorize a production effect or physical model transition.
