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

State: Active specification for the release-channels capability. Promotion skills now exist under `.codex/skills/`; this doc remains the canonical boundary and invariant contract they consume.
Doc role: Core SoT for the release-channels capability
Owner: `docs/ROADMAP.md`
Temporal class: strategic
Review cadence: biweekly
Last reviewed: 2026-04-21
Last verified against: docs/ENVIRONMENTS.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/OPERATIONS.md, docs/DB_SCHEMA.md

# Release Channels Specification

This directory specifies the capability that lets a **stable build run in prod against the real vault** while **new feature work continues in dev on the same machine**, without dev churn destabilizing prod and without prod freeze blocking dev.

This is the capability that turns the existing `dev` / `test` / `prod` environment model into something the operator can actually *use* day-to-day. [ENVIRONMENTS.md](../ENVIRONMENTS.md) today defines environment selection and artifact path scoping, but it explicitly leaves deployment automation, schema separation between long-lived environments, and cross-channel safety out of scope. That gap is what blocks running a stable operator-facing system while active development continues — and therefore what this capability closes.

## Current direction: prod baseline before promotion hardening

The immediate operator priority is **establishing a stable prod baseline**, not completing the full promotion-governance workflow. These are sequential concerns, not parallel ones.

Before promotion workflows can be trusted, the prod runtime must be running safely: correct compose overlay (`docker-compose.prod.yml`), explicit project namespace (`pkm-prod`), explicit `PKM_ENVIRONMENT=prod`, and an operator-supplied `VAULT_ROOT` pointing at the real vault. This binding is not optional and cannot be defaulted.

### Prod runtime binding

A correctly bound prod startup requires all four elements to be explicit and operator-verified before the process starts:
1. Compose file: `docker-compose.yaml:docker-compose.prod.yml`
2. Project namespace: `pkm-prod` (prevents resource collision with dev/test)
3. Environment selector: `PKM_ENVIRONMENT=prod` (controls vault root, DB name, artifact paths)
4. Vault root: operator-supplied absolute path to the real vault (never a dev or test path)

Use `make prod-start-full VAULT_ROOT=<path>` for the canonical prod startup that enforces all four. See `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md §Startup command semantics`.

### Future promotion hardening

Once the prod baseline is stable, the promotion workflow (prepare → execute → verify → rollback) will be hardened as a separate governance layer. The test channel (`pkm-test`) is a deliberate intermediate stage in that path. What belongs to future promotion hardening and not to the current baseline:
- the `promote-to-test` and `promote-test-to-prod` staged workflows
- automated migration reversal classification
- operator acknowledgement receipts for forward-only migrations
- CI/UAT-as-test policy for the test channel

The absence of these does not block establishing a prod baseline. Operators should not wait for promotion hardening to run prod.

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

Three channels map one-to-one onto the existing environment model, but add identity and isolation guarantees.

DB isolation is two-layer: a **container layer** (shipped, PR #596) provides physical isolation via separate Postgres containers on dedicated host ports; a **resolver layer** (Issue #594, in progress) ensures application code resolves the correct DB name through `app.config.environment` rather than hard-coded strings. Both layers are required.

| Channel | Environment | Compose target | Postgres port | Code ref | Vault | Runtime artifacts |
| --- | --- | --- | --- | --- | --- | --- |
| **stable** | `prod` | `make prod-up` | 15432 | `stable` (tag or branch) | real operator vault | `tmp/` |
| **dev** | `dev` | `make dev-up` | 15433 | `main` or feature branch | `vault-dev/` | `tmp-dev/` |
| **test** | `test` (workflow-driven) | `make test-up` | 15434 | current worktree | `vault-test/` | `tmp-test/` |

The channel is the operational identity; the environment is the runtime selector that resolves paths and policies. A channel's build can be inspected by resolving its code ref; its data footprint can be inspected by resolving its DB name (via Issue #594), vault root, and runtime-artifact directory.

## Invariants (MUST hold)

These extend the cross-environment invariants in [ENVIRONMENTS.md §Cross-Environment Invariants](../ENVIRONMENTS.md) with channel-scoped isolation rules.

1. **DB-per-channel.** Each channel runs against a separate logical Postgres database in a single local cluster. The outbox, event log, and any schema-carrying table lives in the channel's own DB. No cross-channel writes. No cross-channel consumers.
2. **Vault-per-channel.** No channel ever writes to another channel's vault root. The prod vault is never targeted by dev or test processes, including during migration, reset, or experimentation.
3. **Runtime-artifacts-per-channel.** Watcher state, heartbeats, incident logs, event logs, and all other runtime artifacts stay under the channel's runtime-artifact directory. Already partially true via [ENVIRONMENTS.md §Stores and Persistence](../ENVIRONMENTS.md); this capability extends the same rule to the DB.
4. **Code-ref-per-channel.** The prod process runs from a checkout pinned to the `stable` ref. Dev work must not be able to swap code under a running prod process. On a single-user machine this is satisfied by running prod and dev from separate checkouts (git worktrees are the recommended shape).
5. **Promotion is explicit and recorded.** No implicit promotion. Every stable-ref movement is an intentional operator act with a resolvable receipt (git tag annotation, log entry, or equivalent).
6. **Rollback is always available.** The previous stable ref is always resolvable and the migration reversal path is always specified at promotion time. If a migration is not reversibly specified, the promotion is rejected.
7. **Same contracts everywhere.** Channel separation does not change the event envelope, artifact identity, provenance, receipt semantics, or write-safety rules. A channel is an operational boundary, not a different product.

### Compose/env binding invariant (Issues #1627, #1655, #1769)

A channel's compose overlay must bind `PKM_ENVIRONMENT`, `DATABASE_URL`, and `DB_DSN` to values that match the **intended channel** — not another channel. A test stack whose compose declares `PKM_ENVIRONMENT=prod` would direct all writes at prod resources despite running under the test project namespace; this is a channel-isolation breach.

**Omitted bindings are violations (Issue #1655).** The base compose file feeds every app service (`api`, `worker`, `watcher`) from an `env_file` chain whose first layer is `config/runtime.defaults.env` (prod `app` DSNs). If a channel's overlay omits `DATABASE_URL` / `DB_DSN` for a channel-critical service — by dropping the keys or the entire service block — compose layering silently resolves the binding from that chain. The preflight therefore checks the **effective** binding and fail-closes when it lands on another channel or cannot be verified.

**Resolution follows the full env_file chain (Issue #1769).** Compose services may declare multiple `env_file` entries and **later files win**: the base services layer `${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}` (written by `scripts/export_runtime_env.sh`, carrying `DATABASE_URL` / `DB_DSN`) *after* the defaults file, so the defaults alone are not the effective binding. For omitted DSN keys, the preflight resolves the per-service `env_file` chain of the merged compose model (base `docker-compose.yaml` + overlay, overlay entries appended) in declaration order, interpolating `${VAR:-default}` path expressions the way compose does (invoking environment first, then `.env` in the compose directory). It fail-closes when:

- the effective DSN resolves to another channel (e.g. a prod overlay whose omitted DSN is won by a `tmp/runtime.env` layer carrying `app_test`), or
- a layer that would win exists but cannot be read, or
- a **required** layer is missing at preflight time (compose would refuse to start; the preflight does not silently assume absence), or
- a layer's path expression cannot be resolved, making the effective binding unverifiable.

A `required: false` layer that is absent at preflight time contributes nothing, exactly as compose treats it; the preflight verifies the layering **as it stands at preflight time** — creating or editing env-file layers after the preflight and before stack start bypasses the guard. When no base compose file sits next to the overlay, the base layering is modeled as the single committed defaults file, preserving the #1655 contract.

Omission is only acceptable when the chain-resolved value already binds the intended channel (e.g. `docker-compose.prod.yml` relies on the prod base defaults and a prod-channel runtime layer). This is channel-aware resolution of one shared rule, not a per-channel behavior split.

**Enforcement:** `app/release_channels/channel_isolation_preflight.py` is a read-only preflight guard that fail-closes when a compose overlay's effective env bindings do not match the intended channel. It is invoked:

- by `scripts/test/test_ui_doctor.sh` (and therefore `make test-ui-doctor`) before any Docker or network check;
- by `make verify-test-channel` via `tests/release_channels/test_channel_isolation_preflight.py`;
- and should be called at the start of `promote-to-test` / `execute-promotion` before any stack mutation.

The guard is **read-only**: it reports and fail-closes; it never edits operator files. When it fails, the operator must correct the compose overlay to match the intended channel before proceeding.

## Promotion contract

Promotion is the operation that turns an accepted commit on `main` into the running `stable` build in prod. It has four explicit phases:

1. **Prepare.** Diff `main` against the current `stable` ref. Enumerate:
   - code delta (commits/PRs included);
   - migration delta (schema changes to apply to `pkm_prod`);
   - config / settings delta;
   - risk notes (flags, known regressions, acceptance-criteria status of included PRs).
   The prepare phase produces a **promotion plan** the operator can review before executing.
2. **Execute.** Advance the `stable` ref via a governed PR targeting `stable`. Apply migrations to `pkm_prod`. Restart the prod process from the updated `stable` checkout. Promotion is a single operator-triggered step, not a background automation.
3. **Verify.** Post-promotion health, status, and smoke checks against the running prod. Health must be green against [HEALTH.md](../HEALTH.md) contracts before the promotion is considered accepted.
4. **Rollback (conditional).** If verification fails, return `stable` through a governed rollback PR, update prod to the merged `origin/stable` rollback commit, reverse any reversible migrations, and restart. Non-reversible migrations must be flagged during prepare so the operator chooses knowingly.

Promotion trigger is **manual, single-user**. No PR-merge-triggered automation, no CI-driven promotion. The operator decides when to promote.

### Protected-branch promotion invariant

`origin/stable` is a protected branch (`enforce_admins: true`; required status checks: `smoke`, `smoke-docker`, `pr-contract`; PR required). **Direct pushes and refs-API updates are rejected.**

Every stable-ref movement — whether forward (promotion) or backward (rollback) — proceeds through a governed PR targeting `stable`. The PR must pass all three required status checks before an operator merges it. This is non-negotiable; the protection must not be weakened.

### Ancestry preflight invariant

Before any stable-ref movement, `execute-promotion` verifies:

```bash
git merge-base --is-ancestor origin/stable <candidate-sha>
```

If this check fails, promotion aborts fail-closed with a reconciliation-PR instruction. Promotion cannot proceed until `stable` is an ancestor of the candidate.

**Current state (verified 2026-06-06):** `git merge-base --is-ancestor origin/stable origin/main` returns exit 0 — PASS. stable/main divergence is resolved.

## Rollback posture

- The previous stable ref is always resolvable (recorded as `stable-prev` pointer file in `ops/promotions/` before any stable movement).
- Rollback proceeds via a **governed revert PR targeting `stable`**, not a direct ref write. The revert PR must pass the same required status checks as a promotion PR. After merge, prod is updated to the merged `origin/stable` rollback commit before reversible migrations are reversed; `stable-prev` remains the rollback target/anchor.
- Migrations are classified at promotion time as **reversible** or **forward-only**. Forward-only migrations are allowed but require the operator to acknowledge that rollback cannot restore DB shape.

### Vault is not release state

The real prod vault is the operator's authored content. It is **never rewound by a release rollback operation**. Rolling back the `stable` ref and reversing DB migrations does not alter vault notes, companion notes, or any operator-authored file under the vault root.

This is a deliberate invariant: the vault is a human cognitive surface, not a deployment artifact. Release operations (promote, rollback) are scoped to code, DB schema, and runtime artifacts only. Note-level undo is a vault-level concern (operator action or vault history), not a channel-level concern.

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

## Promotion skills

The repo-local operator skills now exist as downstream governance artifacts. This spec still owns the
capability boundary and invariants; the skills consume those contracts rather than redefine them. One
skill per job, per the human-first one-agent-one-job principle:

- `prepare-promotion` — produce the promotion plan (code/migration/config delta, risk notes, AC status).
- `execute-promotion` — move the `stable` ref, apply migrations, restart prod.
- `verify-promotion` — post-promotion health, status, and smoke checks.
- `rollback-promotion` — merge governed rollback PR, update prod to merged `origin/stable`, reverse reversible migrations, restart.

The skills remain downstream artifacts. Their shape is specified in the task files and the skill
entrypoints under `.codex/skills/`, not redefined here.

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

## Task files

This README is the capability boundary. Task files under this directory are now authored and should
be treated as the bounded specification set for the release-channels capability:

- `DEFINE_CHANNEL_IDENTITY.md` — channel identity, code ref, DB, vault, runtime-artifact mapping.
- `SPLIT_POSTGRES_PER_CHANNEL.md` — `pkm_prod` / `pkm_dev` / `pkm_test` logical databases, connection-string resolution through the environment resolver, migration entry points.
- `DEFINE_PROMOTION_PLAN_CONTRACT.md` — shape of the promotion plan produced by `prepare-promotion`.
- `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — forward-only vs reversible migration classification and where it's declared.
- `DEFINE_CONCURRENCY_RULE.md` — separate checkouts for prod and dev processes; how this is actually arranged on a single machine.
- `DEFINE_ROLLBACK_CONTRACT.md` — previous-stable resolution, migration reversal, acceptance of vault immutability.
- `UPDATE_ENVIRONMENTS_DOC.md` — cross-doc consistency with [ENVIRONMENTS.md](../ENVIRONMENTS.md) after this spec lands.

Feature acceptance, operator validation receipts, and any remaining follow-up issue work still live
outside this README.
