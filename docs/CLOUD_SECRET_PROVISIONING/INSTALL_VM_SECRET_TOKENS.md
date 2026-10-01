---
name: Install VM Secret Tokens
description: Encrypt channel reader machine-account tokens with systemd-creds for Linux VMs.
task_id: BWS-03
github_issue: 5679
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraints
parent_capability: CLOUD_SECRET_PROVISIONING
prerequisites: [BWS-01]
depends_on: [RESOLVE_BWS_CHANNEL_SECRETS.md]
can_parallelize_with: []
---

# Install VM Secret Tokens

## Purpose

Linux VMs need a read-only BWS machine-account token to resolve their channel project. This task defines the repository command that encrypts the selected token for a named VM without exposing it in argv, output, or durable plaintext, and supplies the committed systemd credential binding consumed by BWS-01.

## What This Task Does

Add `secrets push-token <vm>` for the bounded ygg-dev, ygg-test, and ygg-prod target map. Resolve the VM's reader token from the approved agent-host Keychain item, select non-prod for dev/test and prod for prod, and send it over standard input to target-host `systemd-creds` encryption under credential name `bws-machine-account-token`. Store each encrypted candidate as an immutable generation and atomically switch one stable current-source pointer that the committed systemd unit consumes with `LoadCredentialEncrypted=bws-machine-account-token:<encrypted-current-source>`. The pointer identifies its generation with a non-secret operation ID; BWS-01 receives only `BWS_ACCESS_TOKEN_FILE=%d/bws-machine-account-token`, which resolves at runtime to `$CREDENTIALS_DIRECTORY/bws-machine-account-token`. A missing/unreadable loaded file fails before provider access. No token bytes enter argv/output/logs/receipts/environment/app containers or a durable plaintext file.

Before resolving or sending a token, push-token acquires the BWS-01 agent-host operation lock exclusively and creates its value-free pending operation record. The local lock coordinates cooperating entrypoints on that host only; it does not fence another host or a direct BWS writer. The remote operation also holds the VM per-channel mutation lock and writes a durable value-free journal in an owner-only persistent state directory outside the repository and tmpfs, with the same operation ID, target channel, stage, and terminal result. Every stage update is atomic and durable (write temporary file, flush/fsync it, rename, then flush/fsync its parent directory). The remote stages are `prepared`, `applying`, and terminal `committed` or `aborted`. Persist `applying` before changing the current-source pointer; after atomic pointer replacement and readback, persist `committed`, whose durable same-ID record is the terminal receipt. Persist `aborted` only after confirming the pointer is unchanged or rollback completed; its durable record is the terminal receipt. Hold the VM lock until a terminal receipt is durable. The host closes its pending operation only on a matching same-ID terminal receipt, not on pointer observation or VM lock state alone. After SSH loss, a new remote command must acquire the VM lock, inspect and reconcile the journal; an `applying` or unreadable/mismatched receipt remains pending. An indeterminate result keeps later deploy/token operations blocked until terminal reconciliation.

The operation reports only target identity, project class, and success or failure. It does not create machine accounts, change BWS permissions, modify a live unit, or prove that a VM was live-qualified.

## Concretely

A ygg-test request selects non-prod-reader and the non-prod project. A ygg-prod request selects prod-reader and prod. Unknown VM names or mismatched account/project mappings fail before remote mutation. Before starting a push, write a durable value-free operation ID and prior generation ID to the agent-host operation journal. Encryption/transfer failure before the remote `applying` stage leaves the prior encrypted generation current. After SSH loss, pointer contents alone do not establish terminality: if the remote journal is `applying`, absent, mismatched, or unreadable, do not retry or close the host operation. Reconcile only after the prior remote process is known terminal under the VM lock and a durable same-ID receipt proves `committed` or `aborted`. A `committed` receipt must match the current generation pointer; an `aborted` receipt must prove the prior pointer remains current (or that rollback completed). Only after a matching `aborted` receipt may the same pending operation ID be retried. A new service activation reads the current generation; an already-running process keeps its loaded credential until normal restart. Do not modify a live unit or claim live qualification.

## Why This Matters

A shared non-prod token must never be installed as the prod reader. A failed push must not leave an empty, partially written, or plaintext credential that a systemd service can consume.

## Acceptance Criteria

- [ ] Token push uses the BWS-01 agent-host operation lock and VM per-channel lock and remains serialized with deploy and secret administration through a durable matching remote terminal receipt.
  - Verify: `tests/deploy/test_secret_token_push.py::test_token_push_serializes_with_deploy_operation_lock`
- [ ] The bounded VM map selects exactly the correct read-only machine account and project class.
  - Verify: `tests/deploy/test_secret_token_push.py::test_vm_mapping_selects_channel_reader_and_project`
- [ ] Token encryption consumes standard input and the token never enters process argv, stdout, stderr, or receipts.
  - Verify: `tests/deploy/test_secret_token_push.py::test_push_token_encrypts_stdin_and_redacts_token`
- [ ] Failures proven to occur before remote `applying` preserve the prior encrypted credential. The VM stores an owner-only durable value-free journal with `operation_id`, channel, kind, stage, and terminal result; stage writes are atomic and durable. After possible pointer mutation, a lost acknowledgment stays pending while stage is `applying`, absent, mismatched, or unreadable. Pointer identity alone cannot close or retry the operation: a matching durable `committed` receipt must agree with the current pointer, or a matching durable `aborted` receipt must prove the prior pointer remains current/rollback completed. Retries reuse the pending operation ID only after that terminal-aborted receipt.
  - Verify: `tests/deploy/test_secret_token_push.py::test_failed_push_preserves_prior_encrypted_credential`
  - Verify: `tests/deploy/test_secret_token_push.py::test_token_push_lost_ack_is_reconciled_by_generation_id`
  - Verify: `tests/deploy/test_secret_token_push.py::test_token_push_retry_reuses_pending_operation_id`
  - Verify: `tests/deploy/test_secret_token_push.py::test_token_push_unknown_remote_stage_blocks_retry_until_terminal_receipt`
- [ ] Unknown VM names and account/project mismatches fail closed before remote mutation.
  - Verify: `tests/deploy/test_secret_token_push.py::test_invalid_vm_mapping_fails_before_remote_mutation`
- [ ] The committed systemd reader unit/drop-in binds the encrypted credential under the exact BWS-01 file interface, and push-token installs the matching encrypted source; a missing or unreadable loaded credential fails before a provider request or deploy mutation.
  - Verify: `tests/deploy/test_secret_token_push.py::test_repository_managed_reader_unit_binds_encrypted_credential`
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_bws_access_token_file_fails_before_provider_request`

## How to Verify (Pre-Merge)

Run the named tests in tests/deploy/test_secret_token_push.py and tests/ops/test_host_secret_bootstrap.py with fake Keychain, systemd-creds, remote transport, and provider adapters. Inject connection loss before and after pointer mutation. Prove pre-apply failure leaves the prior generation current; after possible apply, `applying` and unknown remote state block retry. Reconcile only after acquiring the VM lock and observing a durable matching terminal receipt; verify committed receipt/pointer agreement and aborted receipt/prior-pointer agreement. Assert the systemd unit consumes the stable encrypted source and the canary token is absent from argv and output. Do not connect to or mutate a live VM.

## Out of Scope

- Provisioning or changing a live VM.
- Creating BWS machine accounts or changing their permissions.
- Updating a running systemd unit on a live host.
- Any live qualification receipt.

## External References

- [systemd Credentials](https://systemd.io/CREDENTIALS/) (encrypted credential loading, `%d`, and `$CREDENTIALS_DIRECTORY`)

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/LOCAL_SECRET_PROVISIONING/README.md
- docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md
- scripts/deploy_channel.sh

## Related GitHub Issues

GitHub issue: #5679 (filed blocked while the specification PR is open).
