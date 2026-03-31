# Runtime Environments

State: SoT v5.5 baseline
Authority: Canonical definition of runtime environment selection semantics and control surfaces
Role: Core SoT for environment model; subordinate to `docs/STATUS.md` for operational baselines and `docs/OPERATIONS.md` for operator runbooks.

## Environment Definitions

The runtime supports two first-class environments:

- **prod**: Production-like environment where all dev/lab-only features are disabled. This is the canonical baseline for standard operations. Default if no environment selection is made.
- **dev**: Development/lab environment where dev-only tuning knobs, diagnostic modes, and experimental features are enabled. Intended for operator diagnostics, testing, and feature development.

## Control Surface

Environment selection has a documented, test-covered control surface with a clear priority hierarchy.

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

2. **Implicit environment from settings profile** (if `PKM_ENVIRONMENT` not set)
   - `PKM_SETTINGS_PROFILE=lab` → `dev` environment
   - `PKM_SETTINGS_PROFILE=operator` → `prod` environment (default)
   - This mapping allows existing operator/lab workflows to continue working without changes

3. **Default to prod** (if neither explicit nor implicit signals are present)
   - Preserves current production-facing baseline behavior
   - Ensures safe defaults when no environment configuration is present

### Backward Compatibility

The existing `PKM_SETTINGS_PROFILE` control mechanism continues to work:

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

- Environment selection does not control vault/store/runtime artifact separation
- Deployment automation, secrets handling, and CI/CD remain out of scope
- Health/status/operator diagnostics changes are independent of environment selection
- Multi-user/multi-instance coordination remains orthogonal to environment selection

## Suggested Validation

- Check environment resolution: `python -c "from app.config.environment import active_environment; print(active_environment())"`
- Explicit environment: `PKM_ENVIRONMENT=dev python -c ...` and `PKM_ENVIRONMENT=prod python -c ...`
- Backward compatibility: `PKM_SETTINGS_PROFILE=lab python -c ...` should resolve to dev
- Tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/config/test_environment.py -m "not pg"`
