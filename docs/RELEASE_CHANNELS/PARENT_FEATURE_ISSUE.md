State: Draft parent feature issue body for the RELEASE_CHANNELS capability. Not yet created on GitHub.

# [Feature] Release channels: run stable in prod while dev continues

> **Draft.** This file is the draft of the GitHub parent feature issue for RELEASE_CHANNELS. It has not been created on GitHub yet. Keep the shape aligned with the repo issue contract so `gh issue create` can copy the body with minimal edits.

## Context

Today, "using the system" and "developing the system" are the same activity against the same runtime. The operator cannot run a stable build against the real vault while new feature work continues, because:

- the Postgres database is shared across environments (per [docs/ENVIRONMENTS.md §Stores and Persistence](../ENVIRONMENTS.md)), so any dev-side migration or experimental event reaches prod's consumer;
- there is no channel identity — "prod" refers to an environment selector, not to a pinned code ref;
- there is no promotion or rollback contract, so release is an improvised terminal session;
- there is no rule preventing a dev `git checkout` from silently replacing the code a running prod process executes.

The result: the operator cannot adopt the system as a daily surface, and every v6.0 priority destabilizes the same running instance they are trying to use. This is the piece that gates actually-using the product.

This feature specifies the release-channels capability: channel identity, DB-per-channel isolation, promotion contract, rollback posture, and the concurrency rule that keeps prod and dev running side by side without interference. It is docs-only at the capability-definition stage; implementation (resolver extension, DB split, the four promotion skills) lives in follow-up child issues.

## Scope

Produce a specification directory at `docs/RELEASE_CHANNELS/` that:

- Defines the three channels (stable, dev, test) and maps them onto the existing environment model.
- Declares four identity properties per channel: code ref, DB name, vault root, runtime-artifact directory.
- Specifies per-channel logical Postgres databases (`pkm_prod`, `pkm_dev`, `pkm_test`) in a single local cluster.
- Defines the promotion plan contract (prepare → execute → verify → rollback).
- Classifies migrations as reversible or forward-only and specifies where the classification is declared.
- Defines the concurrency rule that keeps prod and dev processes running from separate checkouts.
- Defines the rollback contract, including previous-stable resolution and migration reversal.

The outcome boundary of this feature is a reviewable capability spec and a set of task files that later child issues implement. The capability itself is accepted only after a stable build has run unsupervised against the real vault with a recorded promotion and a rehearsed rollback.

## Source Anchors

- [docs/RELEASE_CHANNELS/README.md](README.md) :: Channel model, Invariants, Promotion contract, Rollback posture
- [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md) :: Environment model, Cross-Environment Invariants, Stores and Persistence
- [docs/ROADMAP.md](../ROADMAP.md) :: v6.0 baseline framing, Delivery Control Plane
- [docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md](../plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md) :: v5.6 invariants vs deferred work
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md) :: current runtime structure (unchanged by this feature)
- [docs/DB_SCHEMA.md](../DB_SCHEMA.md) :: schema ownership (migration reversibility declaration lives here in follow-up)
- [docs/OPERATIONS.md](../OPERATIONS.md) :: operator workflows (promotion skills land here in governance-lane follow-up)

## Constraints

- Capability-definition phase is docs-only. No task in this phase may modify Python code, migration tool configuration, or existing DB contents.
- No task may weaken the cross-environment invariants in [ENVIRONMENTS.md](../ENVIRONMENTS.md); the release-channels capability extends those invariants, does not replace them.
- No task may change the outbox-as-canonical-runtime-queue contract. Each channel gets the full contract on its own database.
- No task may introduce hosted deployment, CI/CD-triggered release, or shared-infrastructure topology. This feature is single-user, single-machine.
- No task may introduce a durable "channel" field into artifact payloads. Channel is an operational identity, not an artifact property.
- Multi-vault hot/cold decomposition is flagged as a future extension and must not be implemented here, but the spec must not foreclose it.
- Each task must be independently mergeable as a docs change. If a task cannot be verified on its own, it must be split.

## Acceptance Criteria

- [ ] `docs/RELEASE_CHANNELS/README.md` exists and satisfies the feature-breakdown spec-directory README contract.
  Verify: doc review against [.codex/skills/feature-breakdown/SKILL.md](../../.codex/skills/feature-breakdown/SKILL.md) :: Naming and structure rules.
- [ ] Six task specs are present and mutually exclusive: channel identity, Postgres-per-channel split, promotion plan contract, migration reversibility classification, concurrency rule, rollback contract.
  Verify: `ls docs/RELEASE_CHANNELS/` returns the expected files; doc review confirms no overlap in stated responsibility.
- [ ] The README names the three channels with their four identity properties and states the invariants verbatim enough that every task spec references them consistently.
  Verify: `rg -n "stable|dev|test|pkm_prod|pkm_dev|pkm_test" docs/RELEASE_CHANNELS/README.md`; each task file's property references match the README table.
- [ ] Migration reversibility is classified exactly as reversible or forward-only; no third classification is introduced.
  Verify: `rg -n "reversible|forward-only" docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`.
- [ ] Rollback is bounded and honest: vault immutability is stated, forward-only migrations are acknowledged as non-reversing, external side-effects are explicitly not reversed.
  Verify: `rg -n "vault|forward-only|external|side-effects" docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.
- [ ] The concurrency rule eliminates the shared-checkout foot-gun without mandating a specific path or tooling.
  Verify: doc review of [DEFINE_CONCURRENCY_RULE.md](DEFINE_CONCURRENCY_RULE.md); spec is behavior-level, not path-level.
- [ ] [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md) is updated to point operators at the release-channels capability and to drop the blanket "deployment automation OoS" line now that local single-user promotion is in scope.
  Verify: `rg -n "RELEASE_CHANNELS|release-channels" docs/ENVIRONMENTS.md`.
- [ ] [docs/DOCS_INDEX.md](../DOCS_INDEX.md) lists the new capability directory.
  Verify: `rg -n "RELEASE_CHANNELS" docs/DOCS_INDEX.md`.
- [ ] No file outside `docs/RELEASE_CHANNELS/` is touched by this feature other than the bounded [ENVIRONMENTS.md](../ENVIRONMENTS.md) and [DOCS_INDEX.md](../DOCS_INDEX.md) edits called out above.
  Verify: `git diff --name-only` on the delivering PR lists only files under `docs/RELEASE_CHANNELS/`, plus `docs/ENVIRONMENTS.md` and `docs/DOCS_INDEX.md`.

## Out of Scope

- Implementing the channel-aware resolver in `app.config.environment`.
- Splitting the actual Postgres databases (`pkm_prod`, `pkm_dev`, `pkm_test`) on disk and wiring migration entry points. This lands as child implementation issues after the spec merges.
- Authoring the four promotion skills (`prepare-promotion`, `execute-promotion`, `verify-promotion`, `rollback-promotion`). They live in a separate governance-lane PR under `.codex/skills/`.
- Multi-vault hot/cold decomposition in prod. Flagged as a future capability that extends this one; not implemented here.
- Multi-user coordination. Single-user stance is preserved.
- Hosted deployment, CI/CD-triggered release, secrets management.
- Vault-level undo or history restoration.
- Owner-doc promotion of the release-channel contract into [docs/ARCHITECTURE.md](../ARCHITECTURE.md) or [docs/OPERATIONS.md](../OPERATIONS.md) as stable runtime truth. Promotion is a later PR after the capability is validated.

## Suggested Validation

Capability-level acceptance is not a single test. It accumulates as validation receipts on this parent feature issue:

- A stable build runs unsupervised against the real vault for a bounded soak window.
- A dev session on the same machine exercises schema change, vault reset, and runtime restart without altering prod state.
- An end-to-end promotion is performed (prepare → execute → verify → accept) with a recorded plan.
- A rollback is performed in a controlled setting, with the migration reversal path exercised.

Per [.codex/skills/feature-breakdown/SKILL.md](../../.codex/skills/feature-breakdown/SKILL.md) :: Real-life evidence surfaces, these validation receipts live in this issue's comments or body checklist, not in re-opened owner docs.

## Source Docs

- [docs/RELEASE_CHANNELS/README.md](README.md)
- [docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md](DEFINE_CHANNEL_IDENTITY.md)
- [docs/RELEASE_CHANNELS/SPLIT_POSTGRES_PER_CHANNEL.md](SPLIT_POSTGRES_PER_CHANNEL.md)
- [docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md](DEFINE_PROMOTION_PLAN_CONTRACT.md)
- [docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md](DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md)
- [docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md](DEFINE_CONCURRENCY_RULE.md)
- [docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md](DEFINE_ROLLBACK_CONTRACT.md)
- [docs/ENVIRONMENTS.md](../ENVIRONMENTS.md)
- [docs/ROADMAP.md](../ROADMAP.md)
- [docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md](../plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md)

## Implementation Tasks

Bounded task specs under this directory, intended execution order (independently mergeable; parallelize where possible):

1. [DEFINE_CHANNEL_IDENTITY.md](DEFINE_CHANNEL_IDENTITY.md) — channel identity and four properties; prerequisite for everything else.
2. [SPLIT_POSTGRES_PER_CHANNEL.md](SPLIT_POSTGRES_PER_CHANNEL.md) — per-channel logical DBs; unblocks DB-touching downstream work.
3. [DEFINE_PROMOTION_PLAN_CONTRACT.md](DEFINE_PROMOTION_PLAN_CONTRACT.md) — promotion plan shape; consumed by `prepare-promotion`/`execute-promotion` skills.
4. [DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md](DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md) — reversible vs forward-only; consumed by the promotion plan and the rollback contract.
5. [DEFINE_CONCURRENCY_RULE.md](DEFINE_CONCURRENCY_RULE.md) — separate-checkouts rule; no tooling required, usage discipline plus `execute-promotion` behavior.
6. [DEFINE_ROLLBACK_CONTRACT.md](DEFINE_ROLLBACK_CONTRACT.md) — rollback posture; depends on the promotion plan and migration classification.

Tasks 1, 3, 5 can run in parallel. Tasks 2, 4, 6 depend on 1. Task 6 also depends on 4.

## Verification Path

Per-task: each task spec carries `Acceptance Criteria` with inline `Verify:` markers — grep-based or doc-review checks against the task's own file. No behavioral tests are required at the capability-definition phase because there is no code change.

Capability-level: verification of the capability as a whole lives in the validation section below and accumulates on this feature issue after task PRs merge.

## Validation / Acceptance Path

Post-merge validation receipts accumulate on this issue as comments or checklist progress:

- [ ] Stable channel runs unsupervised against the real vault for a bounded soak window (receipt: operator note + timestamp).
- [ ] Dev session exercises schema change, vault reset, and runtime restart on `pkm_dev` / `vault-dev/` without touching `pkm_prod` / real vault (receipt: dev session log).
- [ ] End-to-end promotion completed with a recorded promotion plan (receipt: plan file path + timestamp).
- [ ] Rollback rehearsed in a controlled setting with migration reversal exercised (receipt: rollback run log).

Owner-doc promotion (updates to [ARCHITECTURE.md](../ARCHITECTURE.md), [OPERATIONS.md](../OPERATIONS.md), [ROADMAP.md](../ROADMAP.md)) happens in a separate PR after all four validation receipts are present on this issue.
