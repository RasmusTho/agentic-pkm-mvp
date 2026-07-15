---
name: Resolve Instance Default Vault
description: Add an explicit durable default and one fail-closed selection precedence resolver
task_id: MVR-02
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Identity and selection"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-01]
depends_on: [ESTABLISH_INSTANCE_VAULT_REGISTRY.md]
can_parallelize_with: []
---

# Resolve Instance Default Vault

## Purpose

`last_active_vault_ref` is interaction history, while env-based `VAULT_ROOT` is a deployment
bootstrap. Neither is a truthful instance default. This slice adds a distinct default and one
fail-closed precedence resolver.

## What This Task Does

- Add nullable `default_vault_binding_id` to the versioned instance registry settings. Treat a
  compatibility `DEFAULT_VAULT_ID` as an untrusted logical-ID lookup that must resolve to exactly
  one local binding.
- Provide one resolver for explicit request, session, default, legacy bootstrap, and no-vault
  outcomes, with inspectable provenance.
- During the one-time schema migration only, materialize a valid legacy
  `last_active_vault_ref` as the default when no default exists, recording
  `legacy_last_active_migration` provenance. Subsequent last-active changes never update default.
- Expose authenticated Companion API and headless CLI get/set/clear commands through one service.
  They validate registration and authority, use MVR-01's locked transaction, emit redacted
  receipts, and never mutate last-active. Tests drive these production commands rather than seeding
  the store or invoking an internal setter directly.
- Preserve no-vault startup and headless bootstrap behavior through explicit adapters.

## Concretely

With vault A configured as the instance default, a fresh background caller resolves A with
`provenance=instance_default`; session B may select vault B without mutating that default. A
request naming a missing vault returns an explicit selection failure instead of A.

## Why This Matters

Conflating last interaction, deploy bootstrap, and default makes restarts nondeterministic and
turns an invalid explicit selection into a dangerous silent read/write against the wrong vault.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Identity and selection`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: precedence`
- `app/config/paths.py :: resolve_optional_vault_root`
- `app/vault/manager.py :: load_last_active`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): PDM, EBF, OEF
- Write class: mechanical durable instance setting
- Authority impact: none; resolver must call GOV before content use
- Persistence impact: additive nullable registry field with migrated producers
- Derived/rebuildable impact: resolution result is ephemeral/rebuildable
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: supplies the compatibility/background fallback binding
- Sync/deployment impact: env remains explicit legacy bootstrap, not hidden default
- External boundary impact: no CWD or mount-path inference
- New or changed contract: default/selection precedence and provenance
- Owner-doc impact: will-update-in-PR at `docs/ENVIRONMENTS.md`
- Transition debt impact: reduces last-active/env/default conflation
- Fitness rule impact: strengthens fail-closed no-silent-fallback behavior

## Constraints

- Explicit unknown, removed, or unauthorized selection fails closed; it never falls through.
- `default_vault_binding_id`, `last_active_vault_ref`, and active request/session selection stay distinct.
- No-vault remains a valid result.

## Acceptance Criteria

- [ ] The production resolver applies explicit request > session > instance default > explicit
  legacy bootstrap > no-vault and reports which branch won.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_production_resolution_precedence_is_explicit`
- [ ] An invalid explicit request/session/default fails closed without selecting last-active,
  another registry entry, CWD, or `./vault`.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_invalid_explicit_selection_never_falls_through`
- [ ] Setting or clearing a default survives restart and never changes `last_active_vault_ref`.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_default_is_durable_and_distinct_from_last_active`
- [ ] Authenticated production API and CLI get/set/clear commands are the tested producers, reject
  unknown/unauthorized bindings, and converge on the same locked registry state and receipt.
  - Verify: `tests/api/test_default_vault_admin.py::test_production_default_commands_share_one_service`
- [ ] A picker-only one-vault legacy store with no explicit default restarts on the same binding
  through the one-time provenance-tagged migration; later selections do not mutate that default.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_legacy_last_active_materializes_default_once`
- [ ] Existing no-vault and single-vault bootstrap paths remain truthful.
  - Verify: `tests/integration/test_single_vault_compatibility.py::test_default_adapter_preserves_bootstrap_and_no_vault`
- [ ] The explicit default persists on the MVR-01 instance-state volume across a pinned-image
  force-recreate and resolves identically in every enabled registry consumer.
  - Verify: `tests/integration/test_vault_registry_container_durability.py::test_default_survives_recreate_after_mvr02`

## Out of Scope

- HTTP session storage, multi-binding contexts, dimensions, or default-vault UI.

## How to Verify (Pre-Merge)

- `pytest -q tests/instance/test_default_vault_resolution.py tests/api/test_default_vault_admin.py tests/integration/test_single_vault_compatibility.py tests/integration/test_vault_registry_container_durability.py`
- `ruff check app tests`

## Restart / Durability Posture

`default_vault_binding_id` survives restart independently of later last-active history. The one-time
legacy migration preserves the pre-existing picker restart journey and records its provenance.
Request/session choices do not survive unless their own session contract says so; after session
loss the explicit instance default (or no-vault) is visible rather than a guessed prior selection.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/ENVIRONMENTS.md`
- `docs/VAULT_OPTIONAL_RUNTIME/README.md`

## Related GitHub Issues

Create one child under #2143 after MVR-01 merges. Persist the Sol/high TCD hint because authority
precedence and durable default semantics are high-risk. Preserve #2003/#2311; do not reopen them.
