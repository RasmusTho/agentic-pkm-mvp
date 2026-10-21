State: Delivered capability contract and repository slices BWS-01 through BWS-04; parent #5667 remains open for integrated acceptance and full live DEV/TEST/PROD deployment/runtime qualification.
Doc role: Linux cloud secret provisioning capability specification
Authority: This directory owns the BWS Linux channel-secret contract. It is subordinate to docs/SECURITY.md, docs/ENVIRONMENTS.md, docs/RELEASE_CHANNELS/README.md, docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md, and the consumer owner docs.
Owner: Yggdrasil Platform and Operations, with Product/Runtime and Builder System boundary review
Temporal class: strategic
Review cadence: after a task merge, BWS account/topology change, or live channel qualification
Source of truth: this directory for target behavior; issue #5667 is the delivery and acceptance hub
Last reviewed: 2026-10-21 (bounded TypeSafe DEV acceptance writeback; broader channel acceptance unchanged)
Last verified against: merged PRs #5683, #5703, #5717, #5725, #5732, #5734, and #6015; #5667 comments #6114638077, #6114724380, and #6114787299. These verify repository delivery, current Free-plan entitlement, both reader scopes, active encrypted reader services on all three channel VMs, the MARR non-prod binding, and the accepted normal-writer model; full integrated channel acceptance remains open.

# Cloud Secret Provisioning

## Outcome

Provide Linux channel VMs with centrally administered Bitwarden Secrets Manager (BWS) secrets, and resolve the MARR TypeSafe provider key from the existing non-prod BWS project through the MARR-only consumer binding. Preserve macOS Keychain for existing Mac-hosted secrets and as the bootstrap store for the non-prod BWS reader token. Keep channel and consumer grants explicit and fail closed before runtime or deployment mutations. Secret values and machine-account tokens stay out of command arguments, output, logs, receipts, Git, BuilderOps records, iCloud, and admin/deploy orchestrator environments. Values reach runtime consumers only through their declared owner-controlled handoff; PostgreSQL credentials use file-backed Compose secrets.

The 2026-09-24 owner decision in #5667 selects BWS, two channel projects named prod and non-prod, and three machine accounts: non-prod-reader, prod-reader, and admin. The admin token remains in the agent host Keychain. Owner direction on 2026-10-07 removes the additional MARR-only project and account requirement for the one-operator rollout. The existing two-project topology remains the store and routing boundary. This specification does not itself provision those objects; current live evidence is recorded separately on #5667.

This is boundary work. Yggdrasil Platform and Operations owns Linux host and Compose lifecycle. Product/Runtime owners retain authority over Heimdal key semantics, database use, and the MARR runtime boundary. Capability owns the TypeSafe judgment contract; Builder System tooling may administer secrets through the approved admin identity, but it does not become a secret store or runtime authority.

## Current status

The repository implements the preserved Mac Keychain path and all four BWS slices: scoped Linux lookup (#5677 / PR #5703), value-free administration (#5678 / PR #5717), encrypted reader-token installation (#5679 / PR #5732), and PostgreSQL file-secret deployment (#5680 / PR #5725). The 2026-10-11 value-free live receipt on #5667 (#6114638077) confirms the Free-plan entitlement, both existing read-only accounts' access to both projects, active repository-managed encrypted reader services and matching receipts on ygg-dev, ygg-test, and ygg-prod, and the exact `dev/typesafe.api-key` import plus current-main `marr-server-dev` check. The follow-up receipt (#6114724380) records retirement of the unused generic VM helper and extra shared reader-token file. The separate decision receipt (#6114787299) accepts Demerzel Keychain custody and `scripts/secrets` as the sole supported normal writer, with deliberate same-user bearer use as an accepted residual; no additional daemon or shared fencing is required for this one-owner setup.

Parent #5667 remains open. Its complete target/action-bound DEV/TEST/PROD deployment/runtime acceptance has not been established by the component receipts above. A consolidated parent receipt must bind the required behavior to the authorized target and action for each channel. The Oct7 receipt covers one DEV deployment only; the Oct13 Karakeep receipt covers Karakeep in DEV/TEST only. Neither supplies the full cloud-secret deployment/runtime acceptance. Any first-initialization action still requires the deployment owner's local qualification file and action-time authority. Existing-host credential cleanup remains a separate operator migration; repository delivery alone does not establish that cleanup.

Native source-backed Product recovery (#5918) runs inside BWS-04's existing activation and API
consumer context, while the ordinary runtime writers are stopped. It uses the selected candidate
image, API bootstrap and PostgreSQL password file; no retired secret alias, new consumer grant,
credential copy or entrypoint override is added. Consumer handles remain owned by the synchronous
activation, and operation-bound one-shot quiescence is required before recovery or retirement.
The deployment owner document defines the finite timeout and strict source/readiness/index gates.
This repository support does not establish live BWS or Product acceptance.

The delegated policy decision recorded on #5667 (#5868385351) defers production `heimdal.raw-store-key` rotation or deletion until a bounded rekey path is delivered. Keep the current key active and refuse protected writes: the current raw record format has one configured AES key and no key identifier or multi-key read path, so changing it could make earlier ciphertext unreadable. Heimdal `archive-pass` remains separately protected pending its own lifecycle policy.

The [2026-10-11 owner receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-6114787299) accepts the normal-writer boundary for this one-owner setup. Broader BWS deployment/runtime qualification remains open. A Product deployment explicitly run with `--existing-secrets-only` may read and validate existing selected values without the write-qualification file; it must stop before RPC when the required PostgreSQL password is missing and must never call the BWS writer. Bootstrap still requires the existing local qualification receipt described by the deployment owner; this documentation reconciliation does not install it.

## Accepted normal writer for single-operator recovery (Issue #5667)

The owner accepted Demerzel host custody plus one supported normal writer on 2026-10-11,
superseding the executable-confinement/fencing interpretation in the earlier #5855 proposal.

- The only active admin machine-account token is held in Demerzel's login Keychain; no admin token
  is installed on the VMs. `scripts/secrets` is the sole supported normal writer on Demerzel,
  using the host-secret controller and coordinated deployment path. The legacy direct writer
  refuses write modes; the generic VM helper and its extra reader-token file are retired from the
  normal path, while active channel-specific encrypted reader credentials remain.
- The human Bitwarden Organization Owner retains break-glass rights. VM reader accounts remain
  read-only; this decision grants no new consumer or store permissions.
- Deliberate same-user code on Demerzel can retrieve the bearer and call BWS outside the controller.
  This is a documented accepted residual, not process-level isolation or externally fenced parity.
  No separate writer daemon or shared fencing layer is required for this setup. Reassess before
  adding another operator/controller or placing prod secrets requiring confidentiality in this
  organization.
- The host-local lock serializes cooperating entrypoints only. It cannot fence direct bearer use,
  another host, retained human administration, or an already-sent provider request. Supported
  operations retain selected-channel/consumer checks, parity, durable history, operation IDs and
  terminal receipts. Unknown provider outcomes remain pending and fail closed. After an out-of-band
  write, re-establish selected-value parity and operation terminality before supported work resumes;
  the controller cannot prevent or observe every deliberate bypass.

The owner receipt resolves only the normal-writer decision. It does not close #5667's broader
deployment/runtime acceptance or #5764's Product/Builder one-shot acceptance. Repository tests
and this docs change do not qualify live channels, install local approval files or authorize secret,
permission or deployment changes.

## Fixed constraints

1. The active identity is shared/<logical-secret> for openai.api-key, anthropic.api-key, github.token, and discord.webhook, and <channel>/<logical-secret> for heimdal.raw-store-key, heimdal.archive-pass, postgres.password, and the MARR-only `dev/typesafe.api-key`. The shared identities are the narrow exception to per-channel value separation approved by the owner in #5667: each externally issued provider value is mirrored in prod and non-prod, so either read-only channel account may retrieve the approved copy. `typesafe.api-key` remains available only to the `dev/marr-server-dev` consumer in code and resolves from the existing non-prod project through the existing non-prod reader identity; both reader identities may have broader store-level access under the accepted one-operator policy. The supported normal admin writer reads pre-state and writes through the designated Demerzel controller; the accepted same-user bearer residual is defined in Fixed constraint 14. The separate direct-agent #5778 path and its reported pre-existing local-helper BWS item do not grant a runtime consumer binding. Product and Builder callers receive no provider key. No other secret uses a shared identity. BWS import updates the store only and does not create or rotate provider credentials.
2. Existing consumer grants remain code-enforced environment bindings. BWS item identity is not per-consumer authorization. The MARR provider-key binding is valid only for `dev/marr-server-dev` through the existing non-prod project and reader identity; missing, malformed, wrong-host, wrong-channel, or undeclared-consumer bindings fail closed before provider dispatch. The accepted broader read scope does not grant a consumer another consumer's key. The only other additional non-environment BWS route is required, channel-scoped `postgres.password` delivered as a file, with non-secret `POSTGRES_PASSWORD_FILE` for Compose `db` and `DATABASE_PASSWORD_FILE` for the five application/migration services; no password environment binding is added. The closed database map remains `postgres-db` -> `db`, `postgres-migrate` -> `migrate`, `postgres-api` -> `api`, `postgres-worker` -> `worker`, `postgres-watcher` -> `watcher`, and `postgres-capture-watch` -> `heimdal-capture-watch`, for dev/test/prod only. Normal database deploys require the selected password before any remote deployment-state mutation and recheck it on the VM before local mutation and Compose. The explicit first-initialization exception is defined in Fixed constraint 15.
3. Channel project selection is fixed: dev and test use non-prod; prod uses prod. The MARR provider key uses the dev identity in non-prod and remains restricted in code to `dev/marr-server-dev`. The existing non-prod-reader and prod-reader accounts are read-only store identities; their broader project scope is an accepted one-operator BWS risk and does not change channel lookup selection or the consumer allowlist.
4. Linux selects BWS explicitly for BWS-managed bindings and fails closed if BWS is unavailable. It never falls back to macOS Keychain. Mac-hosted processes keep using Keychain for their existing secrets and for the MARR BWS bootstrap token; the TypeSafe provider key is read from BWS only by the MARR server and has no Keychain fallback.
5. A secret check takes the exact consumer set selected for the requested runtime/deploy operation and evaluates only those consumers' declared bindings. An absent optional binding may be skipped; every present selected value must pass its grammar, including optional values. The API ingress may omit the raw-store key and report its media/screen lanes unavailable. Capture-watch is selected only when its VM runtime path is configured; raw-migration is selected only when the target migration delta contains the raw-representation migration. A missing key for active capture-watch fails before mutation. The migration consumer may omit the key so HAR-02 can decide under its source-table lock: an empty table migrates without it, while rows with no valid key roll back without committing schema or legacy-byte changes. A present malformed value or divergent selected shared value still fails before migration. An inactive consumer is not checked and does not block an unrelated deploy. Failures name logical identifiers and status only.
6. Secret values and machine-account tokens do not appear in argv, stdout, stderr, shell traces, rendered Compose output, admin/deploy orchestrator environments, logs, receipts, Git, BuilderOps, or iCloud. Runtime exposure follows the existing per-consumer contract. PostgreSQL passwords are not placed in Compose values, the deploy orchestrator environment, application environments, or PostgreSQL server-process environments. Governed-channel `DATABASE_URL` and `DB_DSN` overrides must be credential-free: reject a URI password or keyword-DSN `password` value before it enters Compose or an application environment. Credential-free overrides may supply non-secret connection fields; the PostgreSQL password still comes from the file-backed secret. On every startup, including for an initialized data directory, the official PostgreSQL entrypoint reads POSTGRES_PASSWORD_FILE into its own short-lived startup shell before checking initialization state. On an empty data directory, the upstream entrypoint starts a temporary initialization server through `pg_ctl` before its final POSTGRES_ cleanup; BWS-04 must scrub `POSTGRES_PASSWORD` and `PGPASSWORD` from the `pg_ctl` child environment and separately scrub both from the shell environment immediately before the final steady-state `exec` on every startup path, including initialized data. Only the short-lived entrypoint or initialization-client access needed to initialize the role may retain the value. The VM-side BWS reader runs under a repository-managed systemd unit or drop-in with `LoadCredentialEncrypted=bws-machine-account-token:<encrypted-current-source>` and `BWS_ACCESS_TOKEN_FILE=%d/bws-machine-account-token`; the runtime path is `$CREDENTIALS_DIRECTORY/bws-machine-account-token`. BWS-01 reads the token from that file only, never from a token-valued environment variable. A missing or unreadable credential fails before a provider request or deploy mutation. BWS-03 installs the encrypted source atomically and does not modify a live unit.
7. BWS read responses can contain secret values. The reader may hold a response in memory only long enough to select, validate, or compare values for the requested consumers; it emits no raw provider response.
8. Admin writes use an authenticated request-body interface. Import accepts an externally issued or already-active value only from standard input; it never places the value in argv or echoes it. The BWS CLI create/edit syntax places values in argv and default responses include values, so those forms do not meet this contract. BWS import does not create, revoke, or claim to rotate a provider-side credential; issuer-side rollout and overlap remain external operations.
9. Admin writes persist both target project pre-states before changing either shared copy: snapshot a present value or append a value-free `previous_state=absent` tombstone for an absent copy. The protected local append-only history backend is chosen by BWS-02, but a history write counts as durable only after its flush/fsync-equivalent commit returns. Each paired operation has a non-secret operation ID and a durable prepared record before the first BWS write. Put a machine-readable non-secret operation marker in each BWS item note while preserving owner note text; the marker correlates a successful write but is not an idempotency or fencing token. A provider success/matching marker proves that target applied; only a typed response guaranteed to reject before commit proves no effect. A lost acknowledgment, process death after send, absent marker, mismatched readback, or unavailable readback is indeterminate and does not prove the request cannot still land. While any send is indeterminate, keep the journal pending and do not compensate, retry, start a fresh import, check selected BWS values, or deploy. If BWS exposes no authoritative terminal status for that request, remain blocked; do not invent one from a missing marker or local timeout. After every sent request has an authoritative terminal result, append a terminal history record; compensate only confirmed committed targets to their recorded pre-state under the same exclusive lock, or reconcile a shared import with a fresh stdin value and current-state snapshots/tombstones. Never replay stale compensation over a later import. Other operation kinds use their own durable matching-receipt contracts: token push remote journal, empty-database bootstrap item metadata plus terminal provider outcome, or deploy remote journal. Checks and deploys fail closed until a matching terminal receipt is durable. No task deletes history automatically.
10. Production `heimdal.raw-store-key` rotation or deletion remains refused until a bounded rekey path is delivered, under the delegated safe-hold decision recorded in #5667 comment #5868385351. `archive-pass` remains protected pending its separate lifecycle policy. The PostgreSQL password must match the existing initialized database role: importing its current value is allowed, but changing the BWS item alone does not rotate that role. PostgreSQL password rotation on an initialized data directory requires a separate coordinated database-role cutover contract.
11. For an initialized database, after both secret preflights pass under the host and VM locks, prove the candidate with a real password-authenticated connection to the active role. A stopped database may be started only as a supervised, same-ID PostgreSQL-only `--no-deps` probe: durably record `authenticating` before starting `db`, including its possible recovery/WAL writes. Never activate/recreate migration or application clients before authentication succeeds. On failure preserve a pre-existing running database; stop only a database this operation started, and record `aborted` only after verified quiescence. Otherwise remain pending. `pg_isready`, trust/peer authentication, matching BWS copies, and container startup are not password proof. The PostgreSQL password file is root-owned with mode `0440` and the configured database-client primary GID (`LOCAL_GID`); its parent tmpfs directory is root-only (`0700`). This gives the configured non-root application and migration UID/GID read access without granting host users directory traversal or world access. Grant the file-backed Compose secret only to PostgreSQL and the selected database clients. Local file-backed Compose secrets are bind mounts: Compose ignores secret `uid`, `gid`, and `mode` overrides, so prepare the source file's ownership and mode before mounting it ([Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/), [Compose service secret attributes](https://docs.docker.com/reference/compose-file/services/)). Keep the source present while any consuming container may restart or be recreated; a managed host lifecycle rehydrates it before every Compose start/recreate and after host boot, and removes it only after all consumers stop. Docker must not restart a consumer before rehydration. Exclude the source path from Git and cleanup receipts.
12. The existing Linux channel topology remains two projects and three machine accounts. The MARR TypeSafe binding uses that existing topology and adds no project or account requirement. Current entitlement, reader grants, MARR binding, and VM credential status are qualified in the #5667 receipts cited above; future BWS administration or permission changes remain separate operator actions. No paid-plan or subscription change is authorized by this contract.
13. Repository tests and CI do not prove live BWS setup, token installation, host cleanup, or channel qualification. The cited #5667 receipts verify the specific entitlement, reader, MARR, encrypted VM-token, and retired-helper facts they record, but not complete target/action-bound DEV/TEST/PROD deployment/runtime acceptance. The TypeSafe binding uses fake sources in repository verification; live use separately follows the accepted normal-writer model in Fixed constraint 14 and requires the scoped MARR dev host installation, the already authorized one-call-per-caller dev acceptance with synthetic input, and redacted Product/Builder receipts on #5764. The separate actual DEV receipts are now verified under [TypeSafe development host acceptance](../TYPESAFE_SYSTEM_ONE/README.md#typesafe-development-host-acceptance). Both allowances are consumed; ordinary routes remain disabled, and broader #5667 channel acceptance and TEST/PROD activation retain their separate gates.
14. All supported BWS checks, admin writes, reader-token pushes, and channel deploy dispatches run through the designated Demerzel controller and a stable owner-only local operation lock outside Git/iCloud. The 2026-10-11 owner receipt accepts Demerzel login Keychain custody plus `scripts/secrets` as the sole supported normal writer, with human Organization Owner break-glass and read-only VM accounts. Deliberate same-user bearer use outside the controller is an accepted residual; the credential is not executably confined. No separate writer daemon or shared/distributed fencing is required for this one-owner setup. Reassess before extra operators/controllers or prod secrets requiring confidentiality. The local lock serializes cooperating entrypoints only, not direct bearer use or already-sent provider requests; do not claim externally fenced parity or full live qualification. Bootstrap retains the local qualification receipt requirement documented by the deployment owner. A Product deployment explicitly run with `--existing-secrets-only` may use existing selected values without this write-qualification gate; the host refuses a missing password before RPC and durably binds this mode to the deployment operation before the first RPC. This does not claim global fencing or complete BWS qualification. Lock order is agent-host operation lock first, then VM per-channel mutation lock; never acquire them in reverse. Persist a value-free operation ID, operation kind, target, and stage before external mutation; retain it until a matching terminal receipt is durable. After interruption, recovery must match the journaled operation ID to an authoritative terminal outcome: shared BWS import remains pending on an indeterminate provider send; token push and deploy require durable remote journal receipts; bootstrap also checks the locked empty directory and operation marker. A deploy worker on the VM, supervised independently of SSH, owns the remote lock through Compose completion and receipt write. Its durable stages are `prepared`, `preflighted`, `materialized`, optional `authenticating`, `activating`, then `committed` or `aborted`; `authenticating` precedes DB-only startup and `activating` precedes application Compose activation. A separate value-free request record binds the same ID to its channel, revision, consumer/service set, and bootstrap mode before the worker is prepared; a changed request cannot reuse a terminal receipt. Reconnect joins the same operation ID. If that worker ends without a receipt, a new worker cannot reconcile/admit work until the old worker/subprocess is gone and affected Compose/Docker resources are quiescent; if quiescence is unknown, remain pending. A VM lock snapshot or local lock release alone is not terminal proof.
15. Normal deploys require `postgres.password` to be present before any remote deployment-state mutation. The only absent-password exception is BWS-04 first initialization: under the agent-host operation lock, check all other selected identities, acquire the VM per-channel lock as a coordination-only action, and inspect the actual database data directory under that lock. If it is not empty, release the lock and fail without creating a BWS password or changing deployment state. If it is empty, BWS-04 alone may generate and persist one password after BWS-02 has durably recorded the value-free absence tombstone and prepared operation ID. Include that ID in non-secret BWS item metadata, read the item back, and verify it before any deployment-state mutation; then recheck it on the VM before local mutation and Compose. If interrupted after a create may have reached BWS, the same operation ID remains pending. A retry rechecks emptiness and reads the BWS item; exactly one matching item is read and reused. An absent or ambiguous readback leaves the operation indeterminate and must not trigger another create without authoritative proof the prior request did not commit. It does not silently start a new bootstrap operation or replace an existing item. An initialized database with a missing item must import its current role value and cannot use bootstrap.

16. The only direct runtime BWS consumer outside the Linux channel reader contract is `marr-server-dev`. It resolves `dev/typesafe.api-key` from non-prod through the existing `non-prod-reader` identity; its token is held in the MARR host Keychain and used in process memory. Product and Builder callers still receive neither the provider key nor the reader token, and the code-level MARR consumer binding remains mandatory. The accepted #5667 normal-writer model in Fixed constraint 14 governs BWS administration; the accepted broader read scope does not authorize a consumer or agent to use another binding.

## BOB-1 DevUI GitHub token

The separate Builder System binding is `bob-1/devui.github-token` in the existing
`non-prod` project. It is administered on Demerzel through `scripts/secrets devui`.
It is never an alias or mirror of `shared/github.token`, and it grants no Product
channel consumer access. This closed binding lives in `app/ops/bws_secret_admin.py`;
the existing Product channel and reader-token registries remain unchanged. BOB-1
receives neither a BWS machine-account token nor an administrator token.

Regenerate the existing GitHub credential `bob-1-devui-read-2026-09` with its
existing selected repository and read-only permissions. Do not substitute another
consumer's credential or increase its grants. BWS import changes only the stored
value; it cannot create, restrict, or inspect GitHub's fine-grained token permissions.
The operator must preserve those settings when regenerating the credential.

From an up-to-date checkout on Demerzel, using the existing Python environment
with `bitwarden-sdk` installed (for example, the operator checkout's
`.venv/bin/python`):

```bash
python scripts/secrets devui preflight
python scripts/secrets devui rotate
```

`rotate` first checks BWS and the actual DevUI binding, then prompts through the
local terminal with echo disabled. Paste the regenerated token only at that hidden
prompt. It refuses a terminal that cannot disable echo. No token is placed in a
shell command, process argument, environment, transcript, or temporary input file.
An automation that already owns a protected input stream may instead use
`devui import --stdin`, followed by `devui apply`; never use `echo TOKEN`, a shell
variable, or a here-document containing the token.

The import uses the existing Demerzel Keychain administrator, host-controller lock,
protected append-only secret history, and unknown-provider-outcome rules. Apply
resolves only this BWS item under the same controller lock and sends its value over
standard input through `bob-1-builder-system` with noninteractive `sudo`. No VM
password or interactive VM login is needed. The fixed receiver checks the dedicated
`/run/docker-builderops.sock` engine, the running `builderops-devui-devui-1`
container, its repository, absence of token environment overrides, and its read-only
directory mount before writing. It atomically replaces only the active account's
two `oauth_token` entries in `/opt/builderops/devui-gh/hosts.yml`, preserving its
root ownership, group, mode `0640`, other accounts, and other hosts. The directory
bind mount sees the replacement without a container restart.

Before replacement, the candidate must pass repository, Issues, PRs, branches, and
commit-status GET requests. After replacement, those reads run through `gh` inside
the same actual DevUI container. A failed container read restores the previous file.
The value-free terminal receipt is written durably under
`/opt/builderops/receipts/devui-github-token-<operation-id>.json` and read back over
SSH before the host controller marks the operation terminal. Success proves those
reads, not the absence of extra permissions on the externally issued token.

Use `scripts/secrets devui check` for BWS presence without value output. If SSH
acknowledgement is lost, run `scripts/secrets devui reconcile`: it reads the exact
pending operation's durable remote receipt without resending the token. If no
terminal receipt exists, admission remains pending; do not clear the journal or
repeat import/apply to bypass it. Investigate the bounded operation on BOB-1 before
recovery. Unknown BWS writes retain the existing stricter import recovery rules.

This procedure changes no other GitHub token, runtime image, Compose configuration,
Product channel, or BWS reader permission. Live rotation evidence belongs in the
operation receipt and delivery PR, separately from broader #5667 acceptance.

## Specification delivery

The capability specification and issue traceability were delivered by BWS-00 / #5682 / PR #5683. All repository children are delivered: BWS-01 #5677 / PR #5703, BWS-02 #5678 / PR #5717, BWS-03 #5679 / PR #5732, and BWS-04 #5680 / PR #5725. The parent remains open for integrated acceptance and full live deployment/runtime qualification; the specific BWS, reader-token, MARR, and normal-writer evidence is recorded in #5667 comments #6114638077, #6114724380, and #6114787299.

## Task order

| Order | Task | ID | Prerequisite | Outcome |
| --- | --- | --- | --- | --- |
| 1 | Resolve BWS channel secrets (#5677) | BWS-01 | — | explicit backend selection, preserved Keychain adapter, project-scoped reader, and shared agent-host operation lock/journal |
| 2 | Administer secrets value-free (#5678) | BWS-02 | BWS-01 | consumer-scoped checks, safe stdin import, durable paired history and crash recovery, shared-copy parity |
| 3 | Install VM secret tokens (#5679) | BWS-03 | BWS-01 | encrypted systemd credential handoff with atomic generation identity and ambiguous-outcome recovery |
| 4 | Deploy PostgreSQL with Compose secrets (#5680) | BWS-04 | BWS-01, BWS-02 | serialized preflight, locked empty-directory bootstrap, password-file database/Compose wiring, final owner-doc writeback |
| Decision gate | Protected production data-key rotation/deletion | #5667 | bounded rekey path for `heimdal.raw-store-key`; separate lifecycle policy for `archive-pass` | Keep the current raw-store key active and refuse writes until rekey is delivered; keep archive-pass protected |

Each implementation task is an independent non-trivial issue-agent context and is run serially in the listed order. BWS-03 has no source dependency on BWS-02, but serial execution is selected to keep credential changes and review evidence easy to audit.

## Cross-task invariants / interaction safety

- INV-BWS-1 — channel isolation: dev/test lookup is constrained to the non-prod project and prod lookup is constrained to prod. A failed or unknown channel resolves no project and never falls back.
- INV-BWS-2 — consumer minimization: the code contract decides which logical bindings a consumer can receive. BWS project access is a coarse outer boundary, not a substitute for the allowlist.
- INV-BWS-3 — value non-disclosure: tests assert successful and failing paths do not emit a canary value through output, logs, exceptions, argv, Compose configuration, or receipts.
- INV-BWS-4 — durable history before activation: BWS-02 writes a non-secret operation ID, both project pre-state snapshots/tombstones, and a prepared event to protected append-only history; the durable boundary is a completed flush/fsync-equivalent before any BWS value write. It appends a terminal record only after each sent provider request has an authoritative terminal outcome. An operation marker in an item note correlates success but does not fence or deduplicate a request. A lost acknowledgment, process death after send, missing/mismatched marker, or unavailable readback remains indeterminate: check/deploy stay blocked, and there is no compensation, retry, or fresh stdin import while the earlier request could still land. If the provider offers no authoritative terminal outcome, leave the operation pending. Once all sends are terminal, compensate only confirmed committed targets to a present snapshot or delete a previously absent copy, or reconcile with a fresh stdin import and current snapshots/tombstones. Other mutating operation kinds use their operation-specific journal/readback contracts in INV-BWS-15.
- INV-BWS-5 — serialized preflight and activation: every supported check, import, token push, and deploy uses the same exclusive agent-host operation lock. This local lock serializes cooperating entrypoints on one host only; it cannot fence another host, direct BWS client, or an already-sent provider request. A deploy holds it from before the host parity/selected-consumer check through the VM project-scoped recheck, secret materialization, and Compose activation receipt, so a cooperating admin import cannot interleave between parity check and use. Acquire this lock before the per-channel VM mutation lock. Fixed constraint 14 records the accepted Demerzel normal-writer model and its same-user residual; the lock does not prove global parity race closure or full live readiness. Direct VM bypass is unsupported. Pending operations after process/transport loss block new work until a matching durable terminal receipt; the project-only VM read alone is not a cross-project fence.
- INV-BWS-6 — mounted file lifecycle and access: the PostgreSQL password source is a root-owned `0440` file in a root-only `0700` tmpfs directory, with its group set to the configured database-client primary GID. The file-backed secret is mounted only into PostgreSQL and selected database clients; the actual non-root application/migration UID/GID can read it. Because file-backed Compose secrets are bind mounts and ignore `uid`/`gid`/`mode` remapping, enforce access through source-file metadata. The host lifecycle manager rehydrates before start/restart/recreate and cleans up only after all consumers stop; Compose returning is not a cleanup boundary.
- INV-BWS-7 — protected-key hold: production `heimdal.raw-store-key` rotation or deletion stays refused until a bounded rekey path is delivered; the delegated safe-hold decision is recorded in #5667 comment #5868385351. `archive-pass` remains separately protected pending its lifecycle policy. A partial admin operation cannot change the active value before its applicable gate.
- INV-BWS-8 — repository/live separation: a passing fake-provider test proves code behavior only. It does not assert that BWS accounts exist, tokens are installed, or a VM is healthy.
- INV-BWS-9 — shared-copy parity: the agent-host controller reads both copies under its local operation lock and verifies equality without disclosure. This lock coordinates only cooperating calls on that host. Use the accepted normal-writer model in Fixed constraint 14 for supported deployment parity checks, with the documented same-user residual; do not claim externally fenced parity. Reader identities may have peer-project store access under the accepted one-operator policy, but application lookup remains explicitly channel/project-selected and that store scope is not a consumer grant. Partial write, crash, or unknown provider outcome stays pending/divergent and blocks checks/deploy; a note marker or absent readback is not a provider fence.
- INV-BWS-10 — consumer applicability: only required bindings for consumers selected by the deployment plan can block that operation. The host checks database consumers and the API's degrade-visibly binding; the VM selects capture-watch and raw-migration from its runtime configuration and target migration delta before mutation. The API and raw-migration consumer may omit the raw-store key; HAR-02's locked transaction succeeds without it for an empty legacy table and rolls back without changing legacy schema or bytes when rows require a missing key. Active capture-watch still requires the key. Optional or inactive model-provider credentials remain unprovisioned without blocking unrelated deployment; present malformed values still fail closed when their consumer is selected.
- INV-BWS-11 — database resolver consistency: application configuration, Alembic migration setup, and direct DB clients such as Heimdal raw-store access use one file-aware database resolver. No client bypasses the password file by reading `DATABASE_URL`/`DB_DSN` directly; credential-free DSNs provide only non-secret connection fields, and password-bearing DSNs fail closed.
- INV-BWS-12 — VM token credential binding: the repository-managed systemd reader unit/drop-in loads encrypted credential `bws-machine-account-token` and exposes only the path `$CREDENTIALS_DIRECTORY/bws-machine-account-token` through `BWS_ACCESS_TOKEN_FILE`; BWS-01 reads that file and fails before provider access or mutation when it is absent or unreadable. BWS-03 installs the encrypted credential without claiming a live unit update.
- INV-BWS-13 — database secret identity and authority: `postgres.password` is required, channel-scoped, and file-delivered with no environment binding. The host contract enumerates exactly the six authorized consumer/service pairs in Fixed constraint 2. Normal selected services are checked before remote deployment-state mutation and rechecked before VM mutation/Compose. Only Fixed constraint 15 permits a missing value, and only after a locked empty-directory first-init inspection.
- INV-BWS-14 — absent-copy history: first provisioning and missing-copy recovery append a value-free `previous_state=absent` tombstone for each absent target project/logical identity before any shared copy is updated. Present copies are snapshotted; history failure blocks all writes.
- INV-BWS-15 — coordinated controller admission: a single agent-host operation lock serializes cooperating secret and deploy entrypoints on that host; it does not fence other hosts or direct BWS writers. The normal-writer decision in Fixed constraint 14 is accepted; broader live qualification remains separately required. The operation journal survives process loss and forces operation-ID-matched, durable terminal receipts before admission resumes. Unknown provider writes remain pending and fail-closed. VM token push and deploy use value-free durable remote journals with terminal `committed`/`aborted` receipts; a VM-side deploy supervisor owns the lock independent of SSH, and recovery joins the same ID or proves the old worker and affected Compose/Docker resources quiescent. Lock state alone is not a receipt.
- INV-BWS-16 — first PostgreSQL initialization: absent `postgres.password` is accepted only after BWS-04 holds the channel mutation lock and proves the selected data directory is empty; the absence tombstone and prepared operation ID are durable before the sole initial BWS write. Existing data with a missing password fails before deployment-state changes. A retry with that pending ID rechecks emptiness and reads/reuses exactly one item carrying the same non-secret operation ID; absent or ambiguous readback stays pending and never issues a second potentially duplicating create.

Partial failure paths must preserve these invariants. If a history write or either pre-state record fails, no BWS value changes. A shared import retains history if a value write fails; it may compensate a confirmed changed copy only after all sent requests have authoritative terminal outcomes. A process interruption or unknown provider response leaves a durable prepared operation; after restart, checks and deploy stay blocked, with no compensation, retry, or fresh import until terminality is proven. If the provider cannot supply authoritative terminality, the operation remains pending. After all sends are terminal, a fresh authorized stdin import may record current pre-states, apply one common requested value, verify parity, then close the old operation; it never applies stale rollback over a later import. Bootstrap recovery is distinct: BWS-04 rechecks emptiness under the VM lock and, with the same pending ID, reads the item carrying that operation ID; a possibly sent create with absent/ambiguous readback remains pending without another create. Deploy writes a value-free remote per-channel journal with `operation_id`, channel, operation kind, stage, and terminal result. Persist each stage atomically (write temp, flush/fsync file, rename, flush/fsync parent directory) in an owner-only persistent VM path outside the repo and tmpfs: `prepared`, `preflighted`, `materialized`, optional `authenticating`, `activating`, then `committed` or `aborted`. Persist `authenticating` before the sole DB-only cold-start probe, acknowledging recovery/WAL writes, and `activating` before requested application activation. Real password authentication must precede any new/recreated migration or application client; on failure preserve an already-running database, stop only a database started by the probe, and retain pending unless quiescence is proved. After successful activation, persist `committed`; that durable stage is the terminal receipt. Persist `aborted` only after confirming no deployment effect or completed rollback; its durable stage is the terminal receipt. A VM-side supervised worker keyed by operation ID holds the VM lock and is independent of SSH. Reconnect joins it. Recovery after worker loss proves no old worker/subprocess remains and no affected Compose/Docker transition is in progress before reconciling; if it cannot prove quiescence and terminal outcome, remain pending. The host clears its pending deploy operation only on a matching same-ID terminal receipt, never from lock release/snapshot alone. Token push likewise uses a durable remote same-ID journal/terminal receipt and per-channel lock; current-pointer readback without a terminal receipt is not sufficient to retry or report completion. A cooperating host lock alone does not prove executable confinement or externally fenced parity: Fixed constraint 14 records the accepted normal-writer boundary and residual; full live qualification remains separate. For normal DB deploy, missing required `postgres.password` fails before remote deployment-state mutation. First-init bootstrap is the sole exception in Fixed constraint 15. The VM recheck and lock-protected lifecycle preserve the selected file source through Compose activation and consumer restart/recreate; cleanup waits until every consumer stops.

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
- [ ] PostgreSQL receives its already-active role credential through a file-backed Compose secret with least-privilege source permissions; application, Alembic, and direct DB clients use one file-aware resolver. Password-bearing direct DSNs are rejected, credential-free direct DSNs still use the file-backed password, and changing POSTGRES_PASSWORD_FILE alone never claims to rotate an initialized database role.
      Verify: `tests/db/test_dsn.py::test_runtime_database_config_uses_password_file`
      Verify: `tests/db/test_dsn.py::test_password_bearing_direct_dsn_is_rejected_without_value_disclosure`
      Verify: `tests/db/test_dsn.py::test_credential_free_direct_dsn_uses_password_file`
      Verify: `tests/db/test_dsn.py::test_alembic_uses_file_aware_database_resolver`
      Verify: `tests/heimdal/test_raw_store.py::test_pg_connect_uses_file_aware_database_resolver`
      Verify: `tests/deploy/test_deploy_channel.py::test_postgres_server_process_environment_omits_password`
      Verify: `tests/deploy/test_deploy_channel.py::test_rendered_compose_uses_postgres_secret_file_without_value`
      Verify: `tests/deploy/test_deploy_channel.py::test_initialized_database_role_is_not_changed_by_password_file`
- [ ] The root-only tmpfs source is group-readable only by the configured database-client primary GID and is mounted only into authorized database consumers.
      Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_source_uses_root_only_tmpfs_and_service_gid`
      Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_is_readable_by_configured_non_root_service_user`
      Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_mount_is_limited_to_database_clients`
      Verify: `tests/deploy/test_deploy_channel.py::test_postgres_secret_source_is_ephemeral_and_nonpersistent`
- [ ] The Compose secret source survives consumer restart/recreate and is rehydrated before host-boot startup, then is removed after all consumers stop.
      Verify: `tests/deploy/test_deploy_channel.py::test_compose_secret_source_lifecycle_covers_restart_recreate_and_boot`
- [x] The delegated safe-hold decision for production raw-store-key rotation/deletion is recorded; no protected write is allowed before the bounded rekey path, and archive-pass remains separately protected.
      Verify: [#5667 comment #5868385351](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-5868385351)
- [ ] Owner docs describe repository support and preserve the outstanding live qualification gate.
      Verify: `docs/LOCAL_SECRET_PROVISIONING/README.md :: Linux Bitwarden Secrets Manager`
      Verify: `docs/SECURITY.md :: Secrets in CI`
      Verify: `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Linux channel secret provisioning`
- [ ] The host contract declares required channel-scoped `postgres.password` as file-only and enumerates exactly the six authorized database consumer/service pairs; existing environment grants stay unchanged.
      Verify: `tests/ops/test_host_secret_contract.py::test_postgres_password_contract_is_file_only_and_consumer_set_is_closed`
      Verify: `tests/ops/test_host_secret_contract.py::test_existing_consumer_environment_grants_are_unchanged`
- [ ] A database-bearing deployment fails before its first remote mutation and before VM-side deployment mutation when a selected service's `postgres.password` is missing or unreadable.
      Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_password_preflight_precedes_remote_and_vm_mutation`
- [ ] The single agent-host operation lock prevents a shared import from interleaving with host parity check, VM recheck, value materialization, and Compose activation; crash/transport loss leaves a pending operation that blocks later writes/deploys until readback reconciliation.
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_cannot_interleave_with_deploy_check_to_compose`
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_interruption_blocks_until_reimport_reconciles`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_waits_for_in_progress_shared_import_and_rechecks_parity`
- [ ] A missing PostgreSQL password can enter only the locked BWS-04 first-init path for an empty data directory; an initialized directory fails without a BWS write, and an interrupted bootstrap safely reuses the stored value.
      Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_allows_absent_secret_only_for_locked_empty_data_directory`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_blocks_absent_secret_for_initialized_directory`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_retry_reuses_stored_secret_after_interruption`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_postgres_bootstrap_ambiguous_create_without_matching_operation_note_remains_pending`
- [ ] A token replacement acknowledgement loss is reconciled by its non-secret generation identity and never reported as prior-source-preserved without readback.
      Verify: `tests/deploy/test_secret_token_push.py::test_token_push_lost_ack_is_reconciled_by_generation_id`
      Verify: `tests/deploy/test_secret_token_push.py::test_token_push_retry_reuses_pending_operation_id`
- [ ] Reader-token push and deploy dispatch serialize through the same agent-host lock, and a pending token push cannot be cleared by a mismatched generation readback.
      Verify: `tests/deploy/test_secret_token_push.py::test_token_push_serializes_with_deploy_operation_lock`
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_pending_operation_requires_matching_operation_id_readback`
- [ ] The committed systemd reader unit/drop-in binds the encrypted token under the BWS-01 file interface, and a missing/unreadable credential fails before provider access or deployment mutation.
      Verify: `tests/deploy/test_secret_token_push.py::test_repository_managed_reader_unit_binds_encrypted_credential`
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_bws_access_token_file_fails_before_provider_request`
- [ ] Shared first-provisioning and missing-copy recovery record history for absent copies before any BWS write.
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_history_records_genesis_tombstone_before_first_provision`
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_missing_copy_tombstone_precedes_both_writes`
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_history_failure_leaves_both_copies_unchanged`
- [ ] A failed paired update restores a newly created copy to its recorded absent state or reports value-free divergence while retaining both history events.
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_partial_failure_restores_absent_copy_or_reports_divergent`
- [ ] An unknown outcome after a shared BWS request is sent remains pending: no compensation, retry, fresh import, selected-value check, or deploy is permitted until every sent request has an authoritative terminal result. A note marker or absent readback alone is not terminal proof.
      Verify: `tests/ops/test_secret_admin.py::test_shared_import_unknown_write_outcome_stays_pending_and_blocks_recovery`
      Verify: `tests/ops/test_secret_admin.py::test_delayed_shared_write_cannot_land_after_recovery_import`
- [x] The owner accepts Demerzel login Keychain custody and `scripts/secrets` as the sole supported normal writer, with the human Organization Owner as break-glass and deliberate same-user bearer use as an accepted residual. No separate writer daemon or shared fencing is required for this one-owner setup; reassess before extra operators/controllers or prod secrets requiring confidentiality. This decision does not establish broader deployment/runtime acceptance.
      Verify: [owner normal-writer acceptance receipt on #5667](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-6114787299)
- [ ] Deploy dispatch writes an owner-only durable remote journal with operation-ID-matched terminal receipts; interrupted/nonterminal remote stages and lock release alone cannot admit another operation.
      Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_writes_durable_operation_stages_and_terminal_receipt`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_lost_ack_reconciles_matching_remote_terminal_receipt`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_nonterminal_remote_receipt_blocks_next_operation`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_ssh_loss_joins_same_supervised_operation_until_quiescent`
      Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_nonquiescent_compose_operation_remains_pending`
- [ ] Token push closes or retries a pending operation only after a matching durable remote terminal receipt; pointer readback alone cannot resolve an applying operation.
      Verify: `tests/deploy/test_secret_token_push.py::test_token_push_unknown_remote_stage_blocks_retry_until_terminal_receipt`

## External References

- [systemd Credentials](https://systemd.io/CREDENTIALS/) (service-private credential directories and encrypted credential loading)
- [Bitwarden Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/) (secret creation and non-secret item notes)

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
