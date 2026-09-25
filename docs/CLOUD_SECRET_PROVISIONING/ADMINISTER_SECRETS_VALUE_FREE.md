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

Import reads one value from stdin and updates only the BWS store. Provider credentials must already exist at their issuer; BWS import neither creates, revokes, nor claims to rotate them. Issuer-side rollout and overlap remain external operations. An existing PostgreSQL role credential is imported as currently active; changing the BWS item alone never changes an initialized role. Generation and rotation reject externally issued identities, protected Heimdal keys, and `postgres.password` for an initialized database. Any future generated or rotated identity must be named in a closed BWS-owned allowlist. Before changing a BWS value, the admin writes the prior value to append-only history. Shared imports archive both old copies and apply the one stdin value to both projects; partial failure triggers compensation, and unresolved mismatch is reported as `divergent` and blocks deployment. A BWS password change alone never claims to rotate an initialized PostgreSQL role. History values are never automatically deleted.

Admin writes use an authenticated request-body interface. The BWS CLI create/edit forms are not used to send values because they place values in command arguments; default CLI responses are not forwarded. The admin credential is resolved from the agent host Keychain and is never installed on a VM. Protected production data-encryption secrets remain refused until the owner decision is recorded in #5667 and a separate approved task defines their exact lifecycle.

## Concretely

A check for a declared consumer emits its selected logical names with present, missing, malformed, optional-absent, or divergent status. It exits non-zero when a required binding is missing, any present selected value is malformed even when optional, or a selected shared identity is divergent. Inactive optional provider credentials do not become deploy requirements. Import reads a single value from stdin and emits only identity and status. Generation/rotation reject identities outside the closed BWS-owned allowlist; all accepted writes archive the prior value before activation. The only PostgreSQL creation path is BWS-04 first initialization against a verified empty data directory. Failure to append history leaves the active value unchanged.

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
- [ ] A partial shared-copy update is compensated when possible; unresolved divergence remains value-free and causes deploy preflight to reject the channel until repaired.
  - Verify: `tests/ops/test_secret_admin.py::test_shared_secret_partial_update_is_compensated_or_reported_divergent`
- [ ] Protected production raw-store-key and archive-pass writes remain refused while the owner decision is unresolved, and initialized PostgreSQL credentials cannot be rotated by BWS alone.
  - Verify: `tests/ops/test_secret_admin.py::test_unresolved_protected_rotation_is_refused_without_value_disclosure`
  - Verify: `tests/ops/test_secret_admin.py::test_initialized_postgres_password_cannot_be_rotated`
- [ ] Admin write calls keep secret values out of argv, stdout, stderr, and receipts.
  - Verify: `tests/ops/test_secret_admin.py::test_admin_write_value_never_enters_argv_or_output`

## How to Verify (Pre-Merge)

Run the named tests in tests/ops/test_secret_admin.py with fake BWS read/write adapters. Assert canary values are absent from command arguments, captured output, errors, and logs. Verify selected-consumer checks allow absent inactive optional model credentials while rejecting missing active credentials. Inject failures at each history write, project update, and compensation; prove no success is reported for divergent copies and deploy preflight rejects the mismatch. Verify the VM reader path has no admin credential or cross-project access.

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
