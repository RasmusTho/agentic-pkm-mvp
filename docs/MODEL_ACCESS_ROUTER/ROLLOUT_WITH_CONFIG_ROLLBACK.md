---
name: Roll Out with Config Rollback
description: Prepare the staged dev-to-test-to-prod rollout and verify provider-neutral rollback to the last pinned capability-compatible route through the release-channel workflow.
task_id: MARR-07
github_issue: 5625
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: Delivery gates
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-06]
depends_on: [PROVE_MAC_MINI_ACCEPTANCE.md]
can_parallelize_with: []
---

# ROLLOUT_WITH_CONFIG_ROLLBACK

## Purpose

Make rollout and rollback explicit so a new Codex route is enabled only after VLAN-only host acceptance and each release-channel gate has durable evidence. The current Ygg path policy contains only `ygg_vlan_primary`; Tailscale is not a rollout prerequisite. Rollback does not assume that any particular provider or local model runtime is installed.

## What This Task Does

Prepare the dev → test → prod rollout under the existing release-channel skills. Each stage verifies route health and declared capabilities before advancing, using the checked-in VLAN-only path policy for the Mac executor. Rollback is a config change to the last verified, pinned Product route and path policy that satisfies the current required capability intent. Its fresh no-inference preflight must be bound to the exact current `ModelResolutionRequest`; a pass for a different intent cannot be rebound based only on the route's declared capability flags. If no pinned route satisfies the intent, rollback fails closed and requires an operator decision. Rollback does not imply Tailscale or Ollama availability, weaken policy, or change embedding identity.

Actual test/prod channel mutations, deployment, and rollback use the established operator-acknowledged release workflow. This task does not embed deployment into the Model Access Router code PR.

This child slice implements and tests the pure rollback planner and protects the existing production acknowledgment gate. Live dev/test stage receipts and final production health/rollback evidence remain an integrated acceptance gate owned by parent Issue #5618; merging this child does not claim those runtime stages are complete.

## Concretely

Before a stage advances, its candidate ref, route and path configuration, migration/config delta, health checks, designated-host receipt, and exact rollback target are recorded. If a gate fails, the release workflow restores the last verified pinned capability-compatible route and path policy, then runs the owning verification procedure.

## Why This Matters

A valid PR or designated-host smoke does not prove that a release channel is ready. Separating router code from controlled rollout prevents an adapter change from silently reaching prod.

## Acceptance Criteria

- [ ] Rollback restores only the last verified pinned route and path policy that satisfies the current capability intent, and preserves embedding identity; no provider is assumed.
  - Verify: `tests/release/test_model_access_router_rollback_plan.py::test_rollback_restores_last_pinned_capability_compatible_route`
  - The planner is pure: it requires a fresh no-inference preflight bound to the exact current `ModelResolutionRequest`, selects only a pinned route with a prior verification receipt, and carries the existing embedding identity through unchanged. Applying a plan remains owned by the release-channel workflow.
- [ ] Prod is not advanced unless the current prepare/execute/verify release workflow has its required operator acknowledgment.
  - Verify: `tests/release/test_model_access_router_rollback_plan.py::test_prod_transition_requires_operator_acknowledged_release_plan`
  - The production gate remains the existing `execute-promotion` / `promote-test-to-prod` operator-review gate; this Model Access Router change does not create a second deployment authority.

## How to Verify (Pre-Merge)

- Run pytest -q tests/release/test_model_access_router_rollback_plan.py.
- After this child merges, prepare/execute/verify dev and test under the applicable release-channel skills and attach candidate-bound stage and final verification receipts to parent Issue #5618. Do not close the parent from the PR merge alone.

## Out of Scope

- An ad-hoc deploy, direct stable-pointer movement, migration, or production restart.
- Fallback that weakens a route's capability requirements.
- Changing provider credentials, model downloads, or embedding configuration.

## Related Docs

- docs/RELEASE_CHANNELS/README.md
- docs/ENVIRONMENTS.md
- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/MODEL_ACCESS_ROUTER/README.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
