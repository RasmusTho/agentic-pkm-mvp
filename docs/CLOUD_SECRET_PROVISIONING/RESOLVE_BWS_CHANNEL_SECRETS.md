---
name: Resolve BWS Channel Secrets
description: Add fail-closed Linux BWS lookup while preserving the Mac Keychain adapter.
task_id: BWS-01
github_issue: 5677
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraints
parent_capability: CLOUD_SECRET_PROVISIONING
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Resolve BWS Channel Secrets

## Purpose

Linux channel processes need the accepted BWS store, while Mac-hosted processes must retain the delivered Keychain path. This task adds the provider seam and active identity mapping while preserving all existing environment grants. It also defines one bounded non-environment file-delivery route for required channel-scoped `postgres.password`; it does not expose the password through an environment binding.

## What This Task Does

Add explicit provider selection for Keychain and BWS. Implement the stable owner-only agent-host operation lock and value-free pending-operation journal used by every supported secret check/write, token push, and deploy dispatch. All operations acquire the same exclusive lock before BWS or remote state observation; the pending journal survives process loss and blocks new work until reconciliation. The operation lock is acquired before a VM per-channel lock. The VM BWS reader remains project-scoped and read-only; selected deployment reads run only through the agent-host controller, with no direct VM deployment bypass.

The journal records a non-secret operation ID, operation kind, target identity/channel, and stage before external mutation; append a terminal receipt only after an authoritative terminal result. Its file and parent directory are owner-only, outside Git and iCloud. This local lock serializes only cooperating entrypoints on this host; it cannot fence another host, a direct BWS client, or a provider request already sent. A released OS lock does not clear a pending journal record. Recovery is operation-specific: BWS-02 may reconcile a shared import with a fresh stdin value only after all previous sends are authoritatively terminal; BWS-03 requires a durable same-ID remote terminal receipt agreeing with the encrypted-generation pointer; BWS-04 bootstrap needs an authoritative terminal provider result plus the item carrying its operation ID in non-secret metadata; deploy needs its durable remote same-ID terminal receipt. Unknown, absent, or mismatched evidence blocks later operations; a pointer or VM lock snapshot alone is insufficient. No out-of-band BWS write may run while a journaled operation is active or pending. Before shared parity or live qualification is claimed, the owner must approve and qualify a sole admin writer whose credential is restricted to this controller, or implement shared fencing. Direct VM deployment and secret-resolution bypass remain unsupported.

The VM BWS token is read only through `BWS_ACCESS_TOKEN_FILE`, whose value is the systemd credential path `$CREDENTIALS_DIRECTORY/bws-machine-account-token`; a repository-managed unit/drop-in supplies it through `LoadCredentialEncrypted=bws-machine-account-token:<encrypted-current-source>`. A missing or unreadable file fails before provider access. The VM reader is read-only and is invoked for selected deploy consumers only under the requesting agent-host controller operation lock; it does not hold admin authority, compare peer projects, or authorize a direct VM deployment bypass. Runtime lookup remains project-scoped and provider response values stay in memory only.

## Concretely

A dev lookup for openai.api-key selects shared/openai.api-key in non-prod. A prod lookup for heimdal.raw-store-key selects prod/heimdal.raw-store-key in prod. A non-prod token cannot request or resolve a prod project. Mac configuration selects Keychain and retains the existing Keychain item naming until a separately governed migration.

## Why This Matters

Without an explicit project and consumer boundary, a non-prod deployment could read production credentials or a process could receive secrets outside its declared allowlist. An implicit Keychain fallback on Linux would conceal a missing BWS configuration and prevent fail-closed behavior.

## Acceptance Criteria

- [ ] The Linux BWS adapter resolves only the active identity and project for the requested channel and consumer.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_bws_lookup_uses_scoped_active_identity`
- [ ] Unknown provider, wrong project, missing item, malformed value, and provider failures fail closed without exposing a canary value.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_bws_backend_failure_is_redacted_and_fail_closed`
- [ ] Mac Keychain lookup remains available with its existing key identity and redaction behavior.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_keychain_backend_remains_available_and_backend_failure_is_redacted`
- [ ] Contract validation rejects duplicate or undeclared secret identities and does not grant a consumer outside its existing binding list.
  - Verify: `tests/ops/test_host_secret_contract.py::test_bws_identity_scope_is_closed_and_consumer_grants_are_preserved`
- [ ] Secret checks and deployment-selected BWS reads use the shared agent-host operation lock; process/transport interruption leaves pending state that blocks later reads/writes/deploys until reconciliation.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_agent_host_operation_lock_serializes_bws_and_deploy_entrypoints`
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_pending_operation_journal_blocks_after_process_interruption`
- [ ] The shared owner-only lock serializes all supported secret, token-push, and deploy entrypoints; operation journal records survive process loss and only matching authoritative readback can close a pending mutation.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_agent_host_operation_lock_serializes_bws_and_deploy_entrypoints`
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_pending_operation_journal_blocks_after_process_interruption`
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_pending_operation_requires_matching_operation_id_readback`
- [ ] The contract states that the local lock coordinates cooperating entrypoints on one host only and does not claim cross-host/provider fencing; parent live qualification requires an owner-approved sole admin writer with credential restriction or a shared fencing mechanism.
  - Verify: doc writeback at `docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraint 14`
  - Verify: operator qualification receipt on #5667 :: exclusive BWS admin writer and no bypass
- [ ] The required channel-scoped PostgreSQL password is explicitly file-delivered and the closed consumer list maps exactly to the six authorized Compose services; no existing environment grant changes.
  - Verify: `tests/ops/test_host_secret_contract.py::test_postgres_password_contract_is_file_only_and_consumer_set_is_closed`
  - Verify: `tests/ops/test_host_secret_contract.py::test_existing_consumer_environment_grants_are_unchanged`
- [ ] BWS lookup consumes the token only from `BWS_ACCESS_TOKEN_FILE` at `$CREDENTIALS_DIRECTORY/bws-machine-account-token` and fails before provider access when the systemd credential is missing or unreadable.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_bws_access_token_file_fails_before_provider_request`

## How to Verify (Pre-Merge)

Run the named tests in tests/ops/test_host_secret_bootstrap.py and tests/ops/test_host_secret_contract.py. Verify provider/project scoping, existing Keychain compatibility, exact file delivery, and that deployment-selected VM reads occur only through the agent-host coordinated path. Do not access live BWS or a live VM.

## Out of Scope

- BWS account, project, machine-account, or live VM provisioning.
- Admin writes, secret generation, token transfer, and PostgreSQL Compose changes.
- General environment-consumer grant changes; only the explicit `postgres.password` file-delivery consumer contract defined above is added.

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/LOCAL_SECRET_PROVISIONING/README.md
- config/secrets/host_secret_contract.json
- app/ops/host_secret_contract.py
- app/ops/host_secret_bootstrap.py

## Related GitHub Issues

GitHub issue: #5677 (filed blocked while the specification PR is open).
