---
name: Split Postgres Per Channel
description: Specify the two-layer DB isolation contract: per-channel Postgres runtime stacks and resolver-driven environment DB naming, with per-channel migration entry points.
task_id: RELEASE_CHANNELS-02
source_anchor: docs/RELEASE_CHANNELS/README.md :: Invariants — DB-per-channel
parent_capability: RELEASE_CHANNELS
prerequisites: [RELEASE_CHANNELS-01]
depends_on: [DEFINE_CHANNEL_IDENTITY.md]
can_parallelize_with: [DEFINE_PROMOTION_PLAN_CONTRACT, DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION, DEFINE_CONCURRENCY_RULE, DEFINE_ROLLBACK_CONTRACT]
---

# Split Postgres Per Channel

## Purpose

Capture the now-shipped two-layer DB isolation model for channels so the capability spec reflects implementation reality. The old shared-DB leak is closed by (1) per-channel Postgres runtime stacks and (2) environment-resolver DB naming conventions. This task records the contract and how migration/promotion flows should treat it.

## Current State

The implementation baseline now includes both layers:

| Channel | Compose target | Postgres port | Resolver DB name |
| --- | --- | --- | --- |
| `prod` | `make prod-up` | `15432` | `app` |
| `dev` | `make dev-up` | `15433` | `app_dev` |
| `test` | `make test-up` | `15434` | `app_test` |

- Container/runtime layer shipped via PR #596.
- Resolver naming layer shipped via PR #603 (Issue #594).

## What This Task Does

This task produces the DB-per-channel contract as a docs artifact under `docs/RELEASE_CHANNELS/`. It:

- Captures the container/runtime layer shipped in PR #596.
- Captures the resolver layer shipped in PR #603 (Issue #594).
- Specifies per-channel migration entry points: migrations target the active channel DB/runtime and never mutate another channel's state.
- States reset posture: `test` is resettable by `make test-bootstrap`; `dev` is resettable by dev tooling; `prod` is treated as production data and is never dropped by scripted flows.
- Preserves the outbox, event log, and audit semantics unchanged per channel.

## Concretely

The contract this task establishes:

- **Runtime stacks**: channel-specific Postgres runtimes (`prod`/`dev`/`test`) via compose targets and dedicated ports (15432/15433/15434).
- **Resolver naming**: `app.config.environment` defines DB naming (`app`, `app_dev`, `app_test`) and call sites must use resolver surfaces, not hard-coded names.
- **Migrations**: migration tooling always targets the active channel. Applying to dev or test never mutates prod.
- **Bootstrap**: `make test-bootstrap` may reset test DB state as part of the verification path.
- **Prod safety**: no scripted flow drops or truncates prod DB state. Any destructive operation is explicit operator action.
- **Outbox semantics**: unchanged per channel runtime.

## Why This Matters

Without this contract, channel isolation regresses in practice. The release-channels invariants (vault-per-channel, code-ref-per-channel, promotion plan, rollback) assume DB/runtime separation is real and enforced. The implementation has landed; this spec keeps docs truthful and provides the baseline for future refinements.

## Acceptance Criteria

- [ ] The contract records the shipped container/runtime layer (PR #596) and resolver layer (PR #603 / Issue #594).
  Verify: `rg -n "PR #596|PR #603|Issue #594|15432|15433|15434" docs/RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL.md`.
- [ ] The contract routes DB naming through `app.config.environment`.
  Verify: `rg -n "app.config.environment|app_dev|app_test|app" docs/RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL.md`.
- [ ] The contract specifies per-channel migration targeting and non-interference.
  Verify: `rg -n "migration|active channel|never mutates|never mutate" docs/RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL.md`.
- [ ] The contract states reset and safety posture by channel.
  Verify: `rg -n "test-bootstrap|reset|never dropped|prod safety|destructive" docs/RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL.md`.
- [ ] The contract preserves the outbox-as-canonical-runtime-queue contract per channel.
  Verify: `rg -n "outbox|canonical|runtime queue" docs/RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL.md`; cross-check [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md) :: Cross-Environment Invariants.
- [ ] The contract is docs-only; implementation is scoped to separate follow-up work.
  Verify: `git diff --name-only` for this change touches only files under `docs/RELEASE_CHANNELS/` (and, if needed, `docs/ENVIRONMENTS.md` cross-link updates).

## How to Verify (Pre-Merge)

- Read this file alongside `DEFINE_CHANNEL_IDENTITY.md` and confirm channel identity stays aligned with runtime stack and resolver naming.
- Confirm the spec records shipped behavior from PR #596 and PR #603 without introducing conflicting naming schemes.
- Confirm the spec preserves [ENVIRONMENTS.md](../ENVIRONMENTS.md) cross-environment invariants — none are weakened.

## Out of Scope

- Implementing further resolver changes (the core resolver layer already shipped in PR #603).
- Writing new migration tooling.
- Hosted / remote Postgres topology.
- Changing outbox table shape or event envelope.
- Mandating single-cluster vs multi-cluster production topology beyond the local/runtime contract.

## Related Docs

- [docs/RELEASE_CHANNELS/README.md](README.md)
- [docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md](DEFINE_CHANNEL_IDENTITY.md)
- [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md) :: Parallel Local Stacks
- [docs/DB_SCHEMA.md](../DB_SCHEMA.md)

## Related GitHub Issues

When promoted: "Implements RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL." Historical implementation references: PR #596 (runtime stack separation) and PR #603 / Issue #594 (resolver-driven DB naming).
