---
name: Group Vault Bindings By Dimension
description: Persist non-authoritative dimension membership over registered vault identities
task_id: MVR-04
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Dimensions"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-01, MVR-03]
depends_on: [ESTABLISH_INSTANCE_VAULT_REGISTRY.md, VERSION_ACTIVE_CONTEXT_SELECTION.md]
can_parallelize_with: []
---

# Group Vault Bindings By Dimension

## Purpose

#2143 names dimensions as the owner's grouping axis. Existing scope, sphere, confidentiality,
topology, and authorization contracts already have separate owners, so a dimension must remain a
non-authoritative registry grouping.

## What This Task Does

- Add versioned `dimension_id`, display metadata, and ordered membership over registered
  `vault_binding_id` values to the instance registry.
- Provide add/remove/list/filter operations and resolve a dimension into explicit source bindings.
- Provide authenticated Companion API and headless CLI create/rename/set-members/delete/list/resolve
  commands through the same locked registry service. Additions/replacements validate every proposed
  binding and content authority; instance-authorized remove-member/delete may clear stale or
  unauthorized stored membership without resolving it. All mutations emit redacted receipts and
  are the production producers exercised by tests; no store seeding counts.
- Preserve per-binding identity, provenance, and GOV evaluation in multi-binding contexts.
- Make production dimension-to-context resolution all-or-nothing: an unknown, stale, removed, or
  unauthorized member fails the entire resolution with a redacted member-specific error. It never
  returns an authorized subset. Authenticated registry administration may inspect stored membership
  but that inspection is not an ActiveContextSet or permission result.
- Remove dangling membership transactionally when a registration is removed, while keeping
  removal of a dimension non-destructive to registrations/content. This explicitly extends the
  MVR-01/02 registration-removal transaction; earlier slices do not know the dimension schema.
- Extend the MVR-01 rollback lineage for the additive dimension schema: a pre-MVR-04 image cannot
  read or mutate dimensions, so its scalar projection omits them while the complete dimension state
  remains immutable. On roll-forward, unchanged registrations restore dimensions exactly. A valid
  old-image registration removal is imported in the same locked transaction that removes that
  binding from every dimension, records a repair receipt, and preserves remaining member order;
  ambiguous identity/divergent mutation blocks merge rather than leaving a dangling member or
  guessing membership.

## Concretely

A `work` dimension contains vaults A and B. Resolving it yields two separate bindings, each with
its own GOV verdict and provenance. Deleting `work` leaves A and B registered and untouched.

## Why This Matters

If grouping is allowed to imply permission, topology, or identity, a convenience selector becomes
a hidden authority system and can expose material across real confidentiality boundaries.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Dimensions`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Topology rules`
- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/README.md :: separation`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): GOV, SFC, PDM, EBF
- Write class: mechanical durable instance-local grouping metadata
- Authority impact: none; explicit invariant that dimensions never authorize
- Persistence impact: versioned additive registry membership
- Derived/rebuildable impact: resolved member binding list is rebuildable
- Human knowledge impact: no content merge or identity rewrite
- Memory impact: none directly
- Retrieval/context impact: dimension can seed an explicit many-binding context
- Sync/deployment impact: grouping remains per instance unless a later contract defines sync
- External boundary impact: dimension is neither mount nor confidentiality boundary
- New or changed contract: dimension grouping semantics
- Owner-doc impact: will-update-in-PR at `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`
- Transition debt impact: no effect beyond enabling explicit grouping
- Fitness rule impact: strengthens separation of selection/grouping from authority

## Constraints

- A dimension does not grant access, select a default, merge identities, or imply topology.
- GOV checks every member independently; any unauthorized/unknown/stale member fails the entire
  production context resolution, never an exclusion, partial result, or silent substitution.
- Dimension deletion never deletes vault content or registrations.

## Acceptance Criteria

- [ ] Dimension membership survives restart and retains stable ordered vault-binding IDs, including
  two local clones that share one logical vault ID.
  - Verify: `tests/instance/test_vault_dimensions.py::test_dimension_membership_round_trip`
- [ ] Authenticated production API and CLI administration create, rename, replace membership,
  delete, list, and resolve dimensions through one service with authorization and receipts.
  - Verify: `tests/api/test_vault_dimension_admin.py::test_production_dimension_commands_drive_registry`
- [ ] Resolving a dimension returns explicit per-vault bindings and performs independent production
  authorization for every member.
  - Verify: `tests/api/test_dimension_context_resolution.py::test_dimension_resolution_authorizes_each_binding`
- [ ] An unauthorized/unknown/stale member fails the entire production resolution without exposing
  an authorized partial set, conferring authority, or triggering fallback.
  - Verify: `tests/api/test_dimension_context_resolution.py::test_dimension_never_upgrades_authority_or_falls_back`
- [ ] Removing a dimension preserves registrations/content; removing a registration repairs
  dangling membership transactionally.
  - Verify: `tests/instance/test_vault_dimensions.py::test_dimension_and_registration_removal_are_safe`
- [ ] Instance-authorized administration can remove a stale or unauthorized stored member (or delete
  its dimension) without resolving an authorized subset; additions and resolution still fail closed.
  - Verify: `tests/api/test_vault_dimension_admin.py::test_admin_can_repair_stale_dimension_membership`
- [ ] The parent dimension contract proves that stored membership preserves each binding's
  independent authority and provenance and never upgrades access through grouping.
  - Verify: `tests/integration/test_multi_vault_dimensions.py::test_dimension_preserves_per_binding_authority_and_provenance`
- [ ] A rollback through a pre-MVR-04 compatible scalar image preserves dimension metadata and
  ordered membership; unchanged registrations restore exactly, while a valid rollback-period
  registration removal transactionally removes that member from every dimension with a receipt.
  - Verify: `tests/integration/test_vault_registry_rollback.py::test_mvr04_dimensions_survive_scalar_projection_round_trip`
- [ ] Roll-forward after the old image removes a dimension member never creates dangling membership,
  silently restores the removed registration, or prunes any unrelated ordered member.
  - Verify: `tests/integration/test_vault_registry_rollback.py::test_mvr04_rollforward_repairs_removed_dimension_member_transactionally`
- [ ] The topology owner contract describes the shipped non-authoritative dimension metadata,
  all-or-nothing member resolution, and preserved per-binding provenance in the same PR.
  - Verify: doc writeback at `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Dimensions`

## Out of Scope

- Role/confidentiality policy, sphere membership, topology authority, UI, or automatic grouping.

## How to Verify (Pre-Merge)

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/instance/test_vault_dimensions.py tests/api/test_vault_dimension_admin.py tests/api/test_dimension_context_resolution.py tests/integration/test_multi_vault_dimensions.py tests/integration/test_vault_registry_rollback.py`
- `mypy app`
- `pytest -q -m "not pg"`
- `ruff check app tests`

## Restart / Durability Posture

Dimension metadata and membership survive restart in the registry store. Removing a member or
dimension is transactional and never changes content; failed persistence leaves prior membership
truth visible rather than partially applying it.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`
- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/README.md`

## Related GitHub Issues

Create one child under #2143 after MVR-01 and MVR-03. Sol/high owns initial authority-boundary review; once the
contract is frozen, mechanical registry execution may use Terra/high. Do not duplicate scope/sphere
or topology issues.
