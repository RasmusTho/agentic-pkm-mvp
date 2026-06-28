---
name: Operator Health Glyph (Ambient)
description: >
  A calm, anti-dashboard health indicator legible in the user's actual
  entry/working surfaces (cold-start, no note open), bound to live runtime
  health — the operator does not have to open a diagnosis drawer.
task_id: OBSSTAB-08
source_anchor: >
  companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py ::
  render_index_html entry-state ;
  app/cli/health.py :: required_ok + authority_spine
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH.md
  - OPERATOR_DRAWER_SHOWS_BACKLOG.md
  - UI_HEALTHZ_NOT_FALSE_GREEN.md
---

# Operator Health Glyph (Ambient)

## Purpose

Surface one calm, always-present health glyph in the entry/working surfaces
(cold_start, no-vault, orienting) so a degraded, write-blocked, or
worker-stalled runtime is legible at a glance — without opening anything and
without a note being open. The human diagnoses the system as a user of the
Companion UI, not through a drawer they must deliberately open.

## What This Task Does

Add a single ambient health indicator (a glyph/dot in the topbar or on the
System Map "operator" node label — not a dashboard of tiles; anti-dashboard
posture applies) to all entry states.

Today `_render_operator_telemetry_block` returns `""` when `fields` is `None`
(line ~813 in `serve_dev_page.py`: `if not fields: return ""`), and
`operator_telemetry_html` is only populated when `fields is not None` (line
~9584). Entry renders (cold_start / orienting / no-vault) pass no `fields`, so
the runtime pill is suppressed entirely.

This task:
- Fetches `/api/health` in entry states (today only `/api/companion/orientation`
  is fetched there).
- Derives glyph state from the health response:
  - **green** — `required_ok == true` and `authority_spine.write_guard == "active"`
  - **amber** — health state degraded or `runtime.worker` heartbeat stale/missing
  - **red/blocked** — `authority_spine.write_guard == "blocked"`
- Renders the glyph with a one-line plain-language reason when not green
  (e.g. "Worker stalled", "Writes paused").
- Clicking/expanding the glyph routes to the operator drawer (the detail
  layer already built by OBSSTAB-09/-10).

## Concretely

On the cold-start landing with the worker stalled (stale heartbeat from
`app/cli/health.py :: _worker_runtime_status`) or the runtime in safe_mode,
the operator sees the glyph in amber/red with a one-line reason — without
opening the drawer and without a note open.

A healthy runtime shows a calm neutral glyph. The glyph is present regardless
of which entry state is active; it does not require `fields` (note payload) to
render.

## Why This Matters

Today the only live write-blocked or degraded indicator is suppressed unless a
note is open (`fields is not None`), so on the landing surface the operator has
no health signal at all. The very failures the Fas 0 backend work fixes (worker
stall = `processed_total=0`, write-blocked/degraded via `write_guard`) would
remain invisible to the person who lives in this UI. A host launchd push
(OBSSTAB-04) is the hard-down backstop; this glyph is the primary, in-flow
signal per the owner decision: "both — UI glyph primary + push backstop."

## Acceptance Criteria

- [ ] The health glyph renders in entry states (cold_start / no-vault /
  orienting) without a note open.
  - Verify: `tests/companion_ui/test_operator_health_glyph.py::test_glyph_present_in_entry_states`
- [ ] The glyph reflects write-blocked when `authority_spine.write_guard == "blocked"`.
  - Verify: `tests/companion_ui/test_operator_health_glyph.py::test_glyph_shows_write_blocked`
- [ ] The glyph reflects worker-stall when `health.runtime.worker` is stale
  or missing.
  - Verify: `tests/companion_ui/test_operator_health_glyph.py::test_glyph_shows_worker_stall`
- [ ] Expanding the glyph routes to the operator drawer.
  - Verify: `tests/companion_ui/test_operator_health_glyph.py::test_glyph_drills_into_operator_drawer`

## How to Verify (Pre-Merge)

1. Run `pytest tests/companion_ui/test_operator_health_glyph.py -v` — all four
   cases must pass.
2. Render `render_index_html` with an orientation fixture and no `fields`
   (entry-state path); confirm the glyph testid is present in the HTML output.
3. Confirm no regression in `tests/companion_ui/test_system_map_overlay.py` and
   `tests/companion_ui/test_vault_markdown_renderer.py`.

## Out of Scope

- The operator drawer's internal detail render (OBSSTAB-09, OBSSTAB-10).
- The `/healthz` fix (OBSSTAB-11).
- OS push notifications (OBSSTAB-04).
- A multi-tile dashboard — anti-dashboard posture forbids it.

## Related Docs

- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py`
- `docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md`
- `app/cli/health.py`

## Related GitHub Issues

Child of #2597. Primary operator-facing ambient signal. Pairs with OBSSTAB-04
(#2601) push backstop.
