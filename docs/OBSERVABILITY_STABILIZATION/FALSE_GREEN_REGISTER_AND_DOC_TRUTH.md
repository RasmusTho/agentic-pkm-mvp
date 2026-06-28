---
name: False-Green Register And Doc Truth
description: Add a false-green register to docs/HEALTH.md and correct doc statements that claim guarantees the code does not enforce.
task_id: OBSSTAB-06
source_anchor: "docs/HEALTH.md :: SECTION:HEALTH ; docs/runbooks/RUNBOOK_GO_LIVE.md"
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - READINESS_REFLECTS_DEPENDENCIES.md
  - CONTAINER_HEALTH_SIGNALS.md
  - AUDIT_WRITER_STOPS_LYING.md
  - SCHEDULED_PROBE_AND_PUSH_ALERT.md
  - RUNTIME_VERSION_MARKER.md
  - DEV_DB_SNAPSHOT_RESTORE.md
---

# False-Green Register And Doc Truth

## Purpose

Give operators one authoritative place that states what each health surface's green signal actually means. Remove doc claims that the code does not enforce so operators cannot be misled during go-live or incidents.

## What This Task Does

Adds a "False-green register" section to `docs/HEALTH.md` (after `SECTION:HEALTH`) listing six surfaces — `/healthz`, `/readyz`, `/api/health`, `/agent/health`, the container probe, and the companion-UI `/healthz` — each with a "green means…" line and an explicit false-green note.

Corrects three over-claiming docs:

1. `docs/runbooks/RUNBOOK_GO_LIVE.md:46` — removes the false claim `/readyz` is "gated by migrations and startup checks"; the actual implementation (`app/api/routes/health_contract.py:20-36`) only checks watcher/worker state.
2. `docs/OPERATIONS.md:242` — qualifies the claim "JSON-formatted via `app/observability.setup_logging()`"; `setup_logging()` is defined in `app/observability/__init__.py:13` but is never called at startup, so JSON logs are not active by default.
3. `docs/OBSERVABILITY.md:129` — corrects the module path from `app/obs/log.py` to `app/observability/log.py` (the file that actually exists).

## Concretely

After this task:

```bash
# 1. Register section present
grep -n "False-green register" docs/HEALTH.md
# → one match

# 2. Migration-gate claim gone
grep -n "gated by migrations" docs/runbooks/RUNBOOK_GO_LIVE.md
# → no output

# 3. Wrong module path gone
grep -n "app/obs/log.py" docs/OBSERVABILITY.md
# → no output; replaced with app/observability/log.py
```

`/agent/health` (`app/api/routers/agent.py:7-12`) returns `200 {"heartbeat": ...}` regardless of whether the agent is actually alive; the register documents this. The register also notes that `/api/health` may emit `ok=false` when optional tools like `ffmpeg` are absent — operators must read `required_ok`, not the top-level `ok` (`app/cli/health.py:651-653`).

## Why This Matters

Operators trust docs during go-live and incidents. Today they would believe a migration gate that does not exist, JSON logs that are never activated, and a module path that is wrong — each wastes time or causes a missed check (risk R12). This register must stay consistent with OBSSTAB-01/-02 (cross-task invariant 2 in the README): if it lands first it documents current false-green behavior and must be updated when those tasks fix the underlying signals.

## Acceptance Criteria

- [ ] `docs/HEALTH.md` carries a "False-green register" section enumerating all six surfaces with a "green means…" line and an explicit false-green note for each, including `/agent/health` and the `required_ok` rule for `/api/health`.
  - Verify: doc writeback at `docs/HEALTH.md :: False-green register`
- [ ] `docs/runbooks/RUNBOOK_GO_LIVE.md` no longer claims `/readyz` is migration-gated.
  - Verify: `tests/docs/test_runbook_go_live_no_migration_claim.py::test_no_false_migration_gate_claim`
- [ ] `docs/OPERATIONS.md` JSON-log claim is qualified (not asserted as active-by-default).
  - Verify: doc writeback at `docs/OPERATIONS.md :: Observability`
- [ ] `docs/OBSERVABILITY.md` module path is corrected to `app/observability/log.py`.
  - Verify: doc writeback at `docs/OBSERVABILITY.md :: JSON log and span schema`

## How to Verify (Pre-Merge)

```bash
# Run the new doc-assertion test
pytest tests/docs/test_runbook_go_live_no_migration_claim.py -v

# Confirm register presence and wrong paths are gone
grep -n "False-green register" docs/HEALTH.md
grep -c "gated by migrations" docs/runbooks/RUNBOOK_GO_LIVE.md   # expect 0
grep -c "app/obs/log.py" docs/OBSERVABILITY.md                   # expect 0
```

## Out of Scope

Implementing JSON logging or Prometheus metrics (later phases). Any code change other than docs: the register is purely descriptive of existing behavior. Changing `/agent/health` to return real health status.

## Related Docs

- `docs/HEALTH.md`
- `docs/runbooks/RUNBOOK_GO_LIVE.md`
- `docs/OPERATIONS.md`
- `docs/OBSERVABILITY.md`
- `app/api/routers/agent.py`
- `app/api/routes/health_contract.py`
- `app/observability/__init__.py`
- `app/cli/health.py`

## Related GitHub Issues

Child of the parent Observability Stabilization feature issue. Docs-only — all changes ship in this slice's PR alongside the new test in `tests/docs/`.
