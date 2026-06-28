---
name: Operator Drawer Shows Backlog
description: >
  Surface status.worker_queue.pending and worker_queue.processed_total in the
  operator drawer Status panel so a growing ingest backlog or stalled worker is
  visible to the operator.
task_id: OBSSTAB-10
source_anchor: >
  companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py :: Status panel render (line ~8878);
  app/observability/status_model.py :: WorkerQueueStatus (line 111)
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - OPERATOR_HEALTH_GLYPH_AMBIENT.md
  - OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH.md
  - UI_HEALTHZ_NOT_FALSE_GREEN.md
---

# Operator Drawer Shows Backlog

## Purpose

Let the operator distinguish "worker caught up" from "worker dead, backlog
growing." The operator drawer's Status panel today renders `stores`,
`ingestion`, and `ask` — but not the queue depth — which was the exact
ambiguity behind the silent ingest stall (processed\_total=0, 63 notes never
indexed).

## What This Task Does

In `serve_dev_page.py`, the Status panel render block (around line 8878)
constructs `status_html` from `status_payload` keys `stores`, `ingestion`, and
`ask`. This task adds two `op-stat-row` entries sourced from
`status_payload["worker_queue"]`:

- **Pending (estimate)** — `worker_queue.pending` (`int | None`; `None` when
  the mode is `"none"` or the estimate is unavailable).
- **Processed total** — `worker_queue.processed_total` (`int | None`).

Both fields already exist on `WorkerQueueStatus` (status\_model.py lines
113–114) and are returned by `/api/status`; the gap is that the UI does not
render them.

## Concretely

Given a `/api/status` response that includes:

```json
"worker_queue": {"mode": "db", "pending": 63, "processed_total": 0}
```

the Status panel renders:

```
Worker queue pending   63
Worker processed total 0
```

When the worker is healthy and caught up (`pending: 0`, `processed_total: 512`)
the panel renders:

```
Worker queue pending   0
Worker processed total 512
```

When mode is `"none"` or the values are `null`, the rows show `N/A` (consistent
with the existing ingestion and ASK rows).

## Why This Matters

Without queue depth the operator cannot tell whether ingest is idle-because-
caught-up or idle-because-broken. `ingestion.last_run_at` and store counts are
already shown, but they do not capture whether the worker is consuming — the
operator must infer from staleness alone. Pairing `pending` with
`processed_total` makes a stall (large `pending`, static `processed_total`)
immediately legible without any CLI access.

## Acceptance Criteria

- [ ] The Status panel renders a `pending` row and a `processed_total` row when
  `worker_queue` is present in the status payload.
  - Verify: `tests/companion_ui/test_operator_drawer_render.py::test_status_panel_shows_worker_queue_backlog`

- [ ] When `worker_queue.pending` is `None` or mode is `"none"`, the rows
  display `N/A` rather than crashing or omitting the rows entirely.
  - Verify: `tests/companion_ui/test_operator_drawer_render.py::test_status_panel_shows_worker_queue_backlog`

- [ ] The rendered rows carry `data-testid` attributes
  (`operator-status-worker-pending`, `operator-status-worker-processed`) so
  tests can locate them without text matching.
  - Verify: same test above.

## How to Verify (Pre-Merge)

1. Run `pytest tests/companion_ui/test_operator_drawer_render.py -x` — must
   pass with no xfail regressions.
2. Run the full `not pg` suite to confirm no regressions in neighbouring
   operator-drawer tests.
3. Render the drawer locally via `render_index_html` with a fixture payload that
   includes `worker_queue: {mode: "db", pending: 63, processed_total: 0}` and
   confirm the two rows appear in the browser preview.

## Out of Scope

- The ambient health glyph (OBSSTAB-08).
- Worker liveness / write\_guard render in the same drawer (OBSSTAB-09).
- Backend alerting or push notifications on backlog threshold (Phase 2).
- Any change to `/api/status` response shape — the fields already exist.

## Related Docs

- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` — Status panel render (~line 8878)
- `app/observability/status_model.py` — `WorkerQueueStatus` (line 111)
- `app/observability/status_service.py` — `_get_worker_queue_status()` (line 667)

## Related GitHub Issues

- Child of #2597 (Observability Stabilization parent)
- Complements OBSSTAB-09 (worker liveness in the same drawer panel)
