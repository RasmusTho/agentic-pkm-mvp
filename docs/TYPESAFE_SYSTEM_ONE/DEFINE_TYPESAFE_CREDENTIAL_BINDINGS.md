---
name: Define TypeSafe credential consumer bindings
description: Declare one fail-closed development provider-key binding for the MARR Mac server.
task_id: TSO-05
github_issue: 5770
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraints
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-00]
depends_on: [PUBLISH_CAPABILITY_SPECIFICATION.md]
can_parallelize_with: []
---

# Define TypeSafe Credential Consumer Bindings

## State

The repository declares and tests the single server-only dev binding with fake secret sources. No credential has been installed or provisioned and no runtime route is activated. Live use remains gated on the separate parent #5764 acceptance path.

## Purpose

Keep the runtime TypeSafe provider key on one dedicated MARR development server while Product and Builder retain separate caller authorization, caller credentials, owner profiles, and acceptance.

## What This Task Does

- Declare `typesafe.api-key` for exactly `marr-server-dev` on `dev`, through the existing Mac Keychain resolver. The explicit `keychain_only_secrets` declaration keeps it out of the BWS identity and grant map.
- Product and Builder are separate authenticated callers of the bounded MARR operation. Neither caller resolves or receives the server's provider key; caller policy, credentials, and model profiles remain separate.
- Refuse missing, malformed, unauthorized, Linux, test, and prod bindings through the production resolver before any provider dispatch. Codex and Claude runtime consumers receive no grant.
- Preserve the existing two BWS projects, three machine accounts, shared non-prod reader, and secret grants. This runtime declaration adds no item to either BWS project; the separate direct-agent path under #5778 is outside its grants.
- Use injected fake credential sources for repository verification. Values never enter code, logs, prompts, or receipts.
- Live use requires owner confirmation of rotation after the earlier exposure, a scoped MARR dev host binding, explicit one-call authorization with synthetic input, and a redacted receipt. Separate Product and Builder dev acceptance on #5764 precedes their route activation.
- Direct coding-agent calls are a separately governed one-shot development path (#5778); this runtime binding grants them no access.

## Acceptance Criteria

- [x] The host-secret contract declares exactly one dev-only MARR server consumer; Product and Builder callers receive no provider-key grant.
  - Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_consumer_bindings_are_separate`
- [x] Production resolution allows only the Mac MARR dev consumer and refuses Product, Builder, Codex, Claude, Linux, test, and prod access to the provider key.
  - Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_is_dev_only_and_agent_processes_cannot_resolve_it`
- [x] Missing, malformed, or unauthorized bindings fail closed without exposing a secret.
  - Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_missing_or_unauthorized_binding_fails_closed`
- [x] The credential specification and secret owner documents agree on the single server-only dev binding, unchanged BWS scope, and remaining live operator gates.
  - Verify: doc writeback at `docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraints`
  - Verify: doc writeback at `docs/LOCAL_SECRET_PROVISIONING/README.md :: Declared identifier contract`
  - Verify: doc writeback at `docs/TYPESAFE_SYSTEM_ONE/README.md :: Data and Credential Boundary`

## How to Verify (Pre-Merge)

- `pytest -q tests/ops/test_host_secret_contract.py tests/ops/test_host_secret_bootstrap.py`
- `ruff check app tests companion-ui/companion-app`
- `mypy app`
- `python3 scripts/docs_guard.py --language-only`
- `git diff --check`

## Out of Scope

- Secret rotation, import, provisioning, BWS/Keychain administration, host installation, live TypeSafe calls, route activation, or test/prod rollout.
- Plan, project, or account changes; runtime consumer/profile integrations; direct-agent integration; changing coding-agent or Yggdrasil default models.
