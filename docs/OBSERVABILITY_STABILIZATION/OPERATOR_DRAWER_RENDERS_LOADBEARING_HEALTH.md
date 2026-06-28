---
name: Operator Drawer Renders Load-Bearing Health
description: >
  The operator drawer already fetches the full health payload but renders only a subset;
  render the dropped load-bearing keys (worker/watcher liveness, write_guard, suggested_actions).
task_id: OBSSTAB-09
source_anchor: >
  companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py :: render_operator_overlay_html ;
  app/cli/health.py :: _runtime_ok + _suggested_actions + _check_authority_spine
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - OPERATOR_HEALTH_GLYPH_AMBIENT.md
  - OPERATOR_DRAWER_SHOWS_BACKLOG.md
  - UI_HEALTHZ_NOT_FALSE_GREEN.md
---

# Operator Drawer Renders Load-Bearing Health

## Purpose

The operator drawer's Health panel fetches the full `/api/health` payload (which includes
`runtime`, `authority_spine`, and `suggested_actions`) but only renders `ok` and `checks`.
This task wires the three silently-dropped signals into the existing Health panel so a human
inspecting the drawer can see whether the runtime is stalled, whether writes are blocked, and
what to do.

## What This Task Does

In `render_operator_overlay_html` (serve_dev_page.py lines 8839–8933), the Health panel
block (lines 8914–8933) reads `health_payload.get("checks")` and discards `runtime`,
`authority_spine`, and `suggested_actions`. This task extends that block to also render:

1. **Runtime-liveness block** — bound to `health_payload["runtime"]["worker"]["status"]` and
   `health_payload["runtime"]["watcher"]["status"]`; displays distinct labels for `stale`,
   `missing`, and `future` states.
2. **Authority-spine row** — bound to `health_payload["authority_spine"]["write_guard"]`;
   renders `active`, `blocked`, or `unavailable`.
3. **Suggested-actions list** — bound to `health_payload["suggested_actions"]` (list of dicts
   with `message`); renders each action as a plain list item.

No app/ change and no new network call — the data is already in the fetched payload.
`render_operator_overlay_html` is a pure function; only its HTML-generation block changes.

## Concretely

With the ingest worker stalled (heartbeat written >120 s ago), the operator opens the drawer
and the Health panel shows:

```
Worker:  stale (143s)
Watcher: ok
Authority (WriteGuard): active
Suggested actions:
  • Worker heartbeat unhealthy; restart the worker service
```

Today those three fields are fetched and silently discarded; the panel shows only the generic
`checks` table and the overall `ok` pill. In safe-mode (`write_guard = "blocked"`) the drawer
shows "Authority: writes blocked" where it currently shows nothing.

## Why This Matters

The Health panel's check table covers dependency liveness (Postgres, LLM, etc.) but not
runtime-process liveness or governance posture. An operator staring at a "Health: ok" panel
while the worker is stale and the queue grows has a false sense of completeness. The drawer
is the designated drill-in surface (reachable via the System Map operator node); if it drops
exactly the signals that answer "why is the system not processing?" it defeats its own purpose.

## Acceptance Criteria

- [ ] The drawer renders `worker` and `watcher` liveness from `health.runtime`, with `stale`,
  `missing`, and `future` shown as distinct labels (not collapsed to a generic error).
  - Verify: `tests/companion_ui/test_operator_drawer_render.py::test_drawer_renders_worker_liveness`
- [ ] The drawer renders `authority_spine.write_guard` state (`active` / `blocked` / `unavailable`).
  - Verify: `tests/companion_ui/test_operator_drawer_render.py::test_drawer_renders_write_guard`
- [ ] The drawer renders `health.suggested_actions` as a visible list; empty list renders nothing
  (no empty `<ul>`).
  - Verify: `tests/companion_ui/test_operator_drawer_render.py::test_drawer_renders_suggested_actions`
- [ ] All three additions are absent when `health_payload` is `None` (no regression to the
  existing empty-state path).
  - Verify: `tests/companion_ui/test_operator_drawer_render.py::test_drawer_health_empty_state_unchanged`
- [ ] `render_operator_overlay_html` remains a pure function — no network calls, no file I/O.
  - Verify: confirmed by the existing no-network contract; new tests pass with fixture dicts only.

## How to Verify (Pre-Merge)

```
cd companion-ui/companion-app
python -m pytest tests/companion_ui/test_operator_drawer_render.py -v
# Full not-pg suite to catch regressions in the shared render path:
python -m pytest -m "not pg" -v
```

Static UAT: call `render_operator_overlay_html` with a fixture payload that sets
`runtime.worker.status = "stale"`, `authority_spine.write_guard = "blocked"`, and one
`suggested_actions` entry; inspect the returned HTML fragment.

## Out of Scope

- The ambient entry-state glyph (OBSSTAB-08).
- Worker queue backlog depth display (OBSSTAB-10).
- Any change to the upstream `/api/health` payload shape (`app/cli/health.py` is read-only
  for this task).
- Changing the fetch logic in `_render_operator_drawer` or the HTTP handler.

## Related Docs

- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` — `render_operator_overlay_html` (line 8839), Health panel block (lines 8914–8933)
- `app/cli/health.py` — `_runtime_ok` (line 497), `_suggested_actions` (line 516), `_check_authority_spine` (line 603), full payload assembly (line 653)

## Related GitHub Issues

- Child of #2597 (Observability Stabilization parent feature).
- Provides the drill-in health detail that the OBSSTAB-08 ambient glyph links to.
