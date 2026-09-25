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

Linux channel processes need the accepted BWS store, while Mac-hosted processes must retain the delivered Keychain path. This task adds the provider seam and active identity mapping without changing consumer authority.

## What This Task Does

Add explicit provider selection for Keychain and BWS. Map shared secrets to shared/<logical-secret> and channel secrets to <channel>/<logical-secret>. Map dev/test to the non-prod project and prod to prod. Keep the existing declared consumer grants as the only environment-binding authority. Remove consumer-specific BWS items and the shared-key divergence mechanism. Fail closed on an unknown provider, channel, project mapping, missing item, malformed value, or BWS error.

The BWS token is supplied through the machine-account credential path. Runtime lookup is read-only and project-scoped. Provider response values are held in memory only and are never logged or returned in errors.

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

## How to Verify (Pre-Merge)

Run the named tests in tests/ops/test_host_secret_bootstrap.py and tests/ops/test_host_secret_contract.py, then run the selected CI checks for the changed Python and contract files. Review the production bootstrap call site to prove provider selection is explicit and fail-closed.

## Out of Scope

- BWS account, project, machine-account, or live VM provisioning.
- Admin writes, secret generation, token transfer, and PostgreSQL Compose changes.
- Provider calls or consumer policy changes.

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/LOCAL_SECRET_PROVISIONING/README.md
- config/secrets/host_secret_contract.json
- app/ops/host_secret_contract.py
- app/ops/host_secret_bootstrap.py

## Related GitHub Issues

GitHub issue: #5677 (filed blocked while the specification PR is open).
