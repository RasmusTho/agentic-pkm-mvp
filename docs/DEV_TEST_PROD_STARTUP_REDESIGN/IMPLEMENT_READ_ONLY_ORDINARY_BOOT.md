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

State: Implemented in the repository by Issue #4916. The delivered surface is the read-only
resolver/doctor and terminal journal; it does not activate a channel, run migration, or replace the
current canonical prod startup command.

# Implement Read-Only Ordinary Boot

## Purpose

Make ordinary prod boot safe to repeat: it resolves declared state and starts only when compatibility is already true.

## What This Task Does

Adds a deterministic resolver/doctor and terminal journal. Ordinary boot neither pulls, builds, migrates, changes pins, bootstraps BuilderOps, provisions Ollama, ingests, indexes, nor restructures a vault. Dependencies are explicitly `required` or `degraded_ok`.

## Concretely

`python -m app.release_channels.ordinary_boot doctor` reports the resolved
digest/config/vault/schema identities and a single terminal classification; it exits before writers
when required compatibility is absent. A separate caller may act only when the result says
`writers_permitted=true`; this doctor does not expose a writer-start hook.

The dependency input is an already-observed JSON mapping keyed by `artifact`, `config`, `database`,
`gateway`, `schema`, `vault`, and (when declared) `llm`. Each entry carries
`status=available|unavailable`; identity-bearing required dependencies also carry their observed
`identity`. Policy is derived from the exact manifest, never supplied by the observation: identity,
schema, vault, database, gateway, and config are `required`; `llm_policy=declared-optional` maps only
the LLM dependency to `degraded_ok`. Missing observations classify as unavailable, unknown
dependencies fail closed, and raw mismatched observed identity values are not copied into the
terminal journal.

The operation id must be a generated opaque non-secret handle in the narrow
`ob-<32 lowercase hex characters>` format; rejected values and conflict errors never echo the
supplied handle. The journal path must be an absolute `.jsonl` path under a real, same-user-owned
parent that is not group- or world-writable. That checked parent is the trust boundary against an
untrusted alias race. The doctor pins and revalidates the parent plus opened file identity, accepts
only a single-link regular file, and refuses symlink, hardlink, FIFO, or named-path replacement
targets before returning terminal authority.

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
