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
- Provide one resolver for explicit one-request override, retained session selection, default,
  legacy bootstrap, and no-vault outcomes, with inspectable provenance. MVR-05 exposes the two
  production ingress carriers: `X-Active-Context-Override` and `X-Active-Context-Session`.
- During the one-time schema migration only, materialize a valid legacy
  `last_active_vault_ref` as the default when no default exists, recording
  `legacy_last_active_migration` provenance. Subsequent last-active changes never update default.
- Make first-vault initialization a distinct MVR-02 default producer: if the registry has no
  registration/default, its locked registration transaction atomically sets that new binding as the
  explicit default with `first_vault_initialize` provenance. Later picker/last-active writes still
  never infer a default.
- Expose authenticated Companion API and headless CLI get/set/clear commands through one service.
- Extend the MVR-01 rollback projection/roll-forward merge for the default schema introduced here:
  a scalar previous image receives only the already validated explicit rollback target, never an
  inferred default, while the authoritative `default_vault_binding_id` remains in the new-schema
  lineage. On roll-forward, the locked merge first verifies that its binding still exists: it
  restores it only if present, otherwise atomically clears it or blocks for an explicit authorized
  replacement; it never leaves a dangling default or silently chooses another registration. A valid
  current-schema mutation may also have replaced/cleared it before rollback.
  They validate registration and authority, use MVR-01's locked transaction, emit redacted
  receipts, and never mutate last-active. Tests drive these production commands rather than seeding
  the store or invoking an internal setter directly.
- Make registration removal reference-safe: removing the current default returns a conflict unless
  the same locked transaction supplies either `clear_default=true` or one valid authorized
  replacement binding. Explicit clear/replacement updates only MVR-01/02-owned registration/default
  fields and the removal revision/event atomically; it never silently chooses another registration
  or leaves a dangling default. MVR-04 and MVR-06 extend this transaction when they introduce
  dimension and compatibility-intent references—MVR-02 does not interpret their future schemas.
- Publish the versioned default-mutation event later consumed by MVR-06; no MVR-02 caller requires
  or mutates a future background-intent field.
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

- [ ] The production resolver accepts distinct explicit one-request-override and retained-session
  inputs, applies override > session > instance default > explicit legacy bootstrap > no-vault,
  and reports which branch won. MVR-05B owns their later HTTP carriers and non-mutation proof.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_production_resolution_precedence_is_explicit`
- [ ] An invalid explicit request/session/default fails closed without selecting last-active,
  another registry entry, CWD, or `./vault`.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_invalid_explicit_selection_never_falls_through`
- [ ] Setting or clearing a default survives restart and never changes `last_active_vault_ref`.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_default_is_durable_and_distinct_from_last_active`
- [ ] Authenticated production API and CLI get/set/clear commands are the tested producers, reject
  unknown/unauthorized bindings, and converge on the same locked registry state and receipt.
  - Verify: `tests/api/test_default_vault_admin.py::test_production_default_commands_share_one_service`
- [ ] Default set/clear publishes exactly one versioned mutation event carrying the new registry
  revision and no raw binding payload; MVR-06 consumes this contract for compatibility rebind.
  - Verify: `tests/api/test_default_vault_admin.py::test_default_mutation_publishes_versioned_rebind_event`
- [ ] A picker-only one-vault legacy store with no explicit default restarts on the same binding
  through the one-time provenance-tagged migration; later selections do not mutate that default.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_legacy_last_active_materializes_default_once`
- [ ] A no-vault installation that initializes its first vault after MVR-02 atomically records that
  binding as its explicit default; subsequent last-active changes do not alter it.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_first_vault_initialize_materializes_default_once`
- [ ] Existing no-vault and single-vault bootstrap paths remain truthful.
  - Verify: `tests/integration/test_single_vault_compatibility.py::test_default_adapter_preserves_bootstrap_and_no_vault`
- [ ] Removing the current default is rejected unless the production mutation explicitly clears or
  replaces it in the same locked transaction; no dangling or silently substituted default remains.
  - Verify: `tests/api/test_default_vault_admin.py::test_removing_current_default_requires_atomic_clear_or_replacement`
- [ ] The explicit default persists on the MVR-01 instance-state volume across a pinned-image
  force-recreate and resolves identically in every enabled registry consumer.
  - Verify: `tests/integration/test_vault_registry_container_durability.py::test_default_survives_recreate_after_mvr02`
- [ ] Scalar rollback never converts explicit default into last-active or silently changes it; the
  old projection uses the validated rollback target while roll-forward restores the authoritative
  default and rejects divergent/ambiguous mutation.
  - Verify: `tests/integration/test_vault_registry_rollback.py::test_mvr02_default_survives_scalar_projection_round_trip`
- [ ] The environment/vault-context and event owner contracts describe the shipped explicit default,
  one-time last-active migration, versioned default-mutation event, and compatibility/no-vault posture
  in the same PR.
  - Verify: doc writeback at `docs/ENVIRONMENTS.md :: Vault terminology` + doc writeback at
    `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Service Gating` + doc writeback at
    `docs/EVENTS.md :: Events`

## Out of Scope

- HTTP session storage, multi-binding contexts, dimensions, or default-vault UI.

## How to Verify (Pre-Merge)

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/instance/test_default_vault_resolution.py tests/api/test_default_vault_admin.py tests/integration/test_single_vault_compatibility.py tests/integration/test_vault_registry_container_durability.py tests/integration/test_vault_registry_rollback.py`
- `mypy app`
- `pytest -q -m "not pg"`
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
