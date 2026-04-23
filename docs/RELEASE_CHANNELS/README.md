---
name: Release Channels Specification
description: Capability specification for running a stable prod build against the real vault while dev continues evolving on the same single-user machine
type: specification
authority: SoT for the release-channels capability; names channel identity, isolation invariants, promotion contract, and rollback posture. Does not override runtime truth in docs/ARCHITECTURE.md or current environment selection semantics in docs/ENVIRONMENTS.md.
source_of_truth: docs/ROADMAP.md (v6.0 line), docs/ENVIRONMENTS.md (env model it extends)
related_docs:
  - docs/ENVIRONMENTS.md
  - docs/ARCHITECTURE.md
  - docs/OPERATIONS.md
  - docs/DB_SCHEMA.md
  - docs/LOCAL_TEST_BOOTSTRAP/README.md
  - docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md
---

State: Active specification for the release-channels capability. Docs-only at this stage. No code, no schema moves, no skills written yet.
Doc role: Core SoT for the release-channels capability
Owner: `docs/ROADMAP.md`
Temporal class: strategic
Review cadence: biweekly
Last reviewed: 2026-04-21
Last verified against: docs/ENVIRONMENTS.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/OPERATIONS.md, docs/DB_SCHEMA.md

# Release Channels Specification

This directory specifies the capability that lets a **stable build run in prod against the real vault** while **new feature work continues in dev on the same machine**, without dev churn destabilizing prod and without prod freeze blocking dev.

This is the capability that turns the existing `dev` / `test` / `prod` environment model into something the operator can actually *use* day-to-day. [ENVIRONMENTS.md](../ENVIRONMENTS.md) today defines environment selection and artifact path scoping, but it explicitly leaves deployment automation, schema separation between long-lived environments, and cross-channel safety out of scope. That gap is what blocks running a stable operator-facing system while active development continues — and therefore what this capability closes.

## Human need this serves

One specific cognitive-support outcome from `docs/CONCEPTS/USER_NEEDS_MODEL.md`:

- **The system must be trustworthy enough to live in.** If every dev session risks the real vault, the operator cannot adopt the system as a daily surface. Without a stable channel, "using the system" and "developing the system" are the same activity, and that activity is too risky for real cognitive work.

Secondary needs served:

- **Operator can recover from a bad release** — rollback is a first-class operation, not an improvised git dance.
- **Developer can move fast without fear** — dev-side schema and runtime experiments cannot reach the prod DB or prod vault.

## Capability boundary

The release-channels capability owns:

- **Channel identity** — what "stable" and "dev" refer to in terms of code ref, DB, vault, and runtime artifacts.
- **Channel isolation invariants** — what must not leak between channels at any time.
- **Promotion contract** — how a commit on `main` becomes the running `stable` build, including migration posture.
- **Rollback posture** — how the operator returns prod to a previous known-good state.
- **Concurrency rule** — how prod and dev processes coexist on the same single-user machine without interfering with each other.

It does **not** own:

- environment selection semantics (owned by [ENVIRONMENTS.md](../ENVIRONMENTS.md));
- local verification bootstrap (owned by [LOCAL_TEST_BOOTSTRAP](../LOCAL_TEST_BOOTSTRAP/));
- health/status contracts (owned by [HEALTH.md](../HEALTH.md));
- CI pipelines or hosted deployment automation (remains out of scope in this single-user wave);
- multi-vault hot/cold decomposition in prod (future work; flagged below).

## Channel model

Three channels map one-to-one onto the existing environment model, but add identity and isolation guarantees:

| Channel | Environment | Code ref | DB | Vault | Runtime artifacts |
| --- | --- | --- | --- | --- | --- |
| **stable** | `prod` | `stable` (tag or branch) | `pkm_prod` | real operator vault | `tmp/` |
| **dev** | `dev` | `main` or feature branch | `pkm_dev` | `vault-dev/` | `tmp-dev/` |
| **test** | `test` (workflow-driven) | current worktree | `pkm_test` (dropped/recreated by bootstrap) | `vault-test/` | `tmp-test/` |

The channel is the operational identity; the environment is the runtime selector that resolves paths and policies. A channel's build can be inspected by resolving its code ref; its data footprint can be inspected by resolving its DB name, vault root, and runtime-artifact directory.

## Invariants (MUST hold)

These extend the cross-environment invariants in [ENVIRONMENTS.md §Cross-Environment Invariants](../ENVIRONMENTS.md) with channel-scoped isolation rules.

1. **DB-per-channel.** Each channel runs against a separate logical Postgres database in a single local cluster. The outbox, event log, and any schema-carrying table lives in the channel's own DB. No cross-channel writes. No cross-channel consumers.
2. **Vault-per-channel.** No channel ever writes to another channel's vault root. The prod vault is never targeted by dev or test processes, including during migration, reset, or experimentation.
3. **Runtime-artifacts-per-channel.** Watcher state, heartbeats, incident logs, event logs, and all other runtime artifacts stay under the channel's runtime-artifact directory. Already partially true via [ENVIRONMENTS.md §Stores and Persistence](../ENVIRONMENTS.md); this capability extends the same rule to the DB.
4. **Code-ref-per-channel.** The prod process runs from a checkout pinned to the `stable` ref. Dev work must not be able to swap code under a running prod process. On a single-user machine this is satisfied by running prod and dev from separate checkouts (git worktrees are the recommended shape).
5. **Promotion is explicit and recorded.** No implicit promotion. Every stable-ref movement is an intentional operator act with a resolvable receipt (git tag annotation, log entry, or equivalent).
6. **Rollback is always available.** The previous stable ref is always resolvable and the migration reversal path is always specified at promotion time. If a migration is not reversibly specified, the promotion is rejected.
7. **Same contracts everywhere.** Channel separation does not change the event envelope, artifact identity, provenance, receipt semantics, or write-safety rules. A channel is an operational boundary, not a different product.

## Promotion contract

Promotion is the operation that turns an accepted commit on `main` into the running `stable` build in prod. It has four explicit phases:

1. **Prepare.** Diff `main` against the current `stable` ref. Enumerate:
   - code delta (commits/PRs included);
   - migration delta (schema changes to apply to `pkm_prod`);
   - config / settings delta;
   - risk notes (flags, known regressions, acceptance-criteria status of included PRs).
   The prepare phase produces a **promotion plan** the operator can review before executing.
2. **Execute.** Move the `stable` ref to the chosen commit. Apply migrations to `pkm_prod`. Restart the prod process from the updated `stable` checkout. Promotion is a single operator-triggered step, not a background automation.
3. **Verify.** Post-promotion health, status, and smoke checks against the running prod. Health must be green against [HEALTH.md](../HEALTH.md) contracts before the promotion is considered accepted.
4. **Rollback (conditional).** If verification fails, return `stable` to the previous ref, reverse any reversible migrations, and restart. Non-reversible migrations must be flagged during prepare so the operator chooses knowingly.

Promotion trigger is **manual, single-user**. No PR-merge-triggered automation, no CI-driven promotion. The operator decides when to promote.

## Rollback posture

- The previous stable ref is always resolvable (e.g. previous tag retained, or `stable-prev` pointer maintained).
- Migrations are classified at promotion time as **reversible** or **forward-only**. Forward-only migrations are allowed but require the operator to acknowledge that rollback cannot restore DB shape.
- Vault state rolled back separately is out of scope; the vault is the operator's authored content and is never rewound by a release operation. Note-level undo is a vault-level concern, not a channel-level concern.

## Verification path (pre-merge, per task)

This capability is docs-authoring at this stage. Task-level verification lives in the task files under this directory once [feature-breakdown](../../.codex/skills/feature-breakdown/SKILL.md) runs. Expected task-level `Verify:` shapes:

- Behavioral ACs pointing at integration tests that exercise channel isolation (e.g. a dev process cannot connect to `pkm_prod`, a dev write cannot hit `vault/`).
- Non-behavioral ACs pointing at doc writeback anchors (this README, ENVIRONMENTS.md update), at the promotion skills under `.codex/skills/`, and at the promotion plan shape when produced.

## Validation / acceptance path (post-merge)

Capability-level acceptance — the point at which the operator can honestly claim the system is usable — requires the following observable conditions, not a single test:

- A **stable build** is running against the real vault and has run unsupervised for a bounded soak window (measured, not asserted).
- A **dev session** on the same machine has exercised schema change, vault reset, and runtime restart without altering prod state.
- A **promotion** has been performed end-to-end (prepare → execute → verify → accept) with a recorded plan and verification receipt.
- A **rollback** has been performed at least once in a controlled setting, with the migration reversal path exercised.

These accumulate as validation receipts on the parent feature issue (per [feature-breakdown SKILL.md §Real-life evidence surfaces](../../.codex/skills/feature-breakdown/SKILL.md)) before any owner-doc promotion claims "release channels are supported."

## Promotion skills (to be authored, not part of this spec)

Once this capability boundary is accepted, a bounded set of repo-local skills will implement the operator workflow. One skill per job, per the human-first one-agent-one-job principle:

- `prepare-promotion` — produce the promotion plan (code/migration/config delta, risk notes, AC status).
- `execute-promotion` — move the `stable` ref, apply migrations, restart prod.
- `verify-promotion` — post-promotion health, status, and smoke checks.
- `rollback-promotion` — reverse ref, reverse reversible migrations, restart.

The skills are downstream artifacts. Their shape is specified in task files, not here.

## Out of scope

- **Multi-vault hot/cold decomposition in prod.** A known future direction (flagged by the operator 2026-04-21): prod will eventually host multiple vaults to separate hot working surfaces from cold archival surfaces. The release-channels capability must not foreclose this but also does not implement it. Channel identity today is one-vault-per-channel; the multi-vault-per-channel shape will be a later capability that extends this one.
- **Multi-user coordination.** Single-user remains the only operating stance (per user stance). Invariants above are written to be multi-user-compatible but no multi-user work is scheduled.
- **Hosted deployment, secrets management, CI/CD-driven release.** Out of scope for this single-user wave. If the system later runs on shared infrastructure, those capabilities will extend, not replace, this one.
- **Vault-level rollback.** The vault is authored content; release rollback does not rewrite it.
- **Feature flags as a release-channel substitute.** Flags are fine-grained runtime toggles, not a replacement for channel-level isolation.

## Relation to other capabilities

- **[ENVIRONMENTS.md](../ENVIRONMENTS.md)** owns environment selection (`PKM_ENVIRONMENT=dev|prod`) and path scoping. This capability extends that model with channel identity, DB-per-channel, and promotion/rollback contracts. ENVIRONMENTS.md must be updated in the same change that creates this spec to drop the "deployment automation OoS" line (which is now partially superseded) and to point operators here for channel-level questions.
- **[LOCAL_TEST_BOOTSTRAP](../LOCAL_TEST_BOOTSTRAP/)** continues to own the `test` channel's bootstrap golden path. This capability only adds the `pkm_test` DB-per-channel rule.
- **[HEALTH.md](../HEALTH.md)** owns the health contract used during the verify phase of promotion.
- **[DB_SCHEMA.md](../DB_SCHEMA.md)** owns schema definition; migration reversibility classification lives there, referenced during the promotion prepare phase.
- **v6.0 priorities** ([V60_COGNITIVE_SUPPORT_PRIORITIES.md](../plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md)) are orthogonal to this capability. Release channels unblock the operator from actually running the system while the v6.0 priorities continue being built. Without release channels, every v6.0 priority destabilizes the same running instance the operator is trying to use.

## Task files (to be authored by feature-breakdown)

This README is the capability boundary. Task files under this directory will be produced by running [feature-breakdown](../../.codex/skills/feature-breakdown/SKILL.md) against this spec. Candidate task names (not finalized — feature-breakdown decides):

- `DEFINE_CHANNEL_IDENTITY.md` — channel identity, code ref, DB, vault, runtime-artifact mapping.
- `SPLIT_POSTGRES_PER_CHANNEL.md` — `pkm_prod` / `pkm_dev` / `pkm_test` logical databases, connection-string resolution through the environment resolver, migration entry points.
- `DEFINE_PROMOTION_PLAN_CONTRACT.md` — shape of the promotion plan produced by `prepare-promotion`.
- `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — forward-only vs reversible migration classification and where it's declared.
- `DEFINE_CONCURRENCY_RULE.md` — separate checkouts for prod and dev processes; how this is actually arranged on a single machine.
- `DEFINE_ROLLBACK_CONTRACT.md` — previous-stable resolution, migration reversal, acceptance of vault immutability.
- `UPDATE_ENVIRONMENTS_DOC.md` — cross-doc consistency with [ENVIRONMENTS.md](../ENVIRONMENTS.md) after this spec lands.

Issue creation for these tasks and the promotion skills themselves is a later step, not part of this docs-authoring pass.
