---
name: Define Host Secret Contract
task_id: HSP-01
source_anchor: docs/LOCAL_SECRET_PROVISIONING/README.md :: Fixed constraints
parent_capability: Local Secret Provisioning
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Implemented. Delivered by PR #3888 (issue #3845, 2026-07-17).

# Define Host Secret Contract

## Purpose

Define the interface between macOS Keychain and channel-scoped runtime consumers before any bootstrap
script or deployment wiring exists. This prevents a convenience `.env` file from becoming the
accidental secret manager.

## What this task does

1. Define logical secret identifiers, namespaced by channel and consumer, without values.
2. Define Keychain service/account mapping and access expectations for non-interactive local deploy.
3. Define consumer allowlist, temporary runtime-file permissions/cleanup, and redaction rules.
4. Write an operator runbook for initial creation, inspection by identifier, recovery, and the
   explicit non-rotation rule for `HEIMDAL_RAW_STORE_KEY`.

## Operator runbook

Create or inspect a Keychain item only through the logical identifier and its declared channel and
consumer; its account is deterministically produced by percent-encoding each
`{channel}:{consumer}:{secret}` component before colon-joining them. Never paste a value into a shell
history, repository file, issue, or receipt. HSP-02 will own non-interactive retrieval and temporary
runtime material. A raw-store key is generated only when the governed preflight proves no encrypted
records require an existing key; rotation is a separate migration, never a bootstrap retry.

## Acceptance criteria

- [x] The contract lists every initial logical secret, consumer, and permitted channel without a
      secret value or copied environment-file content.
      Verify: doc writeback at `docs/LOCAL_SECRET_PROVISIONING/README.md :: Fixed constraints`
- [x] The contract names a deterministic Keychain lookup rule and rejects an undeclared
      consumer/secret pair.
      Verify: `tests/ops/test_host_secret_contract.py::test_contract_rejects_undeclared_consumer_secret_pair`
- [x] The runbook describes generated-key creation and redacted failure evidence without printing a
      key.
      Verify: doc writeback at `docs/LOCAL_SECRET_PROVISIONING/DEFINE_HOST_SECRET_CONTRACT.md :: What this task does`

## Out of scope

Bootstrap implementation, Docker/deploy integration, secrets in CI, and any external secret service.

## How to verify

`pytest -q tests/ops/test_host_secret_contract.py`
