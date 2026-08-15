---
name: Freeze Channel Manifest And Operation Contract
description: Specify the secret-free channel identity, operation state machine, receipt binding, and hard stops.
task_id: STARTUP-01
github_issue: 4914
source_anchor: docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md :: Kernel invariants
parent_capability: DEV_TEST_PROD_STARTUP_REDESIGN
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Freeze Channel Manifest And Operation Contract

## Purpose

Freeze K1–K9 before changing Compose, pins, database state, or vault bindings. The contract gives subsequent slices one machine-readable identity and one fail-closed operation vocabulary.

## What This Task Does

Defines a non-secret ChannelManifest with channel, intent/mode, Compose project, DB/vault/artifact/worktree identities, schema compatibility, LLM policy, ports, gateway, and secret *references*. Defines terminal operation phases, receipt revocation, and hard-stop conditions.

## Concretely

`channel-manifest validate --channel prod --intent ordinary-boot` must reject an absent digest, ambiguous vault identity, inline secret value, or implicit fallback. `tests/fixtures/startup_redesign/channel_manifest.valid.json` is the P1 schema fixture.

## Why This Matters

Without a shared identity contract, a restart can combine an old DB, mutable checkout, and wrong vault while reporting a green process.

## Acceptance Criteria

- [ ] The contract names every K1–K9 invariant and its enforcement phase. Verify: `tests/architecture/test_startup_redesign_contract.py::test_kernel_contract_names_every_invariant`.
- [ ] The fixture contains only secret references, never secret values. Verify: `tests/architecture/test_startup_redesign_contract.py::test_manifest_fixture_is_secret_free`.
- [ ] Terminal phases distinguish pre-mutation failure, failed-after-migration, activation failure, and PASS. Verify: `tests/architecture/test_startup_redesign_contract.py::test_operation_contract_names_truthful_terminal_phases`.

## How to Verify (Pre-Merge)

`pytest -q tests/architecture/test_startup_redesign_contract.py`

## Out of Scope

Compose, resolver implementation, credential provisioning, migration execution, and any prod mutation.

## Related Docs

`docs/RELEASE_CHANNELS/README.md`; `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`.

## Related GitHub Issues

Pre-filing: reconcile #2655/#2698 and their children first.
