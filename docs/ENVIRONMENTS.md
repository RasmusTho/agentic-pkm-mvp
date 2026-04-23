# Environments

State: SoT v5.5 baseline with explicit `dev` / `test` / `prod` environment model, control surfaces, and artifact separation (Issues #263, #266), with the local `test` environment documented as the canonical bootstrap and verification posture. Channel-level identity, per-channel DB isolation, promotion, and rollback are specified by the v6.0 release-channels capability at `docs/RELEASE_CHANNELS/README.md`; this document continues to own environment selection and path scoping only.
Doc role: Core SoT
Authority: Canonical environment contract for the current baseline and forward-line work; defines what `dev`, `test`, and `prod` mean, what must remain invariant, and what may vary. Architecture, operations, testing, status, and component docs should reference this document instead of restating environment policy. Release-channel semantics (channel identity, DB-per-channel, promotion, rollback) are owned by `docs/RELEASE_CHANNELS/README.md`.

## Overview

This document defines the active environment model for the repo, specifies the control surfaces for runtime environment selection and artifact path scoping, and documents the cross-environment invariants that must hold.

The purpose of this document is to make environment boundaries explicit and ensure that supported environments maintain clear vault, store, and runtime boundaries when isolation is required.

Reading rule:
- Use this document when a change touches environment-specific behavior, storage boundaries, runtime topology, write safety, rollout posture, or local bootstrap expectations.
- Use `docs/ARCHITECTURE.md` for system structure, `docs/OPERATIONS.md` for operator procedure, `docs/TESTING.md` for verification layers, and `docs/STATUS.md` for current rollout posture.

## Minimal Environment Model

The repo uses a lightweight but explicit environment model:

- `dev` = flexible local development environment
- `test` = isolated, resettable, reproducible verification environment
- `prod` = future target contract for the operator-facing runtime

Interpretation rule:
- environment names describe operational posture, not different product semantics
- `test` is the first concrete reference environment for the current stabilization wave
- `prod` is a target contract with important current behavior already present, but it should not be described as a fully completed end-state environment story

## Environment Definitions

### `dev`
- **Purpose**: development, experimentation, debugging, local validation, and bounded forward-line exploration.
- **Isolation level**: flexible. Separate vaults and stores are strongly preferred, but the posture is optimized for iteration rather than strict reproducibility.
- **Vault/state/runtime boundaries**: may use local fixtures, dev-specific vault roots, selective resets, mock providers, and extra diagnostics.
- **Implemented now**: explicit runtime selection exists today through `PKM_ENVIRONMENT=dev` or `PKM_SETTINGS_PROFILE=lab`.
- **Not implied**: `dev` is not the canonical proof path for release readiness.

### `test`
- **Purpose**: isolated, resettable, reproducible local verification and UAT against a clean vault.
- **Isolation level**: explicit and strong. `test` must not depend on a live dev vault, hidden folder hints, or leftover runtime state.
- **Vault/state/runtime boundaries**: separate clean vault, resettable runtime artifacts, and a scripted bootstrap/UAT path that can be rerun from a clean start.
- **Implemented now**: `test` is the first concrete reference environment for bootstrap and verification. Today it is expressed through the repo-supported bootstrap path (`make test-bootstrap`, `make test-vault-init`, `uat-*`, and `scripts/start_full_system.sh`) rather than as a third first-class `PKM_ENVIRONMENT` selector.
- **Target contract**: this is the repo-supported local verification environment that should become self-contained end to end.

### `prod`
- **Purpose**: the operator-facing runtime used against a real vault and its associated runtime surfaces.
- **Isolation level**: conservative and safety-first.
- **Vault/state/runtime boundaries**: the real vault and its continuity artifacts must remain clearly separated from development and test surfaces.
- **Implemented now**: important production-facing contracts already exist, including the operator-safe default posture, health/status surfaces, write-safety expectations, and the current runtime path.
- **Still a target contract**: `prod` should be treated as the future end-state contract for the full operator environment, not as a claim that every operational detail is complete today.

## Cross-Environment Invariants

The following are SoT invariants and MUST remain true in `dev`, `test`, and `prod`:
- The same architecture contracts apply: vault-first human surface, companion/system surface, and rebuildable runtime surface.
- The event envelope and outbox semantics remain stable; DB outbox is canonical runtime queue semantics.
- Writes to tracked notes remain deterministic and guarded by write-safety and idempotency rules.
- Artifact identity, provenance, and receipt semantics do not change by environment.
- Settings and policy remain the control surface for runtime behavior; environment selection must not bypass policy, allowlists, or write guards.
- A real environment split must not redefine the human-facing contract in `docs/HUMAN-FLOWS.md`.

Environment is therefore an operational/runtime distinction, not a different ontology of artifacts or a different semantic model of the product.

## Allowed Variation by Environment

The following may vary between `dev`, `test`, and `prod` without breaking SoT, as long as the invariants above remain intact:
- runtime scale, process topology, and startup wrappers
- provider choice and model profile
- diagnostic verbosity, mocks, and test fixtures
- watcher cadence, tuning, and other explicit lab-only controls
- local fixture vaults, test stores, reset/reseed workflows, and scripted bootstrap wrappers
- operator gating and rollout posture for mutation-capable automation

**Variation rule**: environment-specific defaults may vary; environment-specific contract semantics may not.

## Separation Requirements

Environment separation MUST be explicit across the following surfaces.

### Vaults and Human-Facing Files
- `prod` must operate on the operator's real vault and its associated continuity artifacts.
- `dev` should use a separate fixture, test, or otherwise intentionally non-production vault when environment-specific experimentation or validation is being performed.
- `test` must use a separate clean vault dedicated to the repo-supported bootstrap/UAT path. The canonical local target is `vault-test/` when following `make test-bootstrap`.
- `dev`, `test`, and `prod` must not implicitly share the same writable vault surface when the purpose is environment isolation.

**Implementation Status (Issue #266)**:
- Vault paths are now environment-scoped via `app.config.paths.resolve_vault_root()`.
- Default behavior: `prod` uses `vault/`, `dev` uses `vault-dev/`.
- The `test` path currently uses the explicit bootstrap commands and `TEST_VAULT_ROOT`, which intentionally sit beside the runtime selector while the local verification contract is stabilized.
- Custom overrides via CLI flags bypass environment scoping.

### Stores and Persistence
- `prod` runtime persistence must be treated as production data even when it is rebuildable from the file-based continuity set.
- `dev` stores, indexes, and outbox state may be reset, rebuilt, or replaced for testing.
- `test` runtime state may be reset and rebuilt as part of the supported bootstrap contract; repeatability is more important than persistence.
- Rebuildable does not mean disposable in `prod`; recovery and audit expectations still apply.

**Implementation Status (Issue #266 + #594)**:
- Index outbox and store paths are now environment-scoped via `app.config.paths.resolve_runtime_artifact_path()`.
- Default behavior: `prod` uses `tmp/` subdirectories, `dev` uses `tmp-dev/` subdirectories.
- Watcher settings automatically apply environment scoping to all artifact paths via `load_watcher_settings(environment=...)`.
- PostgreSQL now follows per-environment database naming conventions for runtime stacks:
  - `prod`: `app`
  - `dev`: `app_dev`
  - `test` bootstrap/runtime lane: `app_test`
- Explicit `DATABASE_URL` / `DB_DSN` still overrides environment-derived conventions.
- File-based audit logs respect environment separation.
- The `test` path currently relies on explicit reset/bootstrap commands and test-specific runtime artifacts rather than a separate runtime selector.

### Runtime State and Process Surfaces
- Watcher state, heartbeats, tick logs, incident logs, and similar runtime artifacts must be interpreted as environment-scoped operational surfaces.
- `dev` may expose extra diagnostics and lab-only controls.
- `test` may reuse the standard local runtime topology, but the repo-supported bootstrap path must reset runtime state before verification and must not rely on leftover watcher pause/state files.
- `prod` must keep these surfaces stable enough to support operator verification and incident triage.

**Implementation Status (Issue #266)**:
- Watcher heartbeat, state files, and event logs are now environment-scoped.
- Default behavior: `prod` uses base artifact paths (`tmp/watcher_state.json`), `dev` uses `-dev` subdirectories (`tmp-dev/watcher_state.json`).
- Incidents and audit surfaces respect environment separation to prevent cross-environment contamination.
- The `test` bootstrap path resets runtime state explicitly before startup and verification.

### Settings and Policy Surfaces
- Environment selection must resolve through explicit settings/runtime configuration, not through undocumented convention.
- Lab/dev-only tuning must remain excluded from normal production runtime unless explicitly enabled by the documented control surface.
- The local `test` path may remain workflow-driven while the runtime selector stays limited to `dev` and `prod`, as long as the supported bootstrap contract remains explicit.

## Production Safety Expectations

`prod` carries the following additional expectations:
- safety beats convenience when the two conflict
- bounded writes only; no silent broad note mutation
- degraded or blocked mode is preferable to unsafe mutation
- health, status, and operator verification surfaces must remain meaningful
- rollout of mutation-capable automation must remain explicitly gated
- recovery paths must preserve the continuity set: vault notes plus companion notes

**Operational consequence**: production incidents, unsafe drift, or blocked write conditions should route through health/write-guard/operator workflows rather than ad hoc override behavior.

## Runtime Control Surface

The runtime provides explicit environment selection through a documented control surface with a clear priority hierarchy for `dev` and `prod`.
The local `test` profile is currently controlled by the repo-supported bootstrap commands rather than a third `PKM_ENVIRONMENT` selector.

### Environment Variables

| Variable | Values | Purpose | Default |
| --- | --- | --- | --- |
| `PKM_ENVIRONMENT` | `dev`, `prod` | **Explicit** first-class runtime environment selection. Takes priority over all other signals. | (not set) |
| `PKM_SETTINGS_PROFILE` | `operator`, `lab` | **Legacy** settings profile control. Maintained for backward compatibility. `lab` -> dev environment, `operator` -> prod environment. | `operator` |

### Resolution Hierarchy

Environment resolution follows this priority:

1. **Explicit environment selection via `PKM_ENVIRONMENT`** (if set to `dev` or `prod`)
   - The canonical modern control surface for runtime environment selection
   - Takes priority over settings profile
   - Case-insensitive; whitespace is stripped

2. **Implicit environment from settings profile** (if `PKM_ENVIRONMENT` not set)
   - `PKM_SETTINGS_PROFILE=lab` -> `dev` environment
   - `PKM_SETTINGS_PROFILE=operator` -> `prod` environment (default)
   - This mapping allows existing operator/lab workflows to continue working without changes

3. **Default to prod** (if neither explicit nor implicit signals are present)
   - Preserves current production-facing baseline behavior
   - Ensures safe defaults when no environment configuration is present

### Backward Compatibility

The existing `PKM_SETTINGS_PROFILE` control mechanism continues to work without changes:

- Operator runbooks and scripts using `PKM_SETTINGS_PROFILE=operator` are mapped to the `prod` environment
- Dev/lab workflows using `PKM_SETTINGS_PROFILE=lab` are mapped to the `dev` environment
- **No existing behavior changes silently.** Operators see the same control semantics; they now route through the explicit environment model internally.

The settings profile is now understood as a **narrower control mechanism that lives beneath the environment model**, rather than the full environment specification. As the runtime evolves, new environment-specific behavior should be controlled via `PKM_ENVIRONMENT` rather than extending the settings profile approach. The exception is the current repo-supported `test` bootstrap profile, which is intentionally implemented as a bounded local workflow first.

## Canonical Local Test Bootstrap

The official local `test` golden path is:

```bash
make test-bootstrap
```

Default target vault:
- `TEST_VAULT_ROOT=$(pwd)/vault-test`

Expanded path:
1. reset runtime state
2. initialize a clean test vault
3. seed the UAT notes
4. start the local stack against that vault
5. verify health/status
6. run scripted UAT

Contract:
- resets runtime state
- bootstraps a clean test vault layout without undocumented folder env vars
- seeds the repo-supported UAT note pack
- starts the local stack against that vault
- verifies health/status
- runs the scripted UAT flow successfully

For detailed specification and step-by-step verification contract, see `docs/LOCAL_TEST_BOOTSTRAP/`.

Operator note:
- `make test-vault-init` is the narrow helper that prepares the clean test vault without starting the stack.
- `test` is the current golden path for local verification and stabilization work.
- `dev` remains the flexible development posture, and `prod` remains the conservative operator posture.

## Parallel Local Stacks

The repo supports parallel local Compose stacks for `dev`, `test`, and `prod` on one machine without host-port conflicts.

Commands:

```bash
make prod-up
make dev-up
make test-up
```

Port map:
- `prod`: Postgres `15432`, API `18000`
- `dev`: Postgres `15433`, API `18001`
- `test`: Postgres `15434`, API `18002`

Compose files:
- `docker-compose.yaml` (base + prod defaults)
- `docker-compose.dev.yml` (dev overrides)
- `docker-compose.test.yml` (test overrides)

Notes:
- `make start-test-system` and `make test-bootstrap` remain unchanged and are still the canonical local `test` verification workflow.
- The `test` compose override uses the same runtime environment selector posture as `dev` (`PKM_ENVIRONMENT=dev`) because runtime selection currently supports `dev` and `prod`; test remains a workflow-defined environment in this baseline.
- Full parallel isolation still depends on DB separation work tracked by Issue #594.

## Relation to Current Health, Write Guard, and Settings Direction

### Health and Write Guard

The health contract and write guard remain independent of environment selection. All production safety invariants (deterministic health checks, write guard enforcement, event safety) apply in `dev`, `test`, and `prod`. Environment selection does not bypass safety constraints.

### Settings and Configuration

The environment model provides **one canonical control point for environment-specific behavior across the runtime**, replacing the earlier scattered approach where settings profiles and partial environment knobs controlled different aspects independently.

- **Before**: Operator/lab profiles controlled watcher tuning; other environment-specific features used ad-hoc env vars or configuration files.
- **After**: Environment selection (via `PKM_ENVIRONMENT`) is the canonical signal for `dev` and `prod`. Settings profiles are mapped to it for compatibility. The local `test` path is the explicit workflow-driven verification environment. New environment-specific behavior should register against this model rather than add new scattered controls.

### Operability and Transparency

Operators can check the active environment and understand the configuration state:

- `python -m app.cli settings-explain` and `python -m app.cli status` surface the resolved runtime environment
- logs and diagnostics can report which runtime environment is active
- the test bootstrap path remains explicit in `make test-bootstrap`, `docs/OPERATIONS.md`, and `docs/TESTING.md`
- configuration compiler and settings validator understand environment-aware behavior

Delivery receipt:
- Issue #265 / PR #272 shipped environment-aware operator diagnostics across health, status, settings-explain, and incident-facing surfaces. Environment reporting is no longer pending future work in this document; remaining follow-through should focus on the bounded local `test` bootstrap contract and other explicit slices of the environment model.

## Implementation

### Runtime Contracts

Environment resolution is provided by `app.config.environment`:

```python
from app.config.environment import active_environment, is_dev_environment, is_prod_environment

env = active_environment()

if is_dev_environment():
    pass
```

The resolution follows the documented hierarchy: explicit `PKM_ENVIRONMENT` > implicit from `PKM_SETTINGS_PROFILE` > default to `prod`.

### Integrations

Settings modules (watcher, agent, etc.) that need environment-specific behavior should:

1. Import and use `active_environment()` to check environment state.
2. Document which settings are dev-only or environment-specific.
3. Respect the same write-safety and health constraints in all environments.
4. Test behavior in both runtime-selected environments and keep the workflow-driven `test` path explicit where relevant.

The existing `app.settings.tiering` module continues to work and is now understood as implementing profile-based (operator/lab) access to the underlying environment model.

## Constraints and Out of Scope

- Environment selection does not redefine product semantics.
- Channel identity, promotion, rollback, and DB-per-channel semantics are owned by `docs/RELEASE_CHANNELS/README.md`, not this document. This document continues to own environment selection and path scoping only.
- Hosted deployment, secrets handling, and CI/CD-driven release remain out of scope. Local, single-user promotion between channels is owned by the release-channels capability.
- Health/status/operator diagnostics changes are independent of environment selection.
- Multi-user/multi-instance coordination remains orthogonal to environment selection.
- The current docs wave does not require promoting `test` into a third runtime selector before the supported bootstrap contract is stabilized.

## Suggested Validation

- confirm `python -m app.cli settings-explain` reports the resolved runtime environment coherently for `dev` and `prod`
- confirm `make test-bootstrap` remains the documented local verification golden path for `test`
- confirm environment-specific runtime artifacts do not leak between `dev`, `test`, and `prod` postures
- confirm status/operations/testing docs all describe the same `dev` / `test` / `prod` model and the same bootstrap path
