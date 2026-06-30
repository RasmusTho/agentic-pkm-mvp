---
name: Scheduled Probe And Push Alert
description: >
  A host launchd job that probes /readyz + /api/health required_ok and emits
  one down alert on the outage transition, then one recovery signal on the
  first healthy run; relabel verify-*-channel so the name does not imply a
  live probe.
task_id: OBSSTAB-04
source_anchor: "ops/host-setup/mac-mini/com.yggdrasil.llm-gateway.plist :: launchd pattern ; Makefile :: verify-prod-channel"
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

## Purpose

Give the single operator one always-on signal that prod is actually serving: a
scheduled external probe that pushes exactly one notification on failure.
Detection is the missing capability — mean-time-to-detect is currently
unbounded (risk R3).

## What This Task Does

Add a host launchd plist (modelled on
`ops/host-setup/mac-mini/com.yggdrasil.llm-gateway.plist`) that runs a small
probe script under `ops/` on a configurable interval. The script curls
`/readyz` and the `/api/health` `required_ok` field (not the top-level `ok`)
and checks worker-heartbeat staleness; on the first outage transition it
dispatches one push notification via a pluggable channel (ntfy / Telegram /
mail — channel choice is a deferred operator decision), then clears that state
after the first healthy run so a later distinct outage can alert again.
Relabel the existing Makefile targets
`verify-prod-channel` (line 210) and `verify-test-channel` (line 204) so their
names reflect what they actually do — run pytest channel-isolation suites — and
add a distinct `live-prod-probe` target that invokes the probe script directly.

## Concretely

```
# Simulate prod down
docker compose stop api

# Within the outage exactly one push is delivered, then one recovery signal
# lands on the first healthy run.
# Verify the job is loaded:
launchctl list | grep yggdrasil
# → com.yggdrasil.prod-probe   0   com.yggdrasil.prod-probe

# While the outage remains active the alert does not re-fire; after recovery a
# later distinct outage can alert again:
docker compose start api
# (first healthy run sends recovery; later outage re-arms)

# Relabelled Makefile targets:
make check-prod-channel   # was: verify-prod-channel — runs pytest isolation suite
make live-prod-probe      # new: invokes the probe script once for manual spot-check
```

## Why This Matters

Risk R3: there is no alerting anywhere in the system. A prod failure is
discovered only when the operator manually runs a doctor script or the user
perceives degraded recall. The notification channel and the fact that an
on-mini push path is itself a SPOF are deferred operator decisions; the probe
script must be pluggable so the channel can be swapped later without changing
the launchd job.

## Acceptance Criteria

- [ ] A sustained prod outage results in one down alert, and the first healthy
      run sends one recovery signal.
  - Verify: `tests/ops/test_prod_probe_alert_state.py::test_sustained_outage_alerts_once_and_recovers`
- [ ] A distinct outage after recovery re-alerts.
  - Verify: `tests/ops/test_prod_probe_alert_state.py::test_distinct_outage_realerts_after_recovery`
- [ ] The probe evaluates `/api/health` `required_ok`, not the top-level `ok`
      field.
  - Verify: `tests/ops/test_prod_probe_alert_state.py::test_probe_reads_required_ok`
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

# Load the plist (dry-run validation)
plutil -lint ops/host-setup/mac-mini/com.yggdrasil.prod-probe.plist
```

## Out of Scope

- Choosing the final notification channel (ntfy / Telegram / mail).
- An external off-mini uptime pinger (deferred SPOF decision).
- Prometheus / Alertmanager rules (later phase).
- Worker-heartbeat staleness threshold tuning.

## Related Docs

- `ops/host-setup/mac-mini/com.yggdrasil.llm-gateway.plist` — launchd pattern
- `Makefile` lines 204-213 — targets being relabelled
- `docs/OPERATIONS.md`
- `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`

## Related GitHub Issues

This is a child of the parent Observability Stabilization feature issue.
It depends on OBSSTAB-01 (the probe must hit a dependency-aware `/readyz`
that reflects real subsystem health, not a stub `ok: true`).
