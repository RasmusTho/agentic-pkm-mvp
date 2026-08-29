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
Last reviewed: 2026-08-22
Last live runtime verification: 2026-08-22 (selected deployment profile; `test` unavailable)
Last verified against: docs/ENVIRONMENTS.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/OPERATIONS.md, docs/DB_SCHEMA.md, docs/adr/ADR-0040-prod-promotion-ref-main-interim.md

# Release Channels Specification

## Current live posture

The operator's current topology is a dedicated model-service target plus product runtime targets defined by the
selected deployment profile. The live baseline is incomplete: `dev` answers on API and UI but is
degraded and uses the `mock` LLM provider; `test` is not available; `prod` answers API liveness but
fails functional health and has no reachable UI. The current setup-specific placement record is
[`docs/deployment/profiles/TARS_PROXMOX.md`](../deployment/profiles/TARS_PROXMOX.md).
Both live APIs report an unknown build identity. The old single-host Compose model described in this
specification is therefore a local fallback/reference model, not current live topology.

The promotion chain remains `dev → test → prod`, but it cannot start until the candidate identity is
immutable and observable, the remote deployment handoff is authoritative, `test` is reachable, and
test verification produces a durable PASS receipt. A liveness response alone is not a promotion gate.

This directory specifies the capability that lets a **stable build run in prod against the real vault** while **new feature work continues in dev across the same governed runtime fleet**, without dev churn destabilizing prod and without prod freeze blocking dev.

This is the capability that turns the existing `dev` / `test` / `prod` environment model into something the operator can actually *use* day-to-day. [ENVIRONMENTS.md](../ENVIRONMENTS.md) today defines environment selection and artifact path scoping, but it explicitly leaves deployment automation, schema separation between long-lived environments, and cross-channel safety out of scope. That gap is what blocks running a stable operator-facing system while active development continues — and therefore what this capability closes.

## Current direction: prod baseline before promotion hardening

The immediate operator priority is **establishing a stable prod baseline**, not completing the full promotion-governance workflow. These are sequential concerns, not parallel ones.

Before promotion workflows can be trusted, the prod runtime must be running safely: correct compose overlay (`docker-compose.prod.yml`), explicit project namespace (`pkm-prod`), explicit `PKM_ENVIRONMENT=prod`, and the operator-configured `.env.prod.local` default pointing at the Midgård prod vault. This binding is not optional, but it is configured once per machine rather than restated on every startup.

### Prod runtime binding

A correctly bound prod startup requires all four elements to be explicit and operator-verified before the process starts:
1. Compose file: `docker-compose.yaml:docker-compose.prod.yml`
2. Project namespace: `pkm-prod` (prevents resource collision with dev/test)
3. Environment selector: `PKM_ENVIRONMENT=prod` (controls vault root, DB name, artifact paths)
4. Vault root: `.env.prod.local` resolves to the real Midgård vault (never a dev or test path)

Use `make prod-start-full` for the canonical prod startup that enforces all four. See `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md §Startup command semantics`.

### Future promotion hardening

Once the prod baseline is stable, the promotion workflow (prepare → execute → verify → rollback) will be hardened as a separate governance layer. The test channel (`pkm-test`) is a deliberate intermediate stage in that path. What belongs to future promotion hardening and not to the current baseline:
- the `promote-to-test` and `promote-test-to-prod` staged workflows
- automated enforcement of migration reversibility classification
- durable promotion-plan acknowledgement receipts for forward-only migrations
- CI/UAT-as-test for the test channel: today `.github/workflows/harness-selfverify.yml` only runs the harness (IR-v1 UAT, channel preflight, bootstrap smoke, fault injection) and writes **no** receipt, and `ops/test-promotions/` does not exist. The current test-channel gate is therefore **harness self-verification only**; CI/UAT cannot yet substitute for a live test run because `promote-to-test` still requires a durable machine-readable receipt naming the candidate SHA, channel config, and passing check suite (see `.codex/skills/promote-to-test/SKILL.md` §"CI/UAT as substitute for a live test run"). This stays future hardening until CI emits that candidate-SHA receipt.

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

Channel isolation also does not imply a vault-global writer lock. The shipped YouTube candidate
path performs source fetch, real-time transcription, extraction, and rendering without publication
ownership; unrelated governed writes and different candidate targets can proceed concurrently.
Only the final local macOS/Linux create-once step is target-scoped: WriteGuard, invocation-owned
parent preparation, hidden complete-file stage, atomic no-replace, and a parent durability fence.
Same-target overlap is first-write-wins with no ordering or fairness guarantee. This mechanism adds
no process coordinator, global `Sources/` invariant, migration, or network/distributed semantics.

## Channel model

Three channels map one-to-one onto the existing environment model, but add identity and isolation guarantees.

DB isolation is two-layer: a **container layer** (shipped, PR #596) provides physical isolation via separate Postgres containers on dedicated host ports; a **resolver layer** (Issue #594, closed 2026-04-24, shipped) ensures application code resolves the correct DB name through `app.config.environment` rather than hard-coded strings. Both layers are shipped.

| Channel | Environment | Compose target | Postgres port | Code ref | Vault | Runtime artifacts |
| --- | --- | --- | --- | --- | --- | --- |
| **stable** | `prod` | `make prod-up` | 15432 | `main` (interim baseline — gated `stable` deferred; see [Promotion model](#promotion-model)) | real operator vault | `tmp/` |
| **dev** | `dev` | `make dev-up` | 15433 | `main` or feature branch | `vault-dev/` | `tmp-dev/` |
| **test** | `test` (workflow-driven) | `make test-up` | 15434 | current worktree | `vault-test/` | `tmp-test/` |

The channel is the operational identity; the environment is the runtime selector that resolves paths and policies. A channel's build can be inspected by resolving its code ref; its data footprint can be inspected by resolving its DB name (via Issue #594), vault root, and runtime-artifact directory.

### Multi-vault registry rollout state

Each channel now has a protected named `instance-state` volume mounted at `/app/instance-state` in
API, worker, watcher, and Heimdal capture watcher; prod's `pkm-prod_instance-state` volume is
external and the canonical prod startup/deploy wrappers provision it idempotently. All four
consumers fail-exit through one resolved-path/permissions preflight before starting and use
`/app/instance-state/agentic-pkm/vault-registry.md`. A separate private host bind at
`/app/instance-ownership` carries the HMAC-keyed canonical-root ledger shared across dev/test/prod,
preventing equal or overlapping content roots from becoming active in different channels. Canonical
wrappers resolve its source to one absolute, checkout-independent host-state path before Compose
interpolation; checkout-relative fallbacks are forbidden, and every consumer rejects an active
host-global deployment lease regardless of which channel owns it.

MVR-01B also wires the canonical deploy and start wrappers to one host-global-leased and
channel-fenced producer. Before any init or mutation, it derives dev/test/prod/native legacy owners
from canonical channel/runtime env files, stopped or running Compose writer config and scalar
stores, the native scalar store, and the governed caller binding; two identical snapshots are
required to create the private baseline. Before recreate it then installs the host lease and restart
fence, stops API, worker, watcher, and Heimdal, probes dev/test/prod/native consumers twice, and
durably proves quiescence. The owner producer must reproduce its baseline twice after that stop
before marking it drained. A missing or racing source, or an equal/nested root across owner domains,
fails closed before partial ledger seeding; a post-stop failure leaves the fence in place. While
stopped the finalizer captures the final legacy scalar payload, imports or preserves it on the
durable volume, verifies the private production-derived owner inventory, seeds the shared ledger,
optionally restores a verified backup, and creates the next registry/ledger/key backup. The fence is
removed only after that sequence succeeds; consumer preflight rejects a missing mount, missing
established state, incomplete owner bootstrap, or surviving fence without creating replacement
state. An explicitly selected rollback image that predates the runtime preflight module may pass
only the Compose-owned compatibility guard and only when the host-global lease and every channel
restart fence are absent; module absence during normal startup or deploy remains a fail-closed
error.

MVR-01C authorizes registry cutover only through one complete guarded authority revision. Until
that revision atomically installs the explicit scalar target, authenticated mutation-filtering
gateway, deny-by-default native guard, current legacy projection, minimum-runtime floor, and
roll-forward lineage, the registry remains `authority: dormant` and every registration producer
stays sealed. A complete revision makes the registry authoritative and unseals second-registration
producers in the same commit; the legacy scalar app-local file then becomes an authenticated
compatibility projection rather than independent authority. Transfer, relocation, and removal
producers remain sealed for their later owner-defined activations.

A supported previous scalar image may start only for the validated binding, with no direct host
port or non-selected content mount, through the authenticated gateway; native rollback fails
closed until it has an equivalent mutation-filtering boundary. Roll-forward runs inside the normal
host-leased, restart-fenced stopped-writer deployment window and must merge the authenticated
scalar session as the next registry revision before finalization permits recreate. Missing,
partial, divergent, stale, or interrupted state remains fenced and retryable instead of silently
falling back to either authority source. The detailed deployment mechanics are owned by
[Deployment and Environments](../deployment/DEPLOYMENT_AND_ENVIRONMENTS.md).

## Invariants (MUST hold)

These extend the cross-environment invariants in [ENVIRONMENTS.md §Cross-Environment Invariants](../ENVIRONMENTS.md) with channel-scoped isolation rules.

1. **DB-per-channel.** Each channel runs against a separate logical Postgres database in a single local cluster. The outbox, event log, and any schema-carrying table lives in the channel's own DB. No cross-channel writes. No cross-channel consumers.
2. **Vault-per-channel.** No channel ever writes to another channel's vault root. The prod vault is never targeted by dev or test processes, including during migration, reset, or experimentation.
3. **Runtime-artifacts-per-channel.** Watcher state, heartbeats, incident logs, event logs, and all other runtime artifacts stay under the channel's runtime-artifact directory. Already partially true via [ENVIRONMENTS.md §Stores and Persistence](../ENVIRONMENTS.md); this capability extends the same rule to the DB.
4. **Code-ref-per-channel.** The prod process runs code authorized by the agreed **promotion ref**. In the interim checkout model, that means a checkout pinned to the promotion ref, and the prod runtime must match it exactly with a clean working tree — no machine-local uncommitted state acting as durable truth (Issue #2527). After pinned-image cutover, that means the channel's deploy pin names an image tag built from the authorized promotion ref/SHA, and the running `/version` evidence plus deploy receipt must match that SHA. The promotion ref is currently `main` (interim baseline); a gated `stable` ref is the deferred target (see [Promotion model](#promotion-model) and [ADR-0040](../adr/ADR-0040-prod-promotion-ref-main-interim.md)). Divergence from the checkout promotion ref or a dirty prod tree is flagged by the read-only fitness guard `app/release_channels/prod_ref_fitness.py`; pinned-image drift is detected by the deployment receipt/version checks owned by `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`. Dev work must not be able to swap code under a running prod process. On a single-user machine this is satisfied before cutover by separate checkouts (git worktrees are the recommended shape), and after cutover by the absence of a live repo bind-mount plus per-channel image pins.
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
- a layer's path expression cannot be resolved, making the effective binding unverifiable, or
- the winning entry for a channel-critical key is a bare `KEY` line (no `=`): compose treats it as unset/host-environment passthrough at `compose up` time, so the effective binding is unverifiable at preflight time (a later layer that redefines the key still supersedes it).

A `required: false` layer that is absent at preflight time contributes nothing, exactly as compose treats it; the preflight verifies the layering **as it stands at preflight time** — creating or editing env-file layers after the preflight and before stack start bypasses the guard. When no base compose file sits next to the overlay, the base layering is modeled as the single committed defaults file, preserving the #1655 contract.

Omission is only acceptable when the chain-resolved value already binds the intended channel. The prod overlay is explicit about prod/app DSNs because local dev startup also writes `tmp/runtime.env`; prod must not depend on that default optional layer being absent or already prod-shaped. Those explicit prod DSNs may use Compose interpolation defaults (for example, `${DATABASE_URL:-.../app}`) so intentional prod overrides remain reachable, but the preflight resolves the expression and still rejects `app_dev` / `app_test`. This is channel-aware resolution of one shared rule, not a per-channel behavior split.

Explicit overlay DSNs do not suppress structural `env_file` chain validation. Even when
`DATABASE_URL` and `DB_DSN` are declared with channel-correct values, the preflight still
fail-closes on declared required layers that are missing, unreadable, or have unresolvable path
expressions, because Compose must still resolve and load the service's `env_file` chain safely.

**Enforcement:** `app/release_channels/channel_isolation_preflight.py` is a read-only preflight guard that fail-closes when a compose overlay's effective env bindings do not match the intended channel. It is invoked:

- by `scripts/test/test_ui_doctor.sh` (and therefore `make test-ui-doctor`) before any Docker or network check;
- by `make check-test-channel` via `tests/release_channels/test_channel_isolation_preflight.py`;
- and should be called at the start of `promote-to-test` / `execute-promotion` before any stack mutation.

The guard is **read-only**: it reports and fail-closes; it never edits operator files. When it fails, the operator must correct the compose overlay to match the intended channel before proceeding.

### Environment:-vs-env_file: blank-override clobber invariant (Issue #4230)

Independent of the DSN/`PKM_ENVIRONMENT` isolation guard above, a service's compose `environment:` block always wins over its `env_file:` chain for the **same key**, whatever value it resolves to — including an accidental blank one. `scripts/lib/deploy_channel_compose.sh` deliberately never passes the governed runtime env file as a Compose CLI `--env-file` (that would expose DSNs to Compose interpolation, #3875), so an overlay entry shaped like `${VAR:-}` interpolates to an empty string against the invoking shell and **silently shadows** whatever value the same key would otherwise receive from the service's `env_file` chain. This crash-looped `heimdal-capture-watch` on every dev-channel deploy until commit `f95a6811` deleted the offending `environment:` entries.

**Enforcement:** `app/release_channels/channel_isolation_preflight.py::check_environment_env_file_clobber` detects this shape for every `CHANNEL_SERVICES` service (channel-agnostic — it only compares an override's resolved value against the same key's env_file-chain value, not which channel a binding belongs to). It inspects the **merged** base-plus-overlay per-service `environment:` mapping (Compose merges these per key, overlay wins), so a blank override inherited from the base `docker-compose.yaml` is detected even when the overlay never redeclares the key — or omits the service entirely (#4613). A literal explicit value (including a deliberate literal `""`, e.g. the test channel's fail-closed `WATCHER_VAULT_PATH: ""`) is never flagged — only a value containing a shell-interpolation token (`$...`) that resolves to an empty string while the env_file chain would otherwise supply a non-empty value counts as a clobber.

`scripts/dev_test_environment_clobber_preflight.py` wraps the check for `scripts/deploy_channel.sh`'s `dev` and `test` channel `deploy` actions, invoked before `write_pin` / migration execution. The wrapper resolves Compose interpolation against the same sources as the real invocation — the selected `--env-file config/deploy/<channel>.env` layered under the invoking shell, never the repo-root `.env`, which a `--env-file` replaces (#4613). The invocation point keeps the same placement and read-only, deploy-only-by-contract posture as the pre-existing prod-only pending-retry preflight (`prod_pending_retry_preflight`, #3903). It is deliberately not wired to the prod channel or to `rollback`: prod already carries an analogous, DSN-scoped resolver call (`prod_pending_retry_preflight` / `app.release_channels.channel_isolation_preflight.resolve_effective_dsn`), and rollback must stay ungated so the prior stable ref is always recoverable ([Rollback contract](DEFINE_ROLLBACK_CONTRACT.md)).

## Promotion model

This section records the **current** prod promotion model and how it relates to the **target** gated model below. It is the authoritative reconciliation of the channel table and Invariant 4 with what prod actually runs (Issue #2527; [ADR-0040](../adr/ADR-0040-prod-promotion-ref-main-interim.md)).

### Current: prod tracks `main` (interim baseline)

Prod's promotion ref is **`main`**. The prod process runs from a checkout pinned to `main` with a clean working tree; there is no gated `stable` indirection in force today. This is the interim baseline established while the UI and docs capabilities stabilize in dev — establishing a trustworthy prod runtime comes before promotion-governance hardening (see [Current direction](#current-direction-prod-baseline-before-promotion-hardening)).

#### Current migration reversibility applicability

The migration-reversibility classification is already an operator-safety policy for the current
`main`-tracking production path. Before a migration is run against the active `app` DB under
compose project `pkm-prod`, it must be classified as reversible or forward-only. An
unclassified migration blocks the current prod migration operation. A forward-only migration
requires an explicit operator decision before it runs.

The current baseline does not yet automate that check or create the target promotion-plan
acknowledgement receipt. Those mechanisms belong to the deferred gated-`stable` promotion workflow;
they make the existing active applicability enforceable and auditable, rather than changing which
production database the classification protects.

The read-only `cutover_readiness` preflight is local/CI evidence only, not a deployment or migration
receipt. When Alembic reports more than one current head, it treats the union of their ancestor
sets as already applied; only revisions outside that union are pending. It therefore does not
misclassify an already-applied merge parent as pending.

`origin/stable` (`e2892b18`) is **dormant** and does **not** reflect what prod runs: as of 2026-06-29 it is not an ancestor of `origin/main` (hundreds of commits of divergence under squash-merge history). It must not be treated as the prod source-of-truth until it is restored as a gated ref. The promotion **skills** (`prepare-promotion`, `execute-promotion`, `verify-promotion`, `promote-test-to-prod`) describe the target gated model and remain valid for that future; they do not describe the current `main`-tracking baseline.

**Reproducibility invariant.** Prod must be reconstructible from git alone. The prod runtime HEAD must equal the promotion ref and the working tree must be clean — no uncommitted, machine-local state as durable truth (the Issue #2527 finding was a prod checkout dirty with tracked modifications that existed nowhere in git). The read-only guard `app/release_channels/prod_ref_fitness.py` (Issue #2527 AC3) flags a prod checkout that diverges from the promotion ref or runs a dirty tree; the operator runs it on the prod host to produce the clean-tree receipt:

```
python -m app.release_channels.prod_ref_fitness /Users/rasmus/workspace --promotion-ref main
```

### Deployment model switch: checkout now, pinned image after cutover

The promotion authority above decides **which SHA** prod may run; the deployment model decides **how**
that SHA becomes live. Until a channel's cutover receipt exists (fleet-model fitness PASS recorded in
`ops/deployments/<channel>-latest.json`), that channel stays in the checkout model and the checkout
procedure remains the executable interim path. After the receipt exists, the channel is in the
pinned-image model: the authorized SHA is applied by bumping the channel image pin and recreating via
`scripts/deploy_channel.sh`, with the deploy receipt and live `/version` evidence proving the running
code. This switch does not move ADR-0040 authority: prod's interim promotion ref remains `main` until
a later ADR restores gated `stable`.

### Target: gated `stable` promotion (deferred hardening)

The four-phase gated model in [Promotion contract](#promotion-contract) — prepare → execute → verify → rollback, advancing a protected `stable` ref — is the **target**, deferred to promotion hardening (see [Future promotion hardening](#future-promotion-hardening)). Restoring `stable` as a gated promotion ref, and switching prod from `main`-tracking to `stable`-tracking, is future work that descends from Issue #2527; until then the current baseline above governs.

## Promotion contract

> **This section describes the _target_ gated model — deferred promotion hardening.** The current prod baseline tracks `main` directly; see [Promotion model](#promotion-model) and [ADR-0040](../adr/ADR-0040-prod-promotion-ref-main-interim.md).

Promotion is the operation that turns an accepted commit on `main` into the running `stable` build in prod. It has four explicit phases:

1. **Prepare.** Diff `main` against the current `stable` ref. Enumerate:
   - code delta (commits/PRs included);
   - migration delta (schema changes to apply to the current `app` DB under compose project `pkm-prod`);
   - config / settings delta;
   - risk notes (flags, known regressions, acceptance-criteria status of included PRs).
   The prepare phase produces a **promotion plan** the operator can review before executing.
2. **Execute.** Advance the `stable` ref via a governed PR targeting `stable`. Apply migrations to the current `app` DB under compose project `pkm-prod`. Restart the prod process from the updated `stable` checkout. Promotion is a single operator-triggered step, not a background automation.
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

**Current state (2026-06-29, Issue #2527):** `git merge-base --is-ancestor origin/stable origin/main` returns **non-zero** — `origin/stable` (`e2892b18`) is **not** an ancestor of `origin/main` (hundreds of commits of divergence under squash-merge history; an earlier 2026-06-06 reconciliation has since drifted). This is the dormant-`stable` drift recorded in [Promotion model](#promotion-model) and [ADR-0040](../adr/ADR-0040-prod-promotion-ref-main-interim.md). It does **not** block the current baseline — prod tracks `main` directly — but the gated `stable` promotion path above cannot run until `stable` is restored as an ancestor of the candidate.

## Rollback posture

- The previous stable ref is always resolvable (recorded as `stable-prev` pointer file in `ops/promotions/` before any stable movement).
- Rollback proceeds via a **governed revert PR targeting `stable`**, not a direct ref write. The revert PR must pass the same required status checks as a promotion PR. After merge, prod is updated to the merged `origin/stable` rollback commit before reversible migrations are reversed; `stable-prev` remains the rollback target/anchor.
- Migrations are classified at promotion time as **reversible** or **forward-only**. Forward-only migrations are allowed but require the operator to acknowledge that rollback cannot restore DB shape.

### Runtime floors constrain which images are valid rollback targets

Rollback is a tag-bump, but not every previous tag is a legal target. A shipped **runtime
floor** recorded in instance state names the minimum image capability that may run, and the
runtime refuses an older one rather than starting degraded.

Currently recorded floors:

| Floor key | Value | Shipped by | Blocks |
| --- | --- | --- | --- |
| `minimumRuntimeSchema` | `mvr-05` | MVR-05A8 (#4582), on the MVR-01B/01C floor mechanism | scalar API/worker startup before binding-keyed DB/outbox authority |
| `minimumRuntimePrincipal` | `mvr-03` | MVR-03 (#3857) | a credential-only image with no delegated-principal producer |

`minimumRuntimeSchema` is written only inside the proved host-global deployment window. The
wrapper resolves the effective channel Compose graph, requires a DB-role declaration for every
service, stops every client except the unique migration runner, proves Docker/native quiescence and
an empty PostgreSQL client-session population, then records the floor before migration or runtime writes.
Consequently an image without the binding-aware compatibility ingress and worker gate is not a
legal rollback target even when its tag remains available. The wrapper identifies that capability
by the target tree's `app/instance/mvr05_cutover.py` marker; the older generic
`app/instance/runtime.py` is not evidence that an image can honor this floor.

`minimumRuntimePrincipal` is set together with the private delegated operator-role cutover only
when a channel deployment carries the explicit `MVR03_PRINCIPAL_CUTOVER=1` opt-in. The governed
dev/test/prod channel files each declare that their Docker-published API is not a proven loopback
listener; the deployment wrapper resolves that channel declaration and passes the same posture to
the single-process floor/role cutover. A pre-MVR-03 image cannot resolve a principal at all, so
`app/instance/runtime.py::_require_runtime_floor` refuses it during scalar-rollback preflight,
*before* any legacy projection is materialized. The compatible path is roll-forward: the prior
image's final credential/auth revision is exported under lock and reconciled into the same
role id, and an ambiguous or divergent lineage fails closed without overwriting either side.

A floor is lowered only by a later explicitly verified reversible migration. Rolling the
`stable` ref back does not lower it, and forward-only acknowledgement at promotion time does
not authorize crossing it. The automated cutover operations live in
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Minimum runtime schema floor` and
`:: Minimum runtime principal floor`.

### Vault is not release state

The real prod vault is the operator's authored content. It is **never rewound by a release rollback operation**. Rolling back the `stable` ref and reversing DB migrations does not alter vault notes, companion notes, or any operator-authored file under the vault root.

This is a deliberate invariant: the vault is a human cognitive surface, not a deployment artifact. Release operations (promote, rollback) are scoped to code, DB schema, and runtime artifacts only. Note-level undo is a vault-level concern (operator action or vault history), not a channel-level concern.

## Verification path (pre-merge, per task)

This capability is docs-authoring at this stage. Task-level verification lives in the task files under this directory once [feature-breakdown](../../.codex/skills/feature-breakdown/SKILL.md) runs. Expected task-level `Verify:` shapes:

- Behavioral ACs pointing at integration tests that exercise the **target-state, unshipped** channel-isolation split (e.g. a dev process cannot connect to the planned `pkm_prod`, a dev write cannot hit `vault/`).
- Non-behavioral ACs pointing at doc writeback anchors (this README, ENVIRONMENTS.md update), at the promotion skills under `.codex/skills/`, and at the promotion plan shape when produced.

## Validation / acceptance path (post-merge)

Capability-level acceptance — the point at which the operator can honestly claim the system is usable — requires the following observable conditions, not a single test:

- A **stable build** is running against the real vault and has run unsupervised for a bounded soak window (measured, not asserted).
- A **dev session** on its isolated runtime host has exercised schema change, vault reset, and runtime restart without altering prod state.
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
- **[LOCAL_TEST_BOOTSTRAP](../LOCAL_TEST_BOOTSTRAP/)** continues to own the `test` channel's bootstrap golden path. The **target-state, unshipped** DB-per-channel split adds the planned `pkm_test` rule.
- **[HEALTH.md](../HEALTH.md)** owns the health contract used during the verify phase of promotion.
- **[DB_SCHEMA.md](../DB_SCHEMA.md)** owns schema definition; migration reversibility classification lives there, referenced during the promotion prepare phase.
- **v6.0 priorities** ([V60_COGNITIVE_SUPPORT_PRIORITIES.md](../plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md)) are orthogonal to this capability. Release channels unblock the operator from actually running the system while the v6.0 priorities continue being built. Without release channels, every v6.0 priority destabilizes the same running instance the operator is trying to use.

## Task files

This README is the capability boundary. Task files under this directory are now authored and should
be treated as the bounded specification set for the release-channels capability:

- `DEFINE_CHANNEL_IDENTITY.md` — channel identity, code ref, DB, vault, runtime-artifact mapping.
- `SPLIT_POSTGRES_PER_CHANNEL.md` — the **target-state, unshipped** `pkm_prod` / `pkm_dev` / `pkm_test` logical databases, connection-string resolution through the environment resolver, migration entry points.
- `DEFINE_PROMOTION_PLAN_CONTRACT.md` — shape of the promotion plan produced by `prepare-promotion`.
- `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` — forward-only vs reversible migration classification and where it's declared.
- `DEFINE_CONCURRENCY_RULE.md` — separate checkouts for prod and dev processes; how this is actually arranged on a single machine.
- `DEFINE_ROLLBACK_CONTRACT.md` — previous-stable resolution, migration reversal, acceptance of vault immutability.
- `UPDATE_ENVIRONMENTS_DOC.md` — cross-doc consistency with [ENVIRONMENTS.md](../ENVIRONMENTS.md) after this spec lands.

Feature acceptance, operator validation receipts, and any remaining follow-up issue work still live
outside this README.
