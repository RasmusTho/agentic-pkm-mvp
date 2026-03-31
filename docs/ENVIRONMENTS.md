<<<<<<< HEAD
State: SoT v5.5 Reality-MVP baseline locked with explicit dev/prod environment contract + implementation (Issue #263).
Doc role: Core SoT
Authority: Canonical environment contract for the current baseline and forward-line work; defines what dev and prod mean, what must remain invariant, and what may vary. Architecture, operations, status, and component docs should reference this document instead of restating environment policy.

# Environments

This document defines `dev` and `prod` as first-class environments in the active SoT.

The purpose of this document is to make environment boundaries explicit before more environment-aware implementation work is taken on. It defines the environment contract (what must stay true) and documents the current resolution mechanism (how dev/prod are selected at startup).
=======
# Environments

State: SoT v5.5 Reality-MVP baseline locked with explicit dev/prod environment contract and runtime implementation.
Doc role: Core SoT
Authority: Canonical environment contract and implementation for the current baseline and forward-line work; defines what dev and prod mean, what must remain invariant, and what may vary. Architecture, operations, status, and component docs should reference this document instead of restating environment policy.

## Overview

This document defines `dev` and `prod` as first-class environments in the active SoT, specifies the control surfaces for runtime environment selection, and documents the cross-environment invariants that must hold.

The purpose of this document is to make environment boundaries explicit before more environment-aware implementation work is taken on. It is governing documentation and implementation reference.
>>>>>>> origin/main

Reading rule:
- Use this document when a change touches environment-specific behavior, storage boundaries, runtime topology, write safety, or rollout posture.
- Use `docs/ARCHITECTURE.md` for system structure, `docs/OPERATIONS.md` for operator procedure, `docs/STATUS.md` for current rollout posture, and `docs/guardrails.md` for safety rules.

<<<<<<< HEAD
## Environment definitions

### `dev`
- Purpose: development, experimentation, debugging, local validation, and bounded forward-line exploration.
- Typical users: builders, developers, and operators validating changes before wider runtime use.
- Allowed posture: narrower safety assumptions, mock or local providers, test fixtures, selective resets, and lab-only runtime tuning.
- Typical expectation: failures are acceptable if they are observable, bounded, and do not threaten production continuity artifacts.

### `prod`
- Purpose: the operator-facing runtime used against a real vault and its associated runtime surfaces.
- Typical users: the human operator and the runtime processes that act on the operator's real knowledge environment.
- Required posture: conservative, receipt-bearing, recoverable, and safe by default.
- Typical expectation: the system must prefer blocking, degrading, or emitting diagnostics over silent corruption, silent drift, or unbounded mutation.

## Cross-environment invariants
=======
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
>>>>>>> origin/main

The following are SoT invariants and MUST remain true in both `dev` and `prod`:
- The same architecture contracts apply: vault-first human surface, companion/system surface, and rebuildable runtime surface.
- The event envelope and outbox semantics remain stable; DB outbox is canonical runtime queue semantics.
- Writes to tracked notes remain deterministic and guarded by write-safety and idempotency rules.
- Artifact identity, provenance, and receipt semantics do not change by environment.
- Settings and policy remain the control surface for runtime behavior; environment selection must not bypass policy, allowlists, or write guards.
- A real environment split must not redefine the human-facing contract in `docs/HUMAN-FLOWS.md`.

Environment is therefore an operational/runtime distinction, not a different ontology of artifacts or a different semantic model of the product.

<<<<<<< HEAD
## Allowed variation by environment
=======
## Allowed Variation by Environment
>>>>>>> origin/main

The following may vary between `dev` and `prod` without breaking SoT, as long as the invariants above remain intact:
- runtime scale, process topology, and startup wrappers
- provider choice and model profile
- diagnostic verbosity, mocks, and test fixtures
- watcher cadence, tuning, and other explicit lab-only controls
- local fixture vaults, test stores, and rebuild/reset workflows
- operator gating and rollout posture for mutation-capable automation

<<<<<<< HEAD
Variation rule:
- environment-specific defaults may vary
- environment-specific contract semantics may not

## Separation requirements

Environment separation MUST be explicit across the following surfaces.

### Vaults and human-facing files
=======
**Variation rule**: environment-specific defaults may vary; environment-specific contract semantics may not.

## Separation Requirements

Environment separation MUST be explicit across the following surfaces.

### Vaults and Human-Facing Files
>>>>>>> origin/main
- `prod` must operate on the operator's real vault and its associated continuity artifacts.
- `dev` must use a separate fixture, test, or otherwise intentionally non-production vault when environment-specific experimentation or validation is being performed.
- `dev` and `prod` must not implicitly share the same writable vault surface when the purpose is environment isolation.

<<<<<<< HEAD
### Stores and persistence
=======
### Stores and Persistence
>>>>>>> origin/main
- `prod` runtime persistence must be treated as production data even when it is rebuildable from the file-based continuity set.
- `dev` stores, indexes, and outbox state may be reset, rebuilt, or replaced for testing.
- Rebuildable does not mean disposable in `prod`; recovery and audit expectations still apply.

<<<<<<< HEAD
### Runtime state and process surfaces
=======
### Runtime State and Process Surfaces
>>>>>>> origin/main
- Watcher state, heartbeats, tick logs, incident logs, and similar runtime artifacts must be interpreted as environment-scoped operational surfaces.
- `dev` may expose extra diagnostics and lab-only controls.
- `prod` must keep these surfaces stable enough to support operator verification and incident triage.

<<<<<<< HEAD
### Settings and policy surfaces
- Environment selection must resolve through explicit settings/runtime configuration, not through undocumented convention.
- Lab/dev-only tuning must remain excluded from normal production runtime unless explicitly enabled by the documented control surface.
- Current watcher/settings-profile posture (`PKM_SETTINGS_PROFILE=operator` vs `PKM_SETTINGS_PROFILE=lab`) is one environment-related mechanism, but it is not by itself the full environment model.

## Production safety expectations
=======
### Settings and Policy Surfaces
- Environment selection must resolve through explicit settings/runtime configuration, not through undocumented convention.
- Lab/dev-only tuning must remain excluded from normal production runtime unless explicitly enabled by the documented control surface.

## Production Safety Expectations
>>>>>>> origin/main

`prod` carries the following additional expectations:
- safety beats convenience when the two conflict
- bounded writes only; no silent broad note mutation
- degraded or blocked mode is preferable to unsafe mutation
- health, status, and operator verification surfaces must remain meaningful
- rollout of mutation-capable automation must remain explicitly gated
- recovery paths must preserve the continuity set: vault notes plus companion notes

<<<<<<< HEAD
Operational consequence:
- production incidents, unsafe drift, or blocked write conditions should route through health/write-guard/operator workflows rather than ad hoc override behavior

## Relation to current health, write guard, and settings direction

This environment contract is intentionally aligned to the current SoT direction rather than introducing a new architecture:
- HealthContract remains the environment-agnostic readiness and degradation spine.
- WriteGuard remains the environment-agnostic note-mutation safety boundary.
- Settings provenance and settings tiering remain the control surface for enabling or withholding environment-sensitive behavior.
- Current `operator` versus `lab` settings-profile language should be read as a present-day partial implementation of environment-sensitive controls, not as a complete replacement for explicit `dev` and `prod` environment definitions.

In other words:
- health and write guard define whether a runtime is safe to act
- settings define which behavior is eligible to act
- environment defines the operational expectations and separation boundaries under which those controls are interpreted

## Current baseline posture

For the active SoT baseline:
- runtime defaults and operator docs describe the production-facing path
- lab/dev-only watcher paths remain explicitly non-production
- the repo does not yet claim a complete implementation-level environment model across every runtime surface

## Environment selection mechanism (Issue #263 implementation)

The runtime now includes an explicit environment selection mechanism that resolves `dev` or `prod` at startup. This implementation fulfills the "Settings and policy surfaces" separation requirement.

### Resolution order (backward compatible)

The environment is resolved at startup using this priority:

1. **Explicit environment override** (`PKM_ENVIRONMENT` environment variable)
   - `PKM_ENVIRONMENT=dev` or `PKM_ENVIRONMENT=prod`
   - Takes absolute precedence; must be valid or raises an error
2. **Settings profile mapping** (`PKM_SETTINGS_PROFILE` environment variable)
   - `PKM_SETTINGS_PROFILE=lab` → `dev`
   - `PKM_SETTINGS_PROFILE=operator` (default) → `prod`
   - Provides backward compatibility with existing deployments
3. **Default** → `prod` (production-safe default)

### Configuration examples

```bash
# Explicit production environment
PKM_ENVIRONMENT=prod python -m app.cli watcher run

# Explicit development environment
PKM_ENVIRONMENT=dev python -m app.cli watcher run

# Legacy: lab profile maps to dev (automatically)
PKM_SETTINGS_PROFILE=lab python -m app.cli watcher run

# Legacy: operator profile maps to prod (default)
PKM_SETTINGS_PROFILE=operator python -m app.cli watcher run

# No environment set: defaults to prod
python -m app.cli watcher run
```

### Runtime availability

The resolved environment is available in `InstanceSettings.environment` within the runtime `SettingsBundle`:

```python
from app.settings.runtime import get_settings_bundle

bundle = get_settings_bundle()
current_env = bundle.instance.environment  # 'dev' or 'prod'
```

### Implementation notes

- Resolved at `SettingsBundle` build time via `app.config.environment.resolve_environment()`
- Backward compatible: existing `PKM_SETTINGS_PROFILE` configurations continue to work without changes
- No architecture-breaking changes; maps existing control surfaces

## Current implementation mapping (SoT v5.5)

| Config | Resolved Env | Behavior | Profile Tier |
|--------|---|---|---|
| (unset) | `prod` | Production-safe default | `operator` |
| `PKM_SETTINGS_PROFILE=operator` | `prod` | Explicit production | `operator` |
| `PKM_SETTINGS_PROFILE=lab` | `dev` | Dev/lab features enabled | `lab` |
| `PKM_ENVIRONMENT=dev` | `dev` | Explicit dev (overrides profile) | — |
| `PKM_ENVIRONMENT=prod` | `prod` | Explicit prod (overrides profile) | — |

## Testing and validation

Environment resolution is tested in:
- `tests/test_environment_resolution.py` — environment resolution logic, overrides, defaults, and error cases
- `tests/test_settings_environment_integration.py` — SettingsBundle integration and real-world scenarios

Validation commands:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_environment_resolution.py -m "not pg"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_settings_environment_integration.py -m "not pg"
```

## Forward-looking

Environment selection is the first-class control surface for dev/prod separation. Future work includes:
- Environment-specific vault/store/artifact separation and deployment topology
- Per-environment rollout policy and safety gate configuration
- Environment-aware observability, health signals, and operator workflows
=======
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
- Tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/config/test_environment.py -m "not pg"`
>>>>>>> origin/main
