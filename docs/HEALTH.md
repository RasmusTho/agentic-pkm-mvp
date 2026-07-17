State: SoT v5.5 Reality-MVP baseline locked. This document defines the health CLI behavior and runtime health contract.
# Health CLI & Contract

Fast way to verify local dependencies (`health`) and the runtime health contract snapshot that drives the worker write guard.

For top-level operational runbooks, use `docs/OPERATIONS.md`. For runtime telemetry interpretation beyond the health contract, use `docs/OBSERVABILITY.md`.

<!-- SECTION:HEALTH:BEGIN -->
## Dependency checks
```bash
python -m app.cli health --json
```
- Returns `{"ok": bool, "checks": {...}, "trace_id": "..."}`.
- Exit code `0` when all checks pass, otherwise `1`.
- Use `--trace-id TRACE123` to correlate with other logs.

| Key | Source | What is validated | Remediation |
| --- | --- | --- | --- |
| `ffmpeg` | `app/cli/health.py:20-28` | `shutil.which("ffmpeg")` | Install via a package manager (`brew install ffmpeg` or `apt`). |
| `yt_dlp` | `app/cli/health.py:30-36` | Module import | `pip install -r requirements.txt`. |
| `index_outbox` | `app/cli/health.py:38-46` | Write access to `INDEX_OUTBOX_PATH` (creates directories when missing) | Fix permissions or adjust the env path. |
| `ollama` | `app/cli/health.py:48-49` | GET `${OLLAMA_URL}/api/tags` when `LLM_PROVIDER=ollama`; skipped otherwise | Start Ollama or switch to `LLM_PROVIDER=mock`. |
| `obsidian` | `app/cli/health.py` + `app/knowledge/health.py` | Obsidian CLI in `PATH` and installer compatibility (`>=1.12.4`) when knowledge policy requires Obsidian adapter | Install/update Obsidian installer and ensure `obsidian` command is available. |
| `companion_diagnostics` | `app/cli/health.py:586-635` + `app/services/companion_diagnostics.py` | Calls `companion_diagnostics_summary(vault_root)`; reports `duplicate_companion_count` (UUIDs present in both canonical `⚙️ System/companions/` and legacy `_system/companions/`). Optional check — does not affect the `ok` boolean; skipped when `vault_root` cannot be resolved. | Inspect `checks.companion_diagnostics.data.duplicate_companion_count` in the JSON output (`python -m app.cli health --json`). Non-zero counts indicate historical duplicates from a dual-write era; remove the legacy `_system/companions/<uuid>.md` files manually or wait for a future migration tool. |

## Health contract snapshot
```bash
python -m app.cli health status --json
```
- Emits the `HealthContract` snapshot (`environment`, `state`, `reason`, `outbox_recent_age_s`, `catch_up_progress`, etc.).
- `environment` reflects the resolved runtime environment (`dev` or `prod`); controlled by `PKM_ENVIRONMENT` env var or implicit from `PKM_SETTINGS_PROFILE` (see `docs/ENVIRONMENTS.md`).
- `catch_up_progress` reports how the worker interprets its active queue (DB outbox when `STORE_BACKEND=pg`), while the JSONL audit log (`INDEX_OUTBOX_PATH`) is used for lag/idle detection.
- The worker heartbeat file (`$WORKER_HEARTBEAT_PATH`) is the signal the Docker healthcheck verifies; the contract observes the latest heartbeat timestamp too.

- `catch_up_progress` now leans on `outbox_recent_age_s`, which is computed from the newest timestamp in the JSONL log. `catch_up` therefore means the worker has not seen new events within the configured thresholds rather than being stuck on the oldest record.
- When the newest outbox event age exceeds `outbox_degrade_oldest_age_s` for the configured sample count, the contract transitions to `degraded` with reason `outbox idle ...` and suggests running `events-doctor`.
- Runtime processing is driven by the DB outbox; `INDEX_OUTBOX_PATH` remains the append-only audit log. Clearing the JSONL file only affects audit/diagnostics and does not reset the DB queue.
- There is no `health explain` command in this release; use `python -m app.cli health status --json` (plus the health incident log) to understand why a state transition occurred.

## Dead-letter signal

The contract snapshot surfaces the dead-letter queue state (KERNEL-12 / #2774, audit invariant I-E4) so a "quietly does nothing" pipeline stall is loud instead of invisible:

| Snapshot field | Meaning | Source |
| --- | --- | --- |
| `dead_lettered_count` | Number of `outbox.event.dead_lettered` audit records — outbox rows the worker dropped after exhausting its dispatch-attempt budget. | DB outbox (`topic = 'outbox.event.dead_lettered'`) when `STORE_BACKEND=pg`; otherwise the JSONL audit-log tail. |
| `oldest_undelivered_age_seconds` | Age of the oldest DB outbox row still pending delivery (`delivered_at is null`); `0.0` when the queue is empty. | DB outbox only. On the file/memory path this is always `0.0` — the JSONL log is an audit sink with no delivery tracking. |
| `dead_letter_status` | `pass` or `warn`; `warn` when either threshold below is breached. | Computed from the two fields against `HealthThresholds`. |

Thresholds (configurable in the vault `health.md` `thresholds:` block, same as the outbox-age thresholds; both keys are optional and default when absent):

| Threshold | Default | Breach condition |
| --- | --- | --- |
| `dead_lettered_warn` | `1` | `dead_lettered_count >= dead_lettered_warn` (any dead-letter is loud by default) |
| `oldest_undelivered_age_warn_s` | `600.0` | `oldest_undelivered_age_seconds > oldest_undelivered_age_warn_s` |

Posture — **alerting signal only, read-only, no auto-repair**:

- A breach sets `dead_letter_status: warn` and appends an inspection hint to `suggested_actions`, and the CLI dependency check (`python -m app.cli health --json`, key `checks.dead_letters`) reports `ok: false` with the same fields.
- A breach does **not** block vault writes: dead-letter breach is not in `WRITE_BLOCKED_STATES` (`writes_allowed` stays `true`). Dead-letters are downstream-processing failures; capture is the product and stays available while processing is repaired.
- `checks.dead_letters` is a non-required check: it never flips the aggregate `/api/health` `ok`/`required_ok` booleans, so a full dead-letter queue cannot restart containers.
- Re-driving or clearing dead-lettered rows is an explicit operator/agent action; no health surface mutates the outbox.

## Store-resolution signal

The contract snapshot surfaces store-backend resolution health (#2843, follow-on to KERNEL-03 / #2765) so a misconfigured or unreachable store backend is loud on the health surface — not just at first store write:

| Snapshot field | Meaning | Source |
| --- | --- | --- |
| `store_resolution_status` | `ok` or `failed`. `failed` means the production store seam (`app.stores.resolve_store_backend()`) could not resolve a backend: an explicit but unsupported `STORE_BACKEND` value, a configured-but-unreachable Postgres DSN, or no backend configured at all (no `STORE_BACKEND` and no `DATABASE_URL`/`DB_DSN`). | `app.stores.resolve_store_backend()`, the same seam `get_object_store()` / `get_vector_index()` use. |
| `store_resolution_error` | Human-legible reason when `store_resolution_status` is `failed`; `null` otherwise. | The `RuntimeError` message raised by the store seam. |

Posture:

- A resolution failure forces `state: unhealthy` (the same short-circuit path as a live Postgres-down ping, #2598) — `writes_allowed` is `false` and `/readyz` returns `503`. This is intentionally loud: before this fix, `_count_objects()` swallowed the resolution error and reported `store_object_count: 0` with the state otherwise healthy, so a misconfigured backend (e.g. no `DATABASE_URL`/`STORE_BACKEND` at all) looked identical to a genuinely empty, healthy store.
- A **genuine** empty store (backend resolves successfully, zero objects/outbox events) still reports `store_resolution_status: ok` and `bootstrap_state: empty` — resolution success and store emptiness are tracked independently so an empty store is never misread as a failure.
- A narrower post-resolution store-access fault (backend resolved, but `count_objects()` itself later raises — e.g. a migration-owned table missing) does not force `unhealthy`; it reports `bootstrap_state: unknown` with the error in `bootstrap_reason` and adds a `python -m app.cli health --json` hint to `suggested_actions`, so it is still visibly distinct from both `empty` and `active` rather than silently counted as zero.
- No-vault/no-DB idle boot (#2005) is unaffected: the API process still starts and `/healthz` stays an unconditional `200` liveness probe regardless of store-resolution state — only the deeper `/readyz`/contract snapshot goes loud. Loud is not the same as fatal at boot.
- Three sibling sites (`_count_outbox_lines_db`, `_dead_letter_stats_db`, the DB-dependency-down check) previously re-derived "is this backend pg?" from `os.getenv("STORE_BACKEND")` directly, defaulting an unset value to `"memory"` — diverging from the store seam's unset -> DSN-resolution semantics and silently skipping the DB-down short-circuit when a DSN was configured but unreachable. All three now consume one shared `resolve_store_backend()` resolution per `evaluate()` call instead of re-deriving backend semantics locally.

## Span + logging
The command is wrapped with `@span("health.check")`, so health check runs are recorded in `docs/OBSERVABILITY.md`. Exceptions populate `extra.error`.

## CI behavior
- `.github/workflows/ci-smoke.yaml` runs the dependency check with `LLM_PROVIDER=mock`.
- Run `python -m app.cli health status --json` after manual ingestion to confirm `state` is `running` and that `catch_up_progress["processing_mode"]` is `idle` (or `replay` while the worker catches up).
## Health threshold env-var overrides (lab profile only)

The `HEALTH_THRESHOLDS_*` environment variables can override the threshold
values that are normally read from the vault settings file:

| Variable | Field | Type |
| --- | --- | --- |
| `HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S` | `outbox_degrade_oldest_age_s` | `float` |
| `HEALTH_THRESHOLDS_OUTBOX_RECOVER_OLDEST_AGE_S` | `outbox_recover_oldest_age_s` | `float` |
| `HEALTH_THRESHOLDS_DEGRADE_SAMPLES` | `degrade_samples` | `int` |
| `HEALTH_THRESHOLDS_RECOVER_SAMPLES` | `recover_samples` | `int` |
| `HEALTH_THRESHOLDS_DEAD_LETTERED_WARN` | `dead_lettered_warn` | `int` |
| `HEALTH_THRESHOLDS_OLDEST_UNDELIVERED_AGE_WARN_S` | `oldest_undelivered_age_warn_s` | `float` |

**These overrides are only applied when `PKM_SETTINGS_PROFILE=lab`.**
In operator/prod profiles (the default) the variables are silently ignored,
so accidental environment state cannot alter production thresholds.

To use threshold overrides locally:

```bash
export PKM_SETTINGS_PROFILE=lab
export HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S=5.0
python -m app.cli health status --json
```

An invalid value for any override (e.g. non-numeric string) causes the load to
fail with `status: "fail"` and the runtime falls back to built-in defaults.

## Authority Spine Diagnostic

The `/api/health` response includes an `authority_spine` key that surfaces a bounded operator-visible posture summary for the runtime governance spine.

**This is a diagnostic surface only — it does not grant or deny authority and must never be treated as a semantic authority source.**

Fields returned under `authority_spine`:

| Field | Possible values | Meaning |
| --- | --- | --- |
| `write_guard` | `active`, `blocked`, `unavailable` | Current WriteGuard posture. `active` means writes are permitted; `blocked` means the current health state (e.g. `safe_mode`, `unhealthy`) is blocking writes; `unavailable` means the WriteGuard snapshot could not be read. |
| `authority_non_upgrade` | `enforced` | Confirms that no health signal is permitted to upgrade operational authority — enforced as an invariant. |
| `provenance_required_for_mutations` | `yes` | Confirms that all mutation-capable paths require explicit provenance; this cannot be disabled. |
| `read_projection_isolation` | `active` | Confirms that read projections are isolated from write/mutation paths. |

All values are bounded status strings; no raw state, path, secret, token, or traceback is exposed. The sanitization gate in `_sanitize_health_value()` applies to `authority_spine` exactly as it does to every other health field.

The `write_guard` field reflects the current cached `HealthContract` state without evaluating the WriteGuard or running the full health contract diagnostics. It transitions to `blocked` whenever the runtime enters a `safe_mode` or `unhealthy` state (see `app/health_contract.py:WRITE_BLOCKED_STATES`).
<!-- SECTION:HEALTH:END -->

## Outbox and dead-letter signals

Cross-reference for every outbox signal that touches dead-lettering: the always-on read/alert
signal above (`## Dead-letter signal`) plus the PROD deploy-time stop condition below (#3903).

### PROD deploy pending-retry preflight

`scripts/deploy_channel.sh deploy prod <sha>` runs a read-only preflight,
`scripts/prod_deploy_retry_preflight.py`, before the pin file is written or Compose is touched. It
inspects pending (`delivered_at is null`) DB outbox rows and blocks the deploy when any row is
already at a **terminal retry boundary** — a state where the row's very next processing pass
dead-letters it instead of retrying, with no further code change or failure needed to get there:

- **Worker-level transient retry counter** — the re-emitted event payload's `_worker_retry_count`
  (stamped by the prior cycle onto the retry row) has already reached
  `_MAX_TRANSIENT_RETRY_ATTEMPTS` (3, `app/workers/outbox_worker.py`); the next transient failure
  for that row dead-letters immediately instead of being re-queued (`_queue_transient_retry`).
- **Dispatch-attempt crash-loop counter** — the outbox row's own `attempts` column has already
  reached `_MAX_DISPATCH_ATTEMPTS − 1` (4 with the default budget of 5; the budget is overridable
  via `WORKER_MAX_DISPATCH_ATTEMPTS`, same variable the worker itself reads). The worker bumps
  `attempts` and then dead-letters+acks in the *same* consume cycle, so a row observed pending
  between cycles tops out at `max − 1` — and that *is* the terminal state: its next non-transient
  dispatch failure dead-letters it. (`attempts == max` is only observable in the milliseconds
  crash window between the bump and the ack.)

The preflight understands both live row shapes: envelope rows written by
`write_outbox_event` (counter nested at `payload->'payload'->'_worker_retry_count'`) and legacy
flat rows (counter at the top level) — mirroring the worker's own `_coerce_event_from_db`
unwrapping.

This is exactly the failure class that let #3124's promotion pass every existing gate (deploy,
health, exact-SHA, embedding, live smoke) while eight `panel.scan.requested` rows already at
retry-3 silently dead-lettered the moment the worker restarted — undetected until post-promotion
verification.

Posture:

- **Read-only.** The preflight never acks, replays, edits, or otherwise mutates an outbox row
  (KERNEL-12 invariant, same as `dead_letter_stats()`). It only decides whether the deploy may
  proceed.
- **Redacted.** The failure output reports aggregate counts only — `terminal_pending_count`, a
  `by_topic` breakdown keyed on the event-type label, and a `by_classification` breakdown by which
  counter is exhausted — never payload content, note/source paths, DSNs, or credentials. The DSN
  itself is resolved by asking `app.release_channels.channel_isolation_preflight` (the one
  purpose-built resolver for Compose's own precedence rule) what `docker-compose.prod.yml`'s
  `worker` service actually binds — **not** by reading `./tmp/runtime.env` or any other `env_file`
  layer directly. Compose's documented rule (`docker-compose.dev.yml`, `docs/RELEASE_CHANNELS/README.md`
  :: Compose/env binding invariant) is that a service's `environment:` block always wins over its
  `env_file:` chain for the same key, and the prod overlay sets `DATABASE_URL`/`DB_DSN` directly in
  `environment:` for every channel-critical service — so in the normal case (no shell override) the
  effective binding is the overlay's own interpolation default, regardless of what any `env_file`
  (governed runtime env file included) happens to contain. Nothing is exported to the wider shell,
  passed to Compose, or printed (the #3875 posture); an ambient `DATABASE_URL`/`DB_DSN` override
  behaves identically for the preflight and the real `docker compose` invocation, since both read it
  via the same Compose interpolation semantics from the same shell. In the normal case the resolved
  value names the Compose-internal `db` service, which the preflight (running on the host, not
  inside the Compose network) translates to the host-published port — `docker-compose.yaml`'s `db`
  service publishes container port 5432 on host port 15432 and the prod overlay does not override
  it; any other resolved host is left untouched.
- **Never silent.** The deploy log always carries exactly one status line —
  `prod pending-retry preflight: ok`, `... skipped:<reason>`, or
  `... blocked terminal_pending_count=<n>` — so a skipped safety gate can never masquerade as a
  pass.
- **PROD deploys only.** dev and test channel deploys are unaffected, and `rollback prod` is
  deliberately not gated: the prior stable ref must always be recoverable
  (`docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`).
- **Ordinary pending work is unaffected.** A row below both thresholds never blocks a deploy, no
  matter how large the pending queue is.
- **Fails open on infra unavailability.** No DSN configured, the DB unreachable, or the outbox
  query itself failing skips the check (visible `skipped:<reason>` line) rather than blocking the
  deploy — DB/API availability is a distinct, already-gated concern (health/version gates run
  later in the same script), not this check's job.

Operator action on a block: inspect the reported topic(s) — for example
`python -m app.cli events-doctor --path "$INDEX_OUTBOX_PATH"`, or the live outbox for the affected
topic — to find why processing keeps failing, resolve the underlying cause, then redeploy. The
preflight itself performs no remediation; clearing or replaying the affected rows remains an
explicit, separate operator/agent action, same as any other dead-letter recovery.

## False-green register

One authoritative place stating what each always-on health surface's **green** signal
actually means — and where green can lie. Operators must read this before trusting any
single green during go-live or an incident. Kept consistent with the code as of the
Observability Stabilization epic (#2597); the "fixed by" notes point at the slice that
closed each gap.

| Surface | Green means | Where green can mislead |
|---|---|---|
| `GET /healthz` (api) | the API process is alive and serving HTTP | **Unconditional by design** — returns `200 {"ok": true}` with *every* dependency down. It is a liveness probe, not a dependency signal; use `/readyz`. |
| `GET /readyz` (api) | the readiness contract is in a ready state **and** Postgres is reachable **and** the store backend resolves | Reflects real DB health since **OBSSTAB-01 (#2598)**: a live `ping_postgres()` runs inside `HealthContract.evaluate()`, so a DB outage forces `unhealthy` → `503`. Before #2598 it keyed only on outbox-event age, so a quiet-window outage still returned `200`. Also reflects store-resolution health since **#2843**: an unknown `STORE_BACKEND` value or no backend configured at all (no `STORE_BACKEND` and no `DATABASE_URL`/`DB_DSN`) now also forces `unhealthy` → `503`; before #2843, `_count_objects()` swallowed that resolution error into `store_object_count: 0` and the process reported ready. Note `degraded` is still a *ready* state (writes paused, reads served) — green here does not guarantee writes are accepted. |
| `GET /api/health` (api) | every **required** check passed and the runtime probes are healthy | A `false` here means a **required** check or a runtime probe failed — it is **not** caused by an optional tool: `_checks_ok()` only counts checks with `required=True` (`app/cli/health.py:649-653`), so an absent optional tool (e.g. `ffmpeg`, `companion_diagnostics`) does **not** flip the result. (A common doc myth said `ffmpeg` absence sets `ok=false`; it does not.) `ok` and `required_ok` are currently computed **identically** (both required-only); the OBSSTAB-04 probe keys on `required_ok`. Its synchronous diagnostic work runs off the API event loop; Ollama uses `HEALTH_PROBE_TIMEOUT` (default `2` seconds), independent of generation/embedding `LLM_TIMEOUT`. |
| `GET /agent/health` | the agent HTTP route is mounted and responding | **Known residual false-green:** returns `200 {"heartbeat": …}` regardless of whether the agent loop is actually alive (`app/api/routers/agent.py`). Do not treat it as agent liveness. Making it reflect real agent state is out of scope for Fas 0. |
| Container healthcheck (`docker ps` / compose status) | the worker/watcher **heartbeat is fresh** (and, at startup, db-dependents waited for Postgres before their first query) | Heartbeat freshness is the *only ongoing* signal here (since **OBSSTAB-02 (#2599)** — was a `test -s` file-presence check, so a hung process whose heartbeat file still existed read "healthy", the `processed_total=0` ingest-stall shape; now compares the heartbeat JSON `ts`). **`depends_on: condition: service_healthy` orders startup only** — if Postgres drops *after* startup while an idle worker/watcher keeps writing fresh heartbeats, the container still shows healthy. Ongoing DB health is reflected by `/readyz` and the API container healthcheck that targets it (OBSSTAB-01), **not** by the worker/watcher container probe. `ollama` has an in-image CLI healthcheck. |
| Companion-UI `/healthz` | the UI process reached the **upstream** runtime API | Probes the upstream since **OBSSTAB-11 (#2618)**: it calls `/api/health` and returns `503 {"ok": false, "upstream": "unreachable"}` when the runtime is down (was an unconditional `200`, so the UI read green while every request 502'd). The same fix applies in production via the shared `make_handler` factory. |

**Cross-check:** after OBSSTAB-01/-11, the **DB-aware** signals — `/readyz` and the API container
healthcheck that targets it, plus the companion-UI `/healthz` — go red while Postgres (or, for the
UI, the whole upstream) is down. The worker/watcher **container** probe is *not* DB-aware: it tracks
heartbeat freshness, so it can still read healthy during a post-startup DB drop (see its row). The
intentional always-green exceptions are `/healthz` (liveness, never dependency-aware) and
`/agent/health` (residual, documented above). Active-LLM reachability is **not** a Fas 0 readiness
gate (deferred to #2621) — an LLM outage is surfaced through the operator's "Minne" group, not `/readyz`.

The rich `/api/health` diagnostic is not a container liveness target: API container healthchecks use
`/readyz`, while `/healthz` remains the unconditional process-liveness endpoint. `/readyz` and
`/status` likewise run synchronous contract evaluation off the event loop.
