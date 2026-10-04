---
name: Define TypeSafe credential consumer bindings
description: Declare fail-closed development credential identities for the Product executor and Builder CKM.
task_id: TSO-05
github_issue: 5770
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Current Project and Machine-Account Contract
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-00]
depends_on: [PUBLISH_CAPABILITY_SPECIFICATION.md]
can_parallelize_with: []
---

# Define TypeSafe Credential Consumer Bindings

## State

Awaiting the owner's Bitwarden access-scope decision. The accepted cloud-secret contract fixes two projects and three machine accounts; the non-prod read identity is shared by ygg-dev and ygg-test. Do not change project/account scope or provision a key until this decision is resolved.

## Purpose

Give the Product Mac executor and Builder CKM distinct, dev-only credential consumer bindings while retaining the current fail-closed host-secret behavior.

## What This Task Does

- Declare the `typesafe.api-key` identity and exact allowed consumers in the host-secret contract: Product MARR Mac executor and Builder CKM, development channel only.
- Keep the two runtime resolvers and consumer identities separate. Each resolver returns unavailable when its binding or credential is absent.
- Verify the host-secret contract does not grant the identity to Codex/Claude agent processes, test/prod consumers, or any other runtime.
- Keep credential values in Bitwarden and host-local secure stores only. Never commit, log, or include a value in a receipt.
- Use the existing Bitwarden project/account contract unless the owner explicitly approves an amendment. Do not broaden the shared non-prod reader, add projects/accounts, or upgrade a plan implicitly.

## Acceptance Criteria

- [ ] The host-secret contract declares the TypeSafe key for only the Product Mac-executor and Builder CKM dev consumers with separate resolver bindings.
  - Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_consumer_bindings_are_separate`
- [ ] Missing or malformed credentials remain unavailable before provider dispatch; test/prod and coding-agent consumers are refused.
  - Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_is_dev_only_and_agent_processes_cannot_resolve_it`
- [ ] The BWS read scope is unchanged unless the owner-approved access choice amends the cloud-secret contract.
  - Verify: doc writeback at `docs/CLOUD_SECRET_PROVISIONING/README.md :: Current Project and Machine-Account Contract`

## How to Verify (Pre-Merge)

- `pytest -q tests/ops/test_host_secret_contract.py`
- `git diff --check`

## Out of Scope

- Creating Bitwarden projects or machine accounts, changing plan limits, provisioning a live key, making TypeSafe API calls, or activating any test/prod route.
