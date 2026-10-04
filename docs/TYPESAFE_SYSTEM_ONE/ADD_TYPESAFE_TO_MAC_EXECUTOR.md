---
name: Add TypeSafe to the Mac Model Access Router
description: Add one authenticated, bounded System One judgment operation to the Product Mac executor.
task_id: TSO-02
github_issue: 5766
source_anchor: docs/MODEL_ACCESS_ROUTER/README.md :: Capability Contract
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-01]
depends_on: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md]
can_parallelize_with: []
---

# Add TypeSafe to the Mac Model Access Router

## Purpose

Product requests need to reach Jev without exposing the TypeSafe API key to Product Linux, Codex, or Claude. The Mac executor is the only Product-facing place that owns this external credential.

## What This Task Does

- Add a bounded System One judgment operation to the MARR service and Product client, reusing existing authenticated admission and channel/action authorization.
- Accept only the typed state/questions contract and a Product-selected, declared TypeSafe route; accept no arbitrary endpoint, headers, environment, or commands.
- Execute one `typesafe-sdk` request to the documented TypeSafe API, return typed answer/provenance data, and classify sanitized failures.
- Resolve `typesafe.api-key` only for the dedicated Mac-executor consumer through the host-local Keychain contract. Missing credentials fail closed.
- Do not retry a request after a send may have reached TypeSafe; do not fall back to Codex or Ollama after inference may have started.

## Concretely

Product sends a typed judgment request through the existing authenticated executor ingress. The executor resolves the declared provider credential from Keychain and returns one typed answer. An absent key or unsupported question produces a sanitized typed failure before any inference.

## Why This Matters

Sending the key to Product Linux or a coding-agent process would widen the credential boundary and bypass the chosen Mac-executor path.

## Acceptance Criteria

- [ ] The production MARR route authorizes the same Product channel/action as its peer operations and dispatches exactly one TypeSafe request. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_executor_dispatches_one_bounded_system_one_request`.
- [ ] Missing or malformed Keychain credentials fail before the provider request and never enter logs, responses, or receipts. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_missing_typesafe_credential_fails_before_provider_call`.
- [ ] An ambiguous provider timeout is terminal; the executor does not retry or switch to a completion adapter. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_ambiguous_request_is_not_retried_or_fallback`.
- [ ] The TypeSafe binding is limited to the dedicated executor consumer and does not grant it to unrelated consumers or channels. Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_is_executor_scoped`.
- [ ] MARR owner docs distinguish typed judgments from generic completions and state the supported behavior accurately. Verify: doc writeback at `docs/MODEL_ACCESS_ROUTER/README.md :: Current State and Boundary`.

## How to Verify (Pre-Merge)

- `pytest -q tests/model_access/test_typesafe_judgment_executor.py`
- `pytest -q tests/ops/test_host_secret_contract.py::test_typesafe_key_is_executor_scoped`
- `pytest -q tests/model_access/test_executor_api.py tests/model_access/test_remote_contract.py`
- `git diff --check`

## Out of Scope

- Builder routing, Product intent-classifier semantics, catalog discovery, provider fallback, production host activation, or live API calls in CI.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/MODEL_ACCESS_ROUTER/README.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md :: Mac Keychain`
- `docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md`
