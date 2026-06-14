---
name: prepare-promotion
description: "Produce a promotion plan that diffs main against stable, enumerates code delta, migration delta, config delta, and risk notes, and surfaces every forward-only migration for operator acknowledgment before execution."
---

# Prepare Promotion

Use this skill before any `execute-promotion` run. Its sole job is to produce a reviewable promotion plan. It does not move any ref, apply any migration, or restart any process.

Do not use this skill to:
- execute the promotion (use `execute-promotion`)
- verify that prod came up cleanly after promotion (use `verify-promotion`)
- roll back a failed promotion (use `rollback-promotion`)

## Capability boundary

The release-channels capability spec lives at `docs/RELEASE_CHANNELS/`. Read `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` before running this skill — it is the authoritative contract for what a promotion plan must contain.

## What this skill does

1. Resolves the current `stable` ref (the commit prod is running from).
2. Resolves the target `main` commit the operator wants to promote to.
3. Diffs the two refs and enumerates every PR merged since `stable`.
4. For each included PR: extracts title, link, and any associated GitHub Issue; checks whether ACs are marked satisfied on the Issue; notes any open verification gaps.
5. Enumerates migration files committed since `stable` that have not yet been applied to the prod DB (`pkm_prod` container, port 15432). For each migration: reads its reversibility marker (per `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`) and flags forward-only ones explicitly.
6. Diffs settings/env defaults between the two refs and notes any operator-visible config changes.
7. Assembles risk notes: forward-only migrations, PRs without full AC verification, any cross-channel touchpoints visible in the diff, and a **vault-settings preflight** of the prod vault (`app.vault.promotion_preflight.vault_settings_preflight`, or `python -m app.cli vault preflight --path <prod vault>`). If the vault is `uninitialized` (predates the vault-settings foundation), record a required `python -m app.cli vault init --path <prod vault>` step as a **blocking** risk — otherwise the watcher fail-exits on startup (the #1991 prod failure mode).
8. Writes the promotion plan to `ops/promotions/YYYY-MM-DD-<short-sha>.md` using the required sections from `DEFINE_PROMOTION_PLAN_CONTRACT`.
9. Prints a summary to the operator: plan path, number of PRs, number of migrations (N reversible, M forward-only), and any blocking risks.

The skill does not proceed past step 9 without operator review. It exits after producing the plan.

## Required sections in the output plan

Per `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`:

1. **Promotion target** — from-commit, to-commit, and timestamp.
2. **Code delta** — ordered PR list with AC status and verification receipt links.
3. **Migration delta** — each migration with reversibility classification.
4. **Config / settings delta** — operator-visible changes.
5. **Risk notes** — forward-only migrations, AC gaps, cross-channel concerns.
6. **Rollback path** — previous `stable` ref and migration reversal sequence.
7. **Operator acknowledgments** — checkboxes for forward-only migrations and any AC gaps.

## Pre-conditions

- `docs/RELEASE_CHANNELS/` is present on `main` (docs capability PR merged; originally PR #602). If those docs are not on `main`, do not run this skill.
- `make prod-up` is running and the prod Postgres container is healthy on port 15432.
- The `stable` ref resolves without ambiguity (`git rev-parse stable` succeeds).
- The operator has specified the target commit (defaults to `HEAD` on `main` if not provided).
- The selected prod vault is initialized for the vault-settings foundation (`python -m app.cli vault preflight --path <prod vault>` reports `initialized`). If it reports `uninitialized`, the plan must carry a `python -m app.cli vault init --path <prod vault>` step before execute (idempotent; reviews the scaffolded `paths.md`/`companion-ui.md` against the real vault).

## Operator steps

The `prepare-promotion ...` command below is a skill invocation, not an installed shell binary — it names this skill's entry contract and arguments.

```
# From the prod checkout (not the dev checkout — separate worktree per DEFINE_CONCURRENCY_RULE)
prepare-promotion [--target <sha-or-ref>]

# Review the produced plan at ops/promotions/YYYY-MM-DD-<short-sha>.md
# Tick all operator-acknowledgment checkboxes
# Then hand off to execute-promotion
```

## Output

A single markdown file at `ops/promotions/YYYY-MM-DD-<short-sha>.md` satisfying the promotion plan contract. Also printed to stdout as a human-readable summary.

## Key constraints

- Never move the `stable` ref. That is `execute-promotion`'s job.
- Never apply migrations. Plan only.
- Never restart any process.
- If the `stable` ref is ambiguous or missing, abort and report — do not guess.
- If a migration lacks a reversibility marker, flag it as a blocking risk in the plan and do not classify it silently.

## Authority order for decisions

1. `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md` — plan shape
2. `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — migration classification
3. `docs/RELEASE_CHANNELS/README.md` — invariants
4. `docs/ENVIRONMENTS.md` — environment model

## Routing

- To execute: `execute-promotion` (pass it the plan path produced here)
- To roll back after a failed execute: `rollback-promotion`
- To verify post-execution: `verify-promotion`
