State: Draft capability specification for parent feature issue #5667; child issues are filed blocked while this spec PR is open and become ready after it merges.
Doc role: Linux cloud secret provisioning capability specification
Authority: This directory owns the BWS Linux channel-secret contract. It is subordinate to docs/SECURITY.md, docs/ENVIRONMENTS.md, docs/RELEASE_CHANNELS/README.md, docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md, and the consumer owner docs.
Owner: Yggdrasil Platform and Operations, with Product/Runtime and Builder System boundary review
Temporal class: strategic
Review cadence: after a task merge, BWS account/topology change, or live channel qualification
Source of truth: this directory for target behavior; issue #5667 is the delivery and acceptance hub
Last reviewed: 2026-09-25

# Cloud Secret Provisioning

## Outcome

Provide Linux channel VMs with centrally administered Bitwarden Secrets Manager (BWS) secrets. Preserve the existing macOS Keychain path for Mac-hosted processes. Keep channel and consumer grants explicit and fail closed before runtime or deployment mutations. Secret values and machine-account tokens stay out of command arguments, output, logs, receipts, Git, BuilderOps records, iCloud, and admin/deploy orchestrator environments. Values reach runtime consumers only through their declared owner-controlled handoff; PostgreSQL credentials use file-backed Compose secrets.

The 2026-09-24 owner decision in #5667 selects BWS, two projects named prod and non-prod, and exactly three machine accounts: non-prod-reader shared by ygg-dev and ygg-test, prod-reader for ygg-prod, and admin for writes. The admin token remains in the agent host Keychain. This specification does not provision the account, organization, projects, accounts, or live VMs.

This is boundary work. Yggdrasil Platform and Operations owns Linux host and Compose lifecycle. Product/Runtime owners retain authority over Heimdal key semantics and database use. Builder System tooling may administer secrets through the approved admin identity, but it does not become a secret store or runtime authority.

## Current status

The repository currently implements the Mac Keychain path. This specification defines the Linux BWS target and does not claim live VM qualification. Existing host credential files remain until a separately authorized operator migration; code delivery alone does not remove or rotate live host material.

A decision is still required for production Heimdal raw-store-key rotation. The current raw record format has one configured AES key and no key identifier or multi-key read path. Changing the current value would make earlier ciphertext unreadable. Until the owner records the policy on #5667, the implementation must refuse protected data-key rotation and must not infer approval from an environment or command flag. Heimdal archive-pass is also protected because it encrypts an existing archive volume.

## Fixed constraints

1. The active identity is shared/<logical-secret> for openai.api-key, anthropic.api-key, github.token, and discord.webhook, and <channel>/<logical-secret> for heimdal.raw-store-key, heimdal.archive-pass, and postgres.password. The shared identities are the narrow exception to per-channel value separation approved by the owner in #5667: each externally issued provider value is mirrored in prod and non-prod, so a non-prod project reader can retrieve the same provider value used by prod. No other secret uses a shared identity. BWS import updates the store only and does not create or rotate provider credentials.
2. Consumer grants remain code-enforced environment bindings. BWS item identity is not a per-consumer authorization mechanism.
3. Project selection is fixed: dev and test use non-prod; prod uses prod. Read-only machine accounts are project-scoped. A non-prod request must not reach the prod project.
4. Linux selects BWS explicitly and fails closed if BWS is unavailable. It never falls back to macOS Keychain. Mac-hosted processes keep using Keychain.
5. A secret check takes the exact consumer set selected for the requested runtime/deploy operation and evaluates only those consumers' declared bindings. An absent optional binding may be skipped; every present selected value must pass its grammar, including optional values. An inactive consumer is not checked and does not block an unrelated deploy. A missing required binding, malformed present value, or divergent selected shared value fails. Failures name logical identifiers and status only.
6. Secret values and machine-account tokens do not appear in argv, stdout, stderr, shell traces, rendered Compose output, admin/deploy orchestrator environments, logs, receipts, Git, BuilderOps, or iCloud. Runtime exposure follows the existing per-consumer contract. PostgreSQL passwords are not placed in Compose values, the deploy orchestrator environment, or application environments. Governed-channel `DATABASE_URL` and `DB_DSN` overrides must be credential-free: reject a URI password or keyword-DSN `password` value before it enters Compose or an application environment. Credential-free overrides may supply non-secret connection fields; the PostgreSQL password still comes from the file-backed secret. On every startup, including for an initialized data directory, the official PostgreSQL entrypoint reads POSTGRES_PASSWORD_FILE into its own short-lived startup environment before checking initialization state, then unsets its POSTGRES_ variables before starting the database server.
7. BWS read responses can contain secret values. The reader may hold a response in memory only long enough to select, validate, or compare values for the requested consumers; it emits no raw provider response.
8. Admin writes use an authenticated request-body interface. Import accepts an externally issued or already-active value only from standard input; it never places the value in argv or echoes it. The BWS CLI create/edit syntax places values in argv and default responses include values, so those forms do not meet this contract. BWS import does not create, revoke, or claim to rotate a provider-side credential; issuer-side rollout and overlap remain external operations.
9. Admin writes preserve the prior value in append-only version history before changing the active value. Generation and rotation are allowed only for identities in an explicit closed BWS-owned allowlist; external provider credentials and protected Heimdal keys are never generated or rotated by these commands. A shared import archives both prior copies, then applies the one stdin value to both projects. BWS has no cross-project transaction: on partial write failure the command compensates changed copies, returns failure, and a later value-free check reports any remaining divergence and blocks deploy preflight until parity is restored. No task deletes historical values automatically.
10. Rotation or deletion of protected Heimdal data-encryption secrets remains blocked until #5667 records an owner decision and an approved behavior is specified. The PostgreSQL password must match the existing initialized database role: importing its current value is allowed, but changing the BWS item alone does not rotate that role. PostgreSQL password rotation on an initialized data directory requires a separate coordinated database-role cutover contract.
11. The PostgreSQL Compose secret source is an owner-only, mode-0600 file on a root-only runtime filesystem. Local Compose secrets are mounted from the declared host file source ([Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)). It remains present for as long as any consuming container may restart or be recreated. A managed host lifecycle rehydrates it before every Compose start/recreate and after host boot, and removes it only after all consumers stop. Docker must not independently restart a consumer before rehydration. The source path is excluded from Git and cleanup receipts.
12. BWS plan limits are hard constraints: two projects and three machine accounts. Exceeding them is a design change requiring owner approval.
13. Live BWS setup, VM token installation, host cleanup, and channel qualification are operator actions. Repository tests and CI do not claim those actions occurred.

## Specification delivery

The capability specification and issue traceability are delivered by BWS-00 / #5682. Its PR closes only that documentation task. Parent #5667 remains open, and BWS-01 through BWS-04 remain blocked until the specification PR merges and each child passes strict readiness validation.

## Task order

| Order | Task | ID | Prerequisite | Outcome |
| --- | --- | --- | --- | --- |
| 1 | Resolve BWS channel secrets (#5677) | BWS-01 | — | BWS lookup, active-name mapping, explicit backend selection, preserved Keychain adapter |
| 2 | Administer secrets value-free (#5678) | BWS-02 | BWS-01 | consumer-scoped checks, safe stdin import, closed generation/rotation allowlist, append-only history and shared-copy parity |
| 3 | Install VM secret tokens (#5679) | BWS-03 | BWS-01 | encrypted systemd credential handoff for the selected VM reader |
| 4 | Deploy PostgreSQL with Compose secrets (#5680) | BWS-04 | BWS-01, BWS-02 | pre-mutation check, password-file database/Compose wiring, final owner-doc writeback, parent acceptance handoff |
| Decision gate | Production data-key rotation | #5667 owner answer | owner decision | Do not create an implementation issue until the raw-store and archive-pass policy is recorded |

Each implementation task is an independent non-trivial issue-agent context and is run serially in the listed order. BWS-03 has no source dependency on BWS-02, but serial execution is selected to keep credential changes and review evidence easy to audit.

## Cross-task invariants / interaction safety

- INV-BWS-1 — channel isolation: dev/test lookup is constrained to the non-prod project and prod lookup is constrained to prod. A failed or unknown channel resolves no project and never falls back.
- INV-BWS-2 — consumer minimization: the code contract decides which logical bindings a consumer can receive. BWS project access is a coarse outer boundary, not a substitute for the allowlist.
- INV-BWS-3 — value non-disclosure: tests assert successful and failing paths do not emit a canary value through output, logs, exceptions, argv, Compose configuration, or receipts.
- INV-BWS-4 — history before activation: admin import or allowed rotation first persists prior values to immutable history, then updates the active identity. Shared writes archive both project copies and apply one value to both. If history creation fails, no active copy changes. If an update fails after another copy changes, the command compensates changed copies and returns failure; if compensation also fails, the next value-free check detects divergence and deploy preflight remains blocked until parity is restored.
- INV-BWS-5 — preflight before mutation: the agent-host deployment controller uses its Keychain-backed admin identity to check parity for shared values relevant to the selected deployment before dispatching remote mutation. It does not install the admin token on a VM. The VM reader then checks only its own project's selected consumer set before Compose. A later local recheck closes the check/use gap.
- INV-BWS-6 — mounted file lifecycle: the PostgreSQL secret source remains owner-only on runtime storage throughout the lifecycle of any container that mounts it. The host lifecycle manager rehydrates before start/restart/recreate and cleans up only after all consumers stop; Compose returning is not a cleanup boundary.
- INV-BWS-7 — protected-key hold: while the owner decision is open, protected production-key changes are refused. A partial admin operation cannot change the active value before the policy gate.
- INV-BWS-8 — repository/live separation: a passing fake-provider test proves code behavior only. It does not assert that BWS accounts exist, tokens are installed, or a VM is healthy.
- INV-BWS-9 — shared-copy parity: the authorized agent-host admin check verifies relevant shared-secret values match in prod and non-prod without emitting either value. Project-scoped VM readers never access the peer project. Writes use one imported value for both copies; partial failures are compensated or detected as divergence, and deployment fails while divergence remains.
- INV-BWS-10 — consumer applicability: only required bindings for consumers selected by the deployment plan can block that operation. Optional or inactive model-provider credentials remain unprovisioned without blocking unrelated deployment; present malformed values still fail closed when their consumer is selected.

Partial failure paths must preserve these invariants. If history creation succeeds but active update fails, retain the extra immutable history record and report a redacted failure. For mirrored shared secrets, compensate a project copy already updated if its peer update fails; if compensation cannot restore parity, report a redacted divergence and make value-free check fail until an authorized stdin import restores both copies. If a deploy check succeeds but the later Compose lookup fails, stop before the next deploy mutation; retain any runtime source needed by active consumers and clean it only after they have stopped. If token encryption or transfer fails, keep the prior VM credential in place and never write the new token in plaintext to a durable host path.

## Capability acceptance

- [ ] Linux BWS and Mac Keychain resolve through the explicit provider seam with the correct active identity, project, and consumer allowlist.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_bws_lookup_uses_scoped_active_identity`
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_keychain_backend_remains_available_and_backend_failure_is_redacted`
- [ ] Secret checks evaluate only selected consumers, permit absent optional and inactive credentials, and reject missing required bindings, any present malformed selected value, or divergent relevant values before remote deploy mutation.
      Verify: `tests/ops/test_secret_admin.py::test_check_scopes_required_set_to_selected_consumers`
      Verify: `tests/ops/test_secret_admin.py::test_inactive_optional_provider_credentials_do_not_block_check`
      Verify: `tests/ops/test_secret_admin.py::test_malformed_optional_provider_credential_blocks_check`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_admin_parity_preflight_precedes_remote_deploy_mutation`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_vm_reader_recheck_is_project_scoped_and_precedes_compose`
- [ ] External credentials are imported from stdin without disclosure; generation and rotation enforce the closed BWS-owned allowlist and preserve prior versions.
      Verify: `tests/ops/test_secret_admin.py::test_external_identity_imports_from_stdin_without_value_disclosure`
      Verify: `tests/ops/test_secret_admin.py::test_generation_and_rotation_reject_external_and_protected_identities`
      Verify: `tests/ops/test_secret_admin.py::test_rotation_archives_prior_value_before_update`
- [ ] VM reader tokens are encrypted with systemd-creds and never exposed through argv or receipts.
      Verify: `tests/deploy/test_secret_token_push.py::test_push_token_encrypts_stdin_and_redacts_token`
- [ ] PostgreSQL receives its already-active role credential through a file-backed Compose secret; password-bearing direct DSNs are rejected, credential-free direct DSNs still use the file-backed password, and changing POSTGRES_PASSWORD_FILE alone never claims to rotate an initialized database role.
      Verify: `tests/ops/test_runtime_database_config.py::test_database_password_file_is_resolved_without_environment_value`
      Verify: `tests/ops/test_runtime_database_config.py::test_password_bearing_direct_dsn_override_is_rejected_without_value_disclosure`
      Verify: `tests/ops/test_runtime_database_config.py::test_credential_free_direct_dsn_uses_password_file`
      Verify: `tests/deploy/test_deploy_channel.py::test_postgres_server_process_environment_omits_password`
      Verify: `tests/deploy/test_deploy_channel.py::test_rendered_compose_uses_postgres_secret_file_without_value`
      Verify: `tests/deploy/test_deploy_channel.py::test_initialized_database_role_is_not_changed_by_password_file`
- [ ] The Compose secret source survives consumer restart/recreate and is rehydrated before host-boot startup, then is removed after all consumers stop.
      Verify: `tests/deploy/test_deploy_channel.py::test_compose_secret_source_lifecycle_covers_restart_recreate_and_boot`
- [ ] The raw-store-key/archive-pass owner decision is recorded before their production rotation or deletion behavior is implemented.
      Verify: doc writeback at `docs/CLOUD_SECRET_PROVISIONING/README.md :: Current status`
- [ ] Owner docs describe repository support and preserve the outstanding live qualification gate.
      Verify: `docs/LOCAL_SECRET_PROVISIONING/README.md :: Linux Bitwarden Secrets Manager`
      Verify: `docs/SECURITY.md :: Secrets in CI`
      Verify: `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Linux channel secret provisioning`

## Relationship to GitHub issues

Parent validation hub: #5667. Specification delivery is tracked by #5682. Child implementation issues are filed from these task files while the specification PR is open, remain blocked until it merges, and have their issue numbers written into task frontmatter in that same PR. Post-merge task receipts and integrated repository acceptance evidence live on #5667. Live account setup and host qualification remain a separate operator gate.

## Related docs

- docs/LOCAL_SECRET_PROVISIONING/README.md
- docs/SECURITY.md
- docs/ENVIRONMENTS.md
- docs/RELEASE_CHANNELS/README.md
- docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md
- docs/architecture/SBS_OPERATING_MODEL.md
- docs/HEIMDAL/FABLE_COMPANION.md
