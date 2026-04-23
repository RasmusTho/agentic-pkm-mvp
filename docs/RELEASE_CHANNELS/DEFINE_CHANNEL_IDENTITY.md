---
name: Define Channel Identity
description: Specify the identity of the stable, dev, and test release channels in terms of code ref, DB, vault, and runtime-artifact directory.
task_id: RELEASE_CHANNELS-01
source_anchor: docs/RELEASE_CHANNELS/README.md :: Channel model
parent_capability: RELEASE_CHANNELS
prerequisites: []
depends_on: []
can_parallelize_with: [SPLIT_POSTGRES_PER_CHANNEL, DEFINE_PROMOTION_PLAN_CONTRACT, DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION, DEFINE_CONCURRENCY_RULE, DEFINE_ROLLBACK_CONTRACT]
---

# Define Channel Identity

## Purpose

Give the operator a single, unambiguous answer to "what is actually running in prod right now, and how is it different from what I'm editing in dev?" This task specifies channel identity — the four resolvable properties that together define a channel — so that every downstream task (promotion, rollback, isolation enforcement) has the same ground to stand on.

## What This Task Does

This task produces the channel-identity contract as a docs artifact under `docs/RELEASE_CHANNELS/`. It:

- Names the three channels — `stable`, `dev`, `test` — and their one-to-one mapping onto the existing `prod`, `dev`, `test` environments in [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md).
- Declares the four identity properties per channel: code ref, DB name, vault root, runtime-artifact directory.
- States that channel identity is inspectable at runtime without reading code (i.e. the running process can report its channel by resolving the four properties).
- Draws the line between channel identity (operational) and environment selection (path/policy resolution) so the two concepts do not collapse.

## Concretely

The contract this task establishes:

- **stable channel**: code ref = `stable` (git tag or branch pointer); DB = `pkm_prod`; vault root = the operator's real vault (configured, not hard-coded); runtime artifacts = `tmp/`.
- **dev channel**: code ref = `main` or a feature branch (no pin); DB = `pkm_dev`; vault root = `vault-dev/`; runtime artifacts = `tmp-dev/`.
- **test channel**: code ref = current worktree (whatever `make test-bootstrap` runs against); DB = `pkm_test` (dropped/recreated by bootstrap); vault root = `vault-test/`; runtime artifacts = `tmp-test/`.
- **Resolution point**: channel identity resolves through `app.config.environment` + a new channel-aware extension that exposes the four properties coherently. No scattered env-var soup.
- **Inspection surface**: `python -m app.cli status` and `python -m app.cli settings-explain` must report the active channel including all four properties.

This task does not implement the resolution extension. It specifies the contract the resolver must satisfy.

## Why This Matters

Without a shared channel-identity contract, every downstream feature (promotion, rollback, DB split, concurrency rule) has to re-invent "what channel am I on, really?" That produces scattered env-var checks, drifting defaults, and silent cross-channel leaks. The operator also cannot honestly answer "is my prod stable?" without this contract, because "prod" and "the thing currently running" are not the same without a code-ref pin.

## Acceptance Criteria

- [ ] The contract names three channels (`stable`, `dev`, `test`) and maps each to an existing environment (`prod`, `dev`, `test`).
  Verify: `rg -n "stable|dev|test" docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md :: Concretely`; doc review confirms the mapping table is present and complete.
- [ ] The contract declares the four identity properties per channel (code ref, DB, vault, runtime artifacts).
  Verify: `rg -n "code ref|DB|vault|runtime artifacts" docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md`.
- [ ] The contract states that channel identity must be inspectable at runtime via `settings-explain` and `status`.
  Verify: `rg -n "settings-explain|status|inspectable" docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md`.
- [ ] The contract distinguishes channel identity from environment selection.
  Verify: doc review of the `Purpose` and `What This Task Does` sections; the spec must state that environment resolves paths/policies while channel names the operational build.
- [ ] The contract does not propose code changes; it only specifies what the downstream resolver must satisfy.
  Verify: `git diff --name-only` for this change touches only `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md` (and parent README if cross-linked).

## How to Verify (Pre-Merge)

- Read this file alongside the README and confirm the channel table here matches the channel table in [README.md](README.md) exactly. Any drift is a defect in this task.
- Confirm the task specifies the inspection surface (`settings-explain`, `status`) without mandating specific command output.
- Confirm nothing in this spec prescribes how the resolver is implemented.

## Out of Scope

- Implementing the channel-aware resolver in `app.config.environment`.
- Changing `PKM_ENVIRONMENT` semantics.
- Defining the promotion operation (that is `DEFINE_PROMOTION_PLAN_CONTRACT`).
- Specifying DB-per-channel migration entry points (that is `SPLIT_POSTGRES_PER_CHANNEL`).

## Related Docs

- [docs/RELEASE_CHANNELS/README.md](README.md)
- [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md)
- [docs/OPERATIONS.md](../OPERATIONS.md)

## Related GitHub Issues

When promoted into an implementation issue: "Implements RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY." The docs-only version of the issue carries the ACs above. A separate follow-up issue should implement the resolver extension and inspection surface; that issue is not this one.
