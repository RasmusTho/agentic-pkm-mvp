# Environments

State: SoT v5.5 baseline with explicit dev/prod environment model, control surfaces, and artifact separation (Issues #263, #266).
Doc role: Core SoT
Authority: Canonical environment contract and implementation for the current baseline and forward-line work; defines what dev and prod mean, what must remain invariant, and what may vary. Architecture, operations, status, and component docs should reference this document instead of restating environment policy.

## Overview

This document defines `dev` and `prod` as first-class environments in the active SoT, specifies the control surfaces for runtime environment selection and artifact path scoping, and documents the cross-environment invariants that must hold.

The purpose of this document is to make environment boundaries explicit and ensure that dev and prod maintain separate vault, store, and runtime artifact surfaces when environment isolation is required.

Reading rule:
- Use this document when a change touches environment-specific behavior, storage boundaries, runtime topology, write safety, or rollout posture.
- Use `docs/ARCHITECTURE.md` for system structure, `docs/OPERATIONS.md` for operator procedure, `docs/STATUS.md` for current rollout posture, and `docs/guardrails.md` for safety rules.

## Environment Definitions

### `dev`
- **Purpose**: development, experimentation, debugging, local validation, and bounded forward-line exploration.
- **Typical users**: builders, developers, and operators validating changes before wider runtime use.
- **Allowed posture**: narrower safety assumptions, mock or local providers, test fixtures, selective resets, and lab-only runtime tuning.
- **Typical expectation**: failures are acceptable if they are observable, bounded, and do not threaten production continuity artifacts.

### `prod`
- **Purpose**: the operator-facing runtime used against a real vault and its associated runtime surfaces.
- **Typical users**: the human operator and the runtime processes that act on the operator's real knowledge environment.
- **Required posture**: conservative, receipt-bearing, recoverable, and safe by default.
- **Typical expectation**: the system must prefer blocking, degrading, or emitting diagnostics over silent corruption, silent drift, or unbounded mutation.

## Cross-Environment Invariants

The following are SoT invariants and MUST remain true in both `dev` and `prod`:
- The same architecture contracts apply: vault-first human surface, companion/system surface, and rebuildable runtime surface.
- The event envelope and outbox semantics remain stable; DB outbox is canonical runtime queue semantics.
- Writes to tracked notes remain deterministic and guarded by write-safety and idempotency rules.
- Artifact identity, provenance, and receipt semantics do not change by environment.
- Settings and policy remain the control surface for runtime behavior; environment selection must not bypass policy, allowlists, or write guards.
- A real environment split must not redefine the human-facing contract in `docs/HUMAN-FLOWS.md`.

Environment is therefore an operational/runtime distinction, not a different ontology of artifacts or a different semantic model of the product.

## Allowed Variation by Environment

The following may vary between `dev` and `prod` without breaking SoT, as long as the invariants above remain intact:
- runtime scale, process topology, and startup wrappers
- provider choice and model profile
- diagnostic verbosity, mocks, and test fixtures
- watcher cadence, tuning, and other explicit lab-only controls
- local fixture vaults, test stores, and rebuild/reset workflows
- operator gating and rollout posture for mutation-capable automation

**Variation rule**: environment-specific defaults may vary; environment-specific contract semantics may not.

## Separation Requirements

Environment separation MUST be explicit across the following surfaces.

### Vaults and Human-Facing Files
- `prod` must operate on the operator's real vault and its associated continuity artifacts.
- `dev` must use a separate fixture, test, or otherwise intentionally non-production vault when environment-specific experimentation or validation is being performed.
- `dev` and `prod` must not implicitly share the same writable vault surface when the purpose is environment isolation.

**Implementation Status (Issue #266)**:
- Vault paths are now environment-scoped via `app.config.paths.resolve_vault_root()`.
- Default behavior: `prod` uses `vault/`, `dev` uses `vault-dev/`.
- Custom overrides via CLI flags bypass environment scoping.

### Stores and Persistence
- `prod` runtime persistence must be treated as production data even when it is rebuildable from the file-based continuity set.
- `dev` stores, indexes, and outbox state may be reset, rebuilt, or replaced for testing.
- Rebuildable does not mean disposable in `prod`; recovery and audit expectations still apply.

**Implementation Status (Issue #266)**:
- Index outbox and store paths are now environment-scoped via `app.config.paths.resolve_runtime_artifact_path()`.
- Default behavior: `prod` uses `tmp/` subdirectories, `dev` uses `tmp-dev/` subdirectories.
- Watcher settings automatically apply environment scoping to all artifact paths via `load_watcher_settings(environment=...)`.
- DB outbox (PostgreSQL) is shared; file-based audit logs respect environment separation.

### Runtime State and Process Surfaces
- Watcher state, heartbeats, tick logs, incident logs, and similar runtime artifacts must be interpreted as environment-scoped operational surfaces.
- `dev` may expose extra diagnostics and lab-only controls.
- `prod` must keep these surfaces stable enough to support operator verification and incident triage.

**Implementation Status (Issue #266)**:
- Watcher heartbeat, state files, and event logs are now environment-scoped.
- Default behavior: `prod` uses base artifact paths (`tmp/watcher_state.json`), `dev` uses `-dev` subdirectories (`tmp-dev/watcher_state.json`).
- Incidents and audit surfaces respect environment separation to prevent cross-environment contamination.

### Settings and Policy Surfaces
- Environment selection must resolve through explicit settings/runtime configuration, not through undocumented convention.
- Lab/dev-only tuning must remain excluded from normal production runtime unless explicitly enabled by the documented control surface.

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

The runtime provides explicit environment selection through a documented control surface with a clear priority hierarchy.

### Environment Variables

| Variable | Values | Purpose | Default |
| --- | --- | --- | --- |
| `PKM_ENVIRONMENT` | `dev`, `prod` | **Explicit** first-class environment selection. Takes priority over all other signals. | (not set) |
| `PKM_SETTINGS_PROFILE` | `operator`, `lab` | **Legacy** settings profile control. Maintained for backward compatibility. `lab` → dev environment, `operator` → prod environment. | `operator` |

### Resolution Hierarchy

Environment resolution follows this priority:

1. **Explicit environment selection via `PKM_ENVIRONMENT`** (if set to `dev` or `prod`)
   - The canonical modern control surface for environment selection
   - Takes priority over settings profile
   - Case-insensitive; whitespace is stripped

2. **Implicit environment from settings profile** (if `PKM_ENVIRONMENT` not set)
   - `PKM_SETTINGS_PROFILE=lab` → `dev` environment
   - `PKM_SETTINGS_PROFILE=operator` → `prod` environment (default)
   - This mapping allows existing operator/lab workflows to continue working without changes

3. **Default to prod** (if neither explicit nor implicit signals are present)
   - Preserves current production-facing baseline behavior
   - Ensures safe defaults when no environment configuration is present

### Backward Compatibility

The existing `PKM_SETTINGS_PROFILE` control mechanism continues to work without changes:

- Operator runbooks and scripts using `PKM_SETTINGS_PROFILE=operator` are mapped to the `prod` environment
- Dev/lab workflows using `PKM_SETTINGS_PROFILE=lab` are mapped to the `dev` environment
- **No existing behavior changes silently.** Operators see the same control semantics; they now route through the explicit environment model internally.

The settings profile is now understood as a **narrower control mechanism that lives beneath the environment model**, rather than the full environment specification. As the runtime evolves, new environment-specific behavior should be controlled via `PKM_ENVIRONMENT` rather than extending the settings profile approach.

## Relation to Current Health, Write Guard, and Settings Direction

### Health and Write Guard

The health contract and write guard remain independent of environment selection. All production safety invariants (deterministic health checks, write guard enforcement, event safety) apply in both `dev` and `prod` environments. Environment selection does not bypass safety constraints.

### Settings and Configuration

The environment model provides **one canonical control point for environment-specific behavior across the entire runtime**, replacing the earlier scattered approach where settings profiles and partial environment knobs controlled different aspects independently.

- **Before**: Operator/lab profiles controlled watcher tuning; other environment-specific features used ad-hoc env vars or configuration files
- **After**: Environment selection (via `PKM_ENVIRONMENT`) is the canonical signal. Settings profiles are mapped to it for compatibility. New environment-specific behavior should register against the environment model, not add new scattered controls.

### Operability and Transparency

Operators can check the active environment and understand the configuration state:

- `python -m app.cli settings-explain` and `python -m app.cli status` surface the resolved environment
- Logs and diagnostics can report which environment is active
- Configuration compiler and settings validator understand environment-aware behavior

## Implementation

### Runtime Contracts

Environment resolution is provided by `app.config.environment`:

```python
from app.config.environment import active_environment, is_dev_environment, is_prod_environment

# Get the resolved environment ('dev' or 'prod')
env = active_environment()

# Check environment state
if is_dev_environment():
    # Enable dev-only features
    pass
```

The resolution follows the documented hierarchy: explicit `PKM_ENVIRONMENT` > implicit from `PKM_SETTINGS_PROFILE` > default to `prod`.

### Integrations

Settings modules (watcher, agent, etc.) that need environment-specific behavior should:

1. Import and use `active_environment()` to check environment state
2. Document which settings are dev-only or environment-specific
3. Respect the same write-safety and health constraints in both environments
4. Test behavior in both environments

The existing `app.settings.tiering` module continues to work and is now understood as implementing profile-based (operator/lab) access to the underlying environment model.

## Constraints and Out of Scope

- Environment selection does not control vault/store/runtime artifact separation beyond the separation requirements above
- Deployment automation, secrets handling, and CI/CD remain out of scope
- Health/status/operator diagnostics changes are independent of environment selection
- Multi-user/multi-instance coordination remains orthogonal to environment selection

## Suggested Validation

- Check environment resolution: `python -c "from app.config.environment import active_environment; print(active_environment())"`
- Explicit environment: `PKM_ENVIRONMENT=dev python -c ...` and `PKM_ENVIRONMENT=prod python -c ...`
- Backward compatibility: `PKM_SETTINGS_PROFILE=lab python -c ...` should resolve to dev
- Tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/config/test_environment.py -m "not pg"`in
