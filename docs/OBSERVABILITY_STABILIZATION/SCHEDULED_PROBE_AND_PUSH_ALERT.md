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

The [2026-10-30 readable-rendering installation receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6476#issuecomment-6512944547)
verifies the current one-file update from `0172…` to renderer source
`7436ca29b863fca98faeb8e729d00e9832a71c22`: script SHA-256
`17c2dced67a7830e453f4bf5d18e1e330086dab186501b80b259f569936c8e90` (28,710 bytes), retaining the same
59 files from `777726d3139fc82cd69097dcd3bccc4d1c6c167a`. The mixed 60-file manifest is
`317f99b147d23dcf20c3e59be2d542cd9f3f74aeca98d519ba2393a9eab3a635`.
The normal active/enabled invocation completed 59 qualified cycles with zero restarts. The existing
unhealthy incident remained suppressed, with its latest acknowledgment/correlation state unchanged
and no new down or recovery sends. Configuration, effective unit, normal BWS launcher/SDK child,
interpreter and source/cache compatibility were qualified.

The new executor `32967742602847edb920cab7a1023faf` remains `UNKNOWN` at
`start_intent/main_process_boundary`, with its helper/cgroup reaped. A separately reviewed read-only
qualification verified the actual installed and running postconditions without adopting lifecycle
ownership or rewriting that result. Both the original5b47 and successor request/program/phase/handle/
result bytes and resource fences remain preserved; the original pinned follow tooling remains
intact. Qualification performed no lifecycle, metadata, incident or cache writes and did not resend,
rearm or reset the existing incident. The original installation and 43-cycle upgrade receipts above
retain their exact historical source mappings.

The fixed successor admission came from
[source prerequisite #6475](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6475), merged as
`f3372e5fe88146266825cfa595f667f7d974ceee`. Installation Issue
[#6476](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6476) bound its fresh normal claim to the
actual native owner UUID and the same runtime/registered worktree, generation and committed programs;
the closed source lease supplied no installation authority.

The successor reads and pins the original request, programs, authorization, phase, handle and
UNKNOWN result, freshly proves helper/cgroup quiescence, and qualifies the current source,
configuration, unit, normal invocation and latest incident. It preserves the original `active.json`
fence and uses a separate fixed successor selector under the same physical `resource.lock` as
the legacy protocol. The admitted normal identity remains bound through the first stop, and an
empty or missing prior selector cannot open another operation. Admission and source custody are rechecked before probe effects; lost
responses follow the same new handle, with finite, code-only recovery preserving the latest
incident. Missing, changed, foreign or incomplete proof refuses admission. See
[the operator prerequisites](../OPERATIONS.md#prod-probe-and-push-alert-scheduled-backstop).
The linked #6476 receipt verifies the actual installation; #6475 remains source/protocol support.
#4076's accepted TEST drill remains independent.

The existing shared webhook import is committed under #6347, catalog standing is owner-accepted
under #5506, and the declared consuming-host BWS launch succeeded. No credential was created or
rotated. After fresh verified Linux activity, the exact legacy `com.yggdrasil.prod-probe` job was
[disabled and unloaded on 2026-10-29](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6449#issuecomment-6491766335)
in the qualified current user's GUI domain. The disabled override, absent loaded job and preserved
original plist metadata/selected identity were verified; no legacy arguments were executed.
This retires only the named local consumer and does not assert physical-asset or program-source
equivalence. Issue #4076 remains open for the qualified isolated TEST outage/recovery drill;
production installation and local retirement are not the TEST acceptance receipt.

The [2026-10-30 TEST first-preflight receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6493#issuecomment-6535859691)
records operation `230149723a60e4c497a04f8efc07a9a9` as `REFUSED`: its same-project running-worker
selector did not observe exactly one valid ID. That count-or-ID-shape refusal does not establish
worker absence or health. The original supervisor and cgroup were positively contained, the watch
and TEST probe units were absent, and no qualified-worker or drill entry occurred. Result SHA-256
`542a4448014fc00b91b3cf0a830f4dcdb8a8860febe5325ba4498fcb9a4c7b71` and reconciliation SHA-256
`6a71c89eeaecfd53acc2e16315c8aa153bf0b07529d4a30a27fa6138cacdbfa0` identify that evidence.
Earlier attempts retain their separate `UNKNOWN` results and positive containment receipts.
Controlled down/recovery acceptance and its final owner-doc mapping remain open under #6493.

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
The fixed Linux `heimdal-external-alerts` consumer source supports explicit DEV, TEST, and PROD.
DEV and TEST resolve only `non-prod` / `shared/discord.webhook`; PROD uses the existing `prod`
binding. Endpoint, heartbeat, state, and alert-channel configuration remain explicit. The existing
installer remains TEST/PROD-only, and its shared `/opt/yggdrasil/host-probe` package is not a DEV
installation plan. Native DEV configuration, installation, healthy baseline, effect window, drill,
and restoration remain separately qualified with the Product keeper. No live DEV proof is claimed,
and #4076's controlled live TEST AC4 remains pending.
The source template leads with `DEV hälsoproblem`, `TEST hälsoproblem`, or `PROD hälsoproblem`, not a
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
- [ ] The host installer renders the correct endpoint and heartbeat path for TEST and PROD, and
      the service has no dependency on Docker startup.
  - Verify: `tests/ops/test_linux_host_probe.py`
- [ ] BWS launch is limited to Linux DEV/TEST/PROD and the fixed `heimdal-external-alerts` consumer;
      DEV/TEST use `non-prod` / `shared/discord.webhook`, and the child receives only the temporary
      Discord binding with reader credential/project environment bindings removed. Source support
      does not establish native DEV qualification or the pending live TEST acceptance.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_bws_probe_launch_is_narrowly_scoped`
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_dev_bws_probe_uses_non_prod_temporary_webhook_only`
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
