---
name: Promote Multi Vault Runtime Truth
description: Verify merged capability update owner truth reconcile dependencies and close the parent ledger
task_id: MVR-08
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Capability acceptance"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-01, MVR-02, MVR-03, MVR-04, MVR-05, MVR-06, MVR-07]
depends_on: [ESTABLISH_INSTANCE_VAULT_REGISTRY.md, RESOLVE_INSTANCE_DEFAULT_VAULT.md, VERSION_ACTIVE_CONTEXT_SELECTION.md, GROUP_VAULT_BINDINGS_BY_DIMENSION.md, ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md, BIND_BACKGROUND_LIFECYCLES.md, PRESERVE_SINGLE_VAULT_MIGRATION.md]
can_parallelize_with: []
---

# Promote Multi Vault Runtime Truth

## Purpose

The final slice proves the integrated capability on merged code, updates owner documents and
transition debt, reconciles downstream hubs, and constructs the closure ledger for #2143. It adds
no new runtime behavior.

## What This Task Does

- Run the capability acceptance suite on merged `origin/main`, including concurrent sessions,
  dimension resolution, background lifecycles, governed writes, and no/one-vault compatibility.
- Execute the relevant isolated test-channel journey and record redacted vault-binding/startup
  evidence.
- Promote shipped truth into architecture, ActiveContextSet, topology, settings/environment, SBS
  debt, and docs index surfaces; remove future-state wording only where evidence supports it.
- Reconcile #2566 and #3156/#3163 dependency/status truth without duplicating or auto-closing their
  distinct UI/Settings scope.
- Post a parent ledger mapping every child, parent AC, Verify target, merged PR/SHA, owner-doc
  writeback, and residual debt; close #2143 only when no gap remains.

## Concretely

On one merged SHA, the acceptance suite proves isolated sessions A/B, a two-member dimension,
one governed write with source/target receipt, truthful background health, and the unchanged
single-vault journey. The redacted GitHub ledger links that evidence and every owner-doc diff.

## Why This Matters

Branch-local tests or partially updated docs can make an epic appear delivered while consumers,
operators, or future agents still act on stale single-global-vault truth.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Capability acceptance`
- `docs/MULTI_VAULT_RUNTIME/PARENT_FEATURE_ISSUE.md :: Validation / acceptance path`
- GitHub issue `#2143`
- `docs/architecture/SBS_TRANSITION_DEBT.md`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): all affected owner boundaries; Builder System verification loop
- Write class: docs/governance/process plus external runtime receipt; no product mutation
- Authority impact: verifies GOV separation; no authority change
- Persistence impact: verifies prior slices only
- Derived/rebuildable impact: verifies isolation/rebuildability only
- Human knowledge impact: owner docs become truthful about shipped capability
- Memory impact: verifies provenance/isolation only
- Retrieval/context impact: verifies production request/background adoption
- Sync/deployment impact: test-channel verification receipt and truthful channel notes
- External boundary impact: receipts are redacted; no host paths, secrets, or binding payloads
- New or changed contract: promotes target contract to shipped state where proven
- Owner-doc impact: will-update-in-PR across named owners
- Transition debt impact: close/re-baseline D1/D13/D14 and record any bounded residue
- Fitness rule impact: registers integrated multi-vault runtime fitness targets

## Constraints

- Do not claim delivery from branch-only or local-only evidence; verify merged `origin/main`.
- Do not expose vault paths, secrets, tokens, note content, or raw binding payloads in GitHub receipts.
- Do not close #2566/#3156/#3163 merely because this runtime epic lands.
- Do not close #2143 with a missing child receipt, Verify target, owner-doc writeback, or unresolved
  transition-debt claim.

## Acceptance Criteria

- [ ] Concurrent request/session, dimension, background lifecycle, governed-write, and isolation
  acceptance targets pass on merged `origin/main`.
  - Verify: `tests/integration/test_multi_vault_capability_acceptance.py::test_merged_multi_vault_capability`
- [ ] No-vault and one-vault compatibility targets pass on the same merged head.
  - Verify: `tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`
- [ ] The isolated test-channel journey records a redacted receipt for two vault bindings, two
  sessions, one dimension read, one governed write, and truthful background health.
  - Verify: runtime receipt on GitHub issue `#2143`
- [ ] Architecture/context/topology/settings/environment owner docs and transition debt match
  shipped behavior; every spec file remains indexed.
  - Verify: doc writeback at `docs/ARCHITECTURE.md :: Active context and vault bindings` + doc
  writeback at `docs/contracts/ACTIVE_CONTEXT_SET.md :: Runtime status` + doc writeback at
  `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Runtime selection model` + doc writeback at
  `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Future Multi-Vault` + doc writeback at
  `docs/SETTINGS.md :: Multi-vault settings resolution` + doc writeback at
  `docs/ENVIRONMENTS.md :: Vault terminology` + doc writeback at
  `docs/architecture/SBS_TRANSITION_DEBT.md :: multi-vault runtime selection` + doc writeback at
  `docs/DOCS_INDEX.md :: v6.0 Capability Specifications`
- [ ] #2566 and #3156/#3163 show truthful dependency/status receipts with no duplicate scope.
  - Verify: GitHub comment receipts on issues `#2566`, `#3156`, and `#3163`
- [ ] #2143 contains a complete child/AC/Verify/PR/SHA/owner-doc ledger and has no residual open
  executable scope.
  - Verify: runtime receipt on GitHub issue `#2143`

## Out of Scope

- New implementation, overlay UI #2566, unrelated Settings Spine children, production promotion,
  or multi-writer redesign.

## How to Verify (Pre-Merge)

- `git fetch origin main && git rev-parse HEAD && git rev-parse origin/main`
- `pytest -q tests/integration/test_multi_vault_capability_acceptance.py tests/integration/test_single_vault_compatibility.py`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/`
- `python3 scripts/docs_guard.py`
- Live REST inspection of #2143, all child issues/PRs, #2566, #3156, and #3163

## Restart / Durability Posture

This slice adds no runtime state. It verifies that registry/default semantics survive restart,
session loss resolves visibly, and lifecycle state is rebuilt truthfully; durable evidence lives
in merged docs, CI/UAT runs, and redacted GitHub receipts.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/MULTI_VAULT_RUNTIME/PARENT_FEATURE_ISSUE.md`
- `docs/ARCHITECTURE.md`
- `docs/architecture/SBS_TRANSITION_DEBT.md`

## Related GitHub Issues

Create the terminal child under #2143 and keep it blocked until MVR-01–07 merge. Use Terra/high for
the mechanical ledger and verification; escalate to Sol/high if residual architecture/authority
risk remains. Reconcile but do not duplicate or auto-close #2566, #3156, or #3163.
