---
name: Scheduled Probe And Push Alert
description: >
  A Linux systemd host service that probes /readyz + /api/health required_ok and emits
  one down alert on the outage transition, then one recovery signal on the
  first healthy run; relabel verify-*-channel so the name does not imply a
  live probe.
task_id: OBSSTAB-04
source_anchor: "config/systemd/yggdrasil-host-probe@.service :: TARS probe service ; Makefile :: check-prod-channel"
parent_capability: Observability Stabilization
prerequisites:
  - OBSSTAB-01
depends_on:
  - READINESS_REFLECTS_DEPENDENCIES.md
can_parallelize_with:
  - AUDIT_WRITER_STOPS_LYING.md
  - RUNTIME_VERSION_MARKER.md
---

# Scheduled Probe And Push Alert

## Current-state note (2026-09-12)

The delivered provider-pluggable implementation uses one shared channel module for both the prod
and prod-backup probes and supports the existing `ntfy`, Telegram, mail, and `none` paths. It also
contains a Discord one-way webhook adapter whose credential is accepted only through the declared
host-native runtime secret binding `discord.webhook` / `DISCORD_WEBHOOK`; it does not log or persist
the webhook value. Discord provider/account/channel/webhook enactment, host bootstrap wiring, and
the redacted live drill remain external delivery work bounded by #5506 and #4076.

## Owner decision (2026-09-12)

The target shared delivery capability is a private Discord channel managed by Heimdal under
`docs/HEIMDAL/EXTERNAL_SYSTEMS_CONTROL_PLANE.md`. When the external delivery work is enacted, the
probe remains source/health-owned and Discord remains a one-way secondary warning channel. The
webhook credential is resolved from the declared host-native secure-store boundary (macOS Keychain
on Mac, or through the declared `heimdal-external-alerts` BWS reader on TARS Linux); no value is stored in the
repository, Builder Vault, issues, logs, or receipts.

## Production host correction (2026-10-12)

Prod runs on the TARS Linux host, so the supported always-on probe belongs on that host beside
the runtime and worker heartbeat. The Mac LaunchAgent files remain legacy templates; they are not
the production deployment target. The Linux unit is
`config/systemd/yggdrasil-host-probe@.service`, with explicit per-channel endpoints and heartbeat
paths rendered by `scripts/install_host_probe.py`. The installer prints a plan by default and
requires `--apply` from the exact clean `origin/main` checkout before writing a host. A merged code
change or a plan is not evidence that the service has been installed.

The repository probe qualifies asynchronous health independently of the periodic Companion UI
producer. Each iteration sends one ordinary background `/api/health` request and, for a cold/stale
model-capability result, cache-only reads every 0.5 seconds within 45 seconds, capped at 90 cache
reads. Each request has at most 10 seconds and only the remaining acquisition budget, including
isolated reader startup, DNS, connection, headers and success/error body. A short-lived serial
reader uses the same interpreter and trusted installed source, a scrubbed environment and private
bounded JSON pipes. The parent kills and confirms reaping a timed-out reader within one additional
second; unconfirmed termination stops the probe before another request. No timer state or
persistent service is introduced. Cache reads do not schedule samplers or extend 30-second freshness.
Only final `required_ok=true`, qualified activation, `/readyz` success and a fresh host heartbeat
permit same-correlation recovery; text-capture remains cache-only and unqualified. The loop targets
60-second iteration starts by sleeping the remaining interval after work. Source tests cover slow
25/50/85/100-second synthetic samples and readiness/HTTP delay; slow delivery or scheduling can
still postpone the nominal cadence, and no arbitrary latency or current-health guarantee is made.
The bounded production upgrade is recorded below; #4076's controlled TEST receipt remains open.

The production service reads only the declared `heimdal-external-alerts` BWS binding
`shared/discord.webhook`; its child receives a short-lived mode-0600 runtime file and never inherits
the BWS token. Probe state and secret-controller state stay on the host. It has no Docker service
dependency: it reads the worker heartbeat from the host volume and probes the local API endpoint.
The Linux production probe was installed on `ygg-prod` on 2026-10-29 from source
`777726d3139fc82cd69097dcd3bccc4d1c6c167a`, including the confirmed-delivery repair merged in
PR #6430. The [installation receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6444#issuecomment-6490667131)
verifies all 60 package files, configuration, effective unit and private runtime binding metadata.
The same active/enabled invocation remained stable across two normal 60-second intervals with
zero restarts, one confirmed down alert and two duplicate suppressions. Production already had
`/readyz` HTTP 200 and `required_ok=false` before installation; that alert reports the existing
unhealthy signal and does not claim a controlled outage or repair of its cause.

The [2026-10-29 upgrade receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6457#issuecomment-6502803665)
verifies the subsequent one-file update to source `0d064c012296589e92987c1f374fa18b05104f7b`:
`prod_probe.py` SHA-256 `0172b37565a067c26acd37afed8d650be7a56117ad1962860446fd18353058ac`,
with the other 59 source files retained from `777726d3139fc82cd69097dcd3bccc4d1c6c167a`.
The mixed 60-file manifest is `3ae600b78abefb751ef8fd73e7639b75a41b09f30d44fd4d06b1bb77101ae861`;
it does not represent the whole new main tree. Configuration, effective unit, interpreter and private
child binding matched. The same active/enabled normal invocation completed 43 qualified cycles with
zero restarts, suppressing the existing incident while retaining its current acknowledgment.
Normal caches were qualified without forced deletion or restoration.
The original executor remains `UNKNOWN` at `start_intent/main_process_boundary`; its finite helper
and cgroup are reaped. A separately reviewed read-only verification qualified the actual installed
and running postconditions without adopting lifecycle ownership or rewriting that result. Original
request/program/result/handle bytes and pinned follow tooling remain preserved; the original resource
guard still fences later #6457 apply requests. No guard clearance or further compensation was needed.

The existing shared webhook import is committed under #6347, catalog standing is owner-accepted
under #5506, and the declared consuming-host BWS launch succeeded. No credential was created or
rotated. After fresh verified Linux activity, the exact legacy `com.yggdrasil.prod-probe` job was
[disabled and unloaded on 2026-10-29](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6449#issuecomment-6491766335)
in the qualified current user's GUI domain. The disabled override, absent loaded job and preserved
original plist metadata/selected identity were verified; no legacy arguments were executed.
This retires only the named local consumer and does not assert physical-asset or program-source
equivalence. Issue #4076 remains open for the qualified isolated TEST outage/recovery drill;
production installation and local retirement are not the TEST acceptance receipt.

## Purpose

Give the single operator one always-on signal that prod is actually serving: a
scheduled external probe that pushes exactly one notification on failure.
Detection is the missing capability — mean-time-to-detect is currently
unbounded (risk R3).

## What This Task Does

Run a small host probe on TARS Linux through a systemd service on a configurable interval. The
shared probe script curls
`/readyz` and the `/api/health` `required_ok` field (not the top-level `ok`)
and checks worker-heartbeat staleness; on the first outage transition it dispatches one push
notification through Discord after resolving its declared BWS binding, then clears that state
after the first healthy run so a later distinct outage can alert again. Each alert identifies the
source system, environment, severity, transition, UTC timestamp, correlation ID, and remediation
URL. A sustained outage and its recovery share the same correlation ID.
The source template leads with `PROD hälsoproblem` (or `TEST hälsoproblem`), not a
claim of total outage. It names failed required checks from the finite health-producer mapping
and mandatory runtime database, worker and model components. Optional failures are excluded;
watcher requirement is producer-local and is not inferred from a failed watcher observation.
Unknown or malformed cause metadata yields plain Swedish uncertainty in the human text;
`UNKNOWN` is reserved for technical metadata. Raw health details,
errors, paths and arbitrary keys never become notification text. Templates are deterministic;
there is no language-model call or inferred cause, impact or repair claim. Broader impact remains
unknown in plain Swedish (`impact: UNKNOWN` in the footer); recovery says only that the monitored readiness, required health and heartbeat checks
are green, using the same incident correlation.

Messages include Swedish local date/time in `Europe/Stockholm` (with DST and numeric offset),
fall back to UTC when zone data is unavailable, and retain UTC, transition, severity, source and
correlation metadata below the human text. The finite template fits Discord's 2,000-character
content limit including its bold subject wrapper; the sender itself does not truncate. The next
step points to the fixed incident runbook URL rather than echoing runtime URL configuration.
Use the raw health surface separately for investigation; the alert does not reproduce diagnostics.
This source change does not upgrade an already installed probe. The #4076 owner retains deployed
upgrade and controlled TEST acceptance; the dated installation receipts below remain historical
facts for their exact source versions.

Relabel the existing Makefile targets
`verify-prod-channel` (line 210) and `verify-test-channel` (line 204) so their
names reflect what they actually do — run pytest channel-isolation suites — and
add a distinct `live-prod-probe` target that invokes the probe script directly.

## Concretely

```
# The first end-to-end outage/recovery drill runs in TEST after its BWS reader is configured.
sudo systemctl is-active yggdrasil-host-probe@test.service

# Verify service and recent delivery outcome without printing credential material:
sudo systemctl status yggdrasil-host-probe@test.service --no-pager
sudo journalctl -u yggdrasil-host-probe@test.service --since -10min --no-pager

# Relabelled Makefile targets:
make check-prod-channel   # was: verify-prod-channel — runs pytest isolation suite
make live-prod-probe      # new: invokes the probe script once for manual spot-check
```

## Why This Matters

Risk R3: there is no alerting anywhere in the system. A prod failure is
discovered only when the operator manually runs a doctor script or the user
perceives degraded recall. Heimdal owns the notification provider relationship
and its operational record. The notification remains a secondary warning path,
and the probe must be replaceable so a successor provider can be attached without
changing callers.

## Acceptance Criteria

- [ ] A sustained TEST outage results in one down alert, and the first healthy
      run sends one recovery signal.
  - Verify: `tests/ops/test_prod_probe_alert_state.py::test_sustained_outage_alerts_once_and_recovers`
- [ ] A distinct outage after recovery re-alerts.
  - Verify: `tests/ops/test_prod_probe_alert_state.py::test_distinct_outage_realerts_after_recovery`
- [ ] The probe evaluates `/api/health` `required_ok`, not the top-level `ok`
      field.
  - Verify: `tests/ops/test_prod_probe_alert_state.py::test_probe_reads_required_ok`
- [ ] The host installer renders the correct endpoint and heartbeat path for each channel, and
      the service has no dependency on Docker startup.
  - Verify: `tests/ops/test_linux_host_probe.py`
- [ ] BWS launch is limited to Linux TEST/PROD and the `heimdal-external-alerts` consumer; the
      child receives only the temporary Discord binding.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_bws_probe_launch_is_narrowly_scoped`
- [ ] `verify-prod-channel` and `verify-test-channel` are relabelled (e.g.
      `check-prod-channel` / `check-test-channel`) and a distinct
      `live-prod-probe` target exists in the Makefile.
  - Verify: doc writeback at `Makefile` + `docs/OPERATIONS.md :: live prod probe vs channel-isolation`

## How to Verify (Pre-Merge)

```bash
# Run all probe unit tests
pytest -q tests/ops/test_prod_probe_alert_state.py

# Confirm Makefile targets exist with correct names
grep -n "live-prod-probe\|check-prod-channel\|check-test-channel" Makefile

# Confirm old names are gone
grep -n "verify-prod-channel\|verify-test-channel" Makefile  # should return nothing

# Validate the systemd template and render the production plan without applying it.
systemd-analyze verify config/systemd/yggdrasil-host-probe@.service
python3 scripts/install_host_probe.py --channel prod
```

## Out of Scope

- Creating or rotating the provider-side Discord account, channel, or webhook; that is the external
  delivery operation tracked by the parent/bug Issues.
- An external off-mini uptime pinger (deferred SPOF decision).
- Prometheus / Alertmanager rules (later phase).
- Worker-heartbeat staleness threshold tuning.

## Related Docs

- `config/systemd/yggdrasil-host-probe@.service` — TARS Linux host service
- `Makefile` lines 204-213 — targets being relabelled
- `docs/OPERATIONS.md`
- `docs/HEIMDAL/EXTERNAL_SYSTEMS_CONTROL_PLANE.md`
- `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`

## Related GitHub Issues

This is a child of the parent Observability Stabilization feature issue.
It depends on OBSSTAB-01 (the probe must hit a dependency-aware `/readyz`
that reflects real subsystem health, not a stub `ok: true`).
