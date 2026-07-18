---
name: Rebind On Vault Selection
description: Selecting or switching a vault durably rebinds the compatibility watcher after protected instance-state authority exists
task_id: SETTINGS-05
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F4
parent_capability: Settings Spine
prerequisites: [SETTINGS-01, SETTINGS-03, SETTINGS-04, MVR-01B, MVR-01C]
depends_on: [WIRE_SETTINGS_INGESTION.md, CANONICALIZE_SETTINGS_LOCATION.md, RECEIPT_EVERY_SETTINGS_WRITE.md, ../MULTI_VAULT_RUNTIME/ESTABLISH_INSTANCE_VAULT_REGISTRY.md]
can_parallelize_with: []
---

# Rebind On Vault Selection

## Purpose

Close audit finding F4 (SET-7): `WATCHER_VAULT_PATH` is read once at watcher boot and never
rebinds when a vault is selected through the Companion UI, so a capture can succeed while
remaining invisible to ingest (`docs/ENVIRONMENTS.md:94-108`). Vault-scoped settings consumers
must follow the committed compatibility selection, not a frozen environment snapshot.

**Owner ruling (2026-07-07) supersedes prior posture.** Issue #2476 ("document the split, do not
converge") and #3119's closing fix (PR #3126, visible-warning-only, not self-healing) deliberately
chose not to make the watcher follow live selection. SETTINGS-05 implements the opposite ruling:
the compatibility watcher follows the one committed compatibility binding.

This is future-state specification, not shipped truth. GitHub issue #3163 is the blocked SETTINGS-05
validation hub. It must not be claimed as one implementation issue.

## Authority boundary and prerequisites

SETTINGS-05 does **not** create, migrate, back up, export, or activate `/app/instance-state`.
Those substrate and registry responsibilities are owned by MVR-01:

- MVR-01B / #3854 owns the protected external volume, final legacy-writer fence, final export/import,
  cross-process path identity, backup/restore, and the dormant protected registry substrate.
- MVR-01C / #3855 owns guarded registry authority cutover, supported scalar rollback isolation, the
  registry minimum-runtime floor, and roll-forward lineage.
- SETTINGS-05 begins only after both are merged and reconciled on `origin/main`. It stores its
  compatibility rebind record in the already-authoritative protected store and may not reopen MVR's
  volume, migration, writer-fence, export, backup, or rollback decisions.
- SETTINGS-05A owns the schema-specific `minimum_settings_rebind_runtime=1` floor. It records that
  floor before the first `settings_rebind.v1` record becomes authoritative, migrates every producer,
  and adds host/process preflight so an older writer cannot read or rewrite the new record.

## What This Task Does

- Adds a versioned `settings_rebind.v1` compatibility record to the protected instance-state store.
  It carries schema revision, monotonic desired/applied revisions, phase, prior/candidate stable
  binding IDs, lifecycle posture, and recovery checksum. The record is initially dormant: it can be
  read, written, and recovered, but cannot change picker, watcher, or settings behavior.
- Adds a separately deployed watcher reconciler for the dormant record. It drains its captured old
  tick, enters durable handoff observation for A, scans before acknowledging prepare, and retains the
  A subscription plus durable event buffer through commit. After commit it performs the bracketing A
  scan, drains and receipts the buffer, then may apply B. The production picker/API remains sealed
  from initiating this path until the activation slice.
- Activates the production compatibility picker transaction only after the durable record and watcher
  reconciler are proven. The picker closes and drains compatibility-mutation ingress, prepares the
  revision, waits for watcher quiescence (or durable `no_lifecycle`), commits selection and binding,
  then resumes the watcher and invokes the SETTINGS-01 reload path exactly once. `VaultChangedEvent`
  remains an optional same-process wake-up hint, never cross-process delivery authority.
- Recovers pre-commit failure by cancelling and resuming A before ingress reopens. Post-commit recovery
  rolls forward while ingress remains blocked until the old-root scan/buffer drain and resume finish.
  No candidate-root effect occurs before commit; no accepted or direct-filesystem A write in the
  handoff window is stranded.
- Makes `ingest_binding` report binding, schema, phase, desired/applied revision, and failure posture
  truthfully. Display-only fields in `runtime/settings/instance.yaml` never decide a binding.

## Concretely

```text
# after SETTINGS-05C activation; watcher running, no vault selected -> idle
POST /api/companion/vault/select {"ref":"<registered-binding>"}
GET  /api/health -> watcher.ingest_binding.status == "bound"
# a new file under the committed binding is ingested without a container restart
```

## Why This Matters

Selection can be the compatibility source of truth only when the independently deployed watcher
follows it without losing old-root work or observing the candidate root prematurely.

## Bounded implementation issue decomposition

This specification maps to three serial, independently mergeable GitHub child issues under blocked
validation hub #3163. It must never be filed or claimed as one monolithic implementation issue.
Each extracted issue copies the shared Context, Source Anchors, SBS Impact, Constraints, Out of
Scope, and only its mapped acceptance criteria and validation commands.

1. **SETTINGS-05A — durable rebind record and recovery (dormant).** Add the versioned record,
   protected-store transaction, checksum/revision validation, schema-specific runtime floor,
   all-producer migration/preflight, producer fixtures, and restart recovery.
   Every production initiation point remains capability-sealed and the watcher behavior is unchanged.
   Depends on MVR-01B #3854 and MVR-01C #3855.
2. **SETTINGS-05B — watcher reconciler and quiescence (dormant from picker).** Add the production
   watcher loop's prepare acknowledgement, old-root observation, bracketing scans, buffer drain,
   failure recovery, and `no_lifecycle` reconciliation. The picker/API still cannot prepare or commit
   a rebind. Depends on SETTINGS-05A.
3. **SETTINGS-05C — picker/API activation and aggregate acceptance.** Atomically enable the production
   choose/open path, compatibility ingress gate, commit/resume, SETTINGS-01 reload, truthful health,
   integrated cross-process UAT, invariant registration, and owner-doc writeback. Depends on
   SETTINGS-05B and carries the #3163 validation/closure handoff.

No child may borrow a later activation criterion to bypass its dependency. A and B are safe partial
deliveries precisely because production initiation stays fail-closed until C.

## Acceptance Criteria

- [ ] **SETTINGS-05A:** API and watcher startup use the production protected-store resolver to read
      the same complete `settings_rebind.v1` revision; atomic write/restart preserves stable binding
      IDs, monotonic desired/applied revisions, phase, lifecycle posture, and checksum.
  - Verify: `tests/integration/test_settings_rebind_record.py::test_api_and_watcher_startup_share_one_dormant_rebind_revision`
- [ ] **SETTINGS-05A:** Interrupted record writes and every persisted phase recover through the
      production store/startup path to the last complete revision, never a guessed binding or partial
      record; invalid checksum/revision fails before watcher root resolution.
  - Verify: `tests/integration/test_settings_rebind_record.py::test_production_startup_recovers_every_dormant_record_phase_fail_closed`
- [ ] **SETTINGS-05A:** Init/bootstrap, migration, no-lifecycle setup, and runtime fixtures produce the
      same current schema, while production picker/API and direct initiation calls remain sealed and
      cannot change selection or watcher behavior before SETTINGS-05C.
  - Verify: `tests/architecture/test_settings_rebind_producers.py::test_all_producers_match_production_rebind_schema_and_activation_seal`
- [ ] **SETTINGS-05A:** The rollout records `minimum_settings_rebind_runtime=1` before the first
      authoritative v1 record; host-side and process startup guards reject incompatible API/watcher
      capability before protected-state access or root resolution.
  - Verify: `tests/ops/test_settings_rebind_runtime_floor.py::test_rebind_floor_blocks_incompatible_api_and_watcher_before_start`
- [ ] **SETTINGS-05A:** Every CLI, bootstrap/reconciliation, compiler/delta, fixture, and direct
      store/manager producer is migrated in the same slice and fails before protected-state mutation
      when it cannot preserve the v1 floor and revision.
  - Verify: `tests/ops/test_settings_rebind_runtime_floor.py::test_rebind_floor_blocks_every_legacy_writer_after_cutover`

- [ ] **SETTINGS-05B:** The separately deployed production watcher loop consumes a prepared dormant
      revision, finishes the captured A tick, retains durable A event observation through commit,
      acknowledges only after its pre-commit scan, and applies no candidate-root effect.
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_production_watcher_reconciler_quiesces_old_binding_without_picker_activation`
- [ ] **SETTINGS-05B:** The production watcher reconciler brackets commit with old-root scans, drains
      and receipts the A buffer before B, and fault injection at acknowledge/commit/drain/resume
      converges after restart without stranded A work or premature B work.
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_dormant_reconciler_failure_matrix_preserves_old_root_observation`
- [ ] **SETTINGS-05B:** An intentionally absent/disabled production watcher records and reconciles
      durable `no_lifecycle`; missing, invalid, and failed lifecycle states remain loud, while the
      production picker initiation path is still capability-sealed.
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_dormant_no_lifecycle_reconciles_without_unsealing_picker`

- [ ] **SETTINGS-05C:** Production choose/open closes and drains compatibility-mutation ingress,
      prepares the shared revision, waits for production watcher quiescence or `no_lifecycle`, commits
      selection plus binding atomically, then resumes; the API returns success only after commit.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_selection_rebinds_ingest`
- [ ] **SETTINGS-05C:** Mid-run switch admits no candidate-root effect before commit and no B effect
      before the bracketing A scan/buffer drain; in-flight A work completes and health reports the
      exact phase and desired/applied revisions.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_switch_is_clean_and_truthful`
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_prepare_drains_and_final_scans_old_binding_writes`
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_direct_filesystem_write_between_scan_and_commit_is_receipted_under_old_binding`
- [ ] **SETTINGS-05C:** Faults at prepare, acknowledgement, selection commit, old-root drain, and
      resume recover to A before commit or roll forward to B after commit, using the production API
      and separate production watcher process rather than a direct helper call.
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_prepare_commit_resume_is_failure_atomic`
- [ ] **SETTINGS-05C:** Each committed revision invokes the production SETTINGS-01 reload call site
      exactly once and atomically swaps the vault-scoped settings bundle.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_rebind_reloads_settings`
- [ ] **SETTINGS-05C:** No-vault, selected, removed, failed, and `no_lifecycle` transitions remain
      truthful through the production picker and health endpoints; lost wake-up events and independent
      API/watcher restarts converge from protected phase/revision truth.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_novault_transitions_truthful`
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_committed_revision_survives_event_loss_and_process_restart`
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_disabled_watcher_is_durable_no_lifecycle`
- [ ] **SETTINGS-05C:** SET-7 and owner docs describe the activated compatibility transaction and
      its MVR-06B handoff without claiming multi-active lifecycle support.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: vault_selection_rebinds_consumers`
    + doc writeback at `docs/ENVIRONMENTS.md :: Companion UI vault selection vs. watcher/worker ingest binding (#3119)`
    + doc writeback at `app/watcher/config.py` module docstring
- [ ] **SETTINGS-05C:** Aggregate integrated UAT proves a production API selection rebinds the separate
      watcher, ingests a post-commit file, reloads settings once, and leaves a durable revision/receipt;
      #3163 records child receipts and the closure verdict.
  - Verify: `tests/integration/test_watcher_cross_process_rebind.py::test_settings05_parent_acceptance`
    + runtime receipt on GitHub issue `#3163`

## How to Verify (Pre-Merge)

### SETTINGS-05A validation

- `pytest -q tests/integration/test_settings_rebind_record.py tests/architecture/test_settings_rebind_producers.py tests/ops/test_settings_rebind_runtime_floor.py`
- Verify the diff contains no activation of picker/API rebind initiation.

### SETTINGS-05B validation

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_watcher_cross_process_rebind.py -k "dormant or reconciler"`
- Verify the production picker/API remains capability-sealed.

### SETTINGS-05C validation

- `pytest -q tests/watcher/test_ingest_binding_follows_selection.py`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_watcher_cross_process_rebind.py`
- Verify the mapped owner-doc and invariant-registry writebacks.

Every child also runs its mapped no-vault regression selectors. The final activation child runs
`pytest -q -m "not pg"` and the integrated watcher/settings UAT; shared gates never substitute for
the exact production-call-site selectors above.

## Out of Scope

- Creating, migrating, exporting, backing up, restoring, or activating the protected
  `/app/instance-state` store; MVR-01B/01C own that authority.
- Establishing or changing MVR deployment, rollback, or registry minimum-runtime floors. SETTINGS-05A
  still owns its own `minimum_settings_rebind_runtime` floor and all-producer compatibility gate.
- Running more than one watcher or concurrently serving more than one active vault.
- Generic MVR request/session selection; only the legacy compatibility picker binding is changed.
- Removing `WATCHER_VAULT_PATH`; it remains a bootstrap adapter.
- Location migration (SETTINGS-03).

## Restart / Durability Posture

The applied watcher binding is in memory, while `settings_rebind.v1` is mechanical durable state in
MVR's protected instance-state store. SETTINGS-05A proves record recovery while dormant;
SETTINGS-05B proves watcher recovery without picker activation; SETTINGS-05C is the only slice that
allows production initiation. An uncommitted prepare returns to A, a committed revision rolls
forward to B, and `no_lifecycle` is explicit rather than inferred from a missing acknowledgement.

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F4`
- `docs/MULTI_VAULT_RUNTIME/README.md :: Persistence and package placement`
- `docs/MULTI_VAULT_RUNTIME/ESTABLISH_INSTANCE_VAULT_REGISTRY.md :: Bounded implementation issue decomposition`
- `docs/ENVIRONMENTS.md :: Companion UI vault selection vs. watcher/worker ingest binding (#3119)`

## Related GitHub Issues

Issue #3163 is the blocked validation hub. Extract three serial child issues from the stable
`Bounded implementation issue decomposition` anchor after this specification repair merges. Keep
05A blocked on #3854/#3855; keep 05B blocked on 05A and 05C blocked on 05B. Use Sol/xhigh for
architecture/concurrency review; downstream `issue-to-code` re-derives live capability per TCD.
