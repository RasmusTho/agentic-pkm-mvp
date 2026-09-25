---
name: Deploy PostgreSQL with Compose Secrets
description: Gate deployment with host-authorized BWS parity checks and preserve file-backed PostgreSQL credentials through container restarts.
task_id: BWS-04
github_issue: 5680
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Cross-task invariants / interaction safety
parent_capability: CLOUD_SECRET_PROVISIONING
prerequisites: [BWS-01, BWS-02]
depends_on: [RESOLVE_BWS_CHANNEL_SECRETS.md, ADMINISTER_SECRETS_VALUE_FREE.md]
can_parallelize_with: []
---

# Deploy PostgreSQL with Compose Secrets

## Purpose

Channel deployment must not mutate pins, markers, volumes, Docker state, or writers when an active consumer's required BWS secrets are missing, malformed, or divergent. PostgreSQL's password must not be embedded in Compose environment values, rendered configuration, the deploy orchestrator environment, application environments, or PostgreSQL server-process environments. Governed-channel `DATABASE_URL` and `DB_DSN` overrides remain supported only when credential-free; reject URI password components and keyword-DSN `password` values before they enter Compose or an application environment. The password file remains the only credential source. The value must match the active role in an initialized database; changing POSTGRES_PASSWORD_FILE alone does not rotate that role.

## What This Task Does

The agent-host deployment controller uses its Keychain-backed BWS admin identity to check parity for the selected deployment consumers before it dispatches any remote mutation; it never sends the admin token to a VM. The VM then uses its project-scoped reader to recheck only that project's selected consumer set immediately before Compose. The check set comes from the selected Compose/deployment plan, so absent inactive optional model-provider credentials do not block unrelated deployment.

As the final child, post the integrated repository-acceptance receipt to #5667 and leave the parent open until live operator qualification is recorded. Materialize the PostgreSQL password as a controlled mode-0600 source on a root-only tmpfs runtime filesystem and expose it only as a file-backed Compose secret to PostgreSQL and the application services. This is the only host-side plaintext credential file, and it is ephemeral; do not write a persistent plaintext credential or environment file. Keep the tmpfs source available for as long as a mounted container can restart or be recreated. A managed host lifecycle rehydrates it before Compose start/restart/recreate and after host boot, prevents Docker from restarting consumers ahead of rehydration, and removes it only after all consumers stop. Compose returning is not a cleanup boundary.

For an initialized database, import the value already used by the PostgreSQL role and verify that it authenticates; do not generate a replacement or claim that POSTGRES_PASSWORD_FILE changes the existing role. For first initialization, generate and store a PostgreSQL value only after confirming the selected data directory is empty while holding the channel mutation lock. Any later password rotation requires a separate coordinated database-role cutover. For an empty new data directory, the file may initialize the role through the official entrypoint. The upstream entrypoint starts a temporary initialization server via `pg_ctl` before its final POSTGRES_ cleanup: scrub `POSTGRES_PASSWORD` and `PGPASSWORD` from the `pg_ctl` child environment for that temporary server, then separately scrub both from the shell environment immediately before the final steady-state `exec "$@"` on every startup path, including initialized data. Retain only the short-lived in-memory access the entrypoint and initialization client need to initialize the role. Replace inline PostgreSQL password defaults and password-bearing DATABASE_URL/DB_DSN defaults for the governed channel Compose paths. Extend the centralized runtime database resolver so an explicit credential-free direct DSN may supply non-secret connection fields while the resolver obtains the password only from the configured file-backed secret. Reject a credential-bearing direct DSN before it enters Compose or an application environment, without disclosing its value. The deploy orchestrator, rendered Compose, application environments, and PostgreSQL server processes remain value-free. On every startup, including for an initialized data directory, the official PostgreSQL image entrypoint reads POSTGRES_PASSWORD_FILE into its own short-lived startup shell before checking initialization state.

## Concretely

The rendered Compose configuration names the secret mount and source path but contains no PostgreSQL password. The PostgreSQL image receives POSTGRES_PASSWORD_FILE; the official entrypoint reads it into its own short-lived startup shell before checking initialization state and, on an existing data directory, skips initialization without changing the active role password. On an empty data directory, scrub `POSTGRES_PASSWORD` and `PGPASSWORD` from the `pg_ctl` child environment for the temporary initialization server; separately scrub both from the shell environment immediately before the final steady-state `exec` on every path. Tests source the `POSTGRES_PASSWORD` canary from the mounted password file and seed `PGPASSWORD` separately; they do not set both `POSTGRES_PASSWORD` and `POSTGRES_PASSWORD_FILE` in the container's initial environment because the official entrypoint rejects that combination. The initialization-server Verify covers an empty data directory, and the steady-server Verify covers fresh and initialized data-directory startups. The entrypoint and initialization client may hold the value in memory only for the short startup work needed to initialize the role. Application services receive the corresponding secret file and a non-secret path setting; app.config.database resolves the password in process memory when it builds the connection URL. A credential-free explicit DSN may override non-secret connection fields, but URI password components and keyword-DSN `password` values fail closed before environment rendering. A missing or unreadable file, failed role-authentication check, or unready lifecycle-managed source fails closed.

## Why This Matters

Rendered Compose is commonly inspected and retained in deploy output, and environment values appear in container metadata. A BWS preflight after a deployment mutation is too late to prevent partial state changes.

## Acceptance Criteria

- [ ] The agent-host admin parity check for selected active shared identities precedes remote mutation; the VM rechecks only its project-scoped consumer set and never receives the admin token.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_admin_parity_preflight_precedes_remote_deploy_mutation`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_vm_reader_recheck_is_project_scoped_and_precedes_compose`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_inactive_optional_model_credentials_do_not_block_deploy`
- [ ] PostgreSQL and application Compose services use file-backed secret paths with no inlined password in rendered configuration.
  - Verify: `tests/deploy/test_deploy_channel.py::test_rendered_compose_uses_postgres_secret_file_without_value`
- [ ] Runtime database configuration reads the password file without copying its value into the deploy orchestrator, rendered Compose, or application environment. It rejects password-bearing `DATABASE_URL` and `DB_DSN` overrides without disclosing the value, while credential-free direct DSNs may supply non-secret connection fields and still use the file-backed password. The official image entrypoint may hold the value only in its own short-lived startup shell and initialization client as required for first initialization. Scrub `POSTGRES_PASSWORD` and `PGPASSWORD` from the `pg_ctl` child environment for the temporary initialization server, and separately scrub both from the shell environment before final `exec "$@"` on every path. Password-file changes do not claim to rotate an initialized role.
  - Verify: `tests/ops/test_runtime_database_config.py::test_database_password_file_is_resolved_without_environment_value`
  - Verify: `tests/ops/test_runtime_database_config.py::test_password_bearing_direct_dsn_override_is_rejected_without_value_disclosure`
  - Verify: `tests/ops/test_runtime_database_config.py::test_credential_free_direct_dsn_uses_password_file`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_entrypoint_password_file_isolated_from_application_environment`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_initialization_server_process_environment_omits_password` (empty data directory; source `POSTGRES_PASSWORD` from the mounted file and seed `PGPASSWORD` separately)
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_server_process_environment_omits_password` (fresh and initialized data directories; source `POSTGRES_PASSWORD` from the mounted file and seed `PGPASSWORD` separately)
  - Verify: `tests/deploy/test_deploy_channel.py::test_initialized_database_role_is_not_changed_by_password_file`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_secret_generated_only_for_empty_data_directory`
- [ ] The mode-0600 secret source stays available through container restart/recreate, is rehydrated before host-boot startup, and is removed after every consumer stops.
  - Verify: `tests/deploy/test_deploy_channel.py::test_compose_secret_source_lifecycle_covers_restart_recreate_and_boot`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_file_is_private_and_cleaned_after_consumers_stop`
- [ ] No persistent plaintext PostgreSQL credential or environment file is written; the only host-side plaintext source is the controlled mode-0600 file on root-only tmpfs, retained for consumer restart/recreate and removed only after every consumer stops.
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_source_uses_root_only_tmpfs_without_persistent_plaintext_file`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_does_not_create_plaintext_postgres_env_file`
- [ ] Final owner docs describe the shipped repository support and preserve the live qualification gate.
  - Verify: doc writeback at `docs/LOCAL_SECRET_PROVISIONING/README.md :: Linux Bitwarden Secrets Manager`
  - Verify: doc writeback at `docs/SECURITY.md :: Secrets in CI`
  - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Linux channel secret provisioning`

## How to Verify (Pre-Merge)

Run the named deployment and runtime database tests. Render each governed dev, test, and prod Compose overlay with fake secret values and assert the rendered config and deploy orchestrator environment contain no canary password. Inject failures at the host parity check, VM project-scoped recheck, final lookup, Compose launch, rehydration, and cleanup paths; prove no mutation occurs before checks, that restart/recreate/boot rehydrates the file before consumers start, and that cleanup waits until all consumers stop. Verify an initialized role credential authenticates and a password-file change alone cannot alter it. Update the three named owner-doc anchors to describe repository support and pending live qualification. After all child slices merge, record the integrated acceptance and live-gate status on #5667 without closing it before operator qualification.

## Out of Scope

- Cleaning or migrating an existing VM plaintext credential file.
- Live deploys, Docker changes, VM provisioning, or production database changes.
- PostgreSQL password rotation or mutation of an initialized database role; that requires a separate coordinated cutover issue.
- Changes to the production raw-store-key or archive-pass lifecycle; protected rotation and deletion remain refused and require a separate owner-directed task.
- BWS account and project setup.

## External References

- [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/) (local file-backed secrets are mounted from their declared host source)
- [PostgreSQL Official Image](https://github.com/docker-library/docs/blob/master/postgres/README.md#docker-secrets) (POSTGRES_PASSWORD_FILE and initialization-script behavior)

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md
- docs/ENVIRONMENTS.md
- docs/RELEASE_CHANNELS/README.md
- app/config/database.py
- scripts/lib/deploy_channel_compose.sh
- docker-compose.yaml
- docker-compose.dev.yml
- docker-compose.test.yml
- docker-compose.prod.yml

## Related GitHub Issues

GitHub issue: #5680 (filed blocked while the specification PR is open).
