State: SoT v5.5 Reality-MVP baseline locked with explicit dev/prod environment contract for later implementation issues.
Doc role: Core SoT
Authority: Canonical environment contract for the current baseline and forward-line work; defines what dev and prod mean, what must remain invariant, and what may vary. Architecture, operations, status, and component docs should reference this document instead of restating environment policy.
# Environments

This document defines `dev` and `prod` as first-class environments in the active SoT.

The purpose of this document is to make environment boundaries explicit before more environment-aware implementation work is taken on.
It is governing documentation only.
It does not, by itself, claim that all current runtime behavior is already fully environment-separated in code.

Reading rule:
- Use this document when a change touches environment-specific behavior, storage boundaries, runtime topology, write safety, or rollout posture.
- Use `docs/ARCHITECTURE.md` for system structure, `docs/OPERATIONS.md` for operator procedure, `docs/STATUS.md` for current rollout posture, and `docs/guardrails.md` for safety rules.

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

The following are SoT invariants and MUST remain true in both `dev` and `prod`:
- The same architecture contracts apply: vault-first human surface, companion/system surface, and rebuildable runtime surface.
- The event envelope and outbox semantics remain stable; DB outbox is canonical runtime queue semantics.
- Writes to tracked notes remain deterministic and guarded by write-safety and idempotency rules.
- Artifact identity, provenance, and receipt semantics do not change by environment.
- Settings and policy remain the control surface for runtime behavior; environment selection must not bypass policy, allowlists, or write guards.
- A real environment split must not redefine the human-facing contract in `docs/HUMAN-FLOWS.md`.

Environment is therefore an operational/runtime distinction, not a different ontology of artifacts or a different semantic model of the product.

## Allowed variation by environment

The following may vary between `dev` and `prod` without breaking SoT, as long as the invariants above remain intact:
- runtime scale, process topology, and startup wrappers
- provider choice and model profile
- diagnostic verbosity, mocks, and test fixtures
- watcher cadence, tuning, and other explicit lab-only controls
- local fixture vaults, test stores, and rebuild/reset workflows
- operator gating and rollout posture for mutation-capable automation

Variation rule:
- environment-specific defaults may vary
- environment-specific contract semantics may not

## Separation requirements

Environment separation MUST be explicit across the following surfaces.

### Vaults and human-facing files
- `prod` must operate on the operator's real vault and its associated continuity artifacts.
- `dev` must use a separate fixture, test, or otherwise intentionally non-production vault when environment-specific experimentation or validation is being performed.
- `dev` and `prod` must not implicitly share the same writable vault surface when the purpose is environment isolation.

### Stores and persistence
- `prod` runtime persistence must be treated as production data even when it is rebuildable from the file-based continuity set.
- `dev` stores, indexes, and outbox state may be reset, rebuilt, or replaced for testing.
- Rebuildable does not mean disposable in `prod`; recovery and audit expectations still apply.

### Runtime state and process surfaces
- Watcher state, heartbeats, tick logs, incident logs, and similar runtime artifacts must be interpreted as environment-scoped operational surfaces.
- `dev` may expose extra diagnostics and lab-only controls.
- `prod` must keep these surfaces stable enough to support operator verification and incident triage.

### Settings and policy surfaces
- Environment selection must resolve through explicit settings/runtime configuration, not through undocumented convention.
- Lab/dev-only tuning must remain excluded from normal production runtime unless explicitly enabled by the documented control surface.
- Current watcher/settings-profile posture (`PKM_SETTINGS_PROFILE=operator` vs `PKM_SETTINGS_PROFILE=lab`) is one environment-related mechanism, but it is not by itself the full environment model.

## Production safety expectations

`prod` carries the following additional expectations:
- safety beats convenience when the two conflict
- bounded writes only; no silent broad note mutation
- degraded or blocked mode is preferable to unsafe mutation
- health, status, and operator verification surfaces must remain meaningful
- rollout of mutation-capable automation must remain explicitly gated
- recovery paths must preserve the continuity set: vault notes plus companion notes

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

That gap is intentional and should be closed through follow-on implementation issues derived from this document rather than by silently extending runtime behavior without SoT updates.
