---
name: Notable-changes gate to orienting long-mist delta strip only
description: Confirm notable-changes list is entirely suppressed on cold_start and rendered only in the orienting long-mist delta strip (already shipped; this task is a suppression gate + test assertion)
task_id: TELEMETRY_RELOCATION-04
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
parent_capability: TELEMETRY_RELOCATION
prerequisites: []
depends_on: []
can_parallelize_with: [FRESHNESS_TOPBAR_AND_MAP_NODE.md]
---

# Notable-changes gate to orienting long-mist delta strip only

## Purpose

The notable-changes list appeared on the `cold_start` orientation grid. Per the design notes, notable-changes belong only in the `orienting` long-mist delta strip (`data-region="delta-strip"`, shipped via #1784). They must never be manufactured for an empty `cold_start`. This task is primarily a **suppression gate**: confirm the `_render_orientation_notable_changes` call does not run for `cold_start`, and that the shipped `delta-strip` path is the one and only rendering of notable-changes.

The gate on the `cold_start` body already exists after #2171 (the body is branched on `entry_resolution.state`). This task verifies the suppression via a dedicated test and adds the explicit AC to the parent validation record.

## What This Task Does

1. Confirm (via code inspection + test) that `_render_orientation_notable_changes` is not called when `entry_resolution.state == "cold_start"` in `_render_orientation_index_html`.
2. Confirm the `long_mist` delta strip (`data-region="delta-strip"`) renders notable-changes correctly when present and `entry_resolution.state == "orienting"` with `reentry_shape == "long_mist"`.
3. Add/update the named test asserting both the suppression and the delta-strip presence.

## Concretely

```bash
pytest -q \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_adds_delta_strip_and_whisper_column
```

The second test already exists and should remain green. The first is the new suppression assertion.

## Why This Matters

If notable-changes silently appear on `cold_start` even after #2171, the door becomes a partial dashboard again. The test is the enforcement gate — without it, a future render-path change could re-introduce the list invisibly.

## Acceptance Criteria

- [ ] `_render_orientation_notable_changes` output does not appear anywhere in the `cold_start` HTML render (neither as a list region nor a "+N more" overflow).
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions`
- [ ] The `orienting` long-mist delta strip (`data-region="delta-strip"`) correctly renders notable-changes when supplied by the orientation payload.
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_adds_delta_strip_and_whisper_column`
- [ ] No notable-changes rendering appears for `orienting` shapes other than `long_mist` (no manufacturing on `full_mist`, `soft_mist`, `thread_fade`, `no_mist`).
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions` (covers cold_start; existing tests cover the other shapes)

## How to Verify (Pre-Merge)

```bash
ruff check companion-ui/companion-app tests
pytest -q \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_adds_delta_strip_and_whisper_column
```

Both must pass. `test_long_mist_adds_delta_strip_and_whisper_column` already exists; it must remain green (no regression).

## Out of Scope

- Adding notable-changes to any other surface (the design notes table specifies `orienting` long-mist only; no other destination).
- Interactive notable-changes management (read-only display in the delta strip; the shipped strip is already read-only).
- Changing the delta strip content format (shipped behavior; only the suppression gate is new).

## Restart / Durability Posture

Notable-changes in the delta strip are server-rendered from the orientation payload. No changes survive a restart beyond what the next payload supplies. The delta strip appears only for `long_mist` shape; a restart that resolves to `cold_start` or `no_mist` correctly shows no strip.

## Related Docs

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § What moves off the door
- `companion-ui/docs/REENTRY_ORIENTATION_TREATMENT.md`
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (`_render_orientation_notable_changes`, `_render_orientation_index_html`)
- `tests/companion_ui/test_reentry_orientation_treatment.py`

## Related GitHub Issues

Parent: #2174. One implementation issue; can parallelize with FRESHNESS_TOPBAR_AND_MAP_NODE. No prerequisites.
