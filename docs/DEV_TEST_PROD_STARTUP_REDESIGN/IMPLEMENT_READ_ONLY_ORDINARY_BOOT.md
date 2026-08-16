---
name: Implement Read-Only Ordinary Boot
description: Add deterministic manifest resolution, compatibility diagnosis, and one terminal boot result.
task_id: STARTUP-03
github_issue: 4916
source_anchor: docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md :: Kernel invariants
parent_capability: DEV_TEST_PROD_STARTUP_REDESIGN
prerequisites: [STARTUP-01, STARTUP-02]
depends_on: [FREEZE_CHANNEL_MANIFEST_AND_OPERATION_CONTRACT.md, BUILD_IMMUTABLE_ARTIFACT_GRAPH.md]
can_parallelize_with: []
---

# Implement Read-Only Ordinary Boot

## Purpose

Make ordinary prod boot safe to repeat: it resolves declared state and starts only when compatibility is already true.

## What This Task Does

Adds a deterministic resolver/doctor and terminal journal. Ordinary boot neither pulls, builds, migrates, changes pins, bootstraps BuilderOps, provisions Ollama, ingests, indexes, nor restructures a vault. Dependencies are explicitly `required` or `degraded_ok`.

## Concretely

`channel-doctor prod ordinary-boot` reports the resolved digest/config/vault/schema identities and a single terminal classification; it exits before writers when required compatibility is absent.

## Why This Matters

Restarting must not silently turn into deployment or data repair.

## Acceptance Criteria

- [ ] Ordinary boot has production call-site assertions proving no build/pull/migrate/pin-write/bootstrap path is invoked. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_ordinary_boot_has_no_mutation_calls`.
- [ ] A missing required dependency fails before writers, while declared degraded dependencies retain their exact classification. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_ordinary_boot_dependency_policy`.

## How to Verify (Pre-Merge)

Replace strict-xfail skeletons with call-site tests and run focused resolver/journal tests.

## Out of Scope

Promotion, schema migration, runtime recovery execution, and UI redesign.

## Related Docs

`docs/ENVIRONMENTS.md`; `docs/OPERATIONS.md`.

## Related GitHub Issues

Filed ownership: #4916 (P3), under parent validation hub #4913. The live overlap reconciliation was completed before filing; this task owns read-only ordinary-boot enforcement for the newer chain.
