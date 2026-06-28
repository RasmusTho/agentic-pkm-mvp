---
name: Observability Stabilization (Fas 0)
description: Make the always-on health signals tell the truth, give the operator one real alert path, stop the silent audit lie, and make the running commit observable.
parent_capability: Observability Stabilization
state: Spec lane — parent feature issue + child slices to be filed.
source: ULTRACODE health/telemetry/observability audit 2026-06-27 (owner decisions in audit §1b Beslutslogg)
---

# Observability Stabilization (Fas 0)

State: Specification directory. Parent feature issue and child slice issues are filed from these specs; the spec is the source of truth, the issues track pickup.

## Why this capability exists

The runtime has genuinely strong **opt-in** deep health (a CLI that really pings Postgres, Ollama, heartbeat freshness, and the index) and a good durable event/outbox layer. But the **always-on** signals — the ones an operator or `docker ps` actually trusts — systematically over-report:

- The prod container healthcheck targets an unconditional `/healthz` that returns `200` with every dependency down.
- The worker/watcher container healthchecks test only that a heartbeat *file is non-empty* (`test -s`), so a hung process reads "healthy" — the exact shape of the prior `processed_total=0` ingest stall.
- `/readyz` keys on outbox-event *age*, not dependency health, so a Postgres/Ollama outage during a quiet window still returns `200`.

On top of that there is **zero alerting** (nothing tells the single operator anything is wrong), the central **audit writer is dead in prod** (schema-mismatched INSERT silently swallowed → zero rows), and **prod runs an unidentifiable commit** (no git SHA at runtime, deploy from a dirty `main` checkout).

This capability is the highest-leverage, lowest-regret remediation set: make the always-on signals honest, give the operator one real alert, stop the silent audit lie, and make the running commit observable.

## Owner decisions baked in (audit §1b)

- **DB = disposable operational working-set; vault/notes = durable system-of-record.** No scheduled prod-DR backup. Durable audit-of-record moves to note-backed storage under a **separate Storage-lifecycle epic**. Therefore `AUDIT_WRITER_STOPS_LYING` fixes only the *silent failure* — it does **not** invest in the DB audit table as the durable system-of-record.
- **Notification channel + single-point-of-failure stance are deferred** owner decisions — the push path is built regardless of which channel is chosen.
- `DEV_DB_SNAPSHOT_RESTORE` is **dev/test ergonomics + on-demand forensic dump**, explicitly **not** scheduled disaster-recovery backup.

## Tasks (execution order)

| Order | Task | id | What it does | Risk | Prio |
|---|---|---|---|---|---|
| 1 | [READINESS_REFLECTS_DEPENDENCIES](READINESS_REFLECTS_DEPENDENCIES.md) | OBSSTAB-01 | Fold a live DB ping (+active-LLM reachability) into `HealthContract.evaluate()` so `/readyz` flips on dependency-down; repoint the container healthcheck from `/healthz` to `/readyz`. | R1,R5 | P0 |
| 2 | [CONTAINER_HEALTH_SIGNALS](CONTAINER_HEALTH_SIGNALS.md) | OBSSTAB-02 | Freshness-based worker/watcher healthchecks; add an `ollama` healthcheck; gate db-dependents on `condition: service_healthy`. | R4,R10 | P0 |
| 3 | [AUDIT_WRITER_STOPS_LYING](AUDIT_WRITER_STOPS_LYING.md) | OBSSTAB-03 | Align the audit INSERT to the table schema, supply the NOT-NULL id, and remove the bare `except` so failures log at ERROR. | R2 | P0 |
| 4 | [SCHEDULED_PROBE_AND_PUSH_ALERT](SCHEDULED_PROBE_AND_PUSH_ALERT.md) | OBSSTAB-04 | A host launchd job that probes `/readyz` + `/api/health required_ok` and pushes one notification on failure; relabel `verify-*-channel`. | R3,R20 | P0 |
| 5 | [RUNTIME_VERSION_MARKER](RUNTIME_VERSION_MARKER.md) | OBSSTAB-05 | Bake git SHA + build time into the image; expose `/version` and a `version` field in `/api/health`. | R7 | P0 |
| 6 | [FALSE_GREEN_REGISTER_AND_DOC_TRUTH](FALSE_GREEN_REGISTER_AND_DOC_TRUTH.md) | OBSSTAB-06 | Add a false-green register to `docs/HEALTH.md`; correct over-claiming doc statements (migration-gate, JSON-logs, stale module path). | R12 | P1 |
| 7 | [DEV_DB_SNAPSHOT_RESTORE](DEV_DB_SNAPSHOT_RESTORE.md) | OBSSTAB-07 | `make db-snapshot` / `db-restore` for dev/test bug reproduction + on-demand `db-dump-prod` forensic snapshot. | backup decision | P1 |
| 8 | [OPERATOR_HEALTH_GLYPH_AMBIENT](OPERATOR_HEALTH_GLYPH_AMBIENT.md) | OBSSTAB-08 | **Operator-facing (primary).** A calm ambient health glyph in the user's entry/working surfaces (not gated behind a drawer or a note being open), bound to `required_ok` + `write_guard` + worker liveness. | UI gap | P0 |
| 9 | [OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH](OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH.md) | OBSSTAB-09 | Operator drawer renders the fetched-but-dropped keys: worker/watcher liveness, `authority_spine.write_guard`, `suggested_actions`. | UI gap | P1 |
| 10 | [OPERATOR_DRAWER_SHOWS_BACKLOG](OPERATOR_DRAWER_SHOWS_BACKLOG.md) | OBSSTAB-10 | Status panel surfaces `worker_queue` pending/processed so a growing backlog / stalled worker is visible. | UI gap | P1 |
| 11 | [UI_HEALTHZ_NOT_FALSE_GREEN](UI_HEALTHZ_NOT_FALSE_GREEN.md) | OBSSTAB-11 | Companion-UI `/healthz` probes upstream and returns 503 when the runtime is down (same in prod). | R11 | P1 |

> **Operator-facing half (08–11) — added 2026-06-28.** The human diagnoses through the Companion UI as a *user*, not via the CLI; the CLI-centric "deep health is available, just run the command" posture is insufficient for the operator. These slices make the honest signals that 01–03 produce **legible where the operator actually looks**. The exact failures the backend slices fix (worker stall, write-blocked/degraded) are currently *fetched by the UI but not rendered*. **08** (ambient glyph) is the primary in-flow signal; the launchd push (**04**) is the hard-down backstop (owner decision: "both"). **09/10** are the drill-in detail in the operator drawer; **11** fixes the UI false-green. `OBSSTAB-06`'s false-green register must enumerate the UI surfaces too.

**Parallelization:** `OBSSTAB-03`, `-05`, `-07` are fully independent and may run in parallel; `-06` (docs) may run anytime but must be reconciled against `-01`/`-02` if it lands first. `OBSSTAB-01 → OBSSTAB-02` are serialized (both edit `docker-compose.yaml`). `OBSSTAB-04` depends on `OBSSTAB-01`.

## Cross-Task Invariants / Interaction Safety

These invariants hold *across* tasks; a breakdown whose tasks are each locally correct can still fail in the seam between them.

1. **Health-truth invariant.** After `OBSSTAB-01` and `-02` merge, **no always-on signal** (container status, `/healthz`, `/readyz`, the worker/watcher container probe) may report healthy while a hard dependency is down (Postgres for any service; the active LLM for readiness). The false-green register in `OBSSTAB-06` must enumerate every always-green HTTP surface (`/healthz`, `/agent/health`, the UI `/healthz`) and stay consistent with `-01`/`-02`.
2. **Doc-vs-code ordering seam.** If `OBSSTAB-06` lands **before** `-01`/`-02`, the register documents current (false-green) behavior and is correct *for that moment*; it **must be updated** when `-01`/`-02` merge so the doc never claims a guarantee the code now actually enforces — or the reverse (claiming a false-green that is now fixed). The capability is not accepted until doc and code agree.
3. **Compose-file edit seam.** `OBSSTAB-01` (prod healthcheck repoint + base healthcheck command) and `OBSSTAB-02` (worker/watcher/ollama healthchecks + `depends_on`) both edit `docker-compose.yaml`. They are **serialized** (`-02` depends on `-01`) to avoid a lost-edit seam; in parallel worktrees the second rebases on the first before publish.
4. **Audit partial-failure invariant.** `OBSSTAB-03` makes the writer fail *loud*, not *fatal*: if the audit INSERT still fails (e.g. Postgres down), the user/agent action **proceeds** and the failure logs at ERROR — an audit-write failure must never abort the action it is recording. Durable audit-of-record is explicitly **out of scope** here (moves to the Storage-lifecycle epic).
5. **Probe-honesty dependency.** `OBSSTAB-04`'s probe asserts on `/readyz` + `/api/health required_ok`. It **depends on `OBSSTAB-01`** so `/readyz` is already dependency-aware; shipping `-04` first would wire an alert to a false-green signal and provide false assurance.

## Capability Acceptance Criteria

- [ ] Kill-dependency: with the stack up, stopping the `db` container makes the api container report `unhealthy` and `/readyz` return `503` within one healthcheck window. Verify: `tests/health/test_readiness_dependency_aware.py::test_readyz_flips_red_when_db_down`
- [ ] Hung worker: a heartbeat file older than `WORKER_HEARTBEAT_STALE_SECONDS` makes the worker container report `unhealthy`. Verify: `tests/health/test_container_health_signals.py::test_worker_unhealthy_on_stale_heartbeat`
- [ ] One push notification reaches the operator on a simulated prod-down. Verify: `tests/ops/test_synthetic_probe.py::test_probe_pushes_once_on_prod_down`
- [ ] After an end-to-end action on a real pg, `SELECT count(*) FROM audit > 0`; a forced INSERT failure logs at ERROR. Verify: `tests/services/test_audit_writer.py::test_audit_row_written_on_action`
- [ ] `GET /version` returns the git SHA matching the deployed checkout. Verify: `tests/api/test_version_marker.py::test_version_matches_git_sha`
- [ ] `docs/HEALTH.md` carries a false-green register; `RUNBOOK_GO_LIVE.md` no longer claims `/readyz` is migration-gated. Verify: doc writeback at `docs/HEALTH.md :: False-green register` + `tests/docs/test_runbook_go_live_no_migration_claim.py::test_no_false_migration_gate_claim`
- [ ] `make db-snapshot` then `make db-restore` round-trips a known row in a dev DB. Verify: `tests/ops/test_db_snapshot_restore.py::test_snapshot_restore_roundtrips_row`

## Relationship to GitHub Issues

- **Parent feature issue:** [#2597](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2597) — validation hub, `agent:blocked` while child slices are open. See `PARENT_FEATURE_ISSUE.md`.
- **Child issues** (filed from the specs; spec is the source of truth, issues track pickup):

  | Task | Issue | Agent state |
  |---|---|---|
  | OBSSTAB-01 READINESS_REFLECTS_DEPENDENCIES | [#2598](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2598) | ready |
  | OBSSTAB-02 CONTAINER_HEALTH_SIGNALS | [#2599](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2599) | blocked (after -01) |
  | OBSSTAB-03 AUDIT_WRITER_STOPS_LYING | [#2600](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2600) | ready |
  | OBSSTAB-04 SCHEDULED_PROBE_AND_PUSH_ALERT | [#2601](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2601) | blocked (after -01) |
  | OBSSTAB-05 RUNTIME_VERSION_MARKER | [#2602](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2602) | ready |
  | OBSSTAB-06 FALSE_GREEN_REGISTER_AND_DOC_TRUTH | [#2603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2603) | ready |
  | OBSSTAB-07 DEV_DB_SNAPSHOT_RESTORE | [#2604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2604) | ready |
  | OBSSTAB-08 OPERATOR_HEALTH_GLYPH_AMBIENT | [#2615](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2615) | ready (P0, operator-facing primary) |
  | OBSSTAB-09 OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH | [#2616](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2616) | ready |
  | OBSSTAB-10 OPERATOR_DRAWER_SHOWS_BACKLOG | [#2617](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2617) | ready |
  | OBSSTAB-11 UI_HEALTHZ_NOT_FALSE_GREEN | [#2618](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2618) | ready |

- **Cross-links:** `OBSSTAB-05` (#2602) complements #2527 (prod-runs-dirty-main, governance) — it makes the running commit observable, it does not replace the deploy-source-of-truth reconciliation. #2589 (healthy-services-but-fails) is a related false-green symptom.

## Related Docs

- `docs/HEALTH.md` — health CLI & contract owner doc (false-green register lands here)
- `docs/OBSERVABILITY.md` — telemetry interpretation owner doc
- `docs/OPERATIONS.md` — operational runbook owner doc
- `docs/runbooks/RUNBOOK_GO_LIVE.md`, `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`
- Audit deliverable (assessment + decisions): scratchpad `observability-health-telemetri-audit.sv.md`
