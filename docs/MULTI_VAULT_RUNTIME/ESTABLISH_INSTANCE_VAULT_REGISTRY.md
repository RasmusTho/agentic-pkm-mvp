---
name: Establish Instance Vault Registry
description: Promote known vaults into a versioned instance-local registry and relocate the package boundary
task_id: MVR-01
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Persistence and package placement"
parent_capability: Multi-vault runtime selection
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Establish Instance Vault Registry

## Purpose

`app/vault/app_local.py` already persists `known_vaults` and `last_active_vault_ref`, but the
state is packaged as a vault detail and has no schema migration or first-class registry boundary.
This slice promotes the existing seed without changing content-vault authority.

## What This Task Does

- Introduce `app/instance/vault_registry.py` with versioned mechanical-durable registry models and
  store operations for add/update/remove/list/lookup.
- Relocate `KnownVaultRef`, `AppLocalSettings`, and their store behind the new package; keep
  `app/vault/app_local.py` as a deprecated compatibility re-export.
- Preserve logical `vault_id`, local-clone `local_instance_id`, and stable registration
  `vault_binding_id` separately from path and device provenance.
- Migrate the existing Markdown payload in place, preserving the installed-instance
  `appInstallId`, every registration, `last_active_vault_ref`, timestamps, and unknown
  forward-compatible fields.
- For container deployments, add a channel/instance-scoped `instance-state` volume mounted at
  `/app/instance-state` in every registry consumer and resolve the production store to
  `/app/instance-state/agentic-pkm/vault-registry.md`. Migrate once from the legacy resolved
  app-local path by atomic validated copy with provenance; never treat the image layer, `$HOME`,
  `/app/tmp`, or `/app/runtime` as durable registry storage.
- Create and maintain the authoritative registry, lock metadata, transaction temporary files,
  validated snapshots, and rollback exports as owner-only mode `0600` (directories `0700`) on
  native hosts and shared volumes. Preflight rejects permissive or unfixable ownership/mode before
  exposing absolute content-root paths or device provenance.
- Add the pre-recreate migration gate: while the old API is still running, resolve the legacy source
  and record its schema/fingerprint, then acquire the channel deployment fence, reject new picker,
  initialize, and headless-CLI registry mutations, drain in-flight mutations, and stop every old
  registry writer. Export the final file from the stopped container/durable source into mode-`0600`
  channel staging, validate its schema and final fingerprint, and recheck that the source has not
  changed before import. The new-image one-shot migrator may mount/import the durable volume only
  while that fence proves no legacy writer can restart. Any writer that cannot be fenced, a changed
  post-stop fingerprint, or an unprovable final source blocks the upgrade; a pre-quiescence snapshot
  is never authoritative. No old container is safe only with proof of a durable legacy source or
  proof that no legacy registry existed.
- Implement the channel deployment fence outside the old image (deployment lock plus ingress and
  container-lifecycle control), so the first upgrade does not assume unsupported fence behavior in
  that image. From MVR-01 onward, production registry API/CLI producers also honor the same durable
  fence before mutation; this makes later upgrades cooperatively drainable without weakening the
  first-upgrade stop-and-final-export rule.
- Keep rollback readable from this first migration onward: every committed registry revision also
  refreshes a versioned, mode-`0600` rollback export under the same lock, and the rollback preflight
  validates and transforms that export into the exact legacy `AppLocalSettingsStore` path before an
  old image starts. A rollback must therefore see the latest committed registrations and
  last-active state, not merely the pre-migration snapshot. This compatibility exporter/transformer
  remains required until MVR-07 proves that no supported rollback reader needs it.
- Treat rollback into a scalar previous image as an explicit authority boundary for the registry
  state MVR-01 introduces. If current state has multiple registrations, rollback preflight requires one operator-supplied
  `rollback_vault_binding_id`; it validates that exact registration and materializes a constrained
  legacy payload/bootstrap whose sole selectable and startup target is that binding. Missing,
  stale, unauthorized, or ambiguous target blocks the old image. The complete new-schema registry,
  snapshots, unknown forward-compatible fields, and lineage remain immutable beside the projection
  for later roll-forward. Each later slice owns rollback/floor handling for the state it introduces;
  MVR-01 does not interpret future default, dimension, or background-intent schemas.
- Enforce that target in deployment, not only in the legacy payload: the rollback compose overlay
  removes the old API's direct published port, exposes it only through an authenticated gateway
  that denies picker select/initialize mutations, and mounts only the chosen content root at the
  canonical legacy path. Startup preflight proves the direct port is absent, the gateway policy is
  active, and no broader host vault roots are mounted. A failed guard blocks rollback startup.
- Treat later `minimum_runtime_schema` as a hard rollback floor. Once MVR-05 records that binding-
  keyed database producers may exist, scalar rollback is forbidden even when the registry currently
  names one binding: the old API/worker cannot safely query, dispatch, or acknowledge that shared
  database state. Preserve the full registry/database lineage for a compatible roll-forward or a
  rollback image at/above the recorded floor; do not synthesize a scalar database projection.
- Before rolling forward again from the previous image, export and validate its latest legacy
  payload while it is still running, compare its recorded fork/base revision with the durable
  registry lineage, and transform rollback-period mutations into the next locked monotonic registry
  revision. If both sides changed from the recorded fork, identity mapping is ambiguous, or the
  legacy export is missing/invalid, fail before recreate and preserve both copies for recovery.
- Serialize every mutation with a shared-volume file lock, monotonic revision/CAS reload, and
  same-directory temp-file + `fsync` + atomic replace + directory `fsync`. Readers observe complete
  revisions; all production writers reuse this store transaction boundary.
- Preserve #2185 without erasing later state: parse corruption encountered by explicit picker
  select/initialize is backed up for forensics. The legacy backup/reseed behavior is allowed only
  when the source is provably pre-MVR/empty and no validated populated snapshot exists. A populated
  current-schema registry is restored from its checksum-verified last-good snapshot and then the
  requested mutation is applied under the normal transaction; if no unambiguous snapshot exists,
  picker mutation fails closed with an explicit recovery path. No empty reset is committed, and the
  rollback export is refreshed only after a validated non-destructive commit. Ambiguous schema
  migrations, identity collisions, and write failures likewise preserve every source.

## Concretely

An existing instance with two `known_vaults` restarts after upgrade and exposes the same two
stable IDs from `app.instance.vault_registry`; moving one content root updates its path without
creating a new identity. A parse-corrupt provably pre-MVR/empty payload selected through the picker
is backed up and reseeded; a populated current-schema payload restores its verified snapshot or
fails closed, and an ambiguous migration reports the file/error and remains untouched.

## Why This Matters

Request/session selection cannot be trustworthy if its binding catalogue is hidden behind a
single-vault package or can silently lose identity during migration.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Persistence and package placement`
- `app/vault/app_local.py :: KnownVaultRef / AppLocalSettings / AppLocalSettingsStore`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md :: identity separation`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): SFC, PDM, EBF
- Write class: mechanical durable instance-local state
- Authority impact: none; registration does not grant content access
- Persistence impact: versioned Markdown schema plus one-time migration into a shared durable
  instance-state volume for containers; native app-data paths remain supported
- Derived/rebuildable impact: any DB/cache projection is rebuildable and non-authoritative
- Human knowledge impact: none; registry state never moves into content vaults
- Memory impact: none
- Retrieval/context impact: supplies typed source bindings for later ActiveContextSet resolution
- Sync/deployment impact: compose/Dockerfile/startup producers mount and preflight one isolated
  instance-state volume shared by API/worker/watcher consumers before force-recreate
- External boundary impact: paths remain EBF binding metadata, not vault identity
- New or changed contract: first-class instance vault registry schema and package boundary
- Owner-doc impact: will-update-in-PR at `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`
- Transition debt impact: reduces global/app-local registry ambiguity; opens no compatibility debt beyond the explicit re-export
- Fitness rule impact: strengthens identity/path and instance/vault separation plus serialized
  cross-process mechanical-state mutation

## Constraints

- Do not store the only registry inside a content vault or authority-bearing database row.
- Two local clones may share one logical `vault_id`; they remain distinct registrations through
  `local_instance_id`/`vault_binding_id`. Path changes alter neither identity.
- Update every producer/fixture of the persisted schema and add a fail-loud preflight in the same PR.

## Acceptance Criteria

- [ ] The production store loads, writes, and restarts with multiple registrations while preserving
  stable vault identity and instance provenance.
  - Verify: `tests/instance/test_vault_registry.py::test_registry_round_trip_preserves_multiple_vaults`
- [ ] A legacy app-local payload migrates in place without changing `appInstallId` or losing
  registrations, `last_active_vault_ref`, timestamps, or unknown fields.
  - Verify: `tests/instance/test_vault_registry_migration.py::test_legacy_app_local_state_migrates_losslessly`
- [ ] Explicit production picker select/initialize over parse-corrupt registry state backs up the
  original and preserves #2185 legacy/empty recovery without a 500.
  - Verify: `tests/api/test_vault_registry_recovery.py::test_picker_recovers_parse_corrupt_registry_with_backup`
- [ ] Parse corruption in a populated current registry restores the checksum-verified last-good
  state before mutation, preserving all registrations/default/dimensions/background intent; when
  no unambiguous snapshot exists it fails closed without committing an empty reset or refreshing
  the rollback export.
  - Verify: `tests/api/test_vault_registry_recovery.py::test_populated_registry_corruption_never_reseeds_empty`
- [ ] Ambiguous migration, identity collision, or write failure fails closed and leaves the
  original payload recoverable.
  - Verify: `tests/instance/test_vault_registry_migration.py::test_ambiguous_registry_migration_fails_without_destructive_reset`
- [ ] Production imports use `app.instance.vault_registry`; the old path is only a tested
  compatibility re-export.
  - Verify: `tests/architecture/test_instance_vault_registry_boundary.py::test_production_registry_imports_use_instance_package`
- [ ] Store initialization, migration, fixtures, and preflight all produce the current schema.
  - Verify: `tests/architecture/test_instance_vault_registry_boundary.py::test_registry_schema_producers_match_runtime_precondition`
- [ ] An old-image-to-new-image pinned force-recreate exports before stop and preserves all MVR-01
  registry state on a per-channel durable volume; API, worker, watcher, and Heimdal resolve and read
  the identical revision after restart.
  - Verify: `tests/integration/test_vault_registry_container_durability.py::test_registry_survives_recreate_and_is_shared_cross_process`
- [ ] The first-volume upgrade fences and drains every legacy registry writer, stops the old API,
  exports and validates the final post-stop fingerprint, and prevents old-writer restart through
  import; an injected mutation or unfenced writer aborts without importing the stale snapshot.
  - Verify: `tests/ops/test_instance_state_volume_contract.py::test_legacy_registry_export_happens_after_writer_quiescence`
- [ ] Compose, startup, and migration preflight fail before recreate when the instance-state mount
  is absent, not writable, channel-colliding, or resolves differently between consumers.
  - Verify: `tests/ops/test_instance_state_volume_contract.py::test_registry_volume_and_preflight_cover_all_consumers`
- [ ] Registry, lock/temporary files, validated snapshots, and rollback exports remain mode `0600`
  under permissive host umasks; parent directories are `0700` and unsafe mode/ownership fails loud.
  - Verify: `tests/instance/test_vault_registry_permissions.py::test_registry_transaction_files_are_private`
- [ ] Concurrent picker/API/CLI registry mutations serialize without lost updates or partial files,
  and stale revision CAS fails explicitly before retry.
  - Verify: `tests/instance/test_vault_registry_concurrency.py::test_production_mutations_are_locked_atomic_and_revision_checked`
- [ ] After a post-migration registry mutation, the supported previous image can be started through
  the rollback preflight and reads the latest committed registration and last-active state from its
  legacy path; a missing, stale, or invalid rollback export blocks startup.
  - Verify: `tests/integration/test_vault_registry_rollback.py::test_previous_image_reads_latest_post_migration_registry_state`
- [ ] Rolling an MVR-01 multi-registration instance into a scalar previous image requires one
  validated explicit rollback binding, constrains legacy startup/selection to that binding, and
  otherwise blocks while preserving the complete MVR-01 registry, unknown fields, and lineage.
  - Verify: `tests/integration/test_vault_registry_rollback.py::test_multi_binding_rollback_requires_one_safe_explicit_target`
- [ ] The scalar rollback deployment exposes the old API only through the authenticated mutation-
  filtering gateway, publishes no bypass port, and mounts no content root except the validated
  target; production picker select/initialize calls for another path are rejected.
  - Verify: `tests/ops/test_scalar_rollback_guard.py::test_rollback_gateway_and_mounts_enforce_selected_binding`
- [ ] A recorded MVR-05-or-later minimum-runtime floor blocks scalar API/worker startup before any
  database connection or queue acknowledgement, preserving the full lineage for a compatible
  rollback/roll-forward.
  - Verify: `tests/ops/test_scalar_rollback_guard.py::test_binding_keyed_database_floor_blocks_scalar_runtime`
- [ ] Registrations and last-active changes made by the previous image during rollback are imported
  as the next registry revision on roll-forward; divergent mutation, ambiguous identity, or invalid
  lineage fails before recreate without overwriting either side.
  - Verify: `tests/integration/test_vault_registry_rollback.py::test_rollback_mutations_round_trip_on_roll_forward`
- [ ] The parent registry acceptance target composes the delivered registry, migration, durability,
  concurrency, recovery, and rollback contracts and passes before MVR-01 merges.
  - Verify: `tests/instance/test_vault_registry_migration.py::test_parent_registry_acceptance`

## Out of Scope

- Default selection, session/request context, dimensions, UI, authorization, or content migration.

## How to Verify (Pre-Merge)

- `pytest -q tests/instance/test_vault_registry.py tests/instance/test_vault_registry_migration.py tests/instance/test_vault_registry_concurrency.py tests/instance/test_vault_registry_permissions.py tests/api/test_vault_registry_recovery.py tests/architecture/test_instance_vault_registry_boundary.py tests/ops/test_instance_state_volume_contract.py tests/ops/test_scalar_rollback_guard.py`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_vault_registry_container_durability.py tests/integration/test_vault_registry_rollback.py`
- `ruff check app tests`

## Restart / Durability Posture

Registry entries and last-active history survive restart and force-recreate in the versioned
instance-local Markdown store. Container consumers share the per-channel `instance-state` volume;
native installs use their app-data directory. The old-container export happens before destructive
recreate, and mode-`0600` staging remains until the new revision is verified across all four
consumers; an independently durable legacy source is also retained when one exists. Mutations are
locked, revision-checked, and atomically replaced, and each commit refreshes the validated rollback
export consumed by the old-image pre-start transformer. A later roll-forward re-exports the running
old image and reconciles its rollback-period changes against the recorded fork revision before the
new image starts; divergent lineages fail closed with both sources intact. A scalar old image starts
only from a validated explicit rollback target when newer state is not scalar-representable, while
the complete new-schema lineage stays immutable for roll-forward. Parse
corruption remains recoverable through legacy/empty backup-reseed or populated last-good-snapshot
restore; it never commits an empty replacement for populated state. An ambiguous recovery,
migration, or write failure leaves prior payload, snapshot, staging, rollback export, and
destination recoverable and blocks only unsafe automatic resolution until repaired.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`

## Related GitHub Issues

Create one implementation issue under #2143. It must cite MVR-01, carry the complete Issue
contract/SBS block above, and use Sol/high because persistence migration and identity loss have a
high defect cost. Preserve #2185 picker recovery and apply `AGENTS.md :: Invariant → producers
rule` after #1991/#1997.
