State: SoT v5.5 Reality-MVP baseline locked; v5.6 delivery line closed; this is the top-level operations entrypoint for the current runtime while v6.0 seams are shipped in bounded form and broader v6.1+ consumption remains planned.
Doc role: Core SoT
Authority: Top-level operator guidance for the current runtime; delegates specialized operational detail to linked companion docs but remains the main operational entrypoint.
Owner: Runtime / operator playbook
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-29
Last verified against: docs/STATUS.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/HEALTH.md, docs/INFRASTRUCTURE.md, docs/ENVIRONMENTS.md, docs/OBSERVABILITY.md, docs/ASK_PROVENANCE_MANIFEST/README.md, docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md, app/agent_memory/ask_provenance_manifest.py, app/relevance/now_surface.py, tests/agent_memory/test_ask_provenance_manifest.py, tests/relevance/test_vault_native_moments.py, Makefile, docker-compose.test.yml, docker-compose.legacy-vault.yml, docker-compose.test-vault.yml, scripts/start_full_system.sh, scripts/verify_runtime_stack.sh, merged PRs #1948/#1977/#2115/#2119/#2127/#2128/#2129/#2131/#2135/#2140/#2142, and current repo state on 2026-07-15
# Operations Playbook

Use this document as the operator-facing starting point for runtime operations.

Specialized companion documents:
- `docs/HEALTH.md` - health CLI behavior and runtime health contract
- `docs/OBSERVABILITY.md` - runtime observability signals, counters, and span/log contracts
- `docs/INFRASTRUCTURE.md` - local runtime stack, Docker/Colima setup, and local observability stack
- `docs/SECURITY_ARCHITECTURE.md` - security review routing, threat-model tiers, and security invariants

Reading order:
1. Start here for runtime expectations, core checks, and escalation paths.
2. Follow `docs/HEALTH.md` when verifying readiness or diagnosing degraded state.
3. Follow `docs/OBSERVABILITY.md` for interpreting telemetry and counters.
4. Use `docs/INFRASTRUCTURE.md` when you need Docker/runtime topology, local startup flow, or the local monitoring stack.
5. Use `docs/runbooks/` only for task-specific walkthroughs after you have identified the affected runtime surface.
6. Use `docs/ENVIRONMENTS.md` when the question is whether behavior belongs to `dev`, `test`, `prod`, or a boundary between them.
7. Use the parallel-stack recipe in `docs/ENVIRONMENTS.md` when you need to run `dev`, `test`, and `prod` Compose stacks simultaneously on one machine.
8. Use `docs/RELEASE_CHANNELS/README.md` plus the promotion skills when the question is stable/dev channel promotion, rollback, or prod-checkout pinning.
9. Use `docs/SECURITY_ARCHITECTURE.md` and `docs/security/API_SECURITY_MATRIX.md` before changing
   API exposure, auth/rate-limit posture, external provider/tool execution, or mutation-capable
   route behavior.

CLI note:
- `python -m app.cli --help` and `python -m app.cli <command> --help` remain the authoritative command discovery surface because the CLI evolves faster than the docs.
- Runtime verification note: `make verify-runtime` is the authoritative local operator check for the live Docker stack because it verifies service health plus in-container CLI health, rather than the host shell environment.
- Canvas note: `python -m app.cli canvas ...` and `/api/canvas/*` now exist as bounded session surfaces behind `CANVAS_ENABLED`; they are materially supported for bounded co-authoring, but still not part of the default production operator surface.

### Heimdal raw-store capacity receipt

Use `python -m app.cli heimdal capacity --vault-root <vault>` to inspect an
aggregate-only capacity receipt for Heimdal's encrypted raw store. The command
reports counts and encrypted-byte totals for the first seven hot days,
archive-eligible records within the configured retention bound, and expired
records. It requires `_heimdal/settings.md` to declare a valid
`retention_window_days`; missing policy fails loud. It neither reads raw
payloads nor performs archive, retention, or storage lifecycle work.

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.
- App-version bumps and git tags are separate from stable-channel promotion. When moving the `stable`
  ref, rehearsing rollback, or validating prod after a promotion, use
  `docs/RELEASE_CHANNELS/README.md` plus `prepare-promotion`, `execute-promotion`,
  `verify-promotion`, and `rollback-promotion`. For the full operator acceptance procedure
  (preflight, smoke test, soak, rollback rehearsal, and receipt), use
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`. Treat release channels as an operator-governed
  capability with outstanding feature acceptance, not as a fully accepted baseline workflow.

## Runtime prerequisites (registry watcher)
- `DATABASE_URL` or `DB_DSN` is required in runtime; startup must fail fast if missing.
- DB outbox is canonical in runtime; the worker consumes the DB outbox.
- JSONL outbox (`INDEX_OUTBOX_PATH`) is audit/diagnostic only and must not be used as the worker queue.
- Registry watcher is the single runtime watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

## Environment posture

This document is primarily the `prod` operator entrypoint.

Environment contract:
- `dev`, `test`, and `prod` are defined in `docs/ENVIRONMENTS.md`.
- Production operation means the runtime is acting against the operator's real vault and its production-facing runtime surfaces.
- The local `test` bootstrap path is the isolated verification posture, not production operation.
- Lab/dev-only flows, fixture vaults, legacy watcher paths, and reset-heavy workflows are not production operation even when they use the same codebase.

Operator rule:
- if a task depends on looser safety assumptions, mock providers, fixture stores, or lab-only tuning, treat it as `dev`
- if a task touches the real vault, production stores, or normal runtime startup/verification surfaces, treat it as `prod`

Current runtime path:
1. The registry watcher scans the vault, emits DB outbox events, and appends `watcher.run` audit rows so status can count runtime ticks.
2. The worker consumes DB outbox rows and performs ingest/index, panel scan, and promotion work, preserving bounded retries for transient missing or unstable notes before giving up.
3. Health, status, and metrics confirm whether that path is healthy.

## Canonical Local Test Bootstrap

The repo-supported local runtime verification path is the local `test` bootstrap golden path.

Use this path when you need a clean-state, repeatable verification run rather than flexible `dev` exploration:

1. reset runtime state
2. initialize a clean test vault
3. seed the UAT notes
4. start the local stack against that vault
5. verify health/status
6. run scripted UAT

Canonical command:

```bash
make test-bootstrap
```

Expanded command path:

```bash
make test-vault-init
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

Operational intent:
- this is the intended repo-supported path for local runtime verification
- `dev` remains the flexible local environment for exploration and debugging
- `test` is the isolated verification environment that should be resettable and reproducible
- the bootstrap path is itself part of the productized verification contract, not just setup glue
- startup, deterministic `make verify-runtime`, and scripted UAT/idempotence slices are shipped, so treat this path as the supported local verification lane while broader bootstrap hardening stays bounded to explicit follow-up slices

TEST startup has two fail-closed Compose modes. With no selected vault, the universal TEST overlay
keeps the watcher disabled and its vault path empty. With an explicit TEST vault, startup composes
the selected-vault mount and then the TEST-only activation overlay, which binds the watcher to the
same in-container `/app/vault` target regardless of inherited parent-shell watcher values.

Use `docs/runbooks/UAT_PANEL_WATCHER.md` for the detailed walkthrough and `docs/runbooks/RUNBOOK_RESET_TO_ZERO.md` when you need the full reset semantics.

When the issue is startup topology or Compose wiring, switch to `docs/INFRASTRUCTURE.md`.
When the issue is signal interpretation, switch to `docs/OBSERVABILITY.md`.
When the issue is health semantics or degraded-state rules, switch to `docs/HEALTH.md`.

## ASK provenance shadow operations

The ASK provenance manifest is an opt-in read-side experiment, not a canonical
audit store. It is disabled unless `ASK_PROVENANCE_MANIFEST_ENABLED=1` and a
local `ASK_PROVENANCE_PRIVACY_KEY` is present. Its JSONL file must remain below
the fixed repo-local `runtime/agent_memory` root; resolved path/root symlinks
and escapes fail closed, so it cannot be relocated into a vault or index
surface.

Enabled capture is dispatched after the answer through a bounded queue to one
daemon worker. File locks, atomic replacement, retention, and fsync therefore
do not extend ASK response latency or create unbounded worker threads. Records
expire after 14 days, are capped at 256 entries, and startup pruning plus an
hourly per-path janitor removes expired records even if no later ASK occurs. An
expired, malformed, inaccessible, or identity-incomplete record is not
comparable and must yield `indeterminate`. Capture/janitor failure is logged
locally and never changes the ASK response or authorizes a write.

## Watcher Operations

Use this section only when the issue is specifically about watcher deployment, config, or execution mode.

### Watcher entrypoint classification

Entrypoints are explicitly classified by environment per `docs/ENVIRONMENTS.md`:

**Production-facing entrypoint:**
- `python -m app.cli watcher run` — canonical production registry watcher (prod/dev)
  - Multi-spec watcher registry loop, artifact path and state separation by environment
  - Supports both `prod` and `dev` environments via `PKM_ENVIRONMENT` or profile-based inference
  - This is the entrypoint for the current production baseline

**Dev-only legacy entrypoints (require `PKM_ENVIRONMENT=dev` or `PKM_SETTINGS_PROFILE=lab`):**
- `python -m app.cli vault-watcher-run` — single-shot snapshot watcher (historical implementation)
- `python -m app.cli vault-watcher-daemon` — snapshot daemon (historical implementation)
- `python -m app.cli runtime-loop` — watcher → panel → promotion loop (historical test path)

The legacy entrypoints are retained for lab/dev workflows but should not be used for production operation. Use `watcher run` for all production-facing and standard dev runtimes.

Watcher auto-exec enablement rule:
- Treat `python -m app.cli settings-explain` plus `python -m app.cli status` as the canonical enablement check.
- `WATCHER_AUTO_EXEC=1` is necessary to arm panel auto-exec, but it is not sufficient on its own to prove rollout safety.
- Before enabling auto-exec for a wider runtime scope, confirm the effective allowlist, recent skip counters, and write-guard/provenance context are coherent across both CLI surfaces.
- When the question is release or merge readiness rather than a live local diagnosis, corroborate the operator view with the enforced CI summary line (`CI SUMMARY GATES ok=<bool>`).
- `python -m app.cli settings-validate` is the schema validation gate for repo-shipped panel action catalog/wiring and watcher settings. It rejects invalid panel action ids, missing required panel fields, malformed watcher `auto_run` values, and unknown watcher allowlist action ids.
- The same governed seam now covers watcher-detected `settings/local.md` deltas for runtime-gating keys, so direct value edits to `enableVaultWatcher` / `enableAutoIndexing` emit `SettingsWriteReceipt`s, and deleting either key from frontmatter emits the same governed file-surface receipt without reintroducing the key (#2512). The registry keeps `settings/local.md` state shared across watcher specs, so a single human edit still yields one receipt per changed runtime-gating setting.
- This validation path does not widen runtime authority: watcher auto-exec remains guarded by `WATCHER_AUTO_EXEC`, allowlist policy, and per-note `ai_panel_auto_run: never` opt-out.
- Sync-latency measurement mode is operator-scoped: keep `vault/@Settings/watchers.md` allowlist at default (`promote.evergreen`) and run harness/measurement sessions with `WATCHER_MEASUREMENT_MODE=1`. This temporarily appends `ingest.summary.create` during the run and returns to the default posture after the process exits.

### Docker-first deployment
1. Set `VAULT_ROOT` to your local vault path:
   `export VAULT_ROOT="/Users/you/PKM - Alpha"`
2. On macOS/iCloud-backed vaults, set container UID/GID mapping so watcher and worker can write UUID heals back into the vault:
   - `export LOCAL_UID=$(id -u)`
   - `export LOCAL_GID=$(id -g)`
   - recreate services after changes: `docker compose up -d --force-recreate watcher worker api`
3. Start the watcher service:
   ```bash
   docker compose up -d watcher
   ```
4. Follow logs:
   ```bash
   docker compose logs -f watcher
   ```

### Host fallback
- Run the registry watcher directly:
  ```bash
  WATCHER_ENABLE=1 WATCHER_VAULT_PATH="/path/to/vault" python -m app.cli watcher run
  ```
- Single-tick safety run:
  ```bash
  python -m app.cli watcher run --max-ticks 1
  ```
- The legacy snapshot watcher remains lab-only and is not part of runtime/start-system flows. Do not use it for current runtime operation.

### Key watcher env and defaults
- `WATCHER_ENABLE=1` arms the registry watcher.
- `WATCHER_VAULT_PATH` points at the vault root.
- `WATCHER_SCOPE_GLOB` overrides scan scope (default `**/*.md`).
- `VAULT_INBOX_DIR_REL` overrides inbox folder behavior when needed.
- `WATCHER_STATE_DIR` stores registry watcher state.
- `WATCHER_HEARTBEAT_PATH` and `WATCHER_TICK_LOG_PATH` control watcher health/tick outputs.
- `WATCHER_AUTO_EXEC=1` arms panel auto-exec; per-note opt-out remains `ai_panel_auto_run: never`.
- `PANEL_PROACTIVE_ASSIST=0|1` controls proactive panel creation.
- `WATCHER_STOP_FILE` pauses scanning when present.
- Registry watcher state is pruned back to the active scope on each tick so stale file history does not accumulate indefinitely.

### Watcher caveats
- The registry watcher remains polling/snapshot-based; no OS file-event hooks are used.
- Paths with spaces are supported; wrap vault paths in quotes.
- When using iCloud/Obsidian sync, keep scopes conservative and rely on debounce/backoff guardrails.
- Do not use the legacy snapshot watcher for runtime start-system flows.
- Do not treat lab/dev-only watcher paths as production equivalents.

## Obsidian sync runtime

Current runtime model:
- Obsidian vault changes flow through the registry watcher into ingest/update events, then into the DB outbox and worker/indexer path
- runtime-side note writes must stay narrow: agreed frontmatter updates, AI panel mutations, inbox/log artifacts, and explicit maintenance writes
- `app/knowledge/write_ops.py` is the shared vault-write boundary for runtime/services; deeper transport details stay behind the knowledge-port abstractions

Operational rules:
- never treat note body rewrites as a normal sync action
- rename or move events should update canonical path state without forcing re-embedding when body content is unchanged
- delete propagation should emit explicit delete semantics only when the removed path was the UUID's last active file-state reference
- settings hot-reload should apply policy changes without restart, while invalid settings payloads should fail closed and preserve the previous active policy

Companion docs:
- `docs/HUMAN-FLOWS.md` for human-facing vault behavior constraints
- `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` for the note-write abstraction and adapter contract
- `docs/runbooks/UAT_PANEL_WATCHER.md` for a watcher/panel walkthrough

## Runtime Compose Stack
- Canonical runtime compose stack: `db`, `api`, `watcher`, `worker`.
- `docker-compose.yaml` starts FastAPI (`api`), `worker`, `watcher`, and Postgres for local development.
- Ensure `.env` contains the desired secrets before running `docker compose up --build`.
- Postgres data lives in the `postgres-data` volume; `docker compose down -v` wipes it.
- The API container runs `scripts/start_api.sh` (migrations + `uvicorn`).
- The worker runs `python -m app.workers.outbox_worker` (consumes DB outbox).
- The watcher runs `python -m app.cli watcher run` (registry loop; emits `ingest.vault.changed` / `panel.scan.requested` DB outbox events and appends `watcher.run` audit rows to the JSONL event log).
- Legacy dev stacks may include agent/redis containers; they are not part of the runtime start-system path.
- `scripts/start_full_system.sh` is the supported startup wrapper. It now auto-probes Ollama reachability from inside the containerized runtime and persists the selected Docker-reachable endpoint into `tmp/runtime.env` before declaring startup healthy.
- When `LLM_PROVIDER=ollama`, startup tries the configured endpoint first, then Docker-safe candidates such as `host.docker.internal`, before failing the run.
- Companion UI channel launchers (`make dev-ui`, `make test-ui`, `make prod-ui`) bind the browser
  UI to `127.0.0.1` by default. Set `CUI_BIND_LAN=1` to explicitly opt a channel into a
  `0.0.0.0` bind for trusted LAN/Tailscale UAT. Public internet exposure remains unsupported.
- The Companion UI proxy pins `/api/companion/*` to the same runtime origin so browser UAT does not
  cross providers or devices accidentally. Runtime-unreachable and wrong-device states are distinct
  operator-visible failures rather than generic vault setup prompts.
- Companion TTS is a local-first runtime surface: configured local voices can be selected for clean
  Markdown read-back, mixed-language segments may route to different voices, and production
  deployment still depends on the Mac mini/local model health path.

### BuilderOps cockpit live GitHub plane (#4484)
- The cockpit's `github-live` source reads GitHub REST from **inside the `api` container** via the
  `gh` CLI, which the runtime image installs (`Dockerfile`, runtime-stage apt layer) alongside
  `ffmpeg`/`espeak-ng`. Before #4484 the binary was absent, so the plane refused on every channel
  regardless of configuration.
- The plane is opt-in per channel. `docker-compose.dev.yml :: api` binds
  `COCKPIT_GITHUB_REPO=RasmusTho/agentic-pkm-mvp`; `test` and `prod` deliberately leave it unset and
  render the source as *not enabled* rather than broken. Turning another channel on is a
  promotion-lane act, not a config default.
- The token is host-supplied, never committed. Provision it as the **Keychain item** for the declared
  optional identifier `github.token` under consumer `heimdal-api-ingress` (#4489) — do not hand-write
  an env file: on a governed `scripts/deploy_channel.sh` run the layer's file is bootstrap-owned and
  rebuilt from declared identifiers only, so a hand-written value is discarded. The bootstrap then
  materializes `GITHUB_TOKEN` onto `HOST_SECRET_RUNTIME_ENV_FILE_API`, the same layer that delivers
  `HEIMDAL_RAW_STORE_KEY`. A repo-scoped read-only token suffices — the plane issues GET requests
  only and persists nothing.
- Because `github.token` is declared `optional`, a host with no token still deploys normally and the
  Heimdal ingress lanes are unaffected; the plane simply refuses.
- **A token that is present but malformed fails the whole channel deploy.** Fail-closed here is
  deliberate — a present-but-wrong credential is a misconfiguration, not an opt-out — but the cost is
  that `docker compose` never runs, so no service starts, not just the cockpit. The error names the
  logical id (`github.token`), never the value. Fix the Keychain item and re-run. The same has always
  been true of a malformed `heimdal.raw-store-key`; tracked as deferred defect `KD-4489-malformed-declared-secret-aborts-channel-deploy` on #4172.
- Note the coupling: this layer is only materialized when `heimdal.raw-store-key` also resolves, so
  provisioning the GitHub token alone is not sufficient on the governed deploy path. Identifier and
  account derivation: `docs/LOCAL_SECRET_PROVISIONING/README.md :: Declared identifier contract`.
- Check it with `curl -s localhost:18001/api/cockpit/registry | jq '.sources[] |
  select(.name=="github-live")'`. Full path and rationale:
  `docs/BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE.md :: What makes that command answer fresh (#4484)`.

### Karakeep managed source service (KMA-02)
- `docker-compose.karakeep.yml` is the repo-owned deployment for the self-hosted Karakeep
  read-later source on the mac mini (Heimdal's external source dependency; ADR-0049 §1). It pins the
  `karakeep`/`meilisearch` images, declares the durable `karakeep-data` / `karakeep-meilisearch-data`
  volumes, health-checks both services, and binds to loopback only — there is no public ingress.
- Secrets and the private endpoint ride the operator-owned, gitignored `config/karakeep.env`
  (template: `config/karakeep.env.example`); the committed manifest and template carry no credential
  or endpoint value.
- Backup / update / rollback steps (and their verification checks) live in
  `docs/KARAKEEP_MIMER_ACQUISITION/DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md :: Restart / Durability Posture`.
- `app.heimdal.karakeep_service.assert_fetch_ready` is the fail-loud gate: Heimdal acquisition is
  refused when a required config reference is absent or service health is red, while Mimer replay of
  already-published evidence is unaffected.
- Scope note: this ships the deployment manifest/runbook and the fetch-readiness gate only. The live
  acquisition pipeline (Heimdal fetch → published evidence → Mimer candidates) is not accepted as
  shipped until the parent Karakeep acquisition feature (#3367) completes its acceptance slice.

Detailed startup, local topology, and recovery procedures live in `docs/INFRASTRUCTURE.md`.
Task-specific operator walkthroughs live in `docs/runbooks/`.

## Auth & Rate Limiting
- Refer to `docs/SECURITY.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Use `docs/SECURITY_ARCHITECTURE.md` for security review routing and
  `docs/security/API_SECURITY_MATRIX.md` for route-by-route exposure and mutation classification.
- Store the API key in environment or secret manager; rotate by updating deployments and monitoring logs for legacy usage.

## Observability
- Logs: a JSON formatter is available via `app/observability.setup_logging()`, but it is **not called at startup**, so logs are **not JSON-formatted by default**. Until a startup hook calls `setup_logging()`, logs are plain text; do not assume structured JSON when wiring a logging stack (CloudWatch, ELK, etc.).
- Version: `GET /version` returns the running git SHA and build time (`OBSSTAB-05`); `/api/health` also carries a `version` field. Use it to confirm which commit is actually deployed during an incident.
- Metrics: enable `METRICS_ENABLED=1` to expose Prometheus metrics under `/metrics` using `prometheus-fastapi-instrumentator` (secure access appropriately).
- Runtime signals and interpretation live in `docs/OBSERVABILITY.md`.
- Local Prometheus+Grafana recipe lives in `docs/INFRASTRUCTURE.md` (Docker Compose).

## Prod probe and push alert (scheduled backstop)

`ops/host-setup/mac-mini/prod_probe.py` is the hard-down backstop probe installed as
a launchd job (`com.yggdrasil.prod-probe`) on the mac mini. It runs on a configurable
interval (default 60 s), curls `/readyz` and `/api/health` `required_ok` (NOT the
top-level `ok`), checks worker-heartbeat staleness, and dispatches one push alert on
the first outage transition. Once the probe sees the first healthy run after that
outage, it emits one recovery signal and clears the outage state so a later distinct
outage can alert again. The configured channel remains pluggable (ntfy / Telegram /
mail — channel choice is an operator decision set via `PROD_PROBE_CHANNEL`).

**Two distinct Makefile targets — do not confuse them:**

| Target | What it does |
| --- | --- |
| `make live-prod-probe` | Invokes the real probe script against `PROBE_BASE_URL` (default `localhost:8000`) — a live spot-check of the actual prod stack. Exits 0 if healthy, 1 if prod is down. |
| `make check-prod-channel` | Runs the pytest channel-isolation suites (`tests/ops/test_release_channel_isolation.py`, `tests/ops/test_release_channel_startup_targets.py`) to confirm that prod and test channels are correctly isolated. No live network calls to the running stack. |
| `make check-test-channel` | Same channel-isolation suites plus the test-channel preflight (`tests/release_channels/test_channel_isolation_preflight.py`). |

**Transition / recovery guarantee:** A sustained outage sends one down alert, repeated
down probes suppress while the outage remains active, and the first healthy run sends one
recovery signal and clears the outage state. A later distinct outage alerts again.
The state marker (`PROD_PROBE_STATE_FILE`, default `/tmp/yggdrasil-prod-probe.state`)
is rebuildable; delete it to reset the transition state manually.

**Install:** See `ops/host-setup/mac-mini/install.sh` for how to register the launchd
job. The plist is at `ops/host-setup/mac-mini/com.yggdrasil.prod-probe.plist`.

## Prod backup watcher (stale or failed nightly dump)

`ops/host-setup/mac-mini/prod_backup_probe.py` is the watcher for the nightly prod DB
dump (`local.prod-pgdump` on the mac mini, which runs `~/bin/prod-pgdump-run.sh`). It is
installed as its own launchd job, `com.yggdrasil.prod-backup-probe`, and runs hourly.

**Why it exists:** the dump job failed every night from 2026-07-06 to 2026-07-29 and the
gap went unseen for three weeks, because nothing read its log. The underlying TCC
permission bug is fixed; this watcher closes the detection gap that let it hide.

**It does not depend on the backup job working.** The load-bearing signal is the dump
directory itself, so a job that stops firing entirely — and therefore writes no `FAIL`
line at all — is still caught. Three checks run on every pass and every failure is
reported in one alert:

| Check | Signal | Default budget |
| --- | --- | --- |
| Dump freshness | newest `prod-*.dump` in `BACKUP_DIR` (`/Volumes/T7/prod-db-backups`) | `BACKUP_MAX_AGE_HOURS=48` — tolerates one missed night |
| Status verdict | last line of `BACKUP_STATUS_FILE` (`~/Library/Logs/prod-pgdump.status`) reports `OK`, not `FAIL` | — |
| Status freshness | that line's own ISO-8601 timestamp | `BACKUP_STATUS_MAX_AGE_HOURS=30` — a job that did not fire |

**Unverifiable is never healthy.** A missing or unmounted `/Volumes/T7`, an unreadable
directory, an empty status file, or a garbled status line all alert. The watcher never
reports green on a signal it could not read.

### The TCC hop (one-time setup)

launchd starts jobs unattributed, with no TCC grants, so it cannot read the removable
volume holding the dumps. Verified on the mini 2026-07-29 — and the failure mode is
deceptive:

```
py_isdir True                                        # stat is allowed
py_listdir_ERR PermissionError [Errno 1] Operation not permitted
```

`Path.glob` silently swallows that `PermissionError` and yields nothing, so a naive
implementation reports "no dumps found" forever instead of "I am blind". The watcher
therefore uses `os.scandir` and separates *not mounted* from *permission denied*.

The fix is the same loopback ssh hop the backup job itself uses, through this watcher's
own key and its own read-only lister (`ops/host-setup/mac-mini/prod_backup_list.sh`,
installed to `~/bin/prod-backup-list.sh`) — no credential or code path is shared with the
backup job. `install.sh` wires the plist and prints these steps; run them once:

```bash
ssh-keygen -t ed25519 -N '' -C prod-backup-list -f ~/.ssh/id_ed25519_prod_backup_list
```

Then add the public key to `~/.ssh/authorized_keys` as a single line, locked to a forced
command so it can only ever list dumps:

```
command="$HOME/bin/prod-backup-list.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... prod-backup-list
```

Until that is done the watcher sends **one** alert saying it cannot see the dump volume
and naming the fix, then suppresses. The status-file checks keep working meanwhile, so a
failed or non-firing backup is still caught. Verify the hop with:

```bash
ssh -F /dev/null -i ~/.ssh/id_ed25519_prod_backup_list -o IdentitiesOnly=yes -o BatchMode=yes localhost
# → one "<epoch-mtime> <path>" line per dump, or MISSING / DENIED / EMPTY
```

**Transition / recovery guarantee:** identical to the prod probe — one alert on entering
a bad state, suppressed while it persists, one recovery signal on the first healthy run,
then re-armed for a later distinct failure. A failed push does *not* record the state, so
a channel outage retries on the next run instead of swallowing the alert. The state
marker (`PROD_BACKUP_PROBE_STATE_FILE`, default
`/tmp/yggdrasil-prod-backup-probe.state`) is rebuildable; delete it to re-arm manually.

The channel is pluggable via `PROD_BACKUP_PROBE_CHANNEL` (`ntfy` | `telegram` | `mail` |
`none`) and defaults to the same `NTFY_TOPIC` the prod probe pushes to, so the operator
watches one topic for both.

```bash
make live-prod-backup-probe                              # live spot-check; exit 1 = backup failed or stale
PROD_BACKUP_PROBE_CHANNEL=none make live-prod-backup-probe   # dry run: log the verdict, push nothing
launchctl list | grep prod-backup-probe                  # confirm the job is loaded
```

**Known current state:** prod is down entirely (issue #4282 — the `pkm-prod_pgdata`
volume is gone), so the status file legitimately reports `FAIL pg_dump_failed` and the
newest dump is from 2026-07-11. The watcher alerts on both facts, which is correct: there
is no current prod backup. Expect it to stay in the alerted (suppressed) state until prod
is restored and a dump lands.

**Install:** `ops/host-setup/mac-mini/install.sh` step 4c registers the launchd job. The
plist is at `ops/host-setup/mac-mini/com.yggdrasil.prod-backup-probe.plist`.

The probe and its lister are installed to `~/bin/` and run under `/usr/bin/python3`, not
out of the repo checkout and not under the gateway venv. Both are deliberate: the probe
is stdlib-only, and a backup watcher must not go dark because the repo is parked on a
feature branch or the gateway venv was never built. `install.sh` is the single producer
of those copies, so the host and the repo cannot drift.

**Status as of 2026-07-29:** both `com.yggdrasil.prod-backup-probe` and
`com.yggdrasil.prod-probe` are loaded on the mini and have each pushed one live alert to
the `yggdrasil-prod-alerts` ntfy topic. The backup watcher is in its suppressed
alerted state pending the one-time key setup and the prod restore (#4282).

## Runtime health: watcher → DB outbox → worker
- Watcher heartbeat: `WATCHER_HEARTBEAT_PATH` (default `/app/tmp/watcher_heartbeat.json` in containers, `tmp/watcher_heartbeat.json` on host).
- Worker heartbeat: `WORKER_HEARTBEAT_PATH` (default `/app/tmp/worker_heartbeat.json`).
- DB outbox: check the `outbox` table for recent `ingest.vault.changed` and `panel.*` events; the worker should mark `delivered_at`.
- JSONL audit: `INDEX_OUTBOX_PATH` should append lines, but it is not the worker queue.
- Status: `python -m app.cli status` reports `worker_queue` vs `events_log` to distinguish DB vs JSONL.
- Settings gate view: `python -m app.cli settings-explain --json` is the canonical provenance and gate-resolution surface for watcher auto-exec, allowlist validity, and write guard context.
- Health command semantics and degradation rules live in `docs/HEALTH.md`.

## Event and queue troubleshooting
- Use the DB `outbox` table as the authoritative queue. Rows with `delivered_at is null` are pending
  or failed work; order them by `created_at` when reconstructing worker consumption order.
- Inspect the worker logs for `worker retry queued`, `worker retry exhausted`, `worker retry enqueue
  failed`, and `worker handler failed` messages. These are the current poison-message and retry
  observation points; there is no separate DLQ service in the active runtime.
- Promotion consumer failures should also surface as `promote.error` rows in the DB outbox or
  JSONL audit stream, with `source_event` and `trace_id` intact so the failed intent can be traced
  back to the originating input.
- Retry events carry `_worker_retry_count`, `_worker_retry_reason`, and
  `_worker_retry_enqueued_at` in the payload so operators can distinguish transient deferrals from
  fresh work.
- Use `event_id` to identify duplicate deliveries and `trace_id` to correlate watcher, worker,
  panel, promotion, and status/audit observations.
- Treat `INDEX_OUTBOX_PATH` JSONL lines as audit evidence only. A line in JSONL does not prove a DB
  outbox row is pending, delivered, or failed, and `python -m app.cli status` keeps
  `events_log` separate from `worker_queue` for that reason.
- A PROD deploy (`scripts/deploy_channel.sh deploy prod <sha>`) refuses to proceed — before pin or
  Compose mutation — when pending outbox rows are already at the terminal retry boundary and would
  deterministically dead-letter on worker restart (#3903). The deploy log always carries a
  `prod pending-retry preflight: ok|skipped:<reason>|blocked ...` status line; on a block, resolve
  the underlying processing failure first (this preflight never mutates the queue), then redeploy.
  Rollback is deliberately not gated. Full contract:
  `docs/HEALTH.md :: Outbox and dead-letter signals`.

Operator triage order:
1. Run `make verify-runtime`.
2. If you need extra detail, run `docker compose exec -T api python -m app.cli health --json`.
3. Run `docker compose exec -T api python -m app.cli settings-explain --json` to confirm watcher gate state, allowlist validity, provenance, and write-guard context.
4. Run `docker compose exec -T api python -m app.cli status` to confirm watcher automation counters, last tick skips, last-run skip reasons, and panel-action/compiler provenance (source paths and combined digest).
5. Check watcher and worker heartbeat files.
6. Inspect DB outbox freshness and `delivered_at`.
7. For enablement decisions, treat `WATCHER_AUTO_EXEC` as necessary but not sufficient; corroborate with `allowlist`, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed`.
8. Escalate to `docs/INFRASTRUCTURE.md` or a task-specific runbook if the issue is startup/runtime-topology specific.

## Common operator CLI commands

Use `python -m app.cli <command> --help` for the full, current argument list. These are the stable operator-facing entrypoints:

| Command | Purpose |
| --- | --- |
| `health` | Local dependency and readiness checks (ffmpeg/yt-dlp/outbox/LLM reachability). |
| `status` | Human-readable runtime status snapshot for watcher/worker/outbox. |
| `watcher run` | Registry watcher loop for the runtime path. |
| `settings-validate` | Validate settings artifacts and compiled settings. |
| `settings-explain` | Show settings provenance and effective resolution. |
| `canvas open|edit|close` | Operate the bounded canvas co-authoring surface when `CANVAS_ENABLED=1`. |
| `llm check` | Probe LLM/embedding endpoint reachability. |
| `index rebuild|doctor|reconcile` | Rebuild derived vectors, diagnose drift read-only, or explicitly reconcile stale/mixed rows. |
| `pipe <note.md>` | Run ingest for a note/path outside the watcher loop. |
| `pkm-alpha-ingest`, `vault-alpha-ingest` | Compatibility aliases for legacy startup and ingest callers; prefer the neutral ingest commands for new scripts. |
| `make verify-runtime` | Check container health plus in-container runtime health/status for the live Docker stack. |

Flow mapping:
- `python -m app.cli watcher run` -> watcher runtime
- `python -m app.cli ask` -> ASK flow (see `docs/HUMAN-FLOWS.md`)
- `python -m app.cli canvas open|edit|close` -> bounded canvas co-authoring surface (flagged; see `docs/HUMAN-FLOWS.md` and `docs/CANVAS_CHAT_SURFACE/README.md`)
- `python -m app.cli runtime-loop` -> legacy/dev-only runtime path, not part of current baseline operations

Useful examples:

```bash
LLM_PROVIDER=mock python -m app.cli health --json
python -m app.cli watcher run --max-ticks 1
python -m app.cli pipe notes/meeting.md
python -m app.cli settings-explain --json
python -m app.cli settings-validate
```

Startup/runtime verification now treats task routes and embeddings explicitly:
- `checks.llm_task_routes` verifies the effective chat/reasoning/embed/eval routes for the current config.
- `checks.embedding_index` reports `rebuild_required=true|false` and the active/stored embedding identity relationship.
- `make verify-runtime` prints both the task-route summary and the embedding-index rebuild state from inside the containerized stack.
- Index operations share the canonical text contract in `docs/DB_SCHEMA.md :: store_vector_index`.
  Every producer removes AI panels to a fixed point once, then uses those exact bytes for the
  provider call, content hash, and derived `content`/`text` aliases. A remainder containing only
  whitespace is treated as non-indexable rather than embedded or upserted as an empty vector payload;
  any prior derived vector is removed.
  `index doctor` remains read-only. During explicit `index reconcile`, a present authoritative
  source that has become canonically non-indexable is selected regardless of its stored hash or
  identity. Before deletion, reconcile locks and reclassifies that source in the same transaction as
  the conditional vector purge: a newly indexable source is embedded instead, while a source that
  disappeared retains the vector-payload fallback. The source row is never mutated.

## Startup telemetry (startup_status.json)
- Location: `tmp/startup_status.json` (workspace root on the host).
- Lifecycle: written by `scripts/start_full_system.sh` on phase changes and in the cleanup trap; the last write happens on exit. Values are merged with the existing file; fields with explicit `None`/empty values are cleared when the writer marks them as clearable.
- Fields:
  - `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `timestamp` (last write). `started_at`/`ended_at` may appear when callers add them.
  - `startup_succeeded`, `runtime_verified`, `operator_interrupted`
  - `ollama_endpoint_repaired`, `ollama_endpoint_drift`, `ollama_configured_base_url`, `ollama_effective_base_url`, `ollama_endpoint_persist_hint`
  - `llm_probe_step`, `llm_probe_cmd`, `llm_probe_rc`, `llm_probe_output_snippet`
  - `compose_up_step`, `compose_up_cmd`, `compose_up_rc`, `compose_up_output_snippet`
  - `db_probe_step`, `db_probe_cmd`, `db_probe_rc`, `db_probe_output_snippet`
- Durable fix flow:
  - If startup auto-repairs the Ollama endpoint, run `make persist-runtime-repairs` to write the working endpoint back to `.env`.
- Debugging cold-start failures after `docker compose down`:
  - Bucket A: compose-up failure → check `compose_up_*` fields; expect `exit_reason=compose_up_failed` and a short `compose_up_output_snippet`.
  - Bucket B: db container/CID failure → `db_probe_step=compose_ps_db` and an empty/failed `db_probe_output_snippet`.
  - Bucket C: exec/psql timing failure → `db_probe_step=db_env_*` or `db_probe_rc!=0`; `db_probe_output_snippet` shows the failing exec/psql error.
- What to paste into an issue/PR comment: `timestamp`, `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `compose_up_*`, `db_probe_*`, `llm_probe_*`.

## Incident handling
1. Identify the failing surface with `health`, `settings-explain`, `status`, and heartbeat/outbox checks.
2. Stabilize the runtime by reducing optional integrations only if needed for diagnosis.
3. If the incident concerns watcher auto-exec safety, record the observed allowlist, skip counters, write-guard/provenance state, and whether `CI SUMMARY GATES ok=<bool>` is green where CI is part of the rollout path.
4. Record whether the incident was observed in `dev` or `prod`, then update `docs/STATUS.md` if current operational reality changed.
5. Use the relevant companion document or runbook for recovery details.
6. For watcher, panel, or CLI-first orchestrator incidents on shipped current-state surfaces, use `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`.

Quick issue routing:
- Missing dependency or local runtime startup issue -> `docs/INFRASTRUCTURE.md` and `docs/DEPENDENCIES.md`
- Health contract or degraded-state interpretation -> `docs/HEALTH.md`
- Metrics/logging interpretation -> `docs/OBSERVABILITY.md`
- Watcher/panel/orchestrator incident triage -> `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`
- Watcher/panel manual walkthrough -> `docs/runbooks/UAT_PANEL_WATCHER.md`
- Go-live/startup diagnostics -> `docs/runbooks/RUNBOOK_GO_LIVE.md`
- Prod go-live acceptance (preflight through soak, rollback rehearsal, receipt) -> `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`

## Companion UI Entry Surfaces

- Current Companion UI operator-visible entry surfaces include the server-rendered System Entry Point substrate: entry-state declarations, latency-ladder re-entry treatment, unified topbar/overlay host, Panel command palette, governed capture modal, memory review drawer, read-only receipts history modal, system map overlay, opt-in guidance layer, settings drawer, read-only commitment surfacing, and the state-gallery validation harness.
- Capture uses `POST /api/companion/capture`; it is a governed vault-inbox append through WriteGuard and `app.knowledge.write_ops`, with `capture.inbox.appended` emitted as metadata-only operational evidence.
- Memory review uses `GET /api/companion/memory/review-queue` and `POST /api/companion/memory/review-queue/{candidate_id}/decision`; accept/reject/revise are governed review outcomes, while defer remains non-terminal queue state.
- Parent #1782 is closed through #1795 validation. Operators should treat source-peek presentation, posture emphasis switching, and the context lane / place band as unshipped follow-ups unless a later owner-doc update promotes them.

## DB snapshot/restore

**Scope: dev-ergonomics and on-demand forensic dump — this is NOT scheduled disaster recovery.**
The vault (Obsidian iCloud) is the durable system-of-record; the database is a disposable projection.
These Makefile targets are for bug-reproduction and incident investigation only.
Do not use them as a prod DR restore path.

Three targets are available:

| Target | Purpose |
|---|---|
| `make db-snapshot` | Dumps the dev/test DB to a timestamped `.dump` file under `.db-snapshots/dev_<UTCstamp>.dump`. Refuses prod-looking DSNs; use `make db-dump-prod` for explicit prod forensic dumps. |
| `make db-restore` | Restores from the most-recent **dev_/test_** snapshot (or pass `SNAPSHOT=<path>` for a named file). |
| `make db-dump-prod` | Writes a timestamped forensic dump from the prod DB on demand (no scheduling). Source `.env.prod.local` first. Dump-only — it never restores. |

All three targets derive the DSN from `DATABASE_URL` / `DB_DSN` via `app/db/dsn.py::resolve_dsn()` — no hardcoded connection strings.

Host-published Postgres ports (see `docker-compose.*.yml`): **dev = `app_dev` on `15433`**, test = `app_test` on `15434`, prod = `app` on `15432`.

Dump files are written to `.db-snapshots/` which is gitignored. No retention/purge policy exists; remove old files manually.

**Restore safety (data-loss guard):**
- A bare `make db-restore` only ever considers `dev_*.dump` / `test_*.dump` snapshots — it will **never** auto-select a `prod_*.dump`. (A named `SNAPSHOT=<path>` restore of any file is still allowed for deliberate forensic work.)
- `db-restore` **refuses** to run when the resolved target DSN looks like prod (database name exactly `app`, or host port `15432`) unless you pass `ALLOW_PROD_RESTORE=1`. This stops a stray `.env.prod.local` in your shell from rewriting prod.

**Usage examples:**

```bash
# Dev snapshot + restore cycle (dev = app_dev on host port 15433)
export DATABASE_URL=postgresql://app:app@127.0.0.1:15433/app_dev
make db-snapshot                            # → .db-snapshots/dev_20260628T...Z.dump
# ...reproduce a bug, mutate state...
make db-restore                             # restores from the latest dev_/test_ snapshot
make db-restore SNAPSHOT=.db-snapshots/dev_20260628T153000Z.dump   # named restore

# Test DB is app_test on host port 15434:
#   export DATABASE_URL=postgresql://app:app@127.0.0.1:15434/app_test

# Prod forensic dump (operator-only, no automation)
source .env.prod.local
make db-dump-prod                           # → .db-snapshots/prod_20260628T...Z.dump
```

**Constraints:**
- These `make` targets are unscheduled and manual; there is no off-host/cloud backup
  strategy and no automated purge. Scheduling exists only for the separate nightly mac
  mini job `local.prod-pgdump` (dumps to `/Volumes/T7/prod-db-backups`), which is watched
  by `com.yggdrasil.prod-backup-probe` — see *Prod backup watcher* above.
- These dumps must not become a production DR restore path.
- pg_dump / pg_restore must be installed on the host (they are not bundled in containers).
