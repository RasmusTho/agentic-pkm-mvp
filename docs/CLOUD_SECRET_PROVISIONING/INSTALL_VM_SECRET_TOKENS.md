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

Linux VMs need a read-only BWS machine-account token to resolve their channel project. This task defines the repository command that encrypts the selected token for a named VM without exposing it in argv, output, or durable plaintext.

## What This Task Does

Add secrets push-token <vm> for the bounded ygg-dev, ygg-test, and ygg-prod target map. Resolve the VM's reader token from the approved agent-host Keychain item, select non-prod for dev/test and prod for prod, and send the token over standard input to systemd-creds encryption on the target host. Store the resulting encrypted credential atomically with the expected owner and mode. The target service obtains the token through systemd credential loading; repository code never writes a plaintext token to a persistent path.

The operation reports only target identity, project class, and success or failure. It does not create machine accounts, change BWS permissions, or prove the VM was live-qualified.

## Concretely

A ygg-test request selects non-prod-reader and the non-prod project. A ygg-prod request selects prod-reader and prod. Unknown VM names, mismatched project/account mappings, SSH failure, encryption failure, or atomic-install failure stop without replacing the prior credential or emitting token content.

## Why This Matters

A shared non-prod token must never be installed as the prod reader. A failed push must not leave an empty, partially written, or plaintext credential that a systemd service can consume.

## Acceptance Criteria

- [ ] The bounded VM map selects exactly the correct read-only machine account and project class.
  - Verify: `tests/deploy/test_secret_token_push.py::test_vm_mapping_selects_channel_reader_and_project`
- [ ] Token encryption consumes standard input and the token never enters process argv, stdout, stderr, or receipts.
  - Verify: `tests/deploy/test_secret_token_push.py::test_push_token_encrypts_stdin_and_redacts_token`
- [ ] Encryption, transfer, or atomic-install failure preserves the previously installed credential.
  - Verify: `tests/deploy/test_secret_token_push.py::test_failed_push_preserves_prior_encrypted_credential`
- [ ] Unknown VM names and account/project mismatches fail closed before remote mutation.
  - Verify: `tests/deploy/test_secret_token_push.py::test_invalid_vm_mapping_fails_before_remote_mutation`

## How to Verify (Pre-Merge)

Run the named tests in tests/deploy/test_secret_token_push.py using fake Keychain, systemd-creds, and remote transport adapters. Assert the canary token is absent from argv and captured output. Do not connect to or mutate a live VM.

## Out of Scope

- Provisioning or changing a live VM.
- Creating BWS machine accounts or changing their permissions.
- Updating a running systemd unit on a live host.
- Any live qualification receipt.

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/LOCAL_SECRET_PROVISIONING/README.md
- docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md
- scripts/deploy_channel.sh

## Related GitHub Issues

GitHub issue: #5679 (filed blocked while the specification PR is open).
