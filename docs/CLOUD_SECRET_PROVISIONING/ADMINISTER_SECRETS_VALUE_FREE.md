---
name: Administer Secrets Value-Free
description: Add consumer-scoped checks, safe stdin imports, and policy-bounded secret writes.
task_id: BWS-02
github_issue: 5678
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraints
parent_capability: CLOUD_SECRET_PROVISIONING
prerequisites: [BWS-01]
depends_on: [RESOLVE_BWS_CHANNEL_SECRETS.md]
can_parallelize_with: []
---

# Administer Secrets Value-Free

## Purpose

Agents need a bounded command surface for checking exactly the selected consumers and writing BWS values without printing or placing them in argv. This task imports externally issued and already-active values through standard input, preserves prior values, and permits generation or rotation only for identities explicitly allowlisted as BWS-owned.

## What This Task Does

Add `secrets check <channel> --consumer <consumer>`, `secrets import <channel> <secret> --stdin`, and policy-bounded `secrets generate` / `secrets rotate` operations. A check validates only the selected consumer's declared bindings. An absent optional binding may be skipped, but every present selected value must pass its grammar, including optional values. Inactive consumers are not checked, so their unprovisioned credentials do not block unrelated deployment. It reports logical identifiers and status only. When an admin check selects a shared identity, it checks both project copies without returning either value. A project-scoped VM reader checks only its selected project's values and never reaches the peer project.

Import reads one value from stdin and updates only BWS; issuer-side credential creation/rotation remains external. Before any active update, append prior-value snapshots for present project copies and value-free `previous_state=absent` tombstones for absent copies. For paired imports, persist both project pre-states and a non-secret operation ID/prepared event before either BWS write. Include that operation ID in a machine-readable, non-secret item-note marker in the same request as each value update, preserving owner note text. The chosen protected local append-only history backend is implementation-defined, but an append counts as durable only after a flush/fsync-equivalent commit returns. A provider success response or matching operation marker is evidence that a target write committed. A typed rejection known to precede commit proves no target change. A lost acknowledgment or process interruption after a request was sent is indeterminate: readback without the marker does not prove that the request cannot still commit. In that state, do not compensate, retry, start a fresh import, check selected BWS values, or deploy; keep the journal pending. Resume only after every sent request has an authoritative terminal outcome. When all effects are known, compensate confirmed changed copies to their recorded pre-state (restoring a snapshot or deleting a formerly absent copy) under the same exclusive lock, or reconcile with a fresh stdin import and retain history.

Admin writes use an authenticated request-body interface. The BWS CLI create/edit forms are not used to send values because they place values in command arguments; default CLI responses are not forwarded. The admin credential is resolved from the agent host Keychain and is never installed on a VM. Protected production data-encryption secrets remain refused until the owner decision is recorded in #5667 and a separate approved task defines their exact lifecycle.

BWS-01 supplies the shared stable, owner-only agent-host operation lock and value-free pending-operation journal. Every supported secrets check/import/generate/rotate, token push, and deployment dispatch acquires that same exclusive lock. The lock is outside Git and iCloud and coordinates cooperating entrypoints on this host only; it cannot fence another host, direct BWS client, or an already-sent provider request. The parent owner/live-qualification gate must approve one designated BWS admin writer and prove its credential is restricted to that controller, or require shared fencing before deploy admission. BWS-02 holds the host lock from before reading either shared copy through durable pre-state history, writes, terminal provider outcomes, compensation, and terminal journal receipt. The deploy controller holds it from before preflight through VM recheck, secret materialization, and matching durable remote Compose receipt. Lock order is agent-host operation lock, then VM per-channel lock; BWS-02 never acquires a VM lock. Direct VM deploy/secret-resolution bypass and an unqualified second controller are unsupported.

If a process or provider connection stops with an unmatched prepared operation, the OS lock may be released but the durable operation journal remains pending. New checks, writes, and deploys fail closed until the operation-specific recovery below reaches a terminal state. A shared import may be reconciled with a fresh explicit `secrets import --stdin` only after every earlier sent provider request is known terminal; it then reads current project states, records their snapshots/tombstones, applies the newly supplied common value to both, verifies parity, and appends a terminal resolution linked to the old operation. Do not replay compensation or issue recovery writes while an earlier request could still land. A missing operation marker is not proof of non-commit. Token push reconciles its operation ID against the current encrypted-generation pointer and durable remote token-operation receipt; it commits only after a matching terminal receipt, retries with the same ID only after a matching terminal-aborted receipt, or remains indeterminate. First-init bootstrap rechecks the data directory under the VM lock and reads the channel-scoped BWS item. Its create request carries the non-secret operation ID in item metadata so readback can identify a committed request. If exactly one item matches, BWS-04 reads and verifies that stored value before deploy proceeds. If a create may have reached BWS but readback is absent or ambiguous, do not send another create; keep the operation pending until an authoritative terminal outcome is established. Bootstrap recovery is permitted only while the directory remains empty and the exclusive controller remains the only supported writer. Deploy recovers only from its durable value-free remote receipt with the same operation ID; a lock snapshot alone is insufficient. If required readback or durable history fails, leave the operation pending and make no new write.

## Concretely

A check for a declared consumer emits selected logical names and statuses only. It takes the same agent-host operation lock so the shared pair is observed consistently. Among cooperating calls on this host, the lock prevents a permitted admin writer from interleaving with a deployment's host parity check, VM project-scoped recheck, selected-value materialization, or Compose activation; it does not establish exclusivity against another host. The owner qualification gate or shared-fencing requirement in the parent capability spec is required before shared parity is treated as deployment-safe. A VM reader's project-only view is not treated as proof of cross-project parity. Import's durable prepared/terminal records make process interruption visible: an unmatched operation blocks check/deploy; a fresh stdin import can reconcile current state only after every earlier provider send has an authoritative terminal outcome, never by replaying stale compensation.

## Why This Matters

A value-free tool can still leak credentials through process listings, exception strings, provider JSON, shell tracing, or partial rotation. Safe ordering and tests for all those paths are required before agents can administer secrets.

## Acceptance Criteria

- [ ] Check evaluates the selected consumer's required set, permits absent optional/inactive credentials, rejects any present malformed selected value even when optional, and emits no canary value.
  - Verify: `tests/ops/test_secret_admin.py::test_check_scopes_required_set_to_selected_consumers`
  - Verify: `tests/ops/test_secret_admin.py::test_inactive_optional_provider_credentials_do_not_block_check`
  - Verify: `tests/ops/test_secret_admin.py::test_malformed_optional_provider_credential_blocks_check`
- [ ] Externally issued credentials are imported through stdin only; generation and rotation reject external, protected, and initialized-database identities unless a closed policy explicitly permits them.
  - Verify: `tests/ops/test_secret_admin.py::test_external_identity_imports_from_stdin_without_value_disclosure`
  - Verify: `tests/ops/test_secret_admin.py::test_generation_and_rotation_reject_external_and_protected_identities`
  - Verify: `tests/ops/test_secret_admin.py::test_initialized_postgres_password_cannot_be_rotated`
- [ ] Ordinary rotation persists prior value(s) to immutable history before updating active value(s); history failure leaves active item(s) unchanged.
  - Verify: `tests/ops/test_secret_admin.py::test_rotation_archives_prior_value_before_update`
  - Verify: `tests/ops/test_secret_admin.py::test_rotation_history_failure_does_not_change_active_value`
- [ ] Shared-secret admin check compares only selected shared identities across prod/non-prod, and stdin import archives prior copies and applies one value to both without disclosure.
  - Verify: `tests/ops/test_secret_admin.py::test_admin_shared_check_detects_missing_and_divergent_copies`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_updates_both_project_copies_without_output`
- [ ] First provisioning and missing-copy recovery append a value-free `previous_state=absent` tombstone for each absent target project/logical identity before any shared-copy write; existing copies are snapshotted, and every required history event is durable before either write.
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_history_records_genesis_tombstone_before_first_provision`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_missing_copy_tombstone_precedes_both_writes`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_history_failure_leaves_both_copies_unchanged`
- [ ] A partial shared-copy update restores each changed copy to its recorded pre-state, including deleting a newly created copy that was previously absent, only after every sent provider request has a known terminal outcome; if any outcome is unknown, no compensation or retry is sent and the value-free pending operation blocks checks/deploy until authoritative terminal evidence exists.
  - Verify: `tests/ops/test_secret_admin.py::test_shared_secret_partial_update_is_compensated_or_reported_divergent`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_partial_failure_restores_absent_copy_or_reports_divergent`
- [ ] The agent-host operation lock serializes checks/imports with deploy preflight through Compose activation; a shared import interrupted after known terminal provider calls may be reconciled with a fresh authorized stdin import, while an in-flight/lost-ack write remains pending with no compensation or recovery write until provider terminality is authoritative.
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_cannot_interleave_with_deploy_check_to_compose`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_interruption_blocks_until_reimport_reconciles`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_unknown_write_outcome_stays_pending_and_blocks_recovery`
  - Verify: `tests/ops/test_secret_admin.py::test_delayed_shared_write_cannot_land_after_recovery_import`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_waits_for_in_progress_shared_import_and_rechecks_parity`
- [ ] Protected production raw-store-key and archive-pass writes remain refused while the owner decision is unresolved, and initialized PostgreSQL credentials cannot be rotated by BWS alone.
  - Verify: `tests/ops/test_secret_admin.py::test_unresolved_protected_rotation_is_refused_without_value_disclosure`
  - Verify: `tests/ops/test_secret_admin.py::test_initialized_postgres_password_cannot_be_rotated`
- [ ] Admin write calls keep secret values out of argv, stdout, stderr, and receipts.
  - Verify: `tests/ops/test_secret_admin.py::test_admin_write_value_never_enters_argv_or_output`

## How to Verify (Pre-Merge)

Run the named tests in tests/ops/test_secret_admin.py with fake BWS adapters and an isolated durable-history backend. Assert canary values are absent from argv, output, errors, and logs. Inject failure at each history append, provider write, readback, compensation, and terminal-record append. Simulate known interruption after prepare and after a completed first-project response; prove a fresh stdin import reconciles under the lock only when prior sends are terminal. Separately delay a sent provider write while dropping its acknowledgment; prove the controller sends no compensation or later recovery write, and checks/deploy remain blocked until authoritative terminal evidence matches the operation ID. Model a provider terminal response that guarantees the delayed request can no longer land; prove recovery starts only after that evidence and that no late write follows the recovery import's terminal receipt. Interleave a deploy at host parity check, between host and VM reads, and before Compose; prove the local lock blocks cooperating imports until activation completes. Verify the VM reader has no admin credential or peer-project access.

## Out of Scope

- BWS account setup or admin token creation.
- Changes to the production raw-store-key or archive-pass lifecycle while the owner decision is unresolved.
- PostgreSQL role password changes for initialized databases; a coordinated database credential cutover requires a separate task.
- VM token delivery, Compose wiring, live provider calls, or host operations.

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/LOCAL_SECRET_PROVISIONING/README.md
- docs/SECURITY.md
- app/ops/host_secret_contract.py
- app/ops/host_secret_bootstrap.py

## Related GitHub Issues

GitHub issue: #5678 (filed blocked while the specification PR is open).
