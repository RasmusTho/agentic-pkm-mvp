---
name: Observability Stabilization (Fas 0) — parent feature issue
description: Local mirror of the filed parent feature issue. GitHub is authoritative.
state: Filed as #2597 (validation hub, agent:blocked while children are open).
---

# Parent Feature Issue — Observability Stabilization (Fas 0)

**Filed:** [#2597](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2597) — this GitHub issue is the **authoritative** backlog/validation surface. This file is a repo-local mirror for navigation.

**Role:** validation hub. It stays `agent:blocked` while child slices are open; it is **not** a direct pickup issue. Each delivered child posts a validation receipt here/on #2597 before the next child is picked up.

## Children (filed from the specs)

| Task | Issue | Prio | Agent state | Depends on |
|---|---|---|---|---|
| OBSSTAB-01 READINESS_REFLECTS_DEPENDENCIES | [#2598](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2598) | P0 | ready | — |
| OBSSTAB-02 CONTAINER_HEALTH_SIGNALS | [#2599](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2599) | P0 | blocked | #2598 (shared compose) |
| OBSSTAB-03 AUDIT_WRITER_STOPS_LYING | [#2600](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2600) | P0 | ready | — |
| OBSSTAB-04 SCHEDULED_PROBE_AND_PUSH_ALERT | [#2601](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2601) | P0 | blocked | #2598 (dependency-aware /readyz) |
| OBSSTAB-05 RUNTIME_VERSION_MARKER | [#2602](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2602) | P0 | ready | — (cross-link #2527) |
| OBSSTAB-06 FALSE_GREEN_REGISTER_AND_DOC_TRUTH | [#2603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2603) | P1 | ready | reconcile w/ #2598/#2599 |
| OBSSTAB-07 DEV_DB_SNAPSHOT_RESTORE | [#2604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2604) | P1 | ready | — |

## Acceptance (capability)

The parent closes when all seven children merge and the capability Acceptance Criteria in `README.md` are validated against a live stack (kill-dependency, stale-heartbeat, simulated-prod-down, audit-count, /version, doc-truth, db-snapshot round-trip). Residual observation routes to a BuilderOps `LearningSignal` or a follow-up issue.

## Source

ULTRACODE health/telemetry/observability audit 2026-06-27 (assessment + owner decisions §1b). Specification: `docs/OBSERVABILITY_STABILIZATION/`.
