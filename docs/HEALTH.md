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

## Span + logging
The command is wrapped with `@span("health.check")`, so health check runs are recorded in `docs/OBSERVABILITY.md`. Exceptions populate `extra.error`.

## CI behavior
- `.github/workflows/smoke.yml` runs the dependency check with `LLM_PROVIDER=mock`.
- Run `python -m app.cli health status --json` after manual ingestion to confirm `state` is `running` and that `catch_up_progress["processing_mode"]` is `idle` (or `replay` while the worker catches up).
## Health threshold env-var overrides (lab profile only)

The four `HEALTH_THRESHOLDS_*` environment variables can override the threshold
values that are normally read from the vault settings file:

| Variable | Field | Type |
| --- | --- | --- |
| `HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S` | `outbox_degrade_oldest_age_s` | `float` |
| `HEALTH_THRESHOLDS_OUTBOX_RECOVER_OLDEST_AGE_S` | `outbox_recover_oldest_age_s` | `float` |
| `HEALTH_THRESHOLDS_DEGRADE_SAMPLES` | `degrade_samples` | `int` |
| `HEALTH_THRESHOLDS_RECOVER_SAMPLES` | `recover_samples` | `int` |

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

## False-green register

One authoritative place stating what each always-on health surface's **green** signal
actually means — and where green can lie. Operators must read this before trusting any
single green during go-live or an incident. Kept consistent with the code as of the
Observability Stabilization epic (#2597); the "fixed by" notes point at the slice that
closed each gap.

| Surface | Green means | Where green can mislead |
|---|---|---|
| `GET /healthz` (api) | the API process is alive and serving HTTP | **Unconditional by design** — returns `200 {"ok": true}` with *every* dependency down. It is a liveness probe, not a dependency signal; use `/readyz`. |
| `GET /readyz` (api) | the readiness contract is in a ready state **and** Postgres is reachable | Reflects real DB health since **OBSSTAB-01 (#2598)**: a live `ping_postgres()` runs inside `HealthContract.evaluate()`, so a DB outage forces `unhealthy` → `503`. Before #2598 it keyed only on outbox-event age, so a quiet-window outage still returned `200`. Note `degraded` is still a *ready* state (writes paused, reads served) — green here does not guarantee writes are accepted. |
| `GET /api/health` (api) | every **required** check passed and the runtime probes are healthy | A `false` here means a **required** check or a runtime probe failed — it is **not** caused by an optional tool: `_checks_ok()` only counts checks with `required=True` (`app/cli/health.py:649-653`), so an absent optional tool (e.g. `ffmpeg`, `companion_diagnostics`) does **not** flip the result. (A common doc myth said `ffmpeg` absence sets `ok=false`; it does not.) `ok` and `required_ok` are currently computed **identically** (both required-only); the OBSSTAB-04 probe keys on `required_ok`. |
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
