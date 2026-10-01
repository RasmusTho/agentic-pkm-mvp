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

Make rollout and rollback explicit so a new Codex route is enabled only after host acceptance and each release-channel gate has durable evidence. Rollback does not assume that any particular provider or local model runtime is installed.

## What This Task Does

Prepare the dev → test → prod rollout under the existing release-channel skills. Each stage verifies route health and declared capabilities before advancing. Rollback is a config change to the last verified, pinned Product route and network-path policy that satisfies the current required capability intent. The candidate must pass no-inference health/preflight before it is restored; if no pinned route satisfies the intent, rollback fails closed and requires an operator decision. Rollback does not imply Ollama availability, weaken policy, or change embedding identity.

Actual test/prod channel mutations, deployment, and rollback use the established operator-acknowledged release workflow. This task does not embed deployment into the Model Access Router code PR.

## Concretely

Before a stage advances, its candidate ref, route and path configuration, migration/config delta, health checks, designated-host receipt, and exact rollback target are recorded. If a gate fails, the release workflow restores the last verified pinned capability-compatible route and path policy, then runs the owning verification procedure.

## Why This Matters

A valid PR or designated-host smoke does not prove that a release channel is ready. Separating router code from controlled rollout prevents an adapter change from silently reaching prod.

## Acceptance Criteria

- [ ] Dev and test rollout evidence is attached to the governing parent and shows the exact candidate SHA, route, and rollback target.
  - Verify: runtime receipt: model_access_router.staged_rollout.v1
- [ ] Rollback restores only the last verified pinned route and path policy that satisfies the current capability intent, and preserves embedding identity; no provider is assumed.
  - Verify: `tests/release/test_model_access_router_rollback_plan.py::test_rollback_restores_last_pinned_capability_compatible_route`
- [ ] Prod is not advanced unless the current prepare/execute/verify release workflow has its required operator acknowledgment.
  - Verify: `tests/release/test_model_access_router_rollback_plan.py::test_prod_transition_requires_operator_acknowledged_release_plan`
- [ ] Final prod health or rollback verification is recorded without claiming completion from a PR merge alone.
  - Verify: runtime receipt: model_access_router.staged_rollout.v1

## How to Verify (Pre-Merge)

- Run pytest -q tests/release/test_model_access_router_rollback_plan.py.
- Prepare the candidate with the applicable release-channel skill. Execute no test/prod mutation until that skill has the complete operator-acknowledged plan.
- Attach the stage and final verification receipts to the parent issue.

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
