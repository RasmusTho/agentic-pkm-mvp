---
name: Observability Stabilization (Fas 0) — parent feature issue
description: Local mirror of the filed parent feature issue. GitHub is authoritative.
state: Filed as #2597 (validation hub). All 11 children closed; #2597 remains open by design pending operator test-deploy acknowledgment.
---

# Parent Feature Issue — Observability Stabilization (Fas 0)

**Filed:** [#2597](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2597) — this GitHub issue is the **authoritative** backlog/validation surface. This file is a repo-local mirror for navigation.

**Role:** validation hub. All child slices are closed; #2597 stays open by design pending operator test-deploy acknowledgment — it is **not** a direct pickup issue. Each delivered child posted a validation receipt here/on #2597.

## Children (filed from the specs)

| Task | Issue | Prio | Agent state | Depends on |
|---|---|---|---|---|
| OBSSTAB-01 READINESS_REFLECTS_DEPENDENCIES | [#2598](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2598) | P0 | closed | — |
| OBSSTAB-02 CONTAINER_HEALTH_SIGNALS | [#2599](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2599) | P0 | closed | #2598 (shared compose) |
| OBSSTAB-03 AUDIT_WRITER_STOPS_LYING | [#2600](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2600) | P0 | closed | — |
| OBSSTAB-04 SCHEDULED_PROBE_AND_PUSH_ALERT | [#2601](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2601) | P0 | closed | #2598 (dependency-aware /readyz) |
| OBSSTAB-05 RUNTIME_VERSION_MARKER | [#2602](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2602) | P0 | closed | — (cross-link #2527) |
| OBSSTAB-06 FALSE_GREEN_REGISTER_AND_DOC_TRUTH | [#2603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2603) | P1 | closed | reconcile w/ #2598/#2599 |
| OBSSTAB-07 DEV_DB_SNAPSHOT_RESTORE | [#2604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2604) | P1 | closed | — |
| OBSSTAB-08 OPERATOR_HEALTH_GLYPH_AMBIENT | [#2615](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2615) | P0 | closed | — (operator-facing primary) |
| OBSSTAB-09 OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH | [#2616](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2616) | P1 | closed | — |
| OBSSTAB-10 OPERATOR_DRAWER_SHOWS_BACKLOG | [#2617](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2617) | P1 | closed | — |
| OBSSTAB-11 UI_HEALTHZ_NOT_FALSE_GREEN | [#2618](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2618) | P1 | closed | #2601 (probe), #2603 (register) |

## Acceptance (capability)

The parent closes when all seven children merge and the capability Acceptance Criteria in `README.md` are validated against a live stack (kill-dependency, stale-heartbeat, simulated-prod-down, audit-count, /version, doc-truth, db-snapshot round-trip). Residual observation routes to a BuilderOps `LearningSignal` or a follow-up issue.

## Source

ULTRACODE health/telemetry/observability audit 2026-06-27 (assessment + owner decisions §1b). Specification: `docs/OBSERVABILITY_STABILIZATION/`.
