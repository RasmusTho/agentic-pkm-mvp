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
- In the MVR-08 PR, change README to shipped capability truth and convert the parent reference from a
  blocked/future template into a closure-ready historical ledger. That repo ledger records merged
  MVR-01A–01C, MVR-02–04, MVR-05A–05D, MVR-06A–06D, and MVR-07 receipts plus the MVR-08 PR/head candidate, but explicitly delegates MVR-08's eventual
  merge SHA and the live open/closed state to GitHub #2143; it never predicts its own merge.
- The parent closure workflow, not the MVR-08 child, runs after MVR-08 merges: it appends that exact
  merge SHA and every final receipt to #2143, closes it only when no gap remains, then creates and
  delivers one docs-only post-close receipt PR that records the live close state and merge SHA. That
  historical writeback is neither an open terminal-child criterion nor reopened runtime scope.

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
- Owner-doc impact: will-update-in-PR across named owners and this capability's README/parent ledger
- Transition debt impact: close/re-baseline D1/D13/D14 and record any bounded residue
- Fitness rule impact: registers integrated multi-vault runtime fitness targets

## Constraints

- Do not claim delivery from branch-only or local-only evidence; verify merged `origin/main`.
- Do not expose vault paths, secrets, tokens, note content, or raw binding payloads in GitHub receipts.
- Do not close #2566/#3156/#3163 merely because this runtime epic lands.
- Do not close #2143 with a missing child receipt, Verify target, owner-doc writeback, or unresolved
  transition-debt claim.

## Acceptance Criteria

- [ ] The MVR-08 candidate adds and passes the aggregate concurrent request/session, dimension,
  background lifecycle, governed-write, and isolation acceptance target. The parent closure
  workflow reruns it on merged `origin/main` after this child merges.
  - Verify: `tests/integration/test_multi_vault_capability_acceptance.py::test_merged_multi_vault_capability`
- [ ] No-vault and one-vault compatibility targets pass on the same MVR-08 candidate head.
  - Verify: `tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`
- [ ] The isolated test-channel journey records a redacted receipt for two vault bindings, two
  sessions, one dimension read, one governed write, and truthful background health.
  - Verify: runtime receipt on GitHub issue `#2143`
- [ ] Architecture/context/topology/settings/environment owner docs and transition debt match
  shipped behavior; every spec file remains indexed.
  - Verify: doc writeback at `docs/ARCHITECTURE.md :: Active context and vault bindings` + doc
  writeback at `docs/contracts/ACTIVE_CONTEXT_SET.md :: Runtime status` + doc writeback at
  `docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: GovernedWriteProtocol` + doc writeback at
  `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Runtime selection model` + doc writeback at
  `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Future Multi-Vault` + doc writeback at
  `docs/SETTINGS.md :: Multi-vault settings resolution` + doc writeback at
  `docs/ENVIRONMENTS.md :: Vault terminology` + doc writeback at
  `docs/HEALTH.md :: Runtime health` + doc writeback at
  `docs/SECURITY.md :: Security` + doc writeback at
  `docs/EVENTS.md :: Events` + doc writeback at
  `docs/DB_SCHEMA.md :: DB Schema (Current Reality)` + doc writeback at
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deployment and Environments` + doc writeback at
  `docs/RELEASE_CHANNELS/README.md :: Release Channels Specification` + doc writeback at
  `docs/architecture/SBS_TRANSITION_DEBT.md :: multi-vault runtime selection` + doc writeback at
  `docs/DOCS_INDEX.md :: v6.0 Capability Specifications`
- [ ] This capability's own lifecycle surfaces no longer claim future/blocked runtime state: README
  records shipped scope/residual debt, while the parent reference contains merged MVR-01A–01C,
  MVR-02–04, MVR-05A–05D, MVR-06A–06D, and MVR-07 receipts,
  the MVR-08 candidate, and an explicit pointer making live #2143 authoritative for MVR-08 merge SHA
  and closure status. The parent closure workflow, outside this child, records exact live closure
  evidence in both checked-in lifecycle surfaces.
  - Verify: doc writeback at `docs/MULTI_VAULT_RUNTIME/README.md :: Multi-vault runtime selection` +
    doc writeback at `docs/MULTI_VAULT_RUNTIME/PARENT_FEATURE_ISSUE.md :: Parent reference — Multi-vault runtime selection`
- [ ] #2566 and #3156/#3163 show truthful dependency/status receipts with no duplicate scope.
  - Verify: GitHub comment receipts on issues `#2566`, `#3156`, and `#3163`
- [ ] The MVR-08 child leaves a complete closure-ready child/AC/Verify/PR/owner-doc ledger in its PR
  and #2143 comment, with no residual executable runtime scope. Its own acceptance ends at that
  receipt; it does not close #2143 or require post-close work.
  - Verify: runtime receipt on GitHub issue `#2143`

## Out of Scope

- New implementation, overlay UI #2566, unrelated Settings Spine children, production promotion,
  or multi-writer redesign.

## How to Verify (Pre-Merge)

- Before authoring owner-doc/debt promotion, fetch MVR-07's merged `origin/main`, create a clean
  detached worktree at that exact ref, run every already-delivered child/capability target there,
  and post the SHA/result to #2143. A dirty, branch-local, or stale run blocks preparation of the
  MVR-08 promotion PR; this proves merged runtime before its description is promoted.
- In that MVR-07 merged-head worktree run:
  `pytest -q tests/instance/test_vault_registry_migration.py::test_parent_registry_acceptance tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance tests/integration/test_multi_vault_lifecycle_and_dimension.py::test_parent_dimension_background_acceptance tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk tests/integration/test_multi_vault_resolution.py::test_resolution_precedence_and_fail_closed_behavior tests/integration/test_multi_vault_dimensions.py::test_dimension_preserves_per_binding_authority_and_provenance tests/architecture/test_multi_vault_context_boundaries.py::test_production_consumers_use_context_seam tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`.
- On the PR head, run every child pre-merge target plus docs/lint checks; this is candidate evidence,
  not the merged-head closure receipt.
- `pytest -q tests/integration/test_multi_vault_capability_acceptance.py::test_merged_multi_vault_capability tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/`
- Route the exact candidate through the governed
  [promote-to-test](../../.codex/skills/promote-to-test/SKILL.md) workflow with
  `MVR08_CANDIDATE_SHA` as its candidate ref. That workflow must run its channel-isolation
  preflight before mutation, select the live checkout or pinned-image deployment model, and emit
  the durable test-promotion receipt for that exact SHA. A direct `deploy_channel.sh` invocation is
  not acceptance evidence; the governed workflow may invoke the script only after it has proved
  that the test channel is pinned-image based. Fail if the selected deployment model cannot resolve
  the exact artifact/checkout SHA.
- With two isolated disposable test bindings declared in the redacted fixture manifest, run
  `python3 scripts/multi_vault_test_channel_smoke.py --channel test --fixture-manifest "$MVR_TEST_FIXTURE_MANIFEST" --json`.
  The MVR-07 compatibility slice owns this harness and its production-path/root-safety tests. Before
  registration it must canonicalize every manifest root, prove each is a distinct descendant of the
  declared test sandbox, and reject known prod/dev/native roots, overlap, or symlink escape with zero
  effects. It then asserts two
  registered bindings, two independent sessions, one dimension read, one governed write to the
  explicit target, and per-binding background health, then emit only SHA, opaque fixture IDs,
  boolean outcomes, and receipt IDs for the #2143 comment—never paths, names, tokens, or content.
- `python3 scripts/docs_guard.py`
- Live REST inspection of #2143, all child issues/PRs, #2566, #3156, and #3163

## How to Verify (Post-Merge Closure)

- Fetch `origin/main`, create a clean detached worktree at that exact ref, and fail unless
  `test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"` and
  `test -z "$(git status --porcelain)"` both succeed inside it. Record that SHA on #2143 before
  parent closure or shipped-status promotion; the earlier pre-PR receipt is the owner-doc gate.
- In that detached merged-head worktree run:
  `pytest -q tests/instance/test_vault_registry_migration.py::test_parent_registry_acceptance tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance tests/integration/test_multi_vault_lifecycle_and_dimension.py::test_parent_dimension_background_acceptance tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk tests/integration/test_multi_vault_resolution.py::test_resolution_precedence_and_fail_closed_behavior tests/integration/test_multi_vault_dimensions.py::test_dimension_preserves_per_binding_authority_and_provenance tests/architecture/test_multi_vault_context_boundaries.py::test_production_consumers_use_context_seam tests/integration/test_multi_vault_capability_acceptance.py::test_merged_multi_vault_capability tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`.
- Run the opt-in integrated UAT in the same worktree and attach its exact merged SHA and result to
  #2143. A branch-local, dirty, stale, skipped, or missing-target run cannot close the parent.
- Route that exact merged `origin/main` SHA through the governed
  [promote-to-test](../../.codex/skills/promote-to-test/SKILL.md) workflow again, then run
  `python3 scripts/multi_vault_test_channel_smoke.py --channel test --fixture-manifest "$MVR_TEST_FIXTURE_MANIFEST" --json`
  against the resulting test deployment. The durable test-promotion receipt and redacted smoke
  receipt must both name the merged SHA; candidate-SHA channel evidence cannot close the parent.
- **Parent closure workflow, outside the MVR-08 child:** after its merge, post MVR-08's exact merge
  SHA and the merged-head receipt to #2143, close the parent only when that ledger is complete, then
  create and merge the required docs-only post-close receipt PR and link it from the closed parent.
  This post-close historical writeback is not an MVR-08 acceptance criterion and does not leave the
  terminal child open or reopen runtime scope.

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

Create the terminal child under #2143 and keep it blocked until MVR-01A–01C, MVR-02–04,
MVR-05A–05D, MVR-06A–06D, and MVR-07 merge. Use Terra/high for
the mechanical ledger and verification; escalate to Sol/high if residual architecture/authority
risk remains. Reconcile but do not duplicate or auto-close #2566, #3156, or #3163.
