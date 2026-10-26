State: Current BuilderOps deployment contract. Amended by #5056: BuilderOps is rebuildable operational state; backup and restore are deferred and never admission gates.
Doc role: BCP-02 owner contract
Authority: Defines the independent BuilderOps Compose, image, secret, ingress, health, and rebuild boundary.

# Independent Authenticated Deployment

## Implementation Status

The repository contract provides a separate BuilderOps Compose project, an import-side-effect-free
Builder package, a retained neutral runtime dependency manifest, immutable control-plane and
PostgreSQL image pins, an isolated Docker context/engine preflight, VM-local secret references,
migration-gated API and worker startup, loopback API exposure, private authenticated ingress,
authenticated probes, rebuild/rollback receipts, and a local disk/WAL guard. The deployment target
for the complete Dev System is TARS VM `bob-1` (VM ID `102`, formerly `vm102`), running guest/system
`builder-system`, with Dev UI as one read-only component; this contract does not activate a live VM
or make a backup/restore claim.

## Rebuildable VM deployment contract

BuilderOps operational state is rebuilt from repository source, exact attested images, pinned configuration, and secret custody. The deployed Compose and candidate image paths include no WAL-G, recovery target, recovery egress, archived-WAL pipeline, backup service, or restore command. A future backup capability requires a separate owner decision and bounded delivery; its absence cannot block deployment, migration, readiness, candidate attestation, rollout, or closure.

The control-plane image fixes its non-root `builderops` identity at UID `100` and GID `101` before
installing OS packages. BuilderOps host secrets consumed by that image remain root-owned, group `101`
and mode `0640`; they are not made world-readable or reassigned to an incidental package-created
group. An unavailable fixed UID/GID fails the image build. The PR/main image probe executes the built
image and requires `100:101`, preserving the same secret reader across candidate activation and
rollback instead of relying on Debian package-install order.

The host-secret provisioning owner must publish `database-owner-url`, `database-app-url`,
`api-credentials.json`, `executor-credentials.json`, and `probe-token` as regular, non-symlink files
owned by numeric `0:101` with mode `0640`. Provisioning may use a root-private temporary file and an
atomic rename, but its published result must satisfy that exact metadata contract; deployment does
not broaden or silently repair access. Before any pin, database, or container mutation, and again at
the target and rollback mutation boundaries, the deployment wrapper validates all five files and
fails with exit `78` when any file is absent, linked, or has drifted metadata. A pre-existing secret
custody defect therefore cannot strand the previous release during an automatic rollback.

PostgreSQL has `archive_mode = off` and an empty `archive_command`. The local guard rejects archive drift, WAL growth, and disk pressure. It never deletes `pg_wal`, invokes `pg_resetwal`, or treats a reset/cleanup tool as a rebuild substitute.

For first database initialization only, deployment preflights the exact regular host source `${BUILDEROPS_SECRET_ROOT}/database-app-password` as root-owned mode `0400` or `0600`. The PostgreSQL image then reads only the fixed Compose secret path `/run/secrets/builderops_database_app_password` and copies that single app-role password into a `postgres`-owned tmpfs file. `init_roles.sh` reads and removes that staged file before the service starts. No other secret is staged or made readable to the init script, and neither the original secret nor its value enters an environment variable, image layer, durable file, log, or another service.

The first-init handoff is fail-closed across crashes: a pending marker is durable before `initdb`, while a ready marker is written only after the app-role transaction commits. A restarted new cluster with a pending marker but no ready marker refuses to start instead of serving incomplete authorization state; an explicit, separately authorized recovery or rebuild is required. Existing clusters that predate this marker have no pending marker and are not modified by this guard.

The deployment wrapper holds a host-local interlock from before the engine/project preflight through
pin, Compose, Tailscale, and final verification. Its private host-local lock path is fixed by the
wrapper rather than caller-controlled configuration, and re-entry requires an inherited descriptor
whose file identity and held-lock state are revalidated; a busy or forged interlock fails closed with
no mutation.
The inherited descriptor itself must own the lock; an unrelated descriptor for the same path cannot
authorize deployment mutation.
After activation it re-reads both engine identities and project listings and requires the BuilderOps
project to be present, no Product project on the BuilderOps engine, and no BuilderOps project on the
Product engine. A competing out-of-band writer therefore fails the post-operation gate; automatic
reactivation of the previous release is also refused while that writer remains visible.

The API and worker recreation step invalidates the forwarder's cached container address. The governed
wrapper therefore restarts the fixed `builderops-loopback-forwarder.service` before any pin, database,
or container mutation, and again immediately after recreation and before the authenticated `wait_ready`
gate, for both target activation and previous release reactivation. A missing `systemctl` or failed
restart fails closed before mutation and readiness polling; the private loopback boundary is never
silently left pointing at a stale API address.

### Prepared Linux BuilderOps monitoring

Issue #6336 provides repository-side probe preparation; `scripts/plan_builderops_probe.py`
remains plan-only. As of 2026-10-26, the separately authorized #6347 component window has installed
the reviewed standalone package and admitted encrypted alert handoff on bob-1, enabled the
`yggdrasil-builderops-probe.timer`, and qualified authenticated health plus a controlled
down/repeat/recovery drill. The [runtime receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6347#issuecomment-6405523126) binds the package, engine,
schema5/epoch77627680301974, native executions, delivery and exact worker restoration.
The one-shot `app.ops.builderops_probe` runs independently of the monitored containers;
future installation or replacement still requires reviewed source/interpreter and operator authority.

The mode-0600 host-owned JSON configuration must name guest `builder-system`, the
dedicated `unix:///run/docker-builderops.sock` engine and its qualified ID, project
`builderops-control-plane`, loopback API `http://127.0.0.1:18100`, expected schema and
authority epoch. Wrong identity refuses before notification. Unavailable containers
or authenticated readiness, stale worker heartbeat, failed database health (including
the existing disk/WAL guard), stale outbox or dead letters are unhealthy. `ready=true`
alone is insufficient: worker freshness is a separate response field. Ambient Docker
context and HTTP proxy settings cannot change the selected transport, and redirects
are refused. No backup or recovery-pipeline field is required.

The probe reads the existing scoped `health:read` token; `/readyz` supplies the required
safe fields, so no additional `status:read` token is needed. A regular owner-private
token file or the existing root-owned `0:101`/`0640` handoff is accepted. The shared
Discord notification adapter consumes only the separately admitted mode-0600 host-secret
runtime handoff. This is not permission to use the Product `test`/`prod` BWS consumer
on bob-1. The #6347 enabling route admits the dedicated Heimdal-owned
`heimdal-builderops-alerts` binding through the
[existing Demerzel controller](../CLOUD_SECRET_PROVISIONING/README.md#bob-1-builderops-alert-handoff).
The service loads its dedicated encrypted systemd credential and materializes the
runtime handoff only for its invocation. It uses the qualified host `/usr/bin/python3`
with the standalone package; no Product bootstrap or BWS client is imported on bob-1.
Separate operator authority and live handoff/delivery receipts remain required before
enabling the timer; the repository route is not an installation claim.

Private locked transition state binds the incident to the engine ID and authority
epoch. Invalid retained state refuses; a failed recovery notification retains the
outage, and failed down delivery remains retryable. Successful repeated down checks
are suppressed and one recovery is sent after a confirmed down transition. Webhook
delivery is not exactly-once across a timeout/crash or a failed state commit. The
outbox age limit is explicit in configuration (the plan suggests 300 seconds).

Repository preparation alone does not establish runtime activation. The #6347 receipts cover
this monitoring component, the explicit client profile and retirement of the exact three Mac
duplicates with their data retained; they do not establish global BCP-05/06 or complete-system
acceptance, import/replay legacy tasks, or change the separate Vault store. A host-local probe
cannot alert while bob-1 itself is powered off; that requires a separately qualified outside observer.

### Complete Dev System admission

This section governs complete-system admission. The separately owner-authorized
[bounded manual DevUI component promotion](#bounded-manual-devui-component-promotion) is a
different, explicitly limited operation; its receipt cannot satisfy this section.

BuilderOps deployment is admitted only as one part of the complete Dev System topology described in
[`README.md :: Complete Dev System VM-102 topology contract`](README.md). A Dev UI-only deployment,
the default Docker engine, or a healthy guest check cannot satisfy this boundary. The component
inventory must classify every known component as `VM-102 resident (target)`, `explicit external
dependency`, or `intentionally non-runtime`, and must leave unresolved identity, service, ingress,
health, lifecycle, migration, and rollback facts as explicit gaps.

The BuilderOps image builds from `Dockerfile.builderops` and
`requirements-builderops.txt`. Its API, worker, and migration entrypoints import only the
BuilderOps control-plane package plus the neutral web, validation, PostgreSQL, and ASGI runtime
dependencies named there. Importing `app` or any Builder entrypoint does not load Product LLM
configuration, Product database/vault initialization, or Product process settings. Product keeps
its own explicit LLM policy preflight at the Product API application entrypoint. This is a
package/build boundary only; it does not prove image qualification, host identity, migration
admission, authority cutover, ingress, or VM-102 activation.

The ordered schemas and bootstrap-without-baseline refusal are owned only by the
[VM-102 evidence and receipt contract](README.md#vm-102-evidence-and-receipt-contract). This BCP-02
contract consumes those receipts but does not redefine them. Locally, deployment still refuses
secret-bearing evidence, unqualified hosts, missing component gaps, and rollback without a
compatible runnable baseline; the repository-side candidate qualification remains insufficient for
live qualification.

The [M1 first-read target](README.md#m1-first-read-qualification-target) has the bounded #5543 producer/consumer implementation for
qualification/observation for the finite managed read journey. It preserves this deployment boundary,
the full inventory and actual operator/host/source prerequisites; it neither supplies a deploy
command nor makes the full validators accept partial evidence. Live qualification is still unproven;
its single bounded record may report only a separately authorized and observed read journey. It is never
a `devsystem_vm102_*` receipt or an input authorizing broader component installation, health,
rollback, authority cutover or full owner-pilot acceptance. Existing release/attestation and private
origin controls still govern each actual install or candidate change.

### Prepared standalone DevUI listener

[`docker-compose.devui.yml`](../../docker-compose.devui.yml) declares the separate
`builderops-devui` project and its single `devui` service, owned by the Builder System release
operator. It reuses the digest-pinned Builder control-plane image and its non-root `builderops`
user, but starts `python -m app.builderops.devui_runtime`. It does not start the control-plane
worker, Product API, Product settings, migrations, or any Product store. The image must contain
this entrypoint at the newly attested candidate; an older candidate is not sufficient.

This is a prepared Linux managed listener, not a deployment executor. Complete-system execution
must qualify the fixed `builderops` context at `unix:///run/docker-builderops.sock`, authenticate
the candidate on VM102, satisfy the ordered receipts and operator gates, and install it through
the governed release path. Neither `deploy_channel.sh` nor an ad hoc process start is that path.
The declaration is not installed or enabled by this repository change.

The container uses host networking with a fixed process bind to `127.0.0.1:8113`, a read-only
root filesystem, dropped capabilities and managed restart. The base declaration mounts the existing
`/opt/builderops/receipts` source, read-only at `/run/builderops/devui-receipts`; Compose must not
create an absent source directory. No Product mounts, env files, public port or generic upstream selector are supplied by the base declaration. Source SHA must equal image-baked `VCS_REF`; image and
DevUI configuration fingerprints and a readable receipt directory are mandatory before binding.
Missing or malformed configuration refuses startup loudly. Candidate markers remain diagnostic
inputs to the external image/config readback, not attestation proof by themselves.

#5522 extends the prepared listener with the finite
[managed page/asset/Overview/Focus GET allowlist](README.md#managed-read-journey-admission).
Direct callers require immediate loopback peer and exact local Host; forwarded identity, unknown
paths, non-GET methods and malformed/unexpected queries stop before source reads. Only Focus admits
one typed subject. This is an independent packaged browser journey with actual standalone-server
proof, not a general Companion gateway or deployment executor. Private operator access must preserve
this boundary, for example through the separately approved SSH tunnel; no ingress is provisioned.
The image copies the six assets through the filtered build stage, replacing only the managed CSS
with its committed source-mapped wrapping variant and adding the generated Yggdrasil token sheet
(#5637). Runtime asset/metadata checks and shared candidate
diagnostics bind served pages and APIs to the addressed package. Historical Companion assets and the
#4833 inventory remain unchanged; the managed reuse receipt and browser evidence are separate.

The process composes the existing pure Overview functions, the B1 receipt reader and #5520's
finite managed source adapter. `DEVUI_REPOSITORY` is explicit, with no hub default. Missing source
configuration leaves the affected source unavailable; contradictory repository, epoch, URL, legacy
selector or baked-document identity refuses startup. Work reads use the existing authenticated
BuilderOps client with source-owned repository and `receipts:read` / `status:read` permission checks
and an explicitly pinned `DEVUI_BUILDEROPS_AUTHORITY_EPOCH`. The source token file is reread each
request, and service revocation or epoch movement withdraws work. CKM is available through the
separately approved [private snapshot publication contract](README.md#private-ckm-publication-and-refresh);
missing, stale or invalid captures retain an independent refusal.

[`docker-compose.devui-sources.yml`](../../docker-compose.devui-sources.yml) is an optional managed
source-configuration overlay, owned by the Builder runtime/release owner; Platform and Operations
owns its qualified host/container bindings. It adds only the fixed read-only Builder API token-file
and gh configuration-directory mounts, both with `create_host_path: false`. It enables bounded gh
REST and names the qualified BuilderOps URL and epoch. Source credential scope/custody and network
admission remain with the existing security and source owners. No credential value enters the
Overview or diagnostics. Host provisioning and use of this overlay are separate operator actions.

The image build now requires `SOURCE_REPOSITORY` alongside `VCS_REF`. The existing image workflow
supplies both from its addressed GitHub candidate; `devui_sources.package_candidate` rejects missing
identity or required document inputs. The immutable image contains the candidate docs/capability
YAML/matrix and their hashes, plus `gh`, `httpx` and PyYAML in the Builder dependency closure.
The finite filtered source package also includes the repository-root `AGENTS.md` at
`/devui-candidate/AGENTS.md`, unchanged and bound by its repository-relative path and SHA. This
allows a selected Issue that names the builder instructions in `Source Docs` to pass the same
candidate-manifest and first-read inspection checks; it does not grant those packaged instructions
runtime authority or broaden the copied file set.
`Dockerfile.builderops.dockerignore` admits that Builder-only closure through the actual Docker
context; the `devui-source-inputs` build stage permits a filtered-input export without booting a
service. Packaged document and capability paths retain their repository-relative identities, so
every emitted candidate URL resolves to the original source file.
Runtime document reads are limited to that baked directory and verify its exact file set and
content at every request; there is no operator-selected document root or store fallback. These
configuration/packaging and real-GET fixture proofs establish repository wiring only.
The mounted source must retain `devui-runtime-prerequisites.json` as specified by the receipt owner.
The listener validates all three typed receipts with those prerequisites before publishing status.
An empty/invalid receipt source or missing verification input withdraws deployment status.
Even a valid chain is withdrawn when
its source SHA, DevUI image, or DevUI configuration differs from this listener. Liveness explicitly
reports `complete_dev_system_health: false`; it cannot satisfy the complete health/owner-pilot
contract. Local managed shell/Focus and browser delivery do not discharge live source qualification,
deployed final-main browser proof, complete-system health or the owner-pilot gates under #5181,
#4749 and parent #4741. ARO-09's
[managed read journey admission](README.md#managed-read-journey-admission) owns those boundaries.
#5520 preserves the delivered three-GET process boundary and installs no service.

### Bounded manual DevUI component promotion

The owner revision recorded in Issue #6105 admits one read-only DevUI-component operation before
complete Dev System qualification. This path replaces ad hoc component recreation; it does not
relax the full-system chain above. `scripts/deploy_devui.sh` runs
`app.ops.devui_component_promotion` while holding the **same fixed host-local deployment interlock**
as the BuilderOps wrapper. Only VM102 guest `builder-system`, context `builderops` at
`unix:///run/docker-builderops.sock`, project `builderops-devui` and service `devui` are admitted.
The control-plane API/worker/database, their active/previous pins, migrations and Product Runtime
are outside this effect boundary. The control-plane unattended authorization profile does not
authorize this project; execution requires the existing explicit manual operator mandate.

The plan binds an exact trusted `main` candidate-pair receipt, host-local attestation, engine,
current container/image/config, retained baseline Compose bytes, target Compose bytes fetched from
that source SHA, and a fingerprint of the effective target configuration excluding its own
fingerprint field. The wrapper checks non-root container posture, fixed command, host networking,
GET-only listener configuration, read-only rootfs, dropped capabilities and the three fixed read-only
receipt/source mounts. It cannot add a token, grant, source transport, public port or ingress.
Optional diagnostic destinations retain the candidate defaults. Existing source bindings are
preserved; stale/refused/unavailable sources remain explicit and are not deployment success claims.

Use the already authenticated normal operator's gh context on VM102. When invoked through sudo,
only the gh subprocess runs as the existing `SUDO_USER`; no token is copied or printed. The
operator Python must already support Playwright Chromium. A launch/close preflight plus the real
baseline Overview browser check runs before service mutation; missing browser tooling refuses the
operation. Prepare host tooling deliberately through the Platform owner before invoking this path.

```bash
sudo scripts/deploy_devui.sh plan --candidate-pair /path/to/candidate-pair.json \
  --authorization-reference 'github:issue:6105; explicit owner deployment mandate' \
  --plan /opt/builderops/receipts/devui-promotion-plan.json
# Review the exact image/config and retained baseline in this plan; use its returned hash.
sudo scripts/deploy_devui.sh apply --candidate-pair /path/to/candidate-pair.json \
  --plan /opt/builderops/receipts/devui-promotion-plan.json \
  --expected-plan-sha256 sha256:<plan-hash>
```

Planning stages only the two exact Compose files under the existing release directory and writes
the operator plan; it does not mutate a running service. Apply re-verifies attestation, baseline,
engine, configuration and browser preconditions under the lock, pulls only the DevUI image, then
durably retains the component attempt/baseline **before** `up --no-deps --force-recreate devui`.
Exact observed `/version`, listener liveness and the real browser Overview → BSC / Focus → BSC →
same Focus journey are required. The browser blocks mutation methods and cross-origin requests and
asserts no browser storage. It supplies technical proof, never an owner acknowledgement.

The finite `devui_component_deployment.v1` record lives in the existing receipt directory as
`devui-component-<plan-hash>.json`; `devui-component-latest.json` retains the latest verified terminal
result. It names source/image/config, engine, authorization reference, plan/candidate hash,
baseline, observed runtime/browser proof and outcome (`pending`, `deployed`, `rolled_back` or
`indeterminate`). It explicitly sets complete-system health, source qualification, owner pilot,
trial and acceptance claims to false. It is not consumed by the full-system receipt reader or by
the Ready-to-try/acceptance paths.

A completed recreate followed by failed smoke restores only the exact bound DevUI baseline and
requires its identity/liveness and Overview browser proof. Manual rollback uses the same plan/hash:

```bash
sudo scripts/deploy_devui.sh rollback --candidate-pair /path/to/candidate-pair.json \
  --plan /opt/builderops/receipts/devui-promotion-plan.json \
  --expected-plan-sha256 sha256:<plan-hash>
```

An interrupted/uncertain Compose or rollback leaves `pending`/`indeterminate` evidence. A subsequent
plan or apply cannot bypass it by choosing a new plan hash. Stop further effects, read back the
actual container/image/config and external operation completion under the existing operator
recovery workflow, then deliberately reconcile the retained attempt. No automatic replay,
blind compensation, database rewind or fabricated terminal receipt is permitted. Successful
component deployment leaves #5181, #4749 and #5399 open; the owner's later trial and acceptance
remain separate observations and decisions.

#### Explicit source-epoch rebind

The operator also implements a config-only source rebind through
`plan --source-authority-epoch <explicit-positive-epoch>`. This is repository support, not a claim
that the operator or a new configuration is installed on VM102. Source/Platform owners retain
their permission and live-effect boundaries. It never discovers or adopts the current epoch as
a default. Without this option, image promotion retains the existing source binding.

Rebind requires the attested application source/image to equal the exact running baseline. Only
`DEVUI_BUILDEROPS_AUTHORITY_EPOCH` and the recomputed `DEVUI_CONFIG_FINGERPRINT` may differ;
repository, API and credential references, diagnostics, Compose bytes, mounts and ingress cannot
change. The existing plan owner emits `devui_component_promotion_plan.v2`, with the closed
`rebind_source_epoch` operation and a bounded source observation. The old v1 operator rejects that
version; new code retains v1 image plans but refuses an epoch change hidden inside them. An epoch
option on apply/rollback is refused: those actions consume only the reviewed exact plan/hash.

`scripts/devui_source_binding_probe.py` is part of the separately installed operator tooling. The
operator executes its bytes inside the existing DevUI container, inheriting that container's
non-root user, configuration and mounted credential. It never uses a host operator's API identity
or passes a token. The probe loads the production runtime/client, requires schema 5 and the explicit
repository/epoch, reads status → bounded tasks and addressed task versions → status, and emits only
closed metadata. It performs no task/import/transition or grant operation. Denied access, changed
epoch/schema/repository/version or malformed source identity refuses admission. Fresh probe results
are at most five minutes old; the historical planning observation remains bound to the plan while
apply obtains new observations. Apply repeats the probe after image pull immediately before
persisting the attempt/recreating DevUI, and after exact runtime/browser readback.

A consistent binding is separate from useful work evidence. In particular, the production
`task_payload_invalid` refusal (such as native `completed` versus payload `ready`) is retained as
`data_outcome: refused`; it is never repaired, hidden or interpreted as empty/healthy work. Generic
unprojectable tasks remain partial, and no Issue evidence remains unavailable. The component
receipt records the rebind operation and before/after source observations while preserving every
false full-system/source/pilot/acceptance claim. A rebind does not transfer prior acceptance to the
new config fingerprint. Task-data correction and full source qualification retain their owners.

All lock, candidate snapshot, exact-baseline, pending-before-effect, browser, compensation and
uncertainty rules above still apply. A failed post-rebind probe uses the existing exact-target
readback before bounded compensation; an unknown outcome remains non-replayable. Manual rollback
restores the retained baseline epoch/config and verifies its component identity/liveness/browser,
not the correctness of that historical source binding. No control-plane pin/data rewind or
permission change follows from either operation.

### Approved candidate attestation runner

The candidate pair must be verified from Bob-1/guest `builder-system` or from a named,
access-controlled operator runner before a live deployment attempt. The selected deployment host
must run the exact verifier locally immediately before that attempt. A separate runner's exit
result cannot be handed off to deployment; no prior remote verifier result is accepted. Before
invoking it, the wrapper requires the fixed `builderops` context to resolve to the existing local
`unix:///run/docker-builderops.sock` endpoint. This execution-boundary check does not qualify VM
identity or deployment readiness; those remain separate receipt gates. The validated runner baseline
is GitHub CLI `2.83.2` with the `attestation` subcommand available. A different CLI version is
permitted only when it supports the same `gh attestation verify` command and flags; the observed
version is recorded in the redacted operator receipt. The runner's GitHub authentication remains
in its normal credential
store or environment and is never copied into the repository, command output, or receipt.

### Owner-delegated unattended updates

The normal `deploy` and `rollback` actions remain available for a deliberately
interactive operator run. To avoid asking the owner to re-authorize every
routine update, the deployment host may install one durable, root-owned owner
authorization profile at `/etc/builderops/owner-authorization.json`. The
profile is a bounded delegation, not a bypass: it admits only this repository,
`refs/heads/main`, the `builderops-control-plane` project on VM 102 guest
`builder-system`, and the fixed `builderops` Docker socket. It must allow
exactly `deploy` and `rollback`, name the owner, and expire within 90 days.

The profile is installed once through the host's normal privileged provisioning
path with mode `0600` or `0640`; it must be a regular file owned by root. Its
canonical JSON fingerprint is recorded in every unattended success or refusal
receipt. The profile contains no GitHub token, SSH key, password, or other
secret. Replacing or revoking it is the owner-control operation; expiry,
hostname mismatch, scope drift, missing profile, or malformed permissions fail
closed before Docker, database, pin, or ingress mutation.

The repository helper can create or deliberately rotate the profile during that
one-time owner operation; it refuses non-root execution, accidental overwrite,
blank owner identity, invalid expiry, and a review window longer than 90 days:

```bash
sudo python3 scripts/builderops/owner_authorization.py issue \
  --file /etc/builderops/owner-authorization.json \
  --authorized-by owner \
  --expires-at 2026-10-17T04:00:00Z \
  --confirm 'AUTHORIZE BOB-1 BUILDEROPS UPDATES'
```

Use `--replace` only when rotating or revoking the existing delegation is the
intentional owner action. The command does not create or copy any GitHub or
runtime secret.

After installation, the bounded no-prompt path is:

```bash
scripts/deploy_builderops.sh unattended-deploy <attested-candidate-pair-receipt.json>
scripts/deploy_builderops.sh unattended-rollback
```

Every unattended deployment still performs the local `gh attestation verify`
against the exact candidate receipt immediately before mutation, and retains
the existing engine/project, secret, migration, readiness, single-writer,
ingress, and automatic-rollback gates. A later candidate therefore needs no
new owner click when it remains inside the delegated scope, but a changed
repository, source ref, target, authorization epoch, security posture, or
expired review window requires a new owner profile. This removes repetitive
approval work without granting universal unattended operation or changing
GitHub delivery authority.

Unattended rollback is intentionally narrower than forward update: the previous
pin must be root-owned and carry the SHA of a stored candidate-pair receipt from
an earlier successful deployment. That receipt is re-read and checked against
the previous source/image pins, repository, `main` ref and attestation workflow
before rollback. A legacy previous pin without this provenance is refused;
manual rollback remains available through the existing operator path.

Run the following command on the VM 102 deployment host with the exact candidate-pair receipt and
source SHA supplied by the release evidence:

```bash
gh --version
gh attestation verify <candidate-pair-receipt.json> \
  --repo RasmusTho/agentic-pkm-mvp \
  --signer-workflow RasmusTho/agentic-pkm-mvp/.github/workflows/app-image-build.yml \
  --source-ref refs/heads/main \
  --source-digest <40-character-source-sha>
```

Exit status `0` is the only success signal. The command must fail closed when `gh`, the
`attestation` subcommand, authentication, or the candidate proof is unavailable on that host; the
deployment script performs this check before Docker or database mutation. Record only the CLI
version, command exit, candidate receipt SHA, source SHA, both immutable image digests, observation
time, and `secret_material: absent`. A successful verifier result is attestation evidence consumed
by `builderops_vm_rebuild_activation.v1`; it is not host qualification, writer selection, deployment,
or owner acceptance.

## Purpose

Keep BuilderOps outside the `pkm-*` Product Runtime failure domain while preserving a truthful,
private, and rebuildable deployment path.

## Constraints

- Both source and image identities are immutable and attested; zero pins are not runnable.
- BuilderOps and Product use distinct Docker contexts and engine identities; no Product project, state, credential, vault, or network identity is admitted on the BuilderOps engine.
- The API publishes only to loopback. Tailscale Serve terminates tailnet-only HTTPS to that endpoint; Funnel is inactive and bearer authentication remains mandatory.
- Migrations, schema version, authority epoch/fencing, no dual writer, health/readiness, and rebuild receipts remain gates. A rollback selects compatible code/config/image and does not rewind data.
- This repository contract does not authorize live VM, Docker, secret, Tailscale, firewall, or PostgreSQL mutation.

## Acceptance Criteria

- [x] Compose has one internal BuilderOps network, loopback-only API exposure, no recovery secret or egress, and rebuildable local durability mode.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_local_control_plane_disables_wal_archiving_without_recovery_egress`.
- [x] Candidate images and attestation bind immutable control-plane and PostgreSQL digests without a restore proof or backup gate.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_rebuildable_candidate_path_has_no_backup_or_restore_gate`.
- [x] Deployment and rollback receipts bind pins, dedicated engine/project, authenticated loopback/Tailscale-Serve-without-Funnel ingress, migration completion, schema/epoch/fencing, no-dual-writer and external-effect-reconciliation requirements, and rollback-without-data-rewind. They contain no backup/restore acceptance field.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch`.
- [x] A non-rebuildable local durability setting fails before image pull or service activation.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_refuses_a_local_mode_that_would_require_recovery_egress`.

## Out of Scope

- Live rollout, data migration, authority cutover, or recovery operations.
- Backup/restore implementation or acceptance.

## How to Verify (Pre-Merge)

- Run the focused BuilderOps compose, deployment-contract, local-WAL-guard, and health tests.
- Run `ruff check app tests`, documentation validation, and the high-risk contract review gate.

## Related Docs

- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
