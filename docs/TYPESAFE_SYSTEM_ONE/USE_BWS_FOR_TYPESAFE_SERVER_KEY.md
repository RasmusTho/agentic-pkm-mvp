---
name: Use Bitwarden for the MARR TypeSafe provider key
description: Bind the MARR provider key to the existing non-prod BWS project with MARR-only consumer selection and controller-bound admin writes.
task_id: TSO-07
github_issue: 5801
source_anchor: docs/TYPESAFE_SYSTEM_ONE/README.md :: Data and Credential Boundary
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-00, TSO-05]
depends_on: [DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md]
can_parallelize_with: []
---

# Use Bitwarden for the MARR TypeSafe Provider Key

## State

Owner direction selects Bitwarden Secrets Manager as the source for the TypeSafe provider key and requests the credential contract and access model be updated. The repository binding uses the existing non-prod BWS project and reader identity; this task changes repository contracts and resolver behavior and does not claim a live BWS permission, token, or provider-key installation.

## Purpose

Keep the rotated TypeSafe provider key in Bitwarden and let only the existing MARR development server read it at runtime. The designated admin controller can read pre-state and write the item under its sole-writer gate. Product and Builder remain independent callers and never receive either the provider key or the BWS reader token.

## What This Task Does

- Resolve `dev/typesafe.api-key` from the existing `non-prod` BWS project through the existing read-only `non-prod-reader` identity. The item remains restricted in code to the `dev/marr-server-dev` consumer.
- Keep the existing two-project, three-account BWS topology. The `non-prod-reader` and `prod-reader` accounts may read both existing projects under the accepted one-operator permission model; channel lookup selection remains explicit in code.
- Resolve the BWS machine-account token for the MARR server from macOS Keychain service `yggdrasil.bws-reader`, account `non-prod-reader.token`. The token stays in process memory and is not read from an environment variable, command argument, shell output, or receipt. It has no admin authority.
- Extend the production MARR host-secret path and strict contract validation to permit only the declared dev/MARR/key/consumer tuple. Keep database and vault environment bindings unchanged. Keychain remains the bootstrap store for the MARR BWS reader token and for unrelated existing Mac secrets; it no longer supplies the TypeSafe provider key.
- Fail closed before inference for a missing or malformed reader token, a missing/ambiguous key, an unexpected BWS project/account scope, or an unknown/unpinned model profile. Never fall back to a Keychain copy, another provider, or an automatic latest model. Preserve the one-inference-attempt boundary: after a Jev request may have been sent, no retry or fallback is allowed.
- Preserve the independent Product and Builder policies, authenticated caller credentials, pinned owner profiles, SDK pin, typed judgment contract, and exact provider/model provenance. Model release versions remain independent of the TypeSafe SDK/package version; SDK changes stay in the adapter and its conformance tests.
- Use fake Keychain and BWS clients for repository proof. Tests must assert exact project and identity selection, exact provider/model provenance, and that credentials never appear in logs, argv, environment passed to callers, or receipts.
- The existing BWS topology remains two projects and three machine accounts. This MARR binding adds no project or account requirement. Verify the existing reader/admin qualification before live setup; do not purchase or upgrade a plan under this task.
- The existing #5667 sole-admin-writer and credential-restriction gate remains required before live project/account or permission changes. Live setup, token installation, and the already separately authorized one-synthetic-attempt-per-caller dev acceptance remain on parent #5764 / BWS parent #5667 and must not be represented as CI proof.
- The `typesafe.api-key` item reported by #5778 in the shared `non-prod` project is now the repository's selected BWS identity for this MARR binding. Any live import or retirement remains behind the #5667 writer gate. TSO-06 direct-agent acceptance is outside this Product/Builder delivery scope.

## Acceptance Criteria

- [ ] The host-secret contract permits `typesafe.api-key` only for `dev/marr-server-dev`, maps it to `non-prod/dev/typesafe.api-key`, and preserves the MARR-only runtime grant; reader project scope does not alter the code-level consumer allowlist.
  - Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_uses_non_prod_project_and_marr_only_consumer`
- [ ] The production MARR startup path reads the BWS token only from the declared Keychain entry, resolves exactly the channel-selected TypeSafe key, and never places either credential in Product or Builder caller environments or receipts.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_typesafe_bws_lookup_uses_non_prod_project_and_reader_token`
  - Verify: `tests/architecture/test_typesafe_runtime_boundary.py::test_runtime_key_stays_on_marr_and_callers_keep_separate_policy`
- [ ] Missing, malformed, ambiguous, or out-of-scope BWS credentials/items fail before Jev dispatch, without Keychain fallback, credential disclosure, or a second inference attempt.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_typesafe_bws_lookup_fails_closed_before_provider_dispatch`
  - Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_bws_lookup_failure_fails_before_provider_call`
  - Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_bws_lookup_failure_fails_before_provider_dispatch`
- [ ] The governed value-free admin path can check or import `dev/typesafe.api-key` only in `non-prod`; it retains its controller lock, durable history, and no-value output contract, while non-dev channels and undeclared consumers cannot address the binding.
  - Verify: `tests/ops/test_secret_admin.py::test_typesafe_import_targets_non_prod_and_rejects_other_channels`
  - Verify: `tests/ops/test_secret_admin.py::test_typesafe_admin_check_uses_only_marr_project_and_exact_consumer_grant`
- [ ] Product and Builder fake-provider profile swaps and the shared typed contract remain unchanged; exact provider/model release provenance is observable without key material, and SDK/package version remains adapter-only.
  - Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_supported_model_profile_swap_keeps_request_contract`
  - Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_supported_model_profile_swap_preserves_candidate_contract`
- [ ] TypeSafe, local-secret, and BWS owner documents agree on the existing project/account topology, MARR-only consumer binding, live gates, and not-yet-qualified state.
  - Verify: doc writeback at `docs/TYPESAFE_SYSTEM_ONE/README.md :: Data and Credential Boundary`
  - Verify: doc writeback at `docs/LOCAL_SECRET_PROVISIONING/README.md :: Declared identifier contract`
  - Verify: doc writeback at `docs/CLOUD_SECRET_PROVISIONING/README.md :: Fixed constraints`

## Out of Scope

- Creating or purchasing a Bitwarden subscription, upgrading a plan, or changing the accepted shared Linux reader scope for the TypeSafe key.
- Live BWS project/account creation, secret import/provisioning, MARR token installation, TypeSafe API calls, key rotation, or Product/Builder route activation.
- Product or Builder caller credentials, policy, or profile ownership changes; generic chat/completion; direct-agent Jev calls; and changing Yggdrasil's default model.

## Suggested Validation

- `pytest -q tests/ops/test_host_secret_contract.py tests/ops/test_host_secret_bootstrap.py tests/model_access/test_typesafe_judgment_executor.py tests/builderops/ckm/test_semantic_typesafe.py tests/architecture/test_typesafe_runtime_boundary.py`
- `ruff check app tests companion-ui/companion-app`
- `mypy app`
- `python3 scripts/docs_guard.py --language-only`
- `git diff --check`

## Source Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/TYPESAFE_SYSTEM_ONE/DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`
- `docs/CLOUD_SECRET_PROVISIONING/README.md`
- `config/secrets/host_secret_contract.json`
- `app/ops/host_secret_contract.py`
- `app/ops/host_secret_bootstrap.py`
- `app/ops/bws_secret_reader.py`

## Applies learning (optional)

The task incorporates the user-directed BWS source correction after #5770 established a Keychain-only binding. The shared Linux `non-prod-reader` is intentionally reused under the accepted one-operator store-level policy; its broader project scope does not create a code-level MARR consumer grant, and channel lookup remains explicitly selected in code.
