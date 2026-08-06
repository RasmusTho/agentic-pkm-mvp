# Deployment and Environments

State: Canonical deployment source-of-truth for the `dev` / `test` / `prod` channels. Defines how images are built once and promoted, how the API stacks and Companion UI gateways are deployed as managed units, the deploy / rollback / migration-gate / health-gate procedure, and the auth↔topology decision behind the docker bridge.
Doc role: Core SoT (deployment)
Authority: Canonical deployment + environment-separation contract. `docs/ENVIRONMENTS.md` owns environment *selection* and *path scoping* (what data/config each channel touches); `docs/RELEASE_CHANNELS/README.md` owns *channel identity, per-channel DB isolation, promotion-plan contract, migration reversibility classification, and rollback semantics*. This document owns *how a deploy physically happens*: image build/promote, managed gateways, deploy/rollback runbook, health gates, and the proxy-trust topology. Operations, runbooks, and component docs should reference this document instead of restating deployment procedure.
Temporal class: operational
Review cadence: as deployment topology, build pipeline, or channel ports change
Last reviewed: 2026-07-19
Last verified against: `docker-compose.yaml`, `docker-compose.{dev,test,prod}.yml`, `docker-compose.{full-host-vault,legacy-vault,test-vault}.yml`, `Makefile`, `Dockerfile`, `scripts/lib/companion_ui_startup.sh`, `scripts/lib/instance_ownership_host_state.sh`, `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`, `serve_production_page.py`, `app/auth.py`, `app/version.py`, `app/api/routes/health_contract.py`, `app/activation/ask_synthesis.py`

## Why this document exists

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

Three channels run in parallel on one host: `dev`, `test`, `prod`. They are isolated by DB name, vault binding, ports, and runtime-artifact paths — see `docs/ENVIRONMENTS.md` for the environment-selection contract these values implement.

### Current reality (verified 2026-07-06)

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
| Container app code source | baked local image `pkm-app:dev-local` | `workspace-app` with shared host checkout bind-mounted at `/app` | `workspace-app` with shared host checkout bind-mounted at `/app` |
| Startup wrappers | `make dev-up` / `make dev-ui` (`scripts/dev/start_niflheim_ui.sh`) | `make test-up` / `make test-ui` (`scripts/test/start_bifrost_ui.sh`) | `make prod-up` / `make prod-ui` (`scripts/prod/start_midgard_ui.sh`) |

Anchors for the values above: ports/DBs in `docker-compose.{dev,test,prod}.yml`; the 2026-07-06 host recon recorded in #3124 / `docs/deployment/PINNED_IMAGE_CUTOVER/README.md`; gateway ports `_DEFAULT_PORT = 8111` (`serve_dev_page.py`) and `_PRODUCTION_PORT = 8113` (`serve_production_page.py`, with test 8112 set via the `PORT` env); vault names per `reference_three_vaults` (names are operator-owned and **never hardcoded**).

Notes on the current model:
- `test` and `prod` still bind-mount the **same host checkout** at `/app`. That repo bind-mount is what removes code isolation: a `git checkout` in the one host tree changes the code under both channels' containers at once. `dev` differs only by running the baked local `pkm-app:dev-local` image, not by running a promoted GHCR SHA pin.
- Companion UI gateways are now declared as managed compose units in the repo, but the running fleet has not yet adopted the pinned-image model. The cutover guard therefore checks gateway-unit participation in the recreate set before #2698 can treat a channel as ready.
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
`${XDG_STATE_HOME:-$HOME/.local/state}/agentic-pkm/instance-ownership` path (or an explicit absolute
override), so separate checkouts and all three channel projects mount the same ledger. Compose may
not create a checkout-relative substitute. Every consumer rejects any active host-global deployment
lease, including a lease owned by another channel, before reading or mutating channel state.

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
equal or nested roots across two different release channels abort without seeding a partial set. A
root shared between the `native` domain and one channel does not abort: per
`docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` the Mac runtime and a channel runtime are
both declared writers of one vault, and their concurrent writes are resolved at write time rather
than by refusing the deploy. A failure at any stage after the lease/fence claim and before
finalization — a live writer, a post-stop owner validation failure, or any other producer stage
failure — surrenders that same-run producer's own host-global lease, public lease copy, and channel
restart fence instead of stranding them; the release is scoped to the exact controller identity (pid
plus start token) that claimed the lease, so it cannot disturb a lease still owned by a live or
unrelated deployment, and a lease whose recorded controller process no longer exists is reclaimable
by the next `deployment-begin` instead of fatal. The nonce-plus-inventory-digest proof
is required for restore, final export/preservation, and legacy bootstrap. The finalizer rejects an
incomplete, non-private, or unvalidated inventory, captures the final legacy fingerprint, imports it
on first volume or preserves it beside an established dormant registry, calls the host-global
legacy-owner bootstrap, and reconciles newly materialized owners even when that bootstrap previously
completed. Reconciliation preserves authenticated binding identity and is atomic with respect to
forbidden release-channel collisions, tombstones, and transfers. The native/channel exception
requires exactly one owner root from each side of the complete overlap-connected component; retained
ownership participates, so an indirect bridge also fails closed. The finalizer then creates a
verified registry/ledger/key backup and clears the fence.
`INSTANCE_STATE_RESTORE_PATH`, when set, is verified and restored inside that stopped interval
before finalization and consumer startup. Failure leaves the fence in place, so upgraded consumer
preflight refuses restart. Rollback to a previous image that predates `app.instance.runtime` is
selected explicitly by the deploy wrapper and uses a Compose-owned compatibility guard: it may
start only when neither the host-global lease nor any channel restart fence exists. Current images
always run the full authenticated runtime preflight; module absence outside explicit rollback fails
closed.

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
| Vault selection mounts | `/Users` + `/Volumes` retained (#2310) | retained | retained |

The target keeps the **ports, DB names, vault bindings, and the `dev/test → serve_dev_page`, `prod → serve_production_page`** split exactly as today. The only changes are: (a) the app code arrives as a **pinned image** instead of a live bind-mount, and (b) gateways become **managed units** instead of `nohup` processes. Everything that varies between channels stays config/data/ports — never a code fork.

## Build-once / promote model

The pipeline builds an image **once per commit** and promotes the *same* image artifact across channels by moving a tag pin. This replaces the "all channels run one bind-mounted checkout" model.

### PR validation is not artifact publication (current policy)

The `App Image Build` GitHub workflow has two deliberately different paths:

- A pull-request run builds an `linux/amd64` image in the ephemeral CI runner, verifies its baked
  `/version` identity, and uses `push: false`. It does **not** log in to GHCR and it leaves no
  pullable candidate image behind.
- A push to `main` builds and publishes the multi-architecture SHA-tagged GHCR image. That is the
  normal registry-artifact path.

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

**Supersedes the bind-mount.** Once a channel runs a pinned image, a `git checkout`/`git pull` in the host tree no longer changes that channel's running code — by design. Deploying new code to a channel means building a new image, pushing it, bumping the pin, and recreating. The "pull without restart serves stale code" failure mode disappears because there is no live code mount to go stale.

## Root-owned image bake vs. host-uid-remapped runtime user (#2991, #3047)

Every channel's `api`/`worker`/`watcher`/`heimdal-capture-watch` service runs as `user: "${LOCAL_UID:-0}:${LOCAL_GID:-0}"` (`docker-compose.yaml`), populated from the host user via `scripts/export_runtime_env.sh` — not as `root`, and not as a fixed container uid. The image itself is built as `root` (`Dockerfile` has no `USER` directive), so every path `COPY . .` creates, and every directory that exists in the repo tree at build time, is `root:root`-owned in the resulting image.

This is a structural mismatch: any code path that lazily creates a directory under `/app` at first use (`Path(...).mkdir(parents=True, exist_ok=True)`) fails with `PermissionError` under the non-root runtime uid unless that directory was pre-created **and** made writable by all uids at build time. Two runtime-writable surfaces have needed this treatment so far:

- **`/app/tmp`** — the shared scratch/heartbeat/outbox surface (#2991), also backed at runtime by the `runtime-tmp` named volume mounted into api/worker/watcher (mount does not imply ownership by itself; the Dockerfile still pre-creates and chmods the mount point so a fresh, unmounted `/app/tmp` — e.g. bare-metal or a container without the volume — is also writable).
- **`/app/runtime`** — the parent of every `runtime/<subdir>/...` receipt/state path defaulted by `app/**` modules (ask synthesis, expansion-gate, agent-memory, relevance, builderops, dispatcher, orientation, panel, proposals — `git grep 'Path("runtime/'`). None of these subdirectories are tracked in git (`.gitignore` lines 51-65), so `/app/runtime` does not exist in the image at all until first write; without the fix it fails the **first** `POST /api/ask` (or any other receipt-emitting request) on every freshly recreated container with `PermissionError: runtime/activation/ask_synthesis_receipts.jsonl` (#3047).

**Contract:** the `Dockerfile` bakes each such surface with `RUN mkdir -p /app/<path> && chmod 1777 /app/<path>` immediately after `COPY . .`. `chmod 1777` (world rwx + sticky bit) makes the directory writable and traversable by any uid while still preventing one uid from deleting another's files — the same property `/tmp` relies on system-wide. This is the general chokepoint for the defect class: a new root-owned runtime-writable path gets its own `mkdir -p && chmod 1777` line at that Dockerfile location rather than a bespoke per-module workaround. It applies identically to `dev`/`test`/`prod` because the image is byte-identical across channels (see the identity invariant above) — there is no per-channel variant of this fix.

## Gateways as managed units

Companion UI gateways must become **managed units** with deterministic recreate-on-deploy and restart-on-failure, retiring the ad-hoc `nohup`/shell-history launch.

Current reality: `scripts/lib/companion_ui_startup.sh` launches the gateway with `nohup … &`, writes a PID file, and curls `/healthz` to confirm liveness — but nothing supervises or restarts the process, and the launch lives in script + shell history rather than a declared unit. The dev/test gateways run `companion_ui.workspace.serve_dev_page`; prod runs `companion_ui.workspace.serve_production_page`; both render through `render_index_html`, so this is a deployment/supervision change, not a UI-behavior change.

Target contract (S4):
- **One declared unit per channel gateway.** Either containerize the gateway in the channel's compose project, or declare a `launchd` unit per channel. The unit owns host/port (`HOST`, `PORT`) and the API base URL (`COMPANION_API_BASE_URL`) exactly as the current startup script passes them.
- **Recreate-on-deploy.** A deploy recreates the gateway unit so it picks up the deployed image/code, in lockstep with the API recreate — never a half-deployed state where the API is new and the gateway is old.
- **Restart-on-failure.** The unit restarts the gateway if it exits (compose `restart: unless-stopped`, matching the API/db/worker services in `docker-compose.yaml`, or the `launchd` `KeepAlive` equivalent). A crashed gateway must come back without a human.
- **Source-of-truth.** The unit definition is committed; there is no "remember the nohup command" step. The per-channel wrappers (`start_niflheim_ui.sh` / `start_bifrost_ui.sh` / `start_midgard_ui.sh`) and doctor scripts are reconciled to invoke the managed unit rather than `nohup`.

The prod gateway keeps its safe default posture (`prod-ui` does not auto-start watchers/workers; write/automation-capable startup stays behind `PROD_UI_ENABLE_AUTOMATION=1`).

## Deploy procedure

The deploy procedure is the same shape for every channel; only the pin target and the migration-ack posture differ (`prod` is the strictest). It assumes the build-once/promote model above.

1. **Pin the ref.** Resolve the commit SHA to deploy and its already-built image tag (`ghcr.io/<owner>/pkm-app:<sha>`). For `prod`, the SHA must be the one authorized by the promotion-plan contract in `docs/RELEASE_CHANNELS/README.md` (the `stable`-ref decision; see also #2527). Update the channel's deploy-pin file to that tag.
2. **Migration gate (forward-only surfaced + operator ack).** Diff the migrations between the currently-running SHA and the target SHA. Classify each per `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`. **Surface every forward-only (irreversible) migration explicitly and require operator acknowledgement before proceeding** — a forward-only migration is the one thing that makes a deploy not cleanly rollback-able. Reversible migrations proceed under the standard gate; forward-only migrations are an `agent:needs-human` stop.
3. **Quiesce/finalize instance state, then execute changed migrations.** Pull the pinned image. For a deploy, `scripts/deploy_channel.sh` runs the instance-state deployment producer before migration execution: it holds the host-global fence, quiesces API/worker/watcher/Heimdal writers, and finalizes or restores the protected instance-state boundary. It then stops every runtime writer again and runs the target image's one-shot migration service before any target runtime is recreated. When the migration diff is non-empty, the executor writes a durable pending-migration marker before mutating the pin. The marker binds the source SHA (or explicit no-baseline sentinel), target SHA, and forward-only acknowledgement; it is removed only after the migration service reports success.
4. **Recreate API + gateway.** Only after the instance-state finalization and migration execution succeed, recreate the channel's API/worker/watcher containers and the gateway unit against the pinned image (`docker compose … up -d --force-recreate` for the channel project + gateway-unit recreate). `scripts/deploy_channel.sh` reads the channel's generated runtime-env reference without sourcing, copying, regenerating, rewriting, or printing it. It pins that governed reference and its parsed `VAULT_HOST_ROOT` selector into the Compose process, so caller-shell values cannot replace them and runtime DSNs never participate in Compose interpolation. For each invocation, the wrapper separately resolves, reachability-validates, and where needed translates `SIGNBOARD_ROOT`, then injects it—or explicitly clears a stale value when no valid root resolves—through an API-only Compose override document delivered via a private (mode-0600, wrapper-owned) temp file removed on return, rather than the wrapper's own stdin, so a caller piping real data into the wrapper (#4536) still reaches the container. The override document itself carries no operator path or secret — only the bare `SIGNBOARD_ROOT:` key, whose value Compose forwards from this governed shell's environment — so writing it to a temp file does not weaken the runtime env ownership boundary. This leaves the runtime env and its `VAULT_ROOT` / `VAULT_HOST_ROOT` binding unchanged; `docs/AGENT_ISSUE_DISPATCHER.md :: Local visual Signboard` owns the detailed resolution, translation, and fail-visible no-vault contract. When the governed vault selector is already reachable through the base same-path `/Users` or `/Volumes` mounts, deploy and rollback append `docker-compose.full-host-vault.yml` and bind runtime selectors to that one container path; they do not add the duplicate legacy `/app/vault` mount. Other explicit sources retain `docker-compose.legacy-vault.yml` compatibility. TEST appends `docker-compose.test-vault.yml` last so its watcher is activated against whichever one container path the access overlay selected. With no explicit vault, no vault overlay is selected and the base+channel no-vault posture remains intact. Because routes load at container start, the recreate — not a file update — is what makes new code live. Recreate API and gateway together so they never diverge in version.
5. **Health gate: liveness first, readiness second.** Block until the channel's API `/healthz` returns `{"ok": true}` (`app/api/routes/health_contract.py`) and then require both readiness probes on the channel's ports: `/readyz` must pass, and `/api/health` must report `required_ok: true`. `/healthz` is only a liveness probe; deploy completion requires readiness evidence that startup dependencies, DB connectivity, and the deployed code path are actually usable. The gateway's own `/healthz` must also respond. A deploy is not "done" until liveness and both readiness predicates pass; a failing gate triggers §Rollback.
6. **Complete every post-mutation gate, then record the deployed SHA.** Confirm `/version` (`{git_sha, built_at}`) and the `version` field on `/api/health` report the SHA just deployed; require the fleet-model fitness check, Companion UI smoke, and capture-watch health gate to pass; then record the deploy receipt (and `ops/promotions/` for prod, per the promotion contract). The successful receipt is the final gate and is not written while any earlier required gate is unresolved. This closes the loop opened by #2602: the marker is only trustworthy once the bind-mount is retired (S5) and the image artifact has been made immutable by digest pinning or explicit SHA-tag enforcement, so S5 must land before the SHA in `/version` can be treated as authoritative for what is running.

Before migration execution begins, a pending marker makes interruption recovery fail closed: a retry must target the marker's exact SHA, revalidate the recorded source-to-target migration classification and forward-only acknowledgement, and cannot deploy a different target until the marker is reconciled. After migration execution begins, a nonzero result is possibly committed even when the migration container did not report success. The executor therefore retains both the pending marker and the schema-compatible target pin rather than recreating a possibly schema-incompatible previous image. For reversible migrations, reconcile the database revision and use the governed rollback path if reversal is proved and appropriate; for forward-only migrations, prove the revision is unchanged or apply a compatible forward fix. In either case, the migration is never auto-reversed by the deploy hot path.

For failures before migration execution starts, the ordinary fail-closed recovery path preserves the failing gate's original non-zero status and diagnostics, restores the previous pin, and attempts to recreate the prior service set before returning. The instance-state fence remains in place if its finalization fails, so consumer preflight refuses restart.

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
3. `principal-record-floor` runs in that window. It requires the lease in `proved` phase for
   this channel and nonce, consumes the quiescence proof plus the drained legacy-owner
   inventory, enumerates `docker-compose.yaml` (failing closed on any unclassified service),
   and adds the producers MVR-01B does not classify — the Companion proxy, credential
   rotation, the headless CLI, and bootstrap/init. Only then does it record the floor.
4. `principal-bootstrap` writes the delegated-role record; it refuses while the floor is
   absent.
5. `deployment-finish` closes the window.

`require_complete_fence` refuses steps 3–4 if the inventory is incomplete, if writers were not
drained, if the inventory was not revalidated after quiescence, if it was probed once, if any
producer role is missing, or if operations are not fenced. `principal-record-floor` also
refuses without the proved deployment lease for this channel and nonce, and it preflights the
auth posture the subsequent role write will use — so a floor can never be recorded on an
instance where the role could not then be written. A crash before the floor leaves old auth
state authoritative and the migration untouched.

> **Not yet automated.** `scripts/lib/instance_state_deployment.sh` does **not** invoke steps
> 3–4. Wiring them requires the credential/listener posture and the native launcher paths to be
> available inside the `instance-state-init` one-shot, which that service does not currently
> have; a half-wired cutover would record the floor and then fail the role write, leaving the
> instance fenced and rollback-blocked. Until that plumbing ships, an operator runs steps 3–4
> explicitly inside the stopped window using the commands below. This is tracked as bounded
> follow-up work on #3857.

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

**Cutover commands (run inside the stopped window, between `deployment-prove` and
`deployment-finish`).** Both refuse outside that window.

```bash
REG=/app/instance-state/agentic-pkm/vault-registry.md
OWN=/app/instance-ownership

python -m app.instance.runtime principal-record-floor \
  --channel "$CHANNEL" --registry-path "$REG" --host-global-root "$OWN" \
  --inventory-path "$OWN/legacy-owner-inventory.json" \
  --quiescence-proof-path "$OWN/deployment-quiescence-proof.json" \
  --compose-base <mounted docker-compose.yaml> \
  --native-producer-root <mounted repo root> \
  [--loopback-listener]

python -m app.instance.runtime principal-bootstrap \
  --registry-path "$REG" [--loopback-listener] [--existing-install]
```

The posture is **read** from server configuration (`API_KEY`, `COMPANION_UI_PROXY_HOSTS`), so
the subjects bound at bootstrap are the ones the request path will actually admit.
`--loopback-listener` declares that this deployment exposes a loopback-local listener, which
makes `trusted_loopback` a *bindable* subject; every request still proves loopback
independently in `app/auth.py::resolve_auth_subject` before that subject is used.

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
- **Embedding-cutover transition is explicit and narrow.** A governed dimension-changing cutover such as `docs/runbooks/RUNBOOK_BGE_M3_CUTOVER.md` necessarily restarts the new profile before its full rebuild can make `embedding_index` green. `--ack-embedding-rebuild-required` may therefore admit only the transitional health payload where `embedding_index` is the sole failed required check and its status is exactly `rebuild_required`. To make that transition reachable without weakening the container health contract, the deploy executor stages API/worker/watcher/capture startup, waits for API `/healthz`, and then starts the gateway without re-applying its `api: service_healthy` startup dependency; the API container itself remains unhealthy on strict `/readyz` until the rebuild succeeds. Without the acknowledgement, the normal combined Compose startup remains strict. Every other required-health failure remains blocking. The acknowledgement is recorded in the deploy receipt and is not a TEST PASS, PROD verification, emergency bypass, or permission to reindex; strict `/readyz`, index doctor, and cited retrieval verification still run after the full rebuild before promotion acceptance.
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

## What this supersedes

- **`docs/ENVIRONMENTS.md` §Deployment.** That document remains the SoT for environment *selection* and *path scoping*; its deployment subsection now points here for *how a deploy happens*. The current-reality matrix and the ad-hoc startup wrappers described there are superseded by the build-once/promote + managed-units model in this document.
- **The narrow scope of #2527.** #2527 ("prod runs dirty `main`, not `stable`") is the *symptom-level* reconciliation: it records the promotion-ref decision and flags a dirty/diverged prod tree. This spec is the *systemic* fix it pointed at — the bind-mounted-checkout model (the reason a "dirty prod tree" was even possible) is replaced by pinned images, so prod stops running an editable, divergent working tree. #2527's promotion-ref decision is consumed by the §Deploy step-1 pin and by `docs/RELEASE_CHANNELS/README.md`; this document does not re-decide it.
- **The `nohup` gateway launch** in `scripts/lib/companion_ui_startup.sh` is superseded by §Gateways as managed units.

This document does **not** supersede `docs/RELEASE_CHANNELS/README.md` (channel identity, per-channel DB, promotion-plan/rollback/migration-classification contracts) — it implements the physical deploy beneath those contracts and references them rather than restating them.

## Implementation slices

The epic (#2655) is delivered as the slices below. S1 is this document. S2–S7 map to concrete targets so `feature-breakdown` can derive child issues. **S7 (cutover) is operator-gated (`agent:needs-human`)** because it authorizes full-environment downtime and may apply forward-only migrations.

- **S1 — Canonical deployment spec (this slice).** `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` + `docs/ENVIRONMENTS.md §Deployment` pointer. Docs-only. *Done in this PR.*
- **S2 — CI builds SHA-tagged image.** CI workflow builds the app image from the repo `Dockerfile`, injects `VCS_REF`/`BUILT_AT`, tags it `ghcr.io/<owner>/pkm-app:<sha>`. Target: `.github/workflows/**` (new build job), reuse the existing `Dockerfile` and the `Makefile` `VCS_REF`/`BUILT_AT` computation.
- **S3 — Artifact identity enforcement + per-channel pin.** Push the SHA-tagged image to GHCR; introduce a per-channel deploy-pin (`config/deploy/<env>.env` with `APP_IMAGE_TAG`); make the base compose `image:` reference the pinned tag with the repo `/app` bind-mount removable behind a flag. Before deploy receipts claim byte identity, enforce either digest pinning or explicit SHA-tag immutability in the registry path. Target: `.github/workflows/**`, `docker-compose.yaml`, new `config/deploy/*.env`.
- **S4 — Gateways as managed units.** Replace the `nohup` launch with a declared per-channel unit (containerized or `launchd`) with restart-on-failure and recreate-on-deploy; add the per-gateway live Playwright post-deploy smoke. Target: `scripts/lib/companion_ui_startup.sh`, `scripts/{dev,test,prod}/start_*_ui.sh`, new unit definitions, `tests/companion_ui/` Playwright smoke.
- **S5 — Deploy script + retire app bind-mount.** A deploy script implementing §Deploy procedure (pin → migration gate → recreate api+gateway → liveness/readiness gate → record SHA) and §Rollback; remove the `./:/app` app-code bind-mount so channels run the pinned image and `/version` becomes authoritative for the running code. Target: new `scripts/deploy_channel.sh` (or equivalent), `docker-compose.yaml`, `Makefile` deploy targets.
- **S6 — Verify/formalize auth↔topology.** Verify and lock the configured trusted-proxy (`X-Forwarded-For` only when peer is loopback or explicitly allowed) topology; add/confirm tests that exercise the proxied path and assert untrusted non-loopback callers and unconfigured bridge peers are still rejected (#2223, #2706). Target: `app/auth.py` (formalize/comment), `tests/**` covering `require_loopback_or_api_key` + `_effective_client_host` on the runtime path.
- **S7 — Cutover (OPERATOR-GATED, `agent:needs-human`).** Cut all three channels over from the shared-checkout bind-mount to pinned images, recreate API + managed gateways, run the migration gate (forward-only ack) and the health + UI smoke gates. **Authorizes full-environment downtime and may apply forward-only migrations — requires operator acknowledgement before execution.** Target: the live host; run S5's deploy script per channel under operator supervision; record receipts in `ops/promotions/`.

Delivery status (2026-07-07): S1–S6 are delivered (#2668, #2693–#2697); the running fleet has **not** adopted the delivered tooling, and the promotion skill chain that landed after these slices is still checkout-based. The remaining work — reconciling the promotion workflow with pinned images, per-channel cutover readiness, a live fleet-model fitness guard, and the operator-gated cutover itself (#2698) — is specified in [`docs/deployment/PINNED_IMAGE_CUTOVER/`](PINNED_IMAGE_CUTOVER/README.md).

## Suggested validation

- Markdown/doc lint or link check if the repo provides one; otherwise manual review against epic #2655 and the verified current-reality matrix above.
- Confirm the matrix values still match `docker-compose.{dev,test,prod}.yml`, the gateway port constants in `serve_dev_page.py`/`serve_production_page.py`, and the launch path in `scripts/lib/companion_ui_startup.sh` when those surfaces change.

## Source anchors

- Epic #2655; adopted #2527; S6 bug #2654 (fixed by PR #2665); version marker #2602; auth intent #2223; full-host vault mounts #2310; legacy `/app/vault` re-baseline #2386.
- `docs/ENVIRONMENTS.md` (environment selection + path scoping), `docs/RELEASE_CHANNELS/README.md` (channel identity / promotion / rollback / migration classification).
- LearningSignal `lrn_20260629093241_59713bc1` (no-deploy-SoT root this epic repairs).
