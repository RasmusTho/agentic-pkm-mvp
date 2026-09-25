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

The host secret contract declares required, channel-scoped `postgres.password` as `delivery=file` with non-secret service paths `POSTGRES_PASSWORD_FILE` for Compose `db` and `DATABASE_PASSWORD_FILE` for the five application/migration services; it creates no password environment binding. Its exact database-consumer-to-Compose map is `postgres-db` -> `db`, `postgres-migrate` -> `migrate`, `postgres-api` -> `api`, `postgres-worker` -> `worker`, `postgres-watcher` -> `watcher`, and `postgres-capture-watch` -> `heimdal-capture-watch`, for dev, test, and prod. No other service is authorized for this file. The agent-host deployment controller takes the shared BWS operation lock before checking selected shared identities and database credentials, and holds it through the VM project-scoped recheck, source materialization, and matching durable remote terminal receipt. It never sends its admin credential to a VM. The VM reader rechecks the selected consumer set before local deployment-state mutation and again before Compose. A missing/unreadable password blocks every normal deploy before remote deployment-state mutation. The sole missing-password exception is BWS-04 first initialization defined below.

As the final child, post the integrated repository-acceptance receipt to #5667 and leave the parent open until live operator qualification is recorded. Materialize the PostgreSQL password as a root-owned mode-0440 source whose group is the configured database-client primary GID (`LOCAL_GID`) inside a root-only mode-0700 tmpfs directory. This permits the configured non-root application and migration UID/GID to read the file without host directory traversal or world access. Expose the file-backed Compose secret only to PostgreSQL and selected database clients. Local file-backed Compose secrets are bind mounts, so Compose ignores their `uid`, `gid`, and `mode` overrides; set and verify ownership/mode on the source file. This is the only host-side plaintext credential file, and it is ephemeral; do not write a persistent plaintext credential or environment file. Keep the tmpfs source available for as long as a mounted container can restart or be recreated. A managed host lifecycle rehydrates it before Compose start/restart/recreate and after host boot, prevents Docker from restarting consumers ahead of rehydration, and removes it only after all consumers stop. Compose returning is not a cleanup boundary.

Every deployment has a value-free durable remote per-channel journal outside the repository and outside tmpfs, in an owner-only persistent VM state directory. The record contains `operation_id`, channel, operation kind, stage, and terminal result only. Persist each stage atomically and durably by writing a temporary file, flushing/fsyncing it, renaming it over the prior record, and flushing/fsyncing the parent directory. A VM-side supervised worker keyed by `operation_id` owns the journal and VM per-channel lock independently of the SSH client; it holds the lock through all deployment mutations, Compose completion, and terminal-stage write. A reconnect with the same ID joins or waits on that worker and never starts a duplicate. The stage sequence is `prepared` (after required host preflight and before remote deployment-state mutation; bootstrap may use it for lock coordination), `preflighted`, `materialized`, `activating`, then terminal `committed` or `aborted`. Persist `activating` before invoking Compose. After Compose activation succeeds, atomically persist `committed`; that durable same-ID record is the terminal receipt. Persist `aborted` only after confirming no deployment effect occurred or rollback completed; that durable record is its terminal receipt. On SSH loss, do not infer that the SSH wrapper's exit made the operation quiescent. Recovery first joins/waits on the same-ID worker. If the worker ended without a terminal receipt, recovery may inspect/reconcile only after proving that no worker/subprocess for that ID remains and the affected Compose/Docker resources have no in-progress transition. If it cannot prove quiescence and a committed/aborted outcome, it remains pending and blocks new work. The agent host clears its pending deploy operation only after reading a matching same-ID terminal remote receipt; a released lock or lock snapshot is not sufficient.

For an initialized database, import the value already used by the PostgreSQL role and verify that it authenticates; a missing BWS item fails closed and cannot enter bootstrap. For first initialization only, when the item is absent, BWS-04 acquires the exclusive agent-host BWS operation lock, checks other selected identities, then acquires the existing per-channel VM mutation lock as a coordination-only action and inspects the actual data directory while holding it. If the directory is not empty, release the lock and fail without writing BWS or deployment state. If empty, BWS-04 alone may generate the initial value; BWS-02 must durably append the `previous_state=absent` history tombstone and prepared operation ID before the BWS write. Include that non-secret ID in BWS item metadata, then read the item back and verify it before any deployment-state mutation. Recheck it on the VM before local mutation and Compose. The per-channel lock serializes this inspection with deploy/rollback; the operation lock serializes it with all supported admin writers. If interrupted after the BWS create may have reached the provider, the same prepared operation remains pending. A later locked attempt verifies the directory is still empty and reads/reuses exactly one item carrying the operation ID. If readback is absent or ambiguous, it does not issue a second create and remains blocked until an authoritative outcome is established. It never starts a new operation or overwrites an existing item. Lock order is always agent-host BWS operation lock before VM per-channel lock. For an initialized data directory, use the current role value; changing the BWS item alone does not rotate that role. Any later password rotation requires a separate coordinated database-role cutover.

## Concretely

The rendered Compose configuration names the secret mount and source path but contains no PostgreSQL password. It mounts the file only into the authorized `db`, `migrate`, `api`, `worker`, `watcher`, and `heimdal-capture-watch` services selected by the corresponding `postgres-*` contract consumers. The PostgreSQL image receives POSTGRES_PASSWORD_FILE; the official entrypoint reads it into its own short-lived startup shell before checking initialization state and, on an existing data directory, skips initialization without changing the active role password. On an empty data directory, scrub `POSTGRES_PASSWORD` and `PGPASSWORD` from the `pg_ctl` child environment for the temporary initialization server; separately scrub both from the shell environment immediately before the final steady-state `exec` on every path. Tests source the `POSTGRES_PASSWORD` canary from the mounted password file and seed `PGPASSWORD` separately; they do not set both `POSTGRES_PASSWORD` and `POSTGRES_PASSWORD_FILE` in the container's initial environment because the official entrypoint rejects that combination. The initialization-server Verify covers an empty data directory, and the steady-server Verify covers fresh and initialized data-directory startups. The entrypoint and initialization client may hold the value in memory only for the short startup work needed to initialize the role. PostgreSQL receives the mount through `POSTGRES_PASSWORD_FILE`; application and migration services receive the same file-backed secret plus the non-secret `DATABASE_PASSWORD_FILE` path. A single file-aware resolver, used by app.config.database, app.db.dsn, Alembic, and direct DB clients such as Heimdal raw-store access, reads the file in process memory and constructs each connection URL. No caller may build a second DSN path from `DATABASE_URL`/`DB_DSN` alone. A credential-free explicit DSN may override non-secret connection fields, but URI password components and keyword-DSN `password` values fail closed before environment rendering. A missing or unreadable file, failed role-authentication check, or unready lifecycle-managed source fails closed.

## Why This Matters

Rendered Compose is commonly inspected and retained in deploy output, and environment values appear in container metadata. A BWS preflight after a deployment mutation is too late to prevent partial state changes.

## Acceptance Criteria

- [ ] The single agent-host operation lock serializes cooperating BWS import/check and deploy entrypoints on that host from host parity preflight through VM recheck, password-source materialization, and Compose activation. The VM per-channel lock is held until a matching durable terminal remote receipt. Interruption leaves a pending operation that cannot be cleared by lock state alone.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_waits_for_in_progress_shared_import_and_rechecks_parity`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_cannot_interleave_with_deploy_check_to_compose`
  - Verify: `tests/ops/test_secret_admin.py::test_shared_import_interruption_blocks_until_reimport_reconciles`
- [ ] The agent-host admin parity check for selected shared identities and consumers precedes remote deployment-state mutation; VM checks remain project-scoped, include the required database file credential, and never receive the admin token.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_admin_parity_preflight_precedes_remote_deploy_mutation`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_vm_reader_recheck_is_project_scoped_and_precedes_compose`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_inactive_optional_model_credentials_do_not_block_deploy`
- [ ] PostgreSQL and application Compose services use file-backed secret paths with no inlined password in rendered configuration.
  - Verify: `tests/deploy/test_deploy_channel.py::test_rendered_compose_uses_postgres_secret_file_without_value`
- [ ] The host contract declares required channel-scoped `postgres.password` as file-only and maps exactly `postgres-db`/`db`, `postgres-migrate`/`migrate`, `postgres-api`/`api`, `postgres-worker`/`worker`, `postgres-watcher`/`watcher`, and `postgres-capture-watch`/`heimdal-capture-watch`; no other consumer or service receives the credential.
  - Verify: `tests/ops/test_host_secret_contract.py::test_postgres_password_contract_is_file_only_and_consumer_set_is_closed`
  - Verify: `tests/deploy/test_deploy_channel.py::test_database_services_map_to_declared_password_consumers`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_mount_is_limited_to_database_clients`
- [ ] A normal database-bearing plan requires `postgres.password` before remote deployment-state mutation, then rechecks it on the VM before local deployment-state mutation and Compose; missing/unreadable values leave deploy state unchanged.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_password_preflight_precedes_remote_and_vm_mutation`
- [ ] When `postgres.password` is absent, BWS-04 creates it only after holding both coordinator locks and proving the selected directory is empty; an initialized directory fails without BWS or deployment-state mutation, and interruption retries reuse the stored value.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_allows_absent_secret_only_for_locked_empty_data_directory`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_blocks_absent_secret_for_initialized_directory`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_retry_reuses_stored_secret_after_interruption`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_ambiguous_create_without_matching_operation_note_remains_pending`
- [ ] Deploy writes a value-free owner-only remote journal with `operation_id`, channel, kind, stage, and terminal result. A VM-side supervised worker keyed by that ID owns the journal and per-channel lock independently of SSH through Compose completion and receipt writing; reconnect joins the same worker. Stage transitions are atomic and durable; `activating` is persisted before Compose, and durable `committed`/`aborted` stages are terminal receipts. Recovery cannot close or retry until the prior worker/subprocess is gone and affected Compose/Docker resources are quiescent; if this cannot be proven, the operation stays pending. Lock release alone is not completion.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_writes_durable_operation_stages_and_terminal_receipt`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_lost_ack_reconciles_matching_remote_terminal_receipt`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_nonterminal_remote_receipt_blocks_next_operation`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_ssh_loss_joins_same_supervised_operation_until_quiescent`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_nonquiescent_compose_operation_remains_pending`
- [ ] One runtime database resolver reads the configured password file without copying its value into the deploy orchestrator, rendered Compose, or application environment. Application configuration, Alembic migrations, and direct DB clients such as Heimdal raw-store access all use that resolver. It rejects password-bearing `DATABASE_URL` and `DB_DSN` overrides without disclosing the value, while credential-free direct DSNs may supply non-secret connection fields and still use the file-backed password. The official image entrypoint may hold the value only in its own short-lived startup shell and initialization client as required for first initialization. Scrub `POSTGRES_PASSWORD` and `PGPASSWORD` from the `pg_ctl` child environment for the temporary initialization server, and separately scrub both from the shell environment before final `exec "$@"` on every path. Password-file changes do not claim to rotate an initialized role.
  - Verify: `tests/db/test_dsn.py::test_runtime_database_config_uses_password_file`
  - Verify: `tests/db/test_dsn.py::test_password_bearing_direct_dsn_is_rejected_without_value_disclosure`
  - Verify: `tests/db/test_dsn.py::test_credential_free_direct_dsn_uses_password_file`
  - Verify: `tests/db/test_dsn.py::test_alembic_uses_file_aware_database_resolver`
  - Verify: `tests/heimdal/test_raw_store.py::test_pg_connect_uses_file_aware_database_resolver`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_entrypoint_password_file_isolated_from_application_environment`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_initialization_server_process_environment_omits_password` (empty data directory; source `POSTGRES_PASSWORD` from the mounted file and seed `PGPASSWORD` separately)
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_server_process_environment_omits_password` (fresh and initialized data directories; source `POSTGRES_PASSWORD` from the mounted file and seed `PGPASSWORD` separately)
  - Verify: `tests/deploy/test_deploy_channel.py::test_initialized_database_role_is_not_changed_by_password_file`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_secret_generated_only_for_empty_data_directory`
- [ ] The root-owned `0440` secret source with the configured service GID stays available through container restart/recreate, is rehydrated before host-boot startup, and is removed after every consumer stops.
  - Verify: `tests/deploy/test_deploy_channel.py::test_compose_secret_source_lifecycle_covers_restart_recreate_and_boot`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_file_is_private_and_cleaned_after_consumers_stop`
- [ ] No persistent plaintext PostgreSQL credential or environment file is written; the only host-side plaintext source is the root-owned `0440` file, group-readable only by the configured database-client GID, inside root-only tmpfs; it is retained for consumer restart/recreate and removed only after every consumer stops.
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_source_uses_root_only_tmpfs_and_service_gid`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_is_readable_by_configured_non_root_service_user`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_mount_is_limited_to_database_clients`
  - Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_source_is_ephemeral_and_nonpersistent`
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_does_not_create_plaintext_postgres_env_file`
- [ ] Final owner docs describe the shipped repository support and preserve the live qualification gate.
  - Verify: doc writeback at `docs/LOCAL_SECRET_PROVISIONING/README.md :: Linux Bitwarden Secrets Manager`
  - Verify: doc writeback at `docs/SECURITY.md :: Secrets in CI`
  - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Linux channel secret provisioning`

## How to Verify (Pre-Merge)

Run the named tests in tests/deploy/test_deploy_channel.py and tests/deploy/test_deploy_channel_script.py using fake provider and transport adapters. Verify the host operation lock is acquired before the VM channel lock. Exercise normal missing-password rejection, absent-password bootstrap with an empty directory, absent-password rejection with initialized data, and interruption after BWS generation followed by safe reuse. Interleave a shared import before host check, between host and VM checks, and before Compose; prove it cannot pass the lock until deployment reaches a matching durable terminal receipt. Inject SSH loss at each journal stage, including immediately before and after Compose; prove reconnect joins the same supervised operation, that the supervisor retains the VM lock through command completion/receipt, and that recovery waits for subprocess and Compose/Docker quiescence. Verify that missing terminal evidence or nonquiescent resources remain pending and that a released lock alone never admits a new operation. Do not connect to or mutate a live VM.

## Out of Scope

- Cleaning or migrating an existing VM plaintext credential file.
- Live deploys, Docker changes, VM provisioning, or production database changes.
- PostgreSQL password rotation or mutation of an initialized database role; that requires a separate coordinated cutover issue.
- Changes to the production raw-store-key or archive-pass lifecycle; protected rotation and deletion remain refused and require a separate owner-directed task.
- BWS account and project setup.

## External References

- [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/) (local file-backed secrets are mounted from their declared host source)
- [Docker Compose service secret attributes](https://docs.docker.com/reference/compose-file/services/) (`uid`, `gid`, and `mode` overrides are ignored for file-backed secrets because they use bind mounts)
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
