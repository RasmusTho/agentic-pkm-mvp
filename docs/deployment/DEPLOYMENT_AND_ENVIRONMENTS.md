# Deployment and Environments

State: Canonical deployment source-of-truth for the `dev` / `test` / `prod` channels. Defines how images are built once and promoted, how the API stacks and Companion UI gateways are deployed as managed units, the deploy / rollback / migration-gate / health-gate procedure, and the auth↔topology decision behind the docker bridge.
Doc role: Core SoT (deployment)
Authority: Canonical deployment + environment-separation contract. `docs/ENVIRONMENTS.md` owns environment *selection* and *path scoping* (what data/config each channel touches); `docs/RELEASE_CHANNELS/README.md` owns *channel identity, per-channel DB isolation, promotion-plan contract, migration reversibility classification, and rollback semantics*. `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md` owns the target ecosystem boundary for the operational platform; it does not replace this current deployment contract. This document owns *how a deploy physically happens*: image build/promote, managed gateways, deploy/rollback runbook, health gates, and the proxy-trust topology. Operations, runbooks, and component docs should reference this document instead of restating deployment procedure.
Temporal class: operational
Review cadence: as deployment topology, build pipeline, or channel ports change
Last reviewed: 2026-10-09
Last live runtime verification: 2026-10-03 UTC (read-only `dev`/`test` host, API, and route-configuration checks from Demerzel over VLAN; `prod` was not queried)
Last verified against: `docker-compose.yaml`, `docker-compose.{dev,test,prod}.yml`, `docker-compose.{full-host-vault,legacy-vault,test-vault}.yml`, `Makefile`, `Dockerfile`, `scripts/lib/companion_ui_startup.sh`, `scripts/lib/instance_ownership_host_state.sh`, `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`, `serve_production_page.py`, `app/auth.py`, `app/version.py`, `app/api/routes/health_contract.py`, `app/activation/ask_synthesis.py`, `config/platform/product_tars_channel_topology.v1.schema.json`, `app/ops/product_tars_channel_topology.py`, `docs/deployment/profiles/TARS_PROXMOX.md`; owner clarification for the TARS → Bob-1 / builder-system identity mapping is recorded in BuilderOps LearningSignal `lrn_20260910211500_ab12b37b`; Builder Vault dated evidence is recorded in `docs/handoffs/TARS_CHANNEL_ACCESS_MEMORY.md`, `docs/handoffs/TARS_CHANNEL_ACCESS_REPAIR_RECEIPT_2026-09-07.md`, and `docs/handoffs/TARS_DEV_WATCHER_UPGRADE_2026-09-07.md`; read-only live evidence is recorded in [MARR Issue #5618, 2026-10-03 addendum](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5618#issuecomment-5973820903); Issue #5868 and the existing-secret deployment Verify targets, which establish repository behavior only.
Verification update (2026-09-25): also checked `.github/workflows/app-image-build.yml`, `.github/workflows/integration-nightly.yaml`, `scripts/deploy_channel.sh`, and `docs/plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md`; the repository workflow set has no caller of the deploy script. This remains repository inspection, not fresh host qualification or deployment evidence.
Verification update (2026-09-29): BWS-03/#5679's encrypted reader-token push command was delivered by PR #5732 (merge commit `6b0ee40a721c65d7bb792c306eb11fc88e2a4cef`). This establishes repository support only; live VM installation and qualification remain separate gates under #5667.

## Why this document exists

Deployment follows the [RSC-01 continuity classification](../REBUILDABLE_SYSTEM_CONTINUITY/README.md#rsc-01-continuity-classification): retained human artifacts, companions, and document-backed governance receipts remain continuity authority; machine mirrors and deployment projections are rebuildable; diagnostic dumps and optional backups are evidence/ergonomics only, never semantic authority or a mandatory restore proof. Deployment journals, leases, ownership records, and fences are operational safety state. Missing lineage requires a new inactive fenced bootstrap and owner-native/external readback before activation; this document does not claim shipped total-loss recovery.

## BuilderOps local rebuildable deployment contract

The BuilderOps control plane is a separate deployment boundary from the Product channels. Its API
binds only to loopback; authenticated private ingress is supplied separately and does not turn the
local port into a public endpoint. Its local PostgreSQL posture is explicitly rebuildable: archive
mode is disabled, the archive command is empty, and the Compose project declares no recovery-egress
network, WAL archive credential, recovery target, backup service, or recovery secret.

This posture is deliberately not a backup, point-in-time recovery, or restore claim. The local WAL
guard refuses archive drift, WAL growth above 2 GiB, and excessive data-volume use; PostgreSQL also
pins `max_slot_wal_keep_size` to 2 GiB. No backup/restore tooling is enabled by a local rebuildable
deployment; any future capability requires a separately governed contract.

The deployment wrapper preserves the previous source and image pins as rollback material and records
both current and previous immutable image identities. A rollback changes the selected release but
does not restore an older database snapshot. Setup-specific placement, qualification evidence, disk
headroom, and Linux alert installation belong in a deployment profile such as
`docs/deployment/profiles/TARS_PROXMOX.md`; they are not generic deployment facts.

## Complete Dev System placement and admission

The portable deployment contract admits a selected setup profile; it does not choose a host. The
TARS/Proxmox profile selects TARS VM `bob-1` (VM ID `102`, formerly referred to as `vm102`) as the
intended cohesive runtime home for the complete Builder System / Dev System. The guest/system
hostname is `builder-system`: it is the system running on `bob-1`, not the Proxmox VM name. This
includes Dev UI as a read-only projection component and the BuilderOps control plane and its internal
providers. It is not a Dev UI-only deployment and it does not merge the Dev System with Product
Runtime.

This identity mapping is naming authority only. It does not claim live qualification, residency,
deployment, health, or SSH access; those facts still require the receipt-bound evidence below.

The complete topology and all unresolved components are owned by
[`docs/BUILDEROPS_CONTROL_PLANE/README.md :: Complete Dev System VM-102 topology contract`](../BUILDEROPS_CONTROL_PLANE/README.md).
Every component must be classified as `VM-102 resident (target)`, `explicit external dependency`,
or `intentionally non-runtime`, with an owner, service/project, source/image identity, ingress/auth
posture, health/version evidence, deployment role, lifecycle evidence, migration boundary, and
rollback boundary. An unknown or unavailable component remains an explicit gap and blocks complete-system admission;
it cannot be silently omitted or inferred from a guest check.

The separate [M1 first-read qualification target](../BUILDEROPS_CONTROL_PLANE/README.md#m1-first-read-qualification-target)
has the bounded #5543 qualification/observation implementation for one real Issue read; live
qualification remains unproven.
It preserves the complete inventory and applicable host/engine, naming, no-dual-writer, source-grant,
private-ingress, operator/Linux-probe, migration and rollback prerequisites. Its bounded record
can attest only the exact selected candidate's observed journey; it cannot authorize deployment,
substitute for any full receipt below, erase an unconsumed component gap, close #5181 or establish
#5399 platform acceptance. The [minimum later implementation](../BUILDEROPS_CONTROL_PLANE/README.md#minimum-later-first-read-implementation)
keeps repository producer/consumer verification separate from source preparation, operator release
and live owner observation. The bounded reader changes no full-system validator or operator permission.

### VM-102 deployment receipts

The ordered receipt schemas and first-deployment rollback refusal are owned only by the
[VM-102 evidence and receipt contract](../BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract).
This portable deployment document consumes that contract without redefining it. It still refuses a
screen observation, Project view, unbound guest readback, healthy default-engine stack,
secret-bearing evidence, or absent compatible rollback baseline as deployment or rollback proof.
The first inventory receipt is produced and validated only through the linked owner's
[`devsystem_vm102_component_inventory.v1` executable boundary](../BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract);
this deployment contract does not collect host evidence or duplicate its schema.

### Infrastructure-to-application interface (Issue #5856; preparation only)

A future private infrastructure repository may prepare the selected host and guest prerequisites,
but it does not become a second deployment owner. Its redaction-safe interface to this document is
limited to the selected guest identity, private endpoint or ingress reference, storage/network
attachment references, and prerequisite readiness. It must not publish secrets, private host
identifiers, database paths, vault paths, or a mutable application checkout.

The application side supplies an immutable image/source identity, selected channel configuration,
migration classification, and release/deployment receipt. Application artifacts and image builds,
Compose service topology, migrations, database/data and vault semantics, channel selection,
promotion, rollback, and runtime health remain owned by this deployment contract and their linked
Product/Runtime owners. A future normal sequence is infrastructure plan and approved effect → guest
prerequisite check → this document's deploy/migration/health gates; a plan or guest check cannot
authorize the next stage.

The finite pilot described in [the Platform and Operations owner](../YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md#proposed-separate-infrastructure-repository-and-disposable-pilot-issue-5856-preparation-only)
uses one disposable dev/test resource and proves provider import/plan, least-privilege scope,
protected state and guest checks. It does not qualify VM-102, admit the complete Dev System, select
a Product Runtime channel, or change the current deployment sequence. Host/VM qualification remains
[#5052](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5052), the BuilderOps control-plane
contract remains [#3788](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3788), the startup
validation chain remains [#4913](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4913), and
secret/provider qualification remains [#5667](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667).
Those issues retain their lifecycle owners; this preparation neither adopts their children nor
introduces a new complete-platform admission gate.

## Product Runtime channel placement

The intended Product Runtime placement for all three channels (`dev`, `test`, and `prod`) is the
TARS-hosted Linux VM topology selected by the TARS deployment profile. This is a placement contract,
not a live residency or deployment claim. The exact channel VM, Docker engine, source/image, ingress,
health/version, data, backup, and rollback identities must come from a fresh,
redaction-safe `product_tars_channel_topology.v1` qualification input; unknown values remain explicit
gaps and do not authorize a channel operation.

Demerzel/Mac mini is not the `dev`, `test`, or `prod` Product API host. It is also the designated
Codex CLI model executor for the Model Access Router, reached over the accepted VLAN-only mTLS path;
Tailscale is not a prerequisite for that route. Local Compose/Colima is an explicitly
non-authoritative development fallback. TARS VM `bob-1` (VM ID `102`) is the separate complete
Builder System / Dev System target, running guest/system `builder-system`, and must not be used as a
Product Runtime channel VM or engine. BuilderOps and Product Runtime placement therefore remain
separate authority boundaries.

Provider and model selection is resolved by capability configuration. Neither this placement profile
nor the topology qualification input encodes a provider, model, or Codex-only runtime architecture.

## Current live runtime posture

The latest read-only check from Demerzel (2026-10-03 UTC) reached `ygg-dev` and `ygg-test` over VLAN;
it was not a deployment run. `ygg-dev` runs image
`8cb453986944b98b7dac483973aae67e8c5e64e7`, reports `required_ok=true`, and enforces
`ollama/llama3.2:3b`; its current health response still checks Ollama and does not yet report
`llm_access`. `ygg-test` runs `dev-local`, reports unknown application SHA and `required_ok=false`,
uses `LLM_PROVIDER=mock`, and has only API and DB containers (no worker or watcher). Product
containers on both channels lack the Model Access VLAN caller settings. The existing test checkout
was stale and dirty and was left untouched.

The accepted MARR-06 receipt proves one Luna completion through the active, loopback-bound Mac mini
Codex CLI executor over VLAN mTLS; it does not prove persistent Product routing. The merged candidate
is not running on either channel, and its pending migrations have not been applied. The read-only SSH
path does not establish the qualified deployment executor or Linux caller-secret qualification
tracked by #5667. No candidate-bound backup or staged-rollout receipt was created. Do not use the old
local Compose projects or matrix below as evidence for the new-host runtime. The remaining authorized
sequence is exact candidate identity and backup/migration review → dev deployment and verification →
test deployment and verification. Production was not contacted and remains out of scope.

### CI deployment automation posture

The repository builds and verifies SHA-identified application images, and `scripts/deploy_channel.sh`
provides channel deployment mechanics. In the verified workflow set, no GitHub Actions workflow calls
that deploy script; post-merge automatic `dev` → `test` delivery is therefore not shipped. The
[fast PR-to-dev/test plan](../plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md) proposes a separate post-merge
path that keeps nightly and live deployment out of the PR merge gate. It requires fresh channel and
executor qualification, exact SHA/digest receipts, per-channel serialization, and a recovery contract
before enablement. Production authority and promotion remain separate.

RCA on 2026-06-29 (BuilderOps LearningSignal `lrn_20260629093241_59713bc1`) found that the system had **no deployment source-of-truth**. The observed reality:

- All three docker API stacks bind-mount a single shared host checkout (`./:/app`) — there is **no code isolation between channels**; every channel runs whatever is checked out in that one tree.
- Companion UI gateways are hand-started ad hoc via `nohup … &` from shell history — there is **no managed unit, no restart-on-failure, and no source-of-truth** for how a gateway is launched.
- API routes load at container start, so a deploy needs a container **restart**, not just a bind-mount/file update — a "pull without restart" silently serves stale code.

This document is the canonical spec that epic #2655 (deployment + environment-separation architecture) is broken out from. **The architecture decisions below are already made by the operator. Encode them; do not re-litigate them.** The §Implementation slices section maps the remaining work (S2–S7) to concrete targets so `feature-breakdown` can derive child issues.

## Operator-decided architecture (encoded, not open for re-litigation)

- **Target = Docker Compose + pinned image tags + a deploy script + managed gateway units.** No new PaaS is introduced.
- **Build-once / promote.** CI builds a SHA-tagged image once; each channel runs a *pinned* tag; the **image is identical across channels**; only config, data, and ports differ. There is no dev/prod feature fork (consistent with `docs/STATUS.md` and the repo-wide "one product, identical features" stance).
- **Full-environment downtime is authorized for the cutover** (S7). The cutover from the shared-checkout bind-mount model to pinned images may take all channels down briefly.
- **Auth↔topology** is reconciled by treating the local reverse proxy / bridge hop as a **trusted proxy** (trusted `X-Forwarded-For`) or by using host networking, while **untrusted callers stay rejected** (#2223 intent). The tactical fix already shipped in PR #2665; this document formalizes it (see §Auth↔topology decision).

## Environment matrix

The contract spans three channels: `dev`, `test`, and `prod`. The local Compose fallback can run them in
parallel on one host; the intended live topology assigns them to isolated Linux hosts. Their ingress
and operator access are governed by the qualified deployment profile; this document does not make
Tailscale a Model Access prerequisite. They
are isolated by DB name, vault binding, ports, and runtime-artifact paths — see `docs/ENVIRONMENTS.md`
for the environment-selection contract these values implement.

### Local Compose fallback matrix (verified 2026-07-06; not the live Product Runtime)

| Surface | dev | test | prod |
| --- | --- | --- | --- |
| `PKM_ENVIRONMENT` | `dev` | `test` | `prod` |
| Compose project | `pkm-dev` | `pkm-test` | `pkm-prod` |
| API (FastAPI, docker) host port | **18001** | **18002** | **18000** |
| Postgres host port | **15433** | **15434** | **15432** |
| Postgres DB name | `app_dev` | `app_test` | `app` |
| Companion UI gateway host port | **8111** | **8112** | **8113** |
| Gateway module | `serve_dev_page` | `serve_dev_page` | `serve_production_page` |
| Shared renderer | `render_index_html` | `render_index_html` | `render_index_html` |
| Vault mount → container `/app/vault` | none (no-vault posture) | Bifröst | Midgård |
| Runtime env / deploy-pin source | `config/deploy/dev.env` + compose env | `config/deploy/test.env` + compose env | generated `tmp/runtime.env` + `config/deploy/prod.env` placeholder pin |
| Container app code source | baked local image `pkm-app:dev-local` (app bind overlay opt-in) | pinned image (app bind overlay opt-in) | pinned image (app bind overlay opt-in) |
| Startup wrappers | `make dev-up` / `make dev-ui` (`scripts/dev/start_niflheim_ui.sh`) | `make test-up` / `make test-ui` (`scripts/test/start_bifrost_ui.sh`) | `make prod-up` / `make prod-ui` (`scripts/prod/start_midgard_ui.sh`) |

Anchors for the values above: ports/DBs in `docker-compose.{dev,test,prod}.yml`; the 2026-07-06 host recon recorded in #3124 / `docs/deployment/PINNED_IMAGE_CUTOVER/README.md`; gateway ports `_DEFAULT_PORT = 8111` (`serve_dev_page.py`) and `_PRODUCTION_PORT = 8113` (`serve_production_page.py`, with test 8112 set via the `PORT` env); vault names per `reference_three_vaults` (names are operator-owned and **never hardcoded**).

Notes on the current model:
- The repo app bind mount is opt-in through `docker-compose.app-bind.yml`; the standard dev, test, and prod Compose/deploy paths omit it. When explicitly enabled for a local hot-reload or exact-worktree UAT session, it mounts the selected checkout at `/app` and therefore is not code-isolated from changes in that checkout. `dev` otherwise runs the baked local `pkm-app:dev-local` image, while test and prod use their channel image pins.
- Companion UI gateways are declared as managed Compose units in the repo. The final #2698 public receipt records a production pinned-image deployment; this document has no fresh equivalent `dev`/`test` receipts and does not infer their current runtime state. The cutover guard checks gateway-unit participation in the recreate set on the configured deployment path.
- Production Compose fixes Companion's publish to `127.0.0.1:8113` and passes the matching explicit
  declaration `COMPANION_UI_BIND_HOST=127.0.0.1` into the gateway as one canonical producer pair;
  ambient shell configuration cannot widen or silently disable it. The production deploy wrapper
  fails before mutation if either half drifts. Noncanonical direct launches with missing or
  nonloopback declarations keep only the devUI routes closed while
  unrelated Companion health remains available. Port `18000` is direct API health/version
  diagnostics, not a supported devUI browser origin. The #4836 candidate's only canonical browser
  entry is `http://127.0.0.1:8113/devui/overview`; its page, Focus, and committed asset routes run
  in the Companion gateway and do not create a FastAPI presentation origin. It remains a candidate
  until the #4746 design/provenance and #4833/#4842 exact-ref browser receipts pass, and it becomes
  deployed truth only after its own deployment receipt.
- A partial build-identity foundation already exists: #2602 bakes `VCS_REF`/`BUILT_AT` into the image (Dockerfile ARG/LABEL/ENV), `get_runtime_version()` in `app/version.py` reads them (falling back to `git rev-parse` for local dev), `/version` returns `{git_sha, built_at}`, and `/api/health` carries a top-level `version` field. **But the `test`/`prod` `/app` bind-mount overrides the baked code**, so today those channels run the host checkout, not the image — the SHA marker can disagree with what is actually executing until the bind-mount is retired.

### Multi-vault instance-state rollout boundary

MVR-01A provides the dormant `app.instance.vault_registry` store and its private-file,
cross-process lock, CAS, physical-root identity, crash-recoverable transaction journal, snapshot,
and corruption-recovery contracts. MVR-01B now provides the protected channel-scoped
`/app/instance-state` named volume, the shared private `/app/instance-ownership` host ledger/key,
and identical fail-loud preflight for API, worker, watcher, and Heimdal capture watcher. The
`instance-state-init` producer verifies owner-only state before those consumers start; their
resolved registry path is `/app/instance-state/agentic-pkm/vault-registry.md`. It does not invent a
missing registry or ledger during consumer preflight. The host bind source is resolved before
Compose interpolation to the canonical absolute
`${XDG_STATE_HOME:-$HOME/.local/state}/agentic-pkm/instance-ownership` path for a non-root caller. The
root BWS systemd supervisor uses an explicit `XDG_STATE_HOME` when configured and otherwise derives
that same default from the validated runtime UID's passwd home, so it never selects a state directory
below `/root`; an explicit absolute `INSTANCE_OWNERSHIP_HOST_STATE_DIR` remains authoritative.
Separate checkouts and all three channel projects therefore mount the same ledger. Compose may not
create a checkout-relative substitute.
Every consumer rejects any active host-global deployment lease, including a lease owned by another
channel, before reading or mutating channel state.

Both `scripts/deploy_channel.sh` and `scripts/start_full_system.sh` invoke
`scripts/lib/instance_state_deployment.sh`. Before the first init or any lease/fence mutation, the
shared producer derives every dev/test/prod/native legacy owner from canonical channel and runtime
env sources, stopped or running Compose writer config and scalar stores, the native scalar store,
and the governed caller binding. It writes a private baseline only after two complete snapshots are
identical. The wrapper then installs a durable host-global deployment lease before its channel
restart fence, stops API/worker/watcher/Heimdal, probes dev/test/prod/native consumers twice, and
durably proves quiescence. Two new owner-source snapshots must reproduce the baseline exactly before
the producer marks the inventory drained and copies it to
`/app/instance-ownership/legacy-owner-inventory.json`; missing sources, config/store races, and
equal or nested roots across owner domains abort without seeding a partial set. A failure at any
stage after the lease/fence claim and before finalization — a live writer, a post-stop owner
validation failure, or any other producer stage failure — surrenders that same-run producer's own
host-global lease, public lease copy, and channel restart fence instead of stranding them; the
release is scoped to the exact controller identity (pid plus start token) that claimed the lease, so
it cannot disturb a lease still owned by a live or unrelated deployment, and a lease whose recorded
controller process no longer exists is reclaimable by the next `deployment-begin` instead of fatal.
The nonce-plus-inventory-digest proof
is required for restore, final export/preservation, and legacy bootstrap. Before the MVR-05 floor,
the producer also passes the SHA-256 of the final host receipt to the runtime. The runtime accepts
the Compose-mounted receipt only when its bytes match that digest; a stale or incomplete mount
projection waits briefly and then fails closed rather than being treated as an authenticated
inventory. The finalizer rejects an
incomplete, non-private, or unvalidated inventory, captures the final legacy fingerprint, imports it
on first volume or preserves it beside an established dormant registry, calls the host-global
legacy-owner bootstrap, creates a verified registry/ledger/key backup, and clears the fence.
`INSTANCE_STATE_RESTORE_PATH`, when set, is verified and restored inside that stopped interval
before finalization and consumer startup. Failure leaves the fence in place, so upgraded consumer
preflight refuses restart. Rollback to a previous image that predates `app.instance.runtime` is
selected explicitly by the deploy wrapper and uses a Compose-owned compatibility guard: it may
start only when neither the host-global lease nor any channel restart fence exists. Current images
always run the full authenticated runtime preflight; module absence outside explicit rollback fails
closed.

#### Legacy owner root namespace authority (#4539)

The owner-authorized decision recorded on 2026-08-30 is host-side validation (Option B). The
Mac/host producer validates legacy-owner roots in the host namespace where those roots actually
exist, including the existing identity, ancestor, collision, and post-quiescence checks, and emits
a private receipt bound to the deployment/quiescence proof. The Docker deployment helper consumes
that bound result and its opaque identity evidence; it does not directly resolve host-only paths or
re-run `root.is_dir()` inside `instance-state-init`.

After finalization, an API, worker, watcher, or Heimdal capture watcher whose selected canonical
root is visible through a container remount but has a different local inode may admit the already
registered active binding only by loading that same private receipt, validating its digest, channel,
binding, and canonical-path correlation, and authenticating its host identity against the active
ownership ledger. Finalization checkpoints the producer receipt digest in that private ledger
lease, and remount admission requires that checkpoint to match. Ordinary materialized-root admission remains the default; a missing, stale,
forged, foreign, ambiguous, unbound, or pending receipt fails closed without registry or ledger mutation.

This decision keeps the one-shot's ordinary mount set intentionally bounded. Ordinary deploy-selected Compose overlays
exclude `/Users`, `/Volumes`, and selected-vault mounts from `instance-state-init`; the selected-root
bind in the full-host overlay is for `api`, `worker`, `watcher`, and `heimdal-capture-watch` only. The rejected Option A—adding
broad `/Users` and `/Volumes` visibility so the container can re-check host paths—would widen deployment
authority filesystem exposure and is not part of the selected repair. If
`DESIGN_HANDOFF_APP_LOCAL_SETTINGS` is explicitly configured to a host-side path, including under
`/Users` or `/Volumes`, the deployment wrapper refuses before initialization rather than silently
treating that legacy source as absent. The bounded receipt handoff and regression proof shipped in
PR #5244 for #5235; this does not claim a live three-channel host deployment. The explicit MVR-01C
authority cutover is the qualified exception: its separately governed `authority-cutover` command
mounts the already-authorized `MVR01C_ROLLBACK_VAULT_ROOT` read-only at `/app/selected-vault` for that
command only. For ordinary deploy/start, the effective setting from the ambient environment or
`config/deploy/<channel>.env` is admitted only at the exact channel container path
(`/app/tmp/agentic-pkm/app-local.md`, or `/app/tmp-test/agentic-pkm/app-local.md` for TEST); host
paths, duplicate declarations, traversal, aliases, symlink-like paths, and other `/app` locations fail closed before the
deployment mutation window. Failure remains fail-closed: missing, changed, incomplete, forged, or unbound host
evidence cannot release the fence or mutate registry/ledger state.

#### Explicit DEV legacy-owner re-attestation

`python -m app.instance.runtime deployment-reattest-legacy-owner` is an explicit local
operator recovery command for a retained DEV schema-v1 owner whose old container parent-inode
chain is unavailable. Ordinary startup and legacy authentication continue to refuse that state.
The command establishes a fresh, receipt-bound ownership epoch; it does not authenticate the lost
chain or infer any previous effect outcome. It is not total-loss recovery.

Run it only inside the canonical producer's proved stopped interval, before MVR-05 floor admission
and `deployment-finish`. Supply `--channel dev`, the existing `--instance-state-root` and
`--host-global-root`, `--owner-receipt-path` and `--quiescence-proof-path` from that interval,
`--vault-binding-id`, the reviewed raw-file `--expected-ledger-sha256` and
`--expected-registry-sha256`, a private `--backup-root`, and
`--acknowledge-new-ownership-epoch`. The acknowledgement is a new authority decision about the
exact retained root/binding; a path or a backup alone is not ownership authority.

Admission requires one dormant registered owner, one matching active v1 lease, the existing
protected key, an authenticated sealed locator and root fingerprint matching the complete current
host inventory, and no tombstones, transfer/lineage, or interrupted rotation. TEST, PROD,
multiple-owner state, stale evidence, and lost root/key/registry identity are refused. The recovery
container consumes the existing host receipt without gaining broad host-root mounts. Missing or
inconsistent last-good, checksum, or legacy-export artifacts are refused without implicit repair;
the recovery lock does not heal any registry evidence before admission or backup.

Under deployment → producer → ledger → registry locks, recovery saves the unchanged registry
artifacts, ledger, and key into an owner-only backup. Its authenticated `manifest.json` binds a
fresh epoch, the explicit decision, before/after digests, and the current stopped-window receipts.
That verified evidence becomes durable before atomic ledger replacement. Only the single lease's
current ancestry and owner-receipt provenance change; registry, key, sealed locator, root identity,
and binding stay unchanged. Public output contains no key material or host paths.

After interruption, retry with the same inputs, private backup, and still-valid deployment window.
A partial backup can resume only when its existing bytes agree. A complete receipt admits exactly
its before or after ledger bytes; changed registry, key, inventory, deployment epoch, or ledger
fails closed. Do not delete authority artifacts to force a retry. If the old deployment window has
ended after successful ledger replacement, use the normal canonical deployment path to revalidate
current ownership; this command does not replay across epochs.

The command leaves the restart fence and deployment lease held and never starts writers, changes
vault files, or migrates SQL. Successful recovery is not activation: normal floor admission and
`deployment-finish` must still validate the recovered ownership under the stopped proof, and the
separately authorized deployment performs runtime startup and functional verification.

MVR-01C cuts registry authority over only by committing one complete rollback floor into the same
locked registry generation. That generation names one validated scalar rollback binding, refreshes
the current legacy projection, records the roll-forward fork revision, and proves both the
authenticated mutation-filtering gateway and the deny-by-default native guard. A partial or missing
proof leaves `authority: dormant` and every registration producer sealed.
The cutover runs before deployment finalization clears the host-global lease/restart fence and
requires the same bound quiescence proof, drained-owner inventory, producer-transition lock, and
exact active ownership coverage. Pending ownership or an unmatched selected-root filesystem
identity therefore blocks the authority revision.
Deployment finalization takes that same producer-transition lock before it can clear the proof,
lease, or fence, so it cannot race past the authority commit. Newly unsealed registration
producers reuse a unique pending reservation for the same physical root and recover a
registry-committed pending lease on retry; crashes on either side of the registry commit do not
mint a second binding or strand ownership.

Supported container rollback into a previous scalar image uses
`docker-compose.scalar-rollback.yml`: the old API publishes no direct host port, the base
companion UI is disabled, the real companion picker select/initialize routes are denied, and the
old API is reachable from the host only through the authenticated gateway. It mounts only the
selected content root at `/app/selected-vault`. `deploy_channel.sh rollback` detects a target
commit that predates `app.instance.runtime`, requires the explicit binding, absolute selected root,
gateway credential file, and a private `0600` netrc proof credential for one matching gateway user
before changing the pin, derives the trusted-current and
previous-image refs from the current/target pins, and then starts only the guard, old API, and
gateway through that overlay. Scalar mode keeps the capable current-image pin as its durable guard
identity and records the old target in the rollback anchor; a failed or restarted establishment
therefore resumes the guarded mode instead of attempting a session-blocked broad-stack restart.
The current guard adopts an existing authenticated session only when its binding, registry
revision, selected root, export, and policy hashes exactly match the retry. The gateway uses the
channel's managed restart posture; deployment records success only after the provisioned proof
credential reaches the old API health endpoint through that live gateway. The legacy projection translates only that
registration's host path to the container alias and authenticates both the canonical registry
export and translated projection, so roll-forward restores the original binding identity rather
than adopting a container path. The ledger validates that alias by its materialized physical-root
fingerprint while separately authenticating the sealed host path and ancestor lineage; container
ancestor names are never treated as host authority. A current guard image revalidates the host-mounted base, overlay,
and nginx bytes that Docker actually activates (not image-local copies), materializes the exact
legacy projection, and installs a host-key-authenticated scalar session before the old API starts. That
trusted one-shot guard alone receives writable ownership state so it can take the shared lock and
sign the session; the previous-image API receives no ownership/key mount. The durable session excludes
current registry writers for the lifetime of the old image; the old image receives neither the
host key nor a writable registry mount. Scalar admission and `deployment-begin` share one
host-global lock. The canonical deployment lease and a runtime-admission lock live in a key-free
host-global control directory mounted read-only into the old API. The old API takes the shared lock,
checks that the lease is absent, and carries the lock across exec; deployment quiescence proof must
take the exclusive side, which catches an API admitted before lease publication. Native rollback currently fails closed: the root-owned
`scripts/scalar_rollback_native.sh` launcher never starts an old image until an authenticated
mutation-filtering boundary equivalent to the Compose gateway exists. A filesystem sandbox alone
is insufficient because it cannot exclude a bypass listener. A binding-keyed
`minimumRuntimeSchema` floor blocks scalar API/worker startup before database or queue work. On
roll-forward, the authenticated session and unchanged registry revision must agree before
rollback-period metadata and last-active state become the next registry revision; divergence
preserves both sides without recreate. The importer is not a free-standing runtime call:
`MVR01C_ROLL_FORWARD_LEGACY_PATH` asks the normal deployment producer to run
`scalar-rollback-roll-forward` only after its host-global lease, restart fence, stopped-writer
proof, and drained-owner receipt are durable, and before `deployment-finish` permits recreate.
Roll-forward and finalization use the same host-admission then channel-producer lock order.
Deployment begin treats the claimed lease as the retry journal for an interrupted channel-fence
projection. Finalization records its result in a cleanup-phase lease before removing the restart
fence and proof. A root-level compatibility block occupies the exact shipped v2 lease path through
cutover and cleanup, preventing a running v2 helper from creating overlapping authority; it is the
last authority artifact removed. Registry generation and scalar-session retirement
share their existing crash journal; interruption recovers the pre-merge session for retry or the
complete committed generation without a stranded stale session.
An already-durable root-level v2 lease remains a blocking authority during upgrade. Only a dead
same-channel `claimed` controller is migrated by publishing the public v3 lease, matching fence,
and root compatibility block without an absence gap; live or `proved` v2 state stays fail-closed on
its original recovery path.

### Target

| Surface | dev | test | prod |
| --- | --- | --- | --- |
| Container app code source | **pinned image tag** (no repo bind-mount of `/app`) | pinned image tag | pinned image tag |
| Image | `ghcr.io/<owner>/pkm-app:<sha>` (identical image, all channels) | same image, different tag pin | same image, different tag pin |
| Pinned tag recorded in | `config/deploy/dev.env` (or equivalent per-channel deploy pin) | `config/deploy/test.env` | `config/deploy/prod.env` |
| Config/data/ports | unchanged from current matrix (only differ by config, not by code) | unchanged | unchanged |
| Gateway | managed unit (container or `launchd`), recreate-on-deploy, restart-on-failure | managed unit | managed unit |
| Vault selection mounts | `/Users` + `/Volumes` retained for runtime consumers (#2310) | retained for runtime consumers | retained for runtime consumers |

The target keeps the **ports, DB names, vault bindings, and the `dev/test → serve_dev_page`, `prod → serve_production_page`** split exactly as today. The vault-selection row is consumer-scoped: ordinary deploy-selected overlays retain selected-root runtime mounts for `api`, `worker`, `watcher`, and `heimdal-capture-watch`, while `instance-state-init` receives no selected-vault mount. The explicit MVR-01C authority-cutover command remains the qualified exception and mounts its already-authorized `MVR01C_ROLLBACK_VAULT_ROOT` read-only at `/app/selected-vault` for that command only. The only other changes are: (a) the app code arrives as a **pinned image** instead of a live bind-mount, and (b) gateways become **managed units** instead of `nohup` processes. Everything that varies between channels stays config/data/ports — never a code fork.

## Build-once / promote model

The pipeline builds an image **once per commit** and promotes the *same* image artifact across channels by moving a tag pin. This replaces the "all channels run one bind-mounted checkout" model.

### PR validation is not artifact publication (current policy)

The `App Image Build` GitHub workflow has two deliberately different paths:

- A pull-request run builds an `linux/amd64` image in the ephemeral CI runner, verifies its baked
  `/version` identity, and uses `push: false`. It does **not** log in to GHCR and it leaves no
  pullable candidate image behind.
- A push to `main` builds and publishes the multi-architecture SHA-tagged GHCR image. That is the
  normal registry-artifact path.

The declared CI image pulls use these explicit `mirror.gcr.io` references. Each digest was verified
against the corresponding upstream Docker Hub content before adoption; the application retains its
established Python index digest in both stages.

| Pull surface | Exact image reference |
| --- | --- |
| Application Python stages | `mirror.gcr.io/library/python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28` |
| BuilderOps Python base | `mirror.gcr.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` |
| Index PG contracts service | `mirror.gcr.io/pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a` |
| BuilderOps PostgreSQL base | `mirror.gcr.io/library/postgres:16-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4` |
| Both Buildx driver images | `mirror.gcr.io/moby/buildkit@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea` |
| Both QEMU helper images | `mirror.gcr.io/tonistiigi/binfmt@sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0` |

Buildx receives its image through `driver-opts: image=...`; QEMU receives its `image` input.
The service uses its exact image before checkout, and each Dockerfile declares its base directly.
A cache miss or pull error fails the affected job: these references add no authentication or Hub
fallback. Google documents daemon-configured cache use and may evict cached content, so this direct
source recovery has no permanent availability guarantee.
See [Google's cache contract](https://docs.cloud.google.com/artifact-registry/docs/pull-cached-dockerhub-images)
and [Docker's BuildKit image input](https://docs.docker.com/build/ci/github-actions/configure-builder/).
Successful registry metadata reads establish content identity and observed availability only.
Acceptance still requires successful PG execution, image builds and the existing runtime/TTS probes
on the current PR head; those results establish no live deployment.

Nightly integration runs are test execution, not a third artifact-publication path. A green PR
image check therefore proves that the Dockerfile builds and that the runner-local image reports the
expected identity; it does not prove that a mac-mini channel can pull or run that PR SHA.

Normal PR publication must not change this boundary. In particular, an agent opening or updating an
ordinary PR must not add a registry push, change a channel image pin, restart a channel, or treat a
locally built image as live-channel evidence just to obtain a UAT receipt. Publishing an image and
deploying an image are separate actions: neither follows from opening a PR.

If exact-SHA live UAT is required before merge, first identify the selected channel's execution mode.
The current checkout-mode test channel can be started from the exact isolated PR worktree with the
explicit `APP_CODE_BIND_COMPOSE=docker-compose.app-bind.yml` overlay while retaining its real
test-channel vault and configuration. That is valid live-channel UAT evidence when the receipt names
the worktree SHA and the selected channel; it neither publishes an image nor changes a channel pin.

A channel already running in pinned-image mode instead requires the candidate tag to exist in GHCR.
When that artifact is absent, record the UAT as blocked with the exact missing tag and command
result; do not broaden the ordinary PR workflow as a workaround. A separately approved, manually
initiated candidate-artifact flow may later publish a named SHA for selected UAT; it must return the
SHA/digest receipt and must not mutate any channel. Channel deployment remains governed by the
promotion and deploy workflows below. This boundary was made explicit after the SETTINGS-01
verification of PR #3517.

1. **Build (CI, S2).** On the appropriate trigger, CI builds the app image from the repo `Dockerfile` and tags it with the immutable commit SHA: `ghcr.io/<owner>/pkm-app:<full-or-short-sha>`. The build injects `VCS_REF`/`BUILT_AT` build-args (already wired in `docker-compose.yaml` and the `Makefile` for local builds; CI mirrors this) so the image's `/version` reports its own SHA.
2. **Registry and artifact identity (S3).** The SHA-tagged image is pushed to a container registry — **GHCR** (`ghcr.io`) is the chosen registry (already the GitHub-native default for this repo's tooling). Byte-identity claims are only truthful once the registry enforces digest pinning or explicit SHA-tag immutability; until then, the channel pin is just a pointer to the intended image artifact, not proof that the registry cannot be retagged.
3. **Per-channel pinned tag.** Each channel records exactly one image tag it is allowed to run (a per-channel deploy-pin file, e.g. `config/deploy/<env>.env` carrying `APP_IMAGE_TAG=<sha>`). Compose runs that pinned tag instead of building locally; the base `image:` reference becomes `ghcr.io/<owner>/pkm-app:${APP_IMAGE_TAG}` and the `./:/app` bind-mount is dropped for app code (vault-selection mounts stay).
4. **Promotion = tag bump + recreate.** Promoting a commit to a channel means updating that channel's pin to the already-built SHA tag and recreating the channel's containers + gateway against it. **No rebuild at promotion time** — the artifact is identical to what was tested. This is the physical mechanism beneath the promotion-plan/`stable`-ref contract in `docs/RELEASE_CHANNELS/README.md`: that document decides *which* SHA is allowed to be promoted and what migration/rollback semantics apply; this document decides *how* the promotion is physically applied (bump pin → recreate → health-gate).

**Identity invariant.** The image bytes for a given SHA are identical in `dev`, `test`, and `prod`. A channel never builds its own variant. Divergence between channels is expressed only through `.env.<env>` / compose env, mounted data (vault, DB volume), and ports.

`app.release_channels.channel_manifest` now provides the side-effect-free STARTUP-02 render boundary
for that identity. Promotion mode requires the manifest's exact image-index and platform digests,
requires every rendered service image to use `repository@sha256:...`, and refuses build directives,
source binds over `/app`, broad writable `/Users` or `/Volumes` mounts, and unresolved interpolation
fallbacks. Before rendering, it validates the complete frozen manifest, including the channel-bound
Compose project, gateway identity, and secret references. The render also requires exact database,
vault, config, and migration identity bindings
through the Compose `x-startup-identities` extension. Its promotion-mode graph contains only fixed
`api` and `database` service roles and field shapes; its complete volume set is exactly the
manifest's database and vault named volumes, mounted once on the role-specific protected targets
with a bounded mount shape. Host binds, additional services or named volumes, unknown mount
fields/options, other mount targets, runtime command, environment, env-file, label, config,
credential, and inline-secret surfaces are refused before they can enter the Compose hash or
output. Local-source mode accepts the explicit source overlay without promotion-only identity
extensions, records source SHA plus dirty state, and is
permanently `promotion_eligible=false`; its render cannot be admitted as a promotion candidate.
Candidate admission revalidates the rendered Compose against an independently supplied manifest,
so recomputing caller-controlled hashes cannot substitute another repository or resource binding.
This renderer does not publish an image, move a pin, restart a channel, or prove that a live host
runs the digest.

**Supersedes the bind-mount.** Once a channel runs a pinned image, a `git checkout`/`git pull` in the host tree no longer changes that channel's running code — by design. Deploying new code to a channel means building a new image, pushing it, bumping the pin, and recreating. The "pull without restart serves stale code" failure mode disappears because there is no live code mount to go stale.

## Root-owned image bake vs. host-uid-remapped runtime user (#2991, #3047)

Every channel's `api`/`worker`/`watcher`/`heimdal-capture-watch` service runs as `user: "${LOCAL_UID:-0}:${LOCAL_GID:-0}"` (`docker-compose.yaml`), populated from the host user via `scripts/export_runtime_env.sh` — not as `root`, and not as a fixed container uid. The image itself is built as `root` (`Dockerfile` has no `USER` directive), so every path `COPY . .` creates, and every directory that exists in the repo tree at build time, is `root:root`-owned in the resulting image.

For pinned channel deployments, `scripts/deploy_channel.sh` reads only the numeric `LOCAL_UID` and `LOCAL_GID` fields from the selected governed runtime env and exports them before its first Compose call. This gives Compose interpolation (including each service's `user:`) and `instance-state-init` the same process identity. The runtime env remains a service `env_file`, not Compose's CLI `--env-file`, so its DSNs and other runtime values are not interpolated into the deployment model. BWS deployments stop before pin or Docker mutation when the governed identity is missing, duplicated, malformed, or outside the supported UID/GID range; local use without a generated runtime env retains its host-identity fallback.

The systemd BWS deployment service runs as root to use its encrypted credentials and control Docker. Root is the deployment supervisor; host-global instance-ownership state remains owned by the validated `LOCAL_UID`/`LOCAL_GID`. The ownership directory stays canonical and mode `0700`. Its ledger lock, any recovery of a journaled key rotation, and ledger reads that produce deployment evidence run under that runtime identity, so ledger files remain private and runtime-owned. Host-produced MVR-05 fence plans are atomically delivered with mode `0600` and runtime ownership before the runtime one-shot reads them. New settings-rebind floor receipts are written with mode `0600` and runtime ownership; the root rollback guard also accepts an older private receipt that the previous supervisor wrote as `root:root`. An existing ownership directory with an unexpected owner is rejected before permissions or ownership are changed.

This is a structural mismatch: any code path that lazily creates a directory under `/app` at first use (`Path(...).mkdir(parents=True, exist_ok=True)`) fails with `PermissionError` under the non-root runtime uid unless that directory was pre-created **and** made writable by all uids at build time. Two runtime-writable surfaces have needed this treatment so far:

- **`/app/tmp`** — the shared scratch/heartbeat/outbox surface (#2991), also backed at runtime by the `runtime-tmp` named volume mounted into api/worker/watcher (mount does not imply ownership by itself; the Dockerfile still pre-creates and chmods the mount point so a fresh, unmounted `/app/tmp` — e.g. bare-metal or a container without the volume — is also writable).
- **`/app/runtime`** — the parent of every `runtime/<subdir>/...` receipt/state path defaulted by `app/**` modules (ask synthesis, expansion-gate, agent-memory, relevance, builderops, dispatcher, orientation, panel, proposals — `git grep 'Path("runtime/'`). None of these subdirectories are tracked in git (`.gitignore` lines 51-65), so `/app/runtime` does not exist in the image at all until first write; without the fix it fails the **first** `POST /api/ask` (or any other receipt-emitting request) on every freshly recreated container with `PermissionError: runtime/activation/ask_synthesis_receipts.jsonl` (#3047).

**Contract:** the `Dockerfile` bakes each such surface with `RUN mkdir -p /app/<path> && chmod 1777 /app/<path>` immediately after `COPY . .`. `chmod 1777` (world rwx + sticky bit) makes the directory writable and traversable by any uid while still preventing one uid from deleting another's files — the same property `/tmp` relies on system-wide. This is the general chokepoint for the defect class: a new root-owned runtime-writable path gets its own `mkdir -p && chmod 1777` line at that Dockerfile location rather than a bespoke per-module workaround. It applies identically to `dev`/`test`/`prod` because the image is byte-identical across channels (see the identity invariant above) — there is no per-channel variant of this fix.

## Gateways as managed units

Companion UI gateways must become **managed units** with deterministic recreate-on-deploy and restart-on-failure, retiring the ad-hoc `nohup`/shell-history launch.

Current reality: `scripts/lib/companion_ui_startup.sh` launches the gateway with `nohup … &`, writes a PID file, and curls `/healthz` to confirm liveness — but nothing supervises or restarts the process, and the launch lives in script + shell history rather than a declared unit. The dev/test gateways run `companion_ui.workspace.serve_dev_page`; prod runs `companion_ui.workspace.serve_production_page`; both render through `render_index_html`, so this is a deployment/supervision change, not a UI-behavior change.

Target contract (S4):
- **One declared unit per channel gateway.** Either containerize the gateway in the channel's compose project, or declare a `launchd` unit per channel. The unit owns host/port (`HOST`, `PORT`) and the API base URL (`COMPANION_API_BASE_URL`) exactly as the current startup script passes them. The production unit also carries the separate external host-publish declaration `COMPANION_UI_BIND_HOST`; its inside-container listener is not exposure authority.
- **Recreate-on-deploy.** A deploy recreates the gateway unit so it picks up the deployed image/code, in lockstep with the API recreate — never a half-deployed state where the API is new and the gateway is old.
- **Restart-on-failure.** The unit restarts the gateway if it exits (compose `restart: unless-stopped`, matching the API/db/worker services in `docker-compose.yaml`, or the `launchd` `KeepAlive` equivalent). A crashed gateway must come back without a human.
- **Source-of-truth.** The unit definition is committed; there is no "remember the nohup command" step. The per-channel wrappers (`start_niflheim_ui.sh` / `start_bifrost_ui.sh` / `start_midgard_ui.sh`) and doctor scripts are reconciled to invoke the managed unit rather than `nohup`.

The prod gateway keeps its safe default posture (`prod-ui` does not auto-start watchers/workers; write/automation-capable startup stays behind `PROD_UI_ENABLE_AUTOMATION=1`).

The managed Compose gateway forwards `COMPANION_API_TIMEOUT_SECONDS` to the UI's
general runtime client. The base default is `2.0` seconds; DEV and TEST overlays
explicitly set `30.0` seconds for workspace reads and capture transport. ASK uses
its separate `COMPANION_ASK_TIMEOUT_SECONDS` budget (default `120.0` seconds).
Production keeps the base environment setting until an operator authorizes a
configuration change through the deployment gate; its distinct production
entrypoint retains its existing client default and does not consume this selector.

Channel qualification must inspect the effective gateway environment and prove
the intended running image/SHA, a real note body, and a capture's matching runtime
acknowledgement and persisted material. `/healthz` alone establishes liveness.
A transport timeout can occur after the runtime has written a capture: reconcile
the material and receipt before deciding whether to retry. The gateway never
replays the write or converts a timeout into success; a reported post-write
acknowledgement failure remains `not_acknowledged`.

## Deploy procedure

The deploy procedure is the same shape for every channel; only the pin target and the migration-ack posture differ (`prod` is the strictest). It assumes the build-once/promote model above.

Repository support for native BWS source recovery (#5918) adds one fixed API-consumer one-shot
after instance-state finalization and migrations, before ordinary API/worker/watcher/capture/UI
recreation. The candidate image must contain `scripts/start_api.sh`'s source-only mode and
`app/ops/native_source_bootstrap.py`; upgrading only the host tooling cannot add that image code.
The run-only `channel:expected-SHA` selector grants no authority: the existing inherited worker
guard, API instance/ownership preflight, selected vault, migration authority and file-backed
PostgreSQL consumer remain required. The one-shot keeps the normal API command/bootstrap and
uses `--no-deps`, so an unready old API or UI health dependency cannot prevent reconstruction.

With the ordinary write-capable services stopped, the producer freshly checks Product readiness.
An explicitly unbound API retains its no-vault picker posture without a SourceAction. For a
configured missing, inaccessible or invalid root, the canonical resolver refuses before any
SourceWrite; it cannot select a foreign root or turn the configured error into an unbound API.
For a selected vault, an already usable projection skips source replay; otherwise the existing
`vault-alpha-ingest --max-notes 0 --force --source-backed-rebuild --json` SourceAction reconstructs
the complete selected inventory. All six counters must be present nonnegative integers,
`scanned == ingested`, and errors/malformed/locked/invalid counts must be zero. A fresh Product
readiness check and the existing strict index doctor must then pass. Missing summaries, partial
work, refused context or an unready index fail the operation; child streams stay private.
Ordinary service recreation and the existing final Data health, version, UI and receipt gates
still follow this step. Ordinary API startup clears the selector and retains migration→uvicorn.

The producer has a two-hour bound; its Docker CLI has sixty additional seconds. Timeout or a
normal termination signal stops
the owned process group. Before restarting any runtime writer, cleanup freshly revalidates the
native operation guard and proves absence or stoppage of the exact API one-shot, checking its
name, project, service, one-off flag, operation ID and target SHA before termination. Unknown
ownership or quiescence retains the target pin and pending operation. Same-ID reconciliation
also checks daemon-owned one-offs omitted by `compose ps`; it never replays activation.
Existing migration markers, forward-only target retention and rollback floors still apply.
This is repository support and deterministic proof; live DEV/TEST/PROD corpus qualification
and functional acceptance remain separate operator work.

Before the first mutable step—and during `--dry-run`—the deploy entrypoint performs a read-only TTS
configuration preflight against the generated runtime-env file selected by the channel deploy
configuration. The canonical generator builds the whole file in a same-directory temporary and
atomically replaces the live path; preflight opens and parses one immutable snapshot and fail-closes
read or parse failures. It never sources, rewrites, or prints that file. `TTS_ENABLED` is pinned over
any caller-shell value and must be unset or exactly `false`/`true`; an enabled channel also requires
`TTS_HOST_ROOT` to classify as an accessible absolute directory outside the repository. The same
validated snapshot is forwarded in the Compose process environment to the existing `/data/tts`
mount and `TTS_ENABLED` binding, never in command arguments and never by passing the runtime-env
file as Compose's CLI `--env-file`. The bind sets `create_host_path: false`, so disappearance after
validation fails instead of creating an empty host directory. Governed Compose child output is
captured privately: only validated container IDs needed by internal probes may cross the wrapper,
while other successes stay quiet and failures emit a fixed redacted receipt. Status and failure
output therefore contains selector names, boolean state, reason code, path class, and fixed command
result only. Disabled/unset channels use the tracked empty `config/tts-disabled` fallback and require
no machine-local TTS root. The check is deploy-only: rollback clears stale caller TTS selectors,
pins the disabled fallback without validating the missing root, and remains unconditionally
reachable through its existing contract.

The HAR-03 archive gate is opt-in for production. When the channel-local `.env.prod.local` file
does not declare `HEIMDAL_ARCHIVE_METADATA_FILE` (and no ambient declaration is supplied), the
deploy/startup preflight reports `not configured` and continues; the current prod release does not
need an archive volume. Once archive metadata is declared, the same preflight remains fail-closed
and requires the already-mounted, identity-verified volume before any prod mutation. A present but
malformed or unreadable channel config is also fail-closed and is never treated as absence. Archive
operations themselves continue to fail closed without a verified binding.

1. **Pin the ref.** Resolve the commit SHA to deploy and its already-built image tag (`ghcr.io/<owner>/pkm-app:<sha>`). For `prod`, the SHA must be the one authorized by the promotion-plan contract in `docs/RELEASE_CHANNELS/README.md` (the `stable`-ref decision; see also #2527). Update the channel's deploy-pin file to that tag.
2. **Migration gate (classification for every channel; operator acknowledgment for prod).** Diff the migrations between the currently-running SHA and the target SHA and classify each per `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`. Record reversible and forward-only migrations in the deploy receipt for every channel. A forward-only classification describes recovery behavior; it does not by itself require an operator decision for `dev` or `test`. On every PROD deploy, a read-only pre-writer-stop probe runs the resolved candidate image's migration graph against `pkm-prod/app`; an explicit, target-bound operator acknowledgment is required before writer stop only when that live database has a pending forward-only migration. Changed classification metadata for an already-applied migration remains in the receipt but does not by itself require an acknowledgment. Reversible migrations proceed under the standard gate. DEV/TEST retain their channel-scoped migration and recovery behavior without inheriting PROD's acknowledgment gate.
3. **Quiesce/finalize instance state, then execute changed migrations.** Pull the pinned image. For a deploy, `scripts/deploy_channel.sh` runs the instance-state deployment producer before migration execution: it holds the host-global fence and derives the stop set from every enabled Compose service with `depends_on: db`, excluding only the unique `run_migrations.sh` authority. The same host-wide inventory also detects native DB/outbox processes. Before ledger migration, floor admission validates the derived fence plan and any existing floor receipt. On a retained host whose authenticated ownership ledger is still schema-v1, admission uses the proved host inventory and existing registry-consistency seam before writing the floor. For a populated registry, the complete owner inventory must exactly match the registered bindings and authenticated ledger fields; missing, extra, or mismatched owners fail closed before the ledger or registry is changed. When the schema-v1 ledger contains retired bindings, the quiescence-bound receipt also carries host-captured root and ancestor identities. Each row must match its registry tombstone or authenticated transfer lineage; missing, replaced, extra, or mismatched retired roots stop before migration. The receipt digest and stable two-probe comparison cover these rows. An exact match may converge the ledger to the current schema, and this operation never activates registry authority. If interrupted after redundant v1-journal cleanup but before the atomic v2 write, the original v1 ledger remains retryable under the same fences. If interrupted after the v2 write and journal cleanup but before floor recording, retry still requires a fresh quiescence proof and digest-bound live-owner inventory. Current v2 inventory need not reconstruct historical retired roots, but registry tombstone paths and any transfer lineage must still match the authenticated ledger. A committed v2 ledger with a surviving v1 rotation journal is checked against the current registry and complete owner inventory before that journal is consumed; an unmatched journal remains fail-closed. The procedure then records the irreversible `minimumRuntimeSchema: mvr-05` floor and its fence receipt before finalizing the protected instance-state boundary, stops every runtime writer again, and runs the target image's one-shot migration service before any target runtime is recreated. When the migration diff is non-empty, the executor writes a durable pending-migration marker before mutating the pin. If the live PROD probe finds pending forward-only work with an empty diff, it also writes the marker and runs the explicit migrator so the same-target retry path retains that migration epoch. The marker binds the source SHA (or explicit no-baseline sentinel), target SHA, and forward-only acknowledgement; it is removed only after the migration service reports success.
4. **Recreate the channel runtime.** Only after instance-state finalization and migration execution succeed, recreate the channel's API, worker, watcher, Companion UI, and gateway unit against the pinned image. Include `heimdal-capture-watch` only when the governed runtime env declares a non-empty `HEIMDAL_CAPTURE_WATCH_DIR`; otherwise stop any old capture watcher and deploy the core runtime without pulling or starting it. A configured capture watcher remains subject to the strict host-secret and health gates. `scripts/deploy_channel.sh` reads the channel's generated runtime-env reference without sourcing, copying, regenerating, rewriting, or printing it. It pins that governed reference plus the preflighted `TTS_ENABLED` / `TTS_HOST_ROOT` snapshot and parsed `VAULT_HOST_ROOT` selector into the Compose process, so caller-shell values cannot replace them and runtime DSNs never participate in Compose interpolation. For each invocation, the wrapper separately resolves, reachability-validates, and where needed translates `SIGNBOARD_ROOT`, then injects it—or explicitly clears a stale value when no valid root resolves—through an API-only Compose override document delivered via a private (mode-0600, wrapper-owned) temp file removed on return, rather than the wrapper's own stdin, so a caller piping real data into the wrapper (#4536) still reaches the container. The override document itself carries no operator path or secret — only the bare `SIGNBOARD_ROOT:` key, whose value Compose forwards from this governed shell's environment — so writing it to a temp file does not weaken the runtime env ownership boundary. This leaves the runtime env and its `VAULT_ROOT` / `VAULT_HOST_ROOT` binding unchanged; `docs/AGENT_ISSUE_DISPATCHER.md :: Local visual Signboard` owns the detailed resolution, translation, and fail-visible no-vault contract. For ordinary deploy-selected Compose overlays, when the governed vault selector is already reachable through the base same-path `/Users` or `/Volumes` mounts, deploy and rollback append `docker-compose.full-host-vault.yml` and bind runtime selectors to that one container path; they do not add the duplicate legacy `/app/vault` mount. That selected-root bind is runtime-only: it is writable for `api`, `worker`, `watcher`, and `heimdal-capture-watch`, while `instance-state-init` receives no selected-vault mount. The explicit MVR-01C authority-cutover command is the qualified exception; it mounts the already-authorized `MVR01C_ROLLBACK_VAULT_ROOT` read-only at `/app/selected-vault` for that command only. During fenced instance-state admission, only the registry-consistency path may migrate authenticated schema-v1 ownership state to schema v2: it authenticates complete owner fields against the registry/inventory and proves either the full legacy/converged chain or the stable `/Users`/`/Volumes` ancestor segment before replacing only ancestor fingerprints. Direct loads, malformed, unknown, inaccessible, or unauthenticated state refuse without rewriting the ledger or key. Other explicit sources retain `docker-compose.legacy-vault.yml` compatibility. TEST appends `docker-compose.test-vault.yml` last so its watcher is activated against whichever one container path the access overlay selected. With no explicit vault, no vault overlay is selected and the base+channel no-vault posture remains intact. Because routes load at container start, the recreate—not a file update—is what makes new code live. Recreate API and gateway together so they never diverge in version.
   For that schema-v1 convergence, “authenticated” means complete mutable owner fields match the registry and proof-bound host inventory, and the ancestor chain matches either the host-captured legacy inode chain, the complete HMAC set for every canonical path ancestor in that same inventory with exact cardinality, or the key-authenticated stable `/Users`/`/Volumes` segment. In mount-blind MVR-05, a complete path-bound chain is consistency evidence only and still requires the channel, binding, sealed root, and root fingerprint to match; it does not create ownership authority. A partial, altered, mixed, or merely hex-shaped chain refuses before any ledger or key rewrite.
   On Linux hosts, a canonical selected vault nested beneath `/srv` selects the same full-host overlay at its exact path; the wrapper does not mount `/srv` itself.
5. **Health gate: liveness first, readiness second.** Block until the channel's API `/healthz` returns `{"ok": true}` (`app/api/routes/health_contract.py`) and then require both readiness probes on the channel's ports: `/readyz` must pass, and `/api/health` must report `required_ok: true`. `/healthz` is only a liveness probe; deploy completion requires readiness evidence that startup dependencies, DB connectivity, and the deployed code path are actually usable. The gateway's own `/healthz` must also respond. A deploy is not "done" until liveness and both readiness predicates pass; a failing gate triggers §Rollback.
6. **Complete every post-mutation gate, then record the deployed SHA.** Confirm `/version` (`{git_sha, built_at}`) and the `version` field on `/api/health` report the SHA just deployed; require the fleet-model fitness check and Companion UI smoke to pass, and require capture-watch health only when `HEIMDAL_CAPTURE_WATCH_DIR` is configured. With capture unconfigured, report the gate as skipped and keep the core runtime deployable. Then record the deploy receipt (and `ops/promotions/` for prod, per the promotion contract). The successful receipt is the final gate and is not written while any earlier required gate is unresolved. This closes the loop opened by #2602: the marker is only trustworthy once the bind-mount is retired (S5) and the image artifact has been made immutable by digest pinning or explicit SHA-tag enforcement, so S5 must land before the SHA in `/version` can be treated as authoritative for what is running.

Before migration execution begins, a pending marker makes interruption recovery fail closed: a retry must target the marker's exact SHA, revalidate the recorded source-to-target migration classification and forward-only acknowledgement, and cannot deploy a different target until the marker is reconciled. After migration execution begins, a nonzero result is possibly committed even when the migration container did not report success. The executor therefore retains both the pending marker and the schema-compatible target pin rather than recreating a possibly schema-incompatible previous image. For reversible migrations, reconcile the database revision and use the governed rollback path if reversal is proved and appropriate; for forward-only migrations, prove the revision is unchanged or apply a compatible forward fix. In either case, the migration is never auto-reversed by the deploy hot path.

For failures before migration execution starts, the ordinary fail-closed recovery path preserves the failing gate's original non-zero status and diagnostics, restores the previous pin, and attempts to recreate the prior service set before returning. The instance-state fence remains in place if its finalization fails, so consumer preflight refuses restart.

## Linux channel secret provisioning

The empty-data exception is bound to the effective managed `db:5432` target and its default `app` role/channel database, without connection-option overrides. An empty local volume never proves an external or overridden target empty: these targets require real password authentication and cannot bootstrap a new BWS password. External-target authentication and activation never start or stop the unrelated local database. The supervisor binds the Compose topology to the same effective target. For external targets, the dedicated overlay removes only local `db` dependency edges and excludes its service/volume from the selected graph, while preserving migration, instance-state, and provider dependencies. Ambient profiles cannot re-enable the excluded database; the inherited worker guard refuses a missing or mismatched topology selector before provider access. The governed BWS prod outbox-retry preflight uses the same file-aware resolver and host endpoint translation; invalid or missing file/connection configuration blocks deployment before pins or Compose mutation. After connection resolution, the existing #3903 policy for genuinely unavailable databases or queries remains in force, including first initialization; a successfully queried terminal-pending row blocks deployment. Legacy non-BWS behavior is unchanged.


BWS-04 adds a governed Linux adapter around the existing channel deploy, migration, writer, and
pin machinery. It does not authorize a live deploy or replace promotion/migration acknowledgement.
Mac Keychain deployment remains unchanged. BWS-03 / #5679's repository token-push command was
delivered by PR #5732; parent #5667 stays open for live VM installation, existing-host migration,
owner-approved sole-writer/credential-restriction or shared-fencing evidence, and channel qualification.

### Proposed dev/test producer and bootstrap qualification map (Issue #5855)

The following is the value-free repository path to qualify before any live operator action. It is a
proposal only; the linked tests prove repository behavior with fake or redacted evidence and do not
prove BWS permissions, token installation, host cleanup, deployment, or live channel health.

| Journey stage | Actual producer / entrypoint | Required preconditions and coupling | Checked-in evidence and remaining gap |
| --- | --- | --- | --- |
| Identity and selected-consumer preflight | `scripts/secrets check <dev\|test> --consumer <name>`; `python3 -m app.ops.host_secret_bootstrap --provider bws --check --channel <dev\|test> --consumer <name>` | Explicit channel and provider; `config/secrets/host_secret_contract.json` allowlist; reader credential at the declared systemd credential path; selected project/consumer binding; no child command for `--check`. | `tests/ops/test_secret_admin.py` selected-set/optional/malformed checks and `tests/ops/test_host_secret_bootstrap.py` scoped identity, token-file, redaction, and lock tests. Live reader permissions and MARR binding remain #5667. |
| Normal writer / missing-copy recovery | `scripts/secrets import <channel> <secret> --stdin`; `SecretAdmin.import_stdin` through `HostSecretController` | Value arrives only on stdin; the controller lock is held; both project pre-states or absence tombstones and the prepared operation record are fsynced before the first provider write; shared values are read back before terminal commit. | `tests/ops/test_secret_admin.py` stdin, parity, history, partial-failure, and unknown-outcome tests. The one-normal-writer restriction and human-admin boundary require the #5667 owner decision and redacted live evidence. |
| VM reader-token recovery | `scripts/secrets push-token <vm>`; the `bws_token_push` actions (`token-push-inspect`, `token-push`, `token-push-worker`, `token-push-status`) via the installed `yggdrasil-bws-deploy` launcher | Existing target mapping; root-owned supervised launcher and systemd credential contract; stdin-only token handoff; same operation ID, generation, per-channel lock, and durable remote terminal receipt; no SSH-session ownership assumption. | `tests/deploy/test_secret_token_push.py` covers stdin/redaction, generation, lock, worker, systemd binding, and terminality. Live encrypted credential installation and VM qualification remain #5667. |
| Existing-password dev/test deployment | `python3 -m app.ops.postgres_deploy_host <channel> <revision> --existing-secrets-only` | Existing selected PostgreSQL password must pass host and VM checks before remote or local mutation; request mode is journal-bound before RPC; no BWS bootstrap is allowed; promotion/migration acknowledgement and target identity still come from this document and release-channel owners. | `tests/deploy/test_deploy_channel_script.py` and `tests/deploy/test_deploy_channel.py` cover preflight ordering, file-backed secret use, and target coupling. Live VM/Compose readiness remains #4913 and #5667. |
| Interrupted existing-secrets-only deployment | `python3 -m app.ops.postgres_deploy_host <channel> <exact-request-revision> --existing-secrets-only --reconcile-pending [--ack-forward-only]` | Use the revision and forward-only acknowledgement from the exact persisted request. The authenticated same-ID RPC refuses a live worker, mismatched request or receipt, held channel lock, malformed lock state, or non-quiescent Compose state, including a still-running `migrate` or `instance-state-init` one-shot. It records `failed` only after the worker ended and the existing lock is acquired; reconciliation changes no pin, migration marker, container, database, vault, or BWS value. | `tests/deploy/test_deploy_channel_script.py::test_failed_bws_activation_reconciles_only_after_worker_and_channel_quiescence`, `::test_failed_bws_activation_reconciliation_preserves_ambiguous_state`, `::test_linux_quiescence_waits_for_one_shot_compose_services`, and `::test_host_reconciles_matching_failed_bws_deploy_receipt` cover the receipt and refusal boundaries. |
| First initialization / recovery | The same host entrypoint without `--existing-secrets-only`, supervised by `scripts/postgres_deploy_service.py` and `app.ops.postgres_deploy_linux` | Only an actually empty managed database directory qualifies; agent-host and VM locks are acquired in order; absence tombstone and prepared ID are durable; one generated value is written and marker/readback verified before deployment-state mutation. The host config JSON is opened as a root-owned regular `0600` file with `O_NOFOLLOW` and a single-link check; its configured runtime-env reference must be absolute and regular. Pending-marker parsing rejects symlinked, non-regular, unreadable, or malformed markers on the Linux preflight, while an absent marker is the documented no-pending baseline. Generated runtime env is published through a private temporary file and rename. The managed root/data paths must be absolute and non-symlinked; the source directory must be an absolute root-owned `0700` tmpfs path, and the password source must be root-owned `0440` with the configured service group; the file-backed consumer map must match. | `tests/deploy/test_deploy_channel.py::test_postgres_secret_source_uses_root_only_tmpfs_and_service_gid`, `::test_postgres_secret_is_readable_by_configured_non_root_service_user`, `::test_bws_runtime_export_produces_only_credential_free_database_defaults`, and `tests/ops/test_host_secret_bootstrap.py::test_runtime_secret_reader_rejects_unsafe_files` cover related source/runtime-file protections; `::test_missing_bws_access_token_file_fails_before_provider_request` covers token-file fail-closed behavior. No focused test currently exercises the Linux host-config JSON, pending-marker symlink branches, or atomic runtime-env publication; that qualification gap remains with #5667/#4913. |
| Channel wrapper / end-to-end acceptance | `scripts/deploy_channel.sh <channel>` with `scripts/export_runtime_env.sh` and the BWS guard | Request-bound candidate and migration acknowledgement; explicit channel environment; `/etc/yggdrasil/bws-deploy/<channel>.json`; selected capture-watch/raw-migration consumers; BWS guard before temporary state, pin, or Docker mutation; first healthy release and rollback receipts remain authoritative. | `tests/deploy/test_deploy_channel_script.py` and `tests/deploy/test_deploy_channel.py` cover ordering and failure isolation. Startup receipt and immutable target coupling remain #4913; TARS host/executor qualification remains #5052. |

The concrete qualification follow-ups are therefore existing authorities: #5667 owns BWS
entitlement, live permissions, credential restriction or shared fencing, VM token installation, and
channel qualification; #4913 owns startup/target receipt gating and first-healthy-release/rollback
acceptance; #5052 owns the TARS host and Linux executor boundary. No new registry, dashboard, or
duplicate implementation issue is needed. The request-bound migration acknowledgment at
`816cb6f3a3569e145d28701851fc2b067cf7c627` remains a prerequisite and is not replaced by this map.

The designated agent-host entrypoint is `python3 -m app.ops.postgres_deploy_host <channel> <revision>`.
It uses the same BWS controller lock as import/check before selected-consumer parity checks, then
contacts only `ygg-<channel>` with value-free requests. For a Product deployment that may only read
existing BWS values, pass `--existing-secrets-only`. The selected checks still run; a missing
PostgreSQL password refuses before any RPC or remote deployment mutation. The host operation journal
binds this mode before the first RPC, so a same-ID retry cannot switch into bootstrap. This read-only
deployment does not require the BWS writer-qualification receipt. If first-init bootstrap is
explicitly allowed and the password is missing, the owner-installed `qualification.json` remains
required before the first RPC; it must be owner-only (`0600`) and record the exact `controller` path,
`sole_writer_approved: true`, `credentials_restricted: true`, and a `live_receipt` comment on #5667.
No CLI flag creates this approval. The admin token remains on the agent host.

After a host session restart, the same invocation recovers missing `BWS_ORGANIZATION_ID`,
`BWS_NON_PROD_PROJECT_ID`, and `BWS_PROD_PROJECT_ID` from the installed canonical
`/etc/yggdrasil/bws-deploy/<channel>.json` on `ygg-dev`, `ygg-test`, and `ygg-prod`.
For example, `python3 -m app.ops.postgres_deploy_host test <authorized-revision>
--existing-secrets-only` needs no metadata exports when those protected sources are available.
Complete explicit metadata remains supported without remote reads; any supplied partial metadata
must match the installed mapping. The host requires canonical UUIDs, one organization, the same
dev/test non-prod project, and a distinct prod project before constructing the admin client.

This fallback uses only strict host-key SSH, noninteractive sudo, and a bounded read-only Python
reader with a 20-second timeout per alias. It checks root-owned, non-writable, nonsymlink directory
ancestry and a root-owned, single-link, regular `0600` channel file no larger than 64 KiB. It accepts
only the existing channel-config fields and returns only organization/project metadata. Unavailable
SSH, unsafe files, malformed or unexpected output, and conflicting mappings refuse before operation
admission with the existing value-free diagnostic. Metadata stays in process memory; the fallback
does not load runtime env or token files, mutate `os.environ`, persist configuration, or contact BWS.
Keychain authentication, selected-consumer checks, the host controller, VM journal/lock, exact
request reconciliation, existing-secrets-only mode, and bootstrap/prod acknowledgment gates retain
their existing authority. Repository tests establish this recovery path; live channel qualification
remains with #5667.

When such a deployment remains pending after its supervised worker has ended, reconcile only the
same operation using its exact request revision and original `--ack-forward-only` choice. The
`--reconcile-pending` command is limited to a pending `--existing-secrets-only` operation and asks
the remote supervisor for authenticated terminal evidence under the same operation ID. Ordinary
same-ID `prepare`, `activate`, or `join` retries run the same lock-reconciliation proof before they
return an existing `failed` receipt, so a receipt cannot clear host state while a retained lock still
blocks the channel. A `failed` receipt means deployment was not verified and effects may need the
normal deployment reconciliation;
it does not mean the deployment was rolled back or that no effects occurred. The supervisor requires
the worker to be inactive, the existing per-channel lock to be available, and Compose state to be
quiescent before writing that receipt. Any unavailable or mismatched proof leaves the local operation
pending. A later deploy uses a new operation ID and still runs the regular candidate, migration,
backup, and health gates.

The root-owned `config/systemd/yggdrasil-bws-deploy@.service` and installed
`scripts/postgres_deploy_service.py` launcher supervise VM work independently of SSH. Operator setup
runs `sudo scripts/install_bws_deploy_runtime.sh` from the checkout. That idempotent command
requires Python 3.12 or newer, creates or updates `/opt/yggdrasil/bws-deploy-runtime` from the
pinned `requirements-bws-deploy.txt` manifest, imports the BWS SDK, PostgreSQL driver, YAML, pytest,
Playwright, Linux supervisor, and the real retrieval-tuning module through that runtime, then
provisions Playwright's matching Chromium headless shell with `playwright install --only-shell
chromium` in `/opt/yggdrasil/bws-deploy-runtime/browsers`. Setup runs the unchanged mandatory
Companion browser preflight: actual `chromium.launch()` and collection of the exact
`tests/companion_ui/test_companion_ui_live_smoke.py` command. Collection retains the intentional
unset-URL module skip and refuses an empty/deselected collection without that skip. The explicit
tuning import covers the existing live pytest fixture's import closure without changing the fixture
or running live smoke. Only after every check passes does setup install the root-owned launcher at
`/usr/local/libexec/yggdrasil-bws-deploy` with the matching interpreter path. The service and RPC
launcher use that interpreter; it is one shared runtime for the host's dev, test, and prod channels.
The canonical service keeps `StandardOutput=null` and `StandardError=null` so raw SDK and child
streams never become journal entries. A failed deploy child's finite allowlisted stage and
`command_failed` class are sent directly to `/run/systemd/journal/socket` as one nonblocking native
datagram containing only `MESSAGE`, fixed `PRIORITY`, and fixed `SYSLOG_IDENTIFIER`. The journal
derives its trusted unit metadata; callers supply no trusted fields, raw output, arguments,
environment, endpoints, paths, or secret values. Socket absence, refusal, or saturation remains
best-effort diagnostic loss and never changes the original refusal, pending operation, lock, or
same-ID reconciliation authority. Repository tests prove the null-stream/Unix-socket boundary;
Live qualification establishes visibility and unit attribution in the existing service namespace
after an authorized host-tool update; code merge alone does not establish that proof.
Managed deployment children receive `PYTHON` bound to the running supervisor's `sys.executable`,
including the deploy shell's inherited guard and every guarded Compose call. The interpreter's bin
directory is prepended to child `PATH`, so bare `python3` inventory and Signboard calls use the same
runtime. Child `PLAYWRIGHT_BROWSERS_PATH` selects that runtime's `browsers` directory; ambient
interpreter and browser-cache selections are replaced on this managed path. The manifest reuses the
application's existing PyYAML, pytest, Pydantic/core and settings pins and narrowly pins their
required imports plus Playwright 1.63.0 (Chromium headless-shell revision 1243). No full application
or ML dependency graph is installed. This host control runtime is installed
independently of the authorized application image; updating it does not select a new application
candidate or authorize a channel deployment, credential/grant change, or migration acknowledgment.
Re-run it after changing the manifest, with no deployment operation in flight, then restart every
active supervisor instance before starting another operation. If dependency installation or its
import/browser/collection check fails, keep supervisor work idle and rerun setup after correcting the runtime issue;
the launcher is installed only after the checks pass. The setup does not install packages into
system Python or install OS libraries. Infrastructure owns prerequisite browser OS libraries;
missing libraries or an unavailable payload fail clearly before launcher publication and require
an authorized host repair. Setup never invokes Playwright's `--with-deps` or `install-deps` modes.

Operator setup then creates an owner-only (`root:root`, `0600`)
`/etc/yggdrasil/bws-deploy/<channel>.json` containing the root-owned, non-writable checkout `root`,
actual existing named-volume `data_directory`, non-root service `uid`/`gid`, `organization_id`,
channel-project `project_id`, and an absolute `runtime_env_file` path to that channel's generated
runtime environment. The service validates this path as a readable regular file and refuses a new
operation before admission if the root config changed since service startup. Apply config changes
only with no deployment in flight, then restart the service before starting another operation. The
service uses the same selected file for database inputs, active-consumer selection, and the
supervised channel deploy. The deploy shell receives it through `BWS_DEPLOY_RUNTIME_ENV_FILE`; local non-BWS
deployments continue to resolve the path from the channel pin or its existing default. The runtime
environment remains a Compose service `env_file`, never the CLI `--env-file`. The service consumes
only the project reader credential at the BWS-03
stable encrypted source `/var/lib/yggdrasil/bws-tokens/<channel>/current`. The config must name the
actual channel volume; a missing volume, foreign/anonymous existing mount, or unproved data directory
is refused. This task neither provisions volumes nor migrates retained plaintext/anonymous data.

Host and VM selected-secret preflights precede deployment mutation. Under the host lock followed by
the existing VM channel lock, the worker writes an owner-only persistent journal in
`/var/lib/yggdrasil/bws-deploy`, outside Git and tmpfs. Stages are `prepared`, `preflighted`,
`materialized`, optional `authenticating`, `activating`, then `committed` or `aborted`. Atomic file
and parent-directory fsyncs make each stage durable; a separate value-free request binding prevents
same-ID retries from changing revision or consumer scope. Reconnect joins the same worker. After
worker loss, missing terminal/quiescence proof stays pending; a released kernel lock is not success
and does not remove the channel admission directory.

For initialized data, the candidate must authenticate to the active PostgreSQL role with real
password authentication. The probe and Compose share one effective credential-free connection snapshot:
process overrides precede deploy-pin values, then generated runtime values; within each source
`DATABASE_URL` precedes `DB_DSN`. The selected role, database, host and connection options are
preserved. Only Compose `db:5432` is translated to its channel's host-published TCP endpoint, with
`hostaddr` retaining the original host for TLS identity checks. Ambiguous container-loopback
endpoints cannot borrow a host-loopback proof and fail closed. A changed effective target during
the operation invalidates admission; both runtime DSN aliases receive the same frozen value. After preflights, a stopped database may be started alone with `--no-deps`
only after durable `authenticating`; its recovery/WAL writes count as deployment mutation. No new or
recreated migration/application clients start before authentication succeeds. Wrong-password failure
preserves a pre-existing running database, stops only a database started by the probe, and records
`aborted` only after quiescence. Unknown outcomes stay pending. First initialization alone permits
an absent BWS password, after locked empty-directory proof and durable absence/prepared history;
an ambiguous sent create cannot be retried merely because its readback is missing.

`docker-compose.bws.yml` is appended only on this managed path. It mounts
`/run/yggdrasil/postgres/<channel>/password` solely into `db`, `migrate`, `api`, `worker`, `watcher`,
and `heimdal-capture-watch`. The root-only tmpfs directory is `0700`; the file is root-owned `0440`
with the configured service GID, verified through a non-root read probe. Compose bind-mount mode
attributes are not relied on. Repeated materialization keeps the same inode and refuses a changed
value while consumers could retain an old mount. Docker auto-restart is disabled for these services:
after host boot the supervisor waits for an authorized managed start, which rehydrates before
consumers start. `ExecStopPost` removes the source only after every consumer stops and Docker is
quiescent; returning from Compose does not clean it. No persistent PostgreSQL password/env file is
created. Other declared consumer environment handoffs are private tmpfs files removed after activation.

A pending Heimdal raw-store migration rechecks its selected credential through the inherited
supervised BWS guard; it never enters the Mac-only child-launch wrapper. The migration consumer may
proceed when the key is absent, because HAR-02 locks the source table and reads the key only when
legacy rows exist. Missing-key refusal for non-empty data occurs inside the transactional migration,
which preserves the legacy schema and encrypted bytes. Configured capture-watch remains a required
key consumer.

The runtime exporter validates BWS direct DSNs before loading them and supplies credential-free
channel defaults. `DATABASE_PASSWORD_FILE` is the sole application password source, resolved in
memory by the shared app/config/DSN/Alembic/direct-client path. Candidate images must declare the
file-credential protocol before admission; every client start/recreate, including automatic rollback,
rechecks the effective pin and refuses a legacy image that lacks that protocol. Such a refused
rollback leaves the deployment pending for compatible-image recovery. The PostgreSQL
wrapper preserves upstream initialization but scrubs both password environment variables from
`pg_ctl` and the final server exec. Repository evidence uses fake values/adapters and static Compose
rendering. It does not establish installation, runtime operation, or live qualification.

## Promotion workflow binding

The governed executor skills for this deploy procedure are `.codex/skills/prepare-promotion/SKILL.md`,
`.codex/skills/execute-promotion/SKILL.md`, `.codex/skills/verify-promotion/SKILL.md`,
`.codex/skills/rollback-promotion/SKILL.md`, `.codex/skills/promote-to-test/SKILL.md`, and
`.codex/skills/promote-test-to-prod/SKILL.md`. Those skills decide when a channel is still in
checkout mode versus pinned-image mode and, after a channel's cutover receipt exists, route physical
execution through `scripts/deploy_channel.sh` so this document remains the owner of pin bump,
migration gate, recreate, health gate, UI smoke, and deploy/rollback receipt semantics.

## Rollback procedure

Rollback reuses the deploy mechanism in reverse, against the previous known-good pin.

1. **Resolve previous-good pin.** Identify the channel's previous known-good image tag (the prior deploy-pin value; for `prod`, the previous `stable` SHA per `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`).
2. **Migration reversal (reversible only).** Reverse only migrations classified reversible. **Forward-only migrations are not auto-reversed** — if the failed deploy applied a forward-only migration, rollback of code can still proceed, but the schema state and any data implications are an operator decision (this is exactly why step 2 of the deploy gates on forward-only ack). Vault content is immutable across rollback.
3. **Recreate against the previous pin.** Bump the channel pin back to the previous tag and recreate API + gateway (same mechanism as deploy step 3). No rebuild — the previous image already exists in the registry.
4. **Health gate + record.** Re-run the §Deploy liveness/readiness gate, confirm `/readyz` passes and `/api/health.required_ok` is `true`, and confirm `/version` now reports the rolled-back SHA. Record the rollback receipt.

Rollback is a tag-bump + recreate because images are immutable and retained in the registry — the same property that makes promotion cheap makes rollback cheap.

Once a manual rollback has selected and pinned the previous known-good target, failure handling follows the actual service state. If image pull or service recreate fails before the target service set is established, the executor restores the pre-rollback pin and recreates that service set so pin and runtime identity do not diverge. After the rollback target has been recreated successfully, a later verification-gate failure preserves that failure's status and diagnostics and retains the rollback target; it does not automatically restore the pre-rollback candidate that the operator is trying to leave. A successful rollback receipt is still withheld until every required gate passes.

## Minimum runtime schema floor (MVR-05A, shipped)

MVR-05A8 (#4582) seals the binding-keyed DB/outbox cutover at `minimumRuntimeSchema: mvr-05`.
The deployment producer discovers the current DB-client population from Compose, keeps `migrate`
as the sole migration authority, stops every other derived client, and consumes the existing
host-global quiescence proof before writing the floor. The floor is therefore durable before the
first binding-keyed migration/write. An older scalar image is not a rollback target: scalar
preflight refuses it before database or queue startup, and recovery is a compatible roll-forward.
Later deployments re-derive and prove their current client population; the initial cutover receipt
remains immutable evidence rather than a hand-maintained service list.

MVR-05A8 derives that population from the effective channel Compose graph, not the base file alone.
The deployment boundary keeps raw `config` output in a private temp file; the governed channel
wrapper may write the same redacted handoff directly. The fence receives only a mode-0600 projection
of service names, DB roles, dependencies, and the migration-runner command, never resolved
environment or mount values. Every service declares one DB role in Compose;
an added or overlay-enabled service without a role fails closed. After the declared clients stop,
the wrapper also requires two consecutive empty
`pg_stat_activity` client-session snapshots before accepting the host process proof or recording the
irreversible `minimumRuntimeSchema: mvr-05` floor.

## Minimum runtime principal floor (MVR-03, shipped)

MVR-03 (#3857) introduces a durable private delegated operator-role record and, with it, a
runtime floor that constrains which images may run. This section records the shipped floor,
the compatible rollback/roll-forward images, and the operator preflight.

**Shipped floor.** `runtimeFloors.minimumRuntimePrincipal = "mvr-03"`, written into the
existing MVR-01 `runtimeFloors` extension slot on the instance vault registry — not a second
floor mechanism. Written by `app/instance/principal_fence.py::record_principal_floor`; read
by `app/instance/runtime.py::_require_runtime_floor`.

**Cutover order (enforced, not merely documented).** MVR-03 runs inside MVR-01B's *existing*
stopped window in `scripts/lib/instance_state_deployment.sh` — the same window MVR-01C's
`authority-cutover` uses. It does not add a second drain, probe, or inventory mechanism,
because its auth producers are the same processes MVR-01B already fences:

1. The wrapper installs the durable restart fence (`deployment-begin`) and stops `api`,
   `worker`, `watcher`, `heimdal-capture-watch`.
2. `scripts/instance_state_writer_inventory.py prove-quiescent` probes production truth twice
   and `deployment-prove` binds the proof to the channel lease.
3. `principal-cutover` performs the floor and role stages in one runtime process. It requires
   the lease in `proved` phase for this channel and nonce, consumes the quiescence proof plus
   the drained legacy-owner inventory, enumerates `docker-compose.yaml` (failing closed on any
   unclassified service), and adds the producers MVR-01B does not classify — the Companion
   proxy, credential rotation, the headless CLI, and bootstrap/init. Only then does it record
   the floor, re-prove the same lease and registry revision, and bootstrap the role.
4. `deployment-finish` closes the window.

`require_complete_fence` refuses step 3 if the inventory is incomplete, if writers were not
drained, if the inventory was not revalidated after quiescence, if it was probed once, if any
producer role is missing, or if operations are not fenced. `principal-cutover` also refuses
without the proved deployment lease for this channel and nonce, and it preflights the auth
posture before the floor write. The fact that this invocation advanced the floor is held only
in process, never accepted from a caller flag. If bootstrap fails before a role record becomes
durable, the failed-bootstrap role recheck and removal of that attempt's MVR-03 floor and fence
run under the same principal-store lock used by the bootstrap floor guard and first-role write,
before the wrapper releases the stopped window. A pre-existing floor is never eligible
for compensation. If a complete matching role became durable before a later bootstrap step
failed, it is never rolled back or reported as success. That case, an unreadable registry,
changed lease, any other ambiguous role state, or failed compensation returns the distinct
fail-closed status `75`; the wrapper preserves the lease/restart fence for repair instead of
restarting old producers. No numeric child status authorizes release: Compose can return the same
status as the runtime without executing it. A clean failure instead writes a private, HMAC-signed,
one-shot receipt bound to the wrapper's random attempt id, current channel/deployment nonce, and
floor/result registry revisions. A second one-shot verifies that binding against the still-proved
lease and current no-floor/no-role state, then consumes the receipt; only that success lets the
wrapper release. A missing, forged, stale, unsafe, or replayed receipt — and every signal or
container death — preserves the lease/restart fence. A crash before the floor leaves old auth state
authoritative and the migration untouched.

**Automated, explicit activation (#4524).** `scripts/lib/instance_state_deployment.sh` invokes
step 3 between `deployment-prove` and `deployment-finish` only when
`MVR03_PRINCIPAL_CUTOVER=1`. Deploying a capable image without that opt-in never advances the
floor. The `instance-state-init` one-shot consumes the same generated runtime-env credential
layer and `COMPANION_UI_PROXY_HOSTS` declaration as `api`; it does not receive the API's
unrelated Heimdal/GitHub host-secret layer. The exact three native launcher producers are
mounted read-only under `/run/principal-fence-native-producers`, and a missing declared path
fails before the floor is written.

**Rollback: credential-only images are blocked.** While the floor exists,
`_preflight_scalar_rollback` raises `CapabilityNotReadyError` before materializing any legacy
projection. A pre-MVR-03 image has no producer for the role record and would resolve requests
with no principal at all, so scalar rollback is refused rather than degraded. The MVR-01
rollback launcher and native preflight inherit this refusal through the same code path.

**Compatible images.** Rollback must target an image that understands
`agentic-pkm.local-operator-principal.v1`. Compatible roll-forward exports the prior image's
final credential/auth revision under the store lock
(`LocalOperatorPrincipalStore.export_final_auth_state`), verifies its recorded fork, and
reconciles only an *unambiguous* credential rotation into the same role id. Missing,
divergent, or ambiguous auth state fails closed without overwriting either lineage. The floor
may be lowered only by a later explicitly verified reversible migration — never by a scalar
rollback.

**Cutover operation.** Run one ordinary governed channel deploy/start with the explicit
one-time opt-in; the wrapper owns the stopped-window operation and its compensation ordering:

```bash
MVR03_PRINCIPAL_CUTOVER=1 scripts/deploy_channel.sh deploy <dev|test|prod> <sha>
```

The posture is **read** from server configuration (`API_KEY`, `COMPANION_UI_PROXY_HOSTS`), so
the subjects bound at bootstrap are the ones the request path will actually admit.
`config/deploy/{dev,test,prod}.env` explicitly sets
`MVR03_PRINCIPAL_LOOPBACK_LISTENER=0`: Docker-published traffic is not proven loopback inside
the API container. A future/native channel may declare `1` only when its effective listener is
proved loopback-local. Both `scripts/deploy_channel.sh` and `scripts/start_full_system.sh` pin
that declaration from the selected channel file rather than trusting ambient shell state. The
wrapper passes the resulting `--loopback-listener` declaration to the atomic cutover. A bare
`scripts/start_full_system.sh` invocation uses its existing implicit `dev` channel for this
declaration too, rather than accepting an undeclared ambient value. Every
request still proves loopback independently in
`app/auth.py::resolve_auth_subject` before that subject is used. `API_KEY` remains config input,
never argv, command output, or a receipt.

**Governed commands (run against a live instance, outside the cutover window).**

```bash
REG=/app/instance-state/agentic-pkm/vault-registry.md

# Confirm the role resolves before enabling request selection.
python -m app.instance.runtime principal-show --registry-path "$REG" --consumer cli

# Governed credential rotation; preserves the role id and keeps the loopback/proxy subjects.
# The new key arrives on stdin, never in argv (/proc/<pid>/cmdline and shell history are
# both readable, so a --credential flag would leak the key it exists to protect).
printf '%s' "$NEW_KEY" | python -m app.instance.runtime principal-rotate-credential \
  --registry-path "$REG" --credential-stdin

# Governed role addition; the new role receives a DISTINCT principal id.
python -m app.instance.runtime principal-add-role \
  --registry-path "$REG" --kind human --label "owner"

# Governed posture change; the only way to drop a bound subject. Refuses to drop the last one.
python -m app.instance.runtime principal-revoke-subject \
  --registry-path "$REG" --subject trusted_companion_proxy

# Roll-forward lineage. The export carries the PRIOR IMAGE's configured credential (read from
# its environment inside the stopped window), not the role record's own fingerprint. The
# reconcile consumes the export on success, so it can never be replayed over a later rotation.
printf '%s' "$OLD_IMAGE_KEY" | python -m app.instance.runtime principal-export-auth-state \
  --registry-path "$REG" --credential-stdin
python -m app.instance.runtime principal-roll-forward --registry-path "$REG"
```

Every receipt is redaction-safe: opaque role id, bound subjects, revision, provenance, and a
`credential_bound` boolean. No credential, fingerprint, or filesystem path is printed.

`--loopback-listener` declares that this deployment exposes a loopback-local listener, which
makes `trusted_loopback` a *bindable* subject. It is not a substitute for enforcement: every
request independently proves loopback in `app/auth.py::resolve_auth_subject` before that
subject is used.

## Live post-deploy UI smoke

A deploy is verified by an **end-to-end UI smoke against the live gateway**, not only by container health. This closes the gap noted in memory `project_companion_gateway_topology` (failures observed were transient `[Errno 61]` connection refusals and stale code after a pull-without-restart, with no live post-deploy UI check to catch them).

Contract (part of S4/S5 verification):
- **Fail-loud companion UI preflight before mutation.** Before a non-dry-run deploy writes the channel pin, applies a migration through Compose, or recreates a container, launch and close Playwright Chromium once, and prove the post-deploy pytest smoke command can start via an offline `pytest --collect-only` on the live-smoke module. A missing Python package, browser runtime, or pytest — or a live-smoke module that fails to import or collects nothing without its intentional `COMPANION_UI_SMOKE_URL` self-skip — blocks the deploy before channel mutation; the deploy script does not install host dependencies implicitly.
- **Per-gateway Playwright smoke.** After the health gate, run a headless Playwright check against each deployed gateway's URL (`http://<host>:8111|8112|8113/`) that loads the workspace shell, asserts the page renders (not a blank/error page), and verifies the authoritative `environment` field in the gateway-proxied operator-health payload matches the expected release channel. The rendered page must also expose gateway-owned `pkm-runtime-channel` and `pkm-runtime-git-sha` metadata; the latter comes from the image-baked `VCS_REF` and must match the exact deployed SHA, so a stale gateway cannot pass by proxying a fresh API. Channel and build proof are independent of active-vault state: the `workspace-vault-channel` DOM row is vault telemetry and may be absent in the valid picker/no-active-vault posture. The repo already has browser-runtime Playwright harnesses for the companion UI (`tests/companion_ui/browser_runtime_harness.py`, `tests/companion_ui/test_companion_ui_live_smoke.py`) to build on.
- **Embedding-cutover transition is explicit and narrow.** A governed dimension-changing cutover such as `docs/runbooks/RUNBOOK_BGE_M3_CUTOVER.md` necessarily restarts the new profile before its full rebuild can make `embedding_index` green. `--ack-embedding-rebuild-required` may therefore admit only the transitional health payload where `embedding_index` is the sole failed required check and its status is exactly `rebuild_required`, and only when `/readyz` returns HTTP 503 while the Product readiness snapshot remains usable. A green `/readyz` always requires `/api/health.required_ok=true`, including acknowledged deploys; ordinary deploys and rollbacks remain strict. To make the red transition reachable without weakening the container health contract, the deploy executor stages API/worker/watcher/capture startup, waits for API `/healthz`, and then starts the gateway without re-applying its `api: service_healthy` startup dependency; the API container itself remains unhealthy on strict `/readyz` until the rebuild succeeds. Without the acknowledgement, the normal combined Compose startup remains strict. Every other required-health failure remains blocking. The acknowledgement is recorded in the deploy receipt and is not a TEST PASS, PROD verification, emergency bypass, or permission to reindex; strict `/readyz`, index doctor, and cited retrieval verification still run after the full rebuild before promotion acceptance.
- **Catch the known failure modes.** The smoke must fail loud on (a) gateway unreachable / connection refused, and (b) a served page whose `/version`-equivalent runtime marker does not match the SHA just deployed (stale-code detection).
- **Run it as part of the deploy, not after.** The smoke is a deploy gate, the same way `/healthz` is — a green container with a broken or stale UI is a failed deploy.

## Auth↔topology decision

**Decision: the local reverse-proxy / docker-bridge hop may be treated as a trusted proxy via configured `X-Forwarded-For`; untrusted callers stay rejected.** Host networking is the accepted alternative where a proxy is not in front. This reconciles loopback-trust with the docker bridge without weakening the #2223 intent that state-changing companion API routes reject untrusted non-loopback callers.

Why it is needed: the API trusts loopback callers (`require_loopback_or_api_key` in `app/auth.py`), but when the gateway/browser reaches the API across the docker bridge, the immediate peer is the bridge address, not loopback. Without an explicit trusted-proxy path, legitimate same-host UI traffic to vault browse/select/initialize is rejected unless `API_KEY` is configured.

How it is implemented: `_effective_client_host()` in `app/auth.py` reads the first `X-Forwarded-For` hop **only when the immediate peer is trusted**: loopback by default, or an operator-declared local docker bridge/reverse-proxy peer via `COMPANION_TRUSTED_PROXY_HOSTS`. A direct external caller cannot spoof loopback by setting the header because non-trusted immediate peers are judged by their own address. Issue **#2706** hardens and documents this posture explicitly:
- The trusted-proxy boundary must be a loopback-local proxy, an explicitly configured local docker bridge/reverse-proxy peer, or host networking so the `X-Forwarded-For` trust assumption holds.
- Untrusted non-loopback callers without a valid API key remain rejected (`require_loopback_or_api_key` still 401s — preserves #2223).
- The deployment topology (managed gateway + API on the same host) must keep the proxy allowlist narrow; if a channel is ever bound to a LAN/Tailscale interface for UAT, the API-key path (not blanket loopback trust) governs untrusted callers.
- S6 verification is locked by `tests/api/test_auth_proxy_topology.py` and `tests/api/test_companion_auth_loopback_behind_proxy.py`: a loopback-local or configured same-host proxy may assert the client via `X-Forwarded-For`, while a genuinely non-loopback caller or unconfigured bridge peer with forged `X-Forwarded-For` remains rejected.

The production devUI read path does **not** reuse that forwarding mechanism. #4841 first rejects
every forwarded identity header, including `Via`, then preserves direct loopback + local Host or
accepts only `resolve_auth_subject(request, None) == SUBJECT_TRUSTED_COMPANION_PROXY` for the
configured Companion container peer. The gateway exposes only exact GET `/api/devui/overview`
and strict GET `/api/devui/focus?subject=...`, constructs a fresh no-credential/no-forwarding
request, and preserves upstream status/JSON. No API key, arbitrary bridge peer, wildcard, write, or
inside-container peer-loopback inference enters that exception.

## What this supersedes

- **`docs/ENVIRONMENTS.md` §Deployment.** That document remains the SoT for environment *selection* and *path scoping*; its deployment subsection now points here for *how a deploy happens*. The current-reality matrix and the ad-hoc startup wrappers described there are superseded by the build-once/promote + managed-units model in this document.
- **The narrow scope of #2527.** #2527 ("prod runs dirty `main`, not `stable`") is the *symptom-level* reconciliation: it records the promotion-ref decision and flags a dirty/diverged prod tree. This spec is the *systemic* fix it pointed at — the bind-mounted-checkout model (the reason a "dirty prod tree" was even possible) is replaced by pinned images, so prod stops running an editable, divergent working tree. #2527's promotion-ref decision is consumed by the §Deploy step-1 pin and by `docs/RELEASE_CHANNELS/README.md`; this document does not re-decide it.
- **The `nohup` gateway launch** in `scripts/lib/companion_ui_startup.sh` is superseded by §Gateways as managed units.

This document does **not** supersede `docs/RELEASE_CHANNELS/README.md` (channel identity, per-channel DB, promotion-plan/rollback/migration-classification contracts) — it implements the physical deploy beneath those contracts and references them rather than restating them.

## Historical implementation slices

The epic (#2655) was delivered as the slices below. S1 is this document. The original task descriptions are retained for provenance; they no longer represent open work. The terminal S7 cutover was operator-gated because it authorized full-environment downtime and could apply forward-only migrations.

- **S1 — Canonical deployment spec (this slice).** `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` + `docs/ENVIRONMENTS.md §Deployment` pointer. Docs-only. *Done in this PR.*
- **S2 — CI builds SHA-tagged image.** CI workflow builds the app image from the repo `Dockerfile`, injects `VCS_REF`/`BUILT_AT`, tags it `ghcr.io/<owner>/pkm-app:<sha>`. Target: `.github/workflows/**` (new build job), reuse the existing `Dockerfile` and the `Makefile` `VCS_REF`/`BUILT_AT` computation.
- **S3 — Artifact identity enforcement + per-channel pin.** Push the SHA-tagged image to GHCR; introduce a per-channel deploy-pin (`config/deploy/<env>.env` with `APP_IMAGE_TAG`); make the base compose `image:` reference the pinned tag with the repo `/app` bind-mount removable behind a flag. Before deploy receipts claim byte identity, enforce either digest pinning or explicit SHA-tag immutability in the registry path. Target: `.github/workflows/**`, `docker-compose.yaml`, new `config/deploy/*.env`.
- **S4 — Gateways as managed units.** Replace the `nohup` launch with a declared per-channel unit (containerized or `launchd`) with restart-on-failure and recreate-on-deploy; add the per-gateway live Playwright post-deploy smoke. Target: `scripts/lib/companion_ui_startup.sh`, `scripts/{dev,test,prod}/start_*_ui.sh`, new unit definitions, `tests/companion_ui/` Playwright smoke.
- **S5 — Deploy script + retire app bind-mount.** A deploy script implementing §Deploy procedure (pin → migration gate → recreate api+gateway → liveness/readiness gate → record SHA) and §Rollback; remove the `./:/app` app-code bind-mount so channels run the pinned image and `/version` becomes authoritative for the running code. Target: new `scripts/deploy_channel.sh` (or equivalent), `docker-compose.yaml`, `Makefile` deploy targets.
- **S6 — Verify/formalize auth↔topology.** Verify and lock the configured trusted-proxy (`X-Forwarded-For` only when peer is loopback or explicitly allowed) topology; add/confirm tests that exercise the proxied path and assert untrusted non-loopback callers and unconfigured bridge peers are still rejected (#2223, #2706). Target: `app/auth.py` (formalize/comment), `tests/**` covering `require_loopback_or_api_key` + `_effective_client_host` on the runtime path.
- **S7 — Cutover (OPERATOR-GATED, `agent:needs-human`).** Cut all three channels over from the shared-checkout bind-mount to pinned images, recreate API + managed gateways, run the migration gate (forward-only ack) and the health + UI smoke gates. **Authorizes full-environment downtime and may apply forward-only migrations — requires operator acknowledgement before execution.** Target: the live host; run S5's deploy script per channel under operator supervision; record receipts in `ops/promotions/`.

Delivery status (2026-09-25): S1–S6 were delivered (#2668, #2693–#2697); the pinned-image reconcile, readiness preflight, and fleet-model guard were delivered in PRs #3206, #3205, and #3207. Issue #2698 is closed; its final public receipt records the production deployment at SHA `311631b08efdf08809a5677d20e3612f80a0022c`. That receipt does not establish fresh equivalent `dev` and `test` evidence here. See the [historical cutover receipt index](PINNED_IMAGE_CUTOVER/README.md). The separate proposed post-merge `dev` → `test` workflow is not shipped; see [FAST_PR_TO_DEV_TEST_AUTOMATION](../plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md).

## Suggested validation

- Markdown/doc lint or link check if the repo provides one; otherwise manual review against epic #2655 and the verified current-reality matrix above.
- Confirm the matrix values still match `docker-compose.{dev,test,prod}.yml`, the gateway port constants in `serve_dev_page.py`/`serve_production_page.py`, and the launch path in `scripts/lib/companion_ui_startup.sh` when those surfaces change.

## Source anchors

- Epic #2655; adopted #2527; S6 bug #2654 (fixed by PR #2665); version marker #2602; auth intent #2223; full-host vault mounts #2310; legacy `/app/vault` re-baseline #2386.
- `docs/ENVIRONMENTS.md` (environment selection + path scoping), `docs/RELEASE_CHANNELS/README.md` (channel identity / promotion / rollback / migration classification).
- LearningSignal `lrn_20260629093241_59713bc1` (no-deploy-SoT root this epic repairs).
