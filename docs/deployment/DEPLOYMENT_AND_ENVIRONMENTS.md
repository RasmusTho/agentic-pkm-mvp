# Deployment and Environments

State: Canonical deployment source-of-truth for the `dev` / `test` / `prod` channels. Defines how images are built once and promoted, how the API stacks and Companion UI gateways are deployed as managed units, the deploy / rollback / migration-gate / health-gate procedure, and the auth↔topology decision behind the docker bridge.
Doc role: Core SoT (deployment)
Authority: Canonical deployment + environment-separation contract. `docs/ENVIRONMENTS.md` owns environment *selection* and *path scoping* (what data/config each channel touches); `docs/RELEASE_CHANNELS/README.md` owns *channel identity, per-channel DB isolation, promotion-plan contract, migration reversibility classification, and rollback semantics*. This document owns *how a deploy physically happens*: image build/promote, managed gateways, deploy/rollback runbook, health gates, and the proxy-trust topology. Operations, runbooks, and component docs should reference this document instead of restating deployment procedure.
Temporal class: operational
Review cadence: as deployment topology, build pipeline, or channel ports change
Last reviewed: 2026-06-29
Last verified against: `docker-compose.yaml`, `docker-compose.{dev,test,prod}.yml`, `Makefile`, `scripts/lib/companion_ui_startup.sh`, `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`, `serve_production_page.py`, `app/auth.py`, `app/version.py`, `app/api/routes/health_contract.py`

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

### Current reality (verified 2026-06-29)

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
| Per-env config file | `.env.<env>` overlays + compose env | same | `.env.prod.local` (machine-local secrets) + compose env |
| Container app code source | **shared checkout `./:/app`** (anti-pattern) | shared `./:/app` | shared `./:/app` |
| Startup wrappers | `make dev-up` / `make dev-ui` (`scripts/dev/start_niflheim_ui.sh`) | `make test-up` / `make test-ui` (`scripts/test/start_bifrost_ui.sh`) | `make prod-up` / `make prod-ui` (`scripts/prod/start_midgard_ui.sh`) |

Anchors for the values above: ports/DBs in `docker-compose.{dev,test,prod}.yml`; the base `./:/app` mount in `docker-compose.yaml`; gateway ports `_DEFAULT_PORT = 8111` (`serve_dev_page.py`) and `_PRODUCTION_PORT = 8113` (`serve_production_page.py`), with test 8112 set via the `PORT` env by `scripts/lib/companion_ui_startup.sh`; vault names per `reference_three_vaults` (names are operator-owned and **never hardcoded**).

Notes on the current model:
- The API stacks bind-mount the **whole repo** at `/app` (`docker-compose.yaml` `volumes: ["./:/app", …]`), plus `/Users` and `/Volumes` at identical container paths for in-process vault selection (#2310). The repo bind-mount is what removes code isolation: a `git checkout` in the one host tree changes the code under every channel's container at once.
- Gateways are **host processes**, not containers. They are launched by `scripts/lib/companion_ui_startup.sh`, which runs `nohup "${py}" -m "${CUI_SERVE_MODULE}" … &` and records a PID file under `tmp/companion-ui-<channel>.pid`. There is no supervisor: if the process dies, nothing restarts it.
- A partial build-identity foundation already exists: #2602 bakes `VCS_REF`/`BUILT_AT` into the image (Dockerfile ARG/LABEL/ENV), `get_runtime_version()` in `app/version.py` reads them (falling back to `git rev-parse` for local dev), `/version` returns `{git_sha, built_at}`, and `/api/health` carries a top-level `version` field. **But the `./:/app` bind-mount overrides the baked code**, so today the running code is the host checkout, not the image — the SHA marker can disagree with what is actually executing until the bind-mount is retired.

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

1. **Build (CI, S2).** On the appropriate trigger, CI builds the app image from the repo `Dockerfile` and tags it with the immutable commit SHA: `ghcr.io/<owner>/pkm-app:<full-or-short-sha>`. The build injects `VCS_REF`/`BUILT_AT` build-args (already wired in `docker-compose.yaml` and the `Makefile` for local builds; CI mirrors this) so the image's `/version` reports its own SHA.
2. **Registry (S3).** The SHA-tagged image is pushed to a container registry — **GHCR** (`ghcr.io`) is the chosen registry (already the GitHub-native default for this repo's tooling). Images are immutable by SHA tag; channel pins are mutable pointers *to* a SHA tag.
3. **Per-channel pinned tag.** Each channel records exactly one image tag it is allowed to run (a per-channel deploy-pin file, e.g. `config/deploy/<env>.env` carrying `APP_IMAGE_TAG=<sha>`). Compose runs that pinned tag instead of building locally; the base `image:` reference becomes `ghcr.io/<owner>/pkm-app:${APP_IMAGE_TAG}` and the `./:/app` bind-mount is dropped for app code (vault-selection mounts stay).
4. **Promotion = tag bump + recreate.** Promoting a commit to a channel means updating that channel's pin to the already-built SHA tag and recreating the channel's containers + gateway against it. **No rebuild at promotion time** — the artifact is identical to what was tested. This is the physical mechanism beneath the promotion-plan/`stable`-ref contract in `docs/RELEASE_CHANNELS/README.md`: that document decides *which* SHA is allowed to be promoted and what migration/rollback semantics apply; this document decides *how* the promotion is physically applied (bump pin → recreate → health-gate).

**Identity invariant.** The image bytes for a given SHA are identical in `dev`, `test`, and `prod`. A channel never builds its own variant. Divergence between channels is expressed only through `.env.<env>` / compose env, mounted data (vault, DB volume), and ports.

**Supersedes the bind-mount.** Once a channel runs a pinned image, a `git checkout`/`git pull` in the host tree no longer changes that channel's running code — by design. Deploying new code to a channel means building a new image, pushing it, bumping the pin, and recreating. The "pull without restart serves stale code" failure mode disappears because there is no live code mount to go stale.

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
3. **Recreate API + gateway.** Pull the pinned image and recreate the channel's API/worker/watcher containers and the gateway unit against it (`docker compose … up -d --force-recreate` for the channel project + gateway-unit recreate). Because routes load at container start, the recreate — not a file update — is what makes new code live. Recreate API and gateway together so they never diverge in version.
4. **Health gate (`/healthz`).** Block until the channel's API `/healthz` returns `{"ok": true}` (`app/api/routes/health_contract.py`) and the gateway's own `/healthz` responds, on the channel's ports. A deploy is not "done" until the health gate passes; a failing health gate triggers §Rollback.
5. **Record the deployed SHA.** Confirm `/version` (`{git_sha, built_at}`) and the `version` field on `/api/health` report the SHA just deployed, and record it in the deploy receipt (and `ops/promotions/` for prod, per the promotion contract). This closes the loop opened by #2602: the marker is only trustworthy once the bind-mount is retired (S5), so S5 must land before the SHA in `/version` can be treated as authoritative for what is running.

## Rollback procedure

Rollback reuses the deploy mechanism in reverse, against the previous known-good pin.

1. **Resolve previous-good pin.** Identify the channel's previous known-good image tag (the prior deploy-pin value; for `prod`, the previous `stable` SHA per `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`).
2. **Migration reversal (reversible only).** Reverse only migrations classified reversible. **Forward-only migrations are not auto-reversed** — if the failed deploy applied a forward-only migration, rollback of code can still proceed, but the schema state and any data implications are an operator decision (this is exactly why step 2 of the deploy gates on forward-only ack). Vault content is immutable across rollback.
3. **Recreate against the previous pin.** Bump the channel pin back to the previous tag and recreate API + gateway (same mechanism as deploy step 3). No rebuild — the previous image already exists in the registry.
4. **Health gate + record.** Re-run the §Deploy `/healthz` gate and confirm `/version` now reports the rolled-back SHA. Record the rollback receipt.

Rollback is a tag-bump + recreate because images are immutable and retained in the registry — the same property that makes promotion cheap makes rollback cheap.

## Live post-deploy UI smoke

A deploy is verified by an **end-to-end UI smoke against the live gateway**, not only by container health. This closes the gap noted in memory `project_companion_gateway_topology` (failures observed were transient `[Errno 61]` connection refusals and stale code after a pull-without-restart, with no live post-deploy UI check to catch them).

Contract (part of S4/S5 verification):
- **Per-gateway Playwright smoke.** After the health gate, run a headless Playwright check against each deployed gateway's URL (`http://<host>:8111|8112|8113/`) that loads the workspace shell and asserts the page renders (not a blank/error page) and that the runtime-channel marker matches the expected channel. The repo already has browser-runtime Playwright harnesses for the companion UI (`tests/companion_ui/browser_runtime_harness.py`, `tests/companion_ui/test_companion_ui_live_smoke.py`) to build on.
- **Catch the known failure modes.** The smoke must fail loud on (a) gateway unreachable / connection refused, and (b) a served page whose `/version`-equivalent runtime marker does not match the SHA just deployed (stale-code detection).
- **Run it as part of the deploy, not after.** The smoke is a deploy gate, the same way `/healthz` is — a green container with a broken or stale UI is a failed deploy.

## Auth↔topology decision

**Decision: the local reverse-proxy / docker-bridge hop is treated as a trusted proxy via trusted `X-Forwarded-For`; untrusted callers stay rejected.** Host networking is the accepted alternative where a proxy is not in front. This reconciles loopback-trust with the docker bridge without weakening the #2223 intent (state-changing companion API routes must reject untrusted non-loopback callers).

Why it is needed: the API trusts loopback callers (`require_loopback_or_api_key` in `app/auth.py`), but when the gateway/browser reaches the API across the docker bridge, the immediate peer is the bridge address, not loopback — so a naive loopback check would reject legitimate same-host UI traffic (the #2654 symptom: vault select/initialize/browse unreachable behind the bridge).

How it is implemented (already shipped, this document formalizes it): `_effective_client_host()` in `app/auth.py` reads the first `X-Forwarded-For` hop **only when the immediate peer is a trusted local proxy**: loopback by default, or an operator-declared local docker bridge proxy host via `COMPANION_TRUSTED_PROXY_HOSTS`. A direct external caller cannot spoof loopback by setting the header because non-trusted immediate peers are judged by their own address. This is the tactical fix delivered in **PR #2665** ("Fix companion loopback trust behind proxy"). S6 in this spec is therefore **verify/formalize**, not fix-from-scratch:
- The trusted-proxy boundary must be a loopback-local proxy, an explicitly configured local docker bridge proxy, or host networking so the `X-Forwarded-For` trust assumption holds.
- Untrusted non-loopback callers without a valid API key remain rejected (`require_loopback_or_api_key` still 401s — preserves #2223).
- The deployment topology (managed gateway + API on the same host) must keep the proxy hop loopback-local; if a channel is ever bound to a LAN/Tailscale interface for UAT, the API-key path (not blanket loopback trust) governs untrusted callers.
- S6 verification (#2697) locks this with `tests/api/test_auth_proxy_topology.py`: a loopback-local proxy may assert a loopback client via `X-Forwarded-For`, while a genuinely non-loopback caller with forged `X-Forwarded-For` remains rejected.

## What this supersedes

- **`docs/ENVIRONMENTS.md` §Deployment.** That document remains the SoT for environment *selection* and *path scoping*; its deployment subsection now points here for *how a deploy happens*. The current-reality matrix and the ad-hoc startup wrappers described there are superseded by the build-once/promote + managed-units model in this document.
- **The narrow scope of #2527.** #2527 ("prod runs dirty `main`, not `stable`") is the *symptom-level* reconciliation: it records the promotion-ref decision and flags a dirty/diverged prod tree. This spec is the *systemic* fix it pointed at — the bind-mounted-checkout model (the reason a "dirty prod tree" was even possible) is replaced by pinned images, so prod stops running an editable, divergent working tree. #2527's promotion-ref decision is consumed by the §Deploy step-1 pin and by `docs/RELEASE_CHANNELS/README.md`; this document does not re-decide it.
- **The `nohup` gateway launch** in `scripts/lib/companion_ui_startup.sh` is superseded by §Gateways as managed units.

This document does **not** supersede `docs/RELEASE_CHANNELS/README.md` (channel identity, per-channel DB, promotion-plan/rollback/migration-classification contracts) — it implements the physical deploy beneath those contracts and references them rather than restating them.

## Implementation slices

The epic (#2655) is delivered as the slices below. S1 is this document. S2–S7 map to concrete targets so `feature-breakdown` can derive child issues. **S7 (cutover) is operator-gated (`agent:needs-human`)** because it authorizes full-environment downtime and may apply forward-only migrations.

- **S1 — Canonical deployment spec (this slice).** `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` + `docs/ENVIRONMENTS.md §Deployment` pointer. Docs-only. *Done in this PR.*
- **S2 — CI builds SHA-tagged image.** CI workflow builds the app image from the repo `Dockerfile`, injects `VCS_REF`/`BUILT_AT`, tags it `ghcr.io/<owner>/pkm-app:<sha>`. Target: `.github/workflows/**` (new build job), reuse the existing `Dockerfile` and the `Makefile` `VCS_REF`/`BUILT_AT` computation.
- **S3 — Push to GHCR + per-channel pin.** Push the SHA-tagged image to GHCR; introduce a per-channel deploy-pin (`config/deploy/<env>.env` with `APP_IMAGE_TAG`); make the base compose `image:` reference the pinned tag with the repo `/app` bind-mount removable behind a flag. Target: `.github/workflows/**`, `docker-compose.yaml`, new `config/deploy/*.env`.
- **S4 — Gateways as managed units.** Replace the `nohup` launch with a declared per-channel unit (containerized or `launchd`) with restart-on-failure and recreate-on-deploy; add the per-gateway live Playwright post-deploy smoke. Target: `scripts/lib/companion_ui_startup.sh`, `scripts/{dev,test,prod}/start_*_ui.sh`, new unit definitions, `tests/companion_ui/` Playwright smoke.
- **S5 — Deploy script + retire app bind-mount.** A deploy script implementing §Deploy procedure (pin → migration gate → recreate api+gateway → `/healthz` gate → record SHA) and §Rollback; remove the `./:/app` app-code bind-mount so channels run the pinned image and `/version` becomes authoritative for the running code. Target: new `scripts/deploy_channel.sh` (or equivalent), `docker-compose.yaml`, `Makefile` deploy targets.
- **S6 — Verify/formalize auth↔topology.** Verify and lock the trusted-proxy (`X-Forwarded-For` only when peer is loopback) topology already shipped in PR #2665; add/confirm a test that exercises the proxied path and asserts untrusted non-loopback callers are still rejected (#2223). Target: `app/auth.py` (formalize/comment), `tests/**` covering `require_loopback_or_api_key` + `_effective_client_host` on the runtime path. *Bug #2654 already fixed tactically — this slice is verify, not fix-from-scratch.*
- **S7 — Cutover (OPERATOR-GATED, `agent:needs-human`).** Cut all three channels over from the shared-checkout bind-mount to pinned images, recreate API + managed gateways, run the migration gate (forward-only ack) and the health + UI smoke gates. **Authorizes full-environment downtime and may apply forward-only migrations — requires operator acknowledgement before execution.** Target: the live host; run S5's deploy script per channel under operator supervision; record receipts in `ops/promotions/`.

## Suggested validation

- Markdown/doc lint or link check if the repo provides one; otherwise manual review against epic #2655 and the verified current-reality matrix above.
- Confirm the matrix values still match `docker-compose.{dev,test,prod}.yml`, the gateway port constants in `serve_dev_page.py`/`serve_production_page.py`, and the launch path in `scripts/lib/companion_ui_startup.sh` when those surfaces change.

## Source anchors

- Epic #2655; adopted #2527; S6 bug #2654 (fixed by PR #2665); version marker #2602; auth intent #2223; full-host vault mounts #2310; legacy `/app/vault` re-baseline #2386.
- `docs/ENVIRONMENTS.md` (environment selection + path scoping), `docs/RELEASE_CHANNELS/README.md` (channel identity / promotion / rollback / migration classification).
- LearningSignal `lrn_20260629093241_59713bc1` (no-deploy-SoT root this epic repairs).
