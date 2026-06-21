---
name: _reentry_counts aggregate suppressed on cold_start, rendered in orienting card
description: Confirm _reentry_counts aggregate never renders on cold_start; assert it renders correctly in full-mist/long-mist orienting re-entry card
task_id: TELEMETRY_RELOCATION-06
source_anchor: companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md :: What moves off the door
parent_capability: TELEMETRY_RELOCATION
prerequisites: []
depends_on: []
can_parallelize_with: [GOVERNANCE_RECEIPTS_AND_MAP_NODE.md]
---

# _reentry_counts aggregate suppressed on cold_start, rendered in orienting card

## Purpose

`_reentry_counts` aggregates open_loops, notable_changes, resurface_candidates, staged (governance), and memory_candidates counts. On `cold_start` this aggregate was used to populate the orientation grid. The design notes state: "counts imply a trajectory `cold_start` cannot back." The destination is `full_mist`/`long_mist` re-entry card in `orienting` — which already renders counts in the shipped `test_full_mist_renders_four_fixed_questions_with_counts` test.

This task is primarily a **suppression gate plus regression guard**: confirm `_reentry_counts` output (or any per-count display from those keys) does not appear on `cold_start`, and that the `orienting` card counts continue to render correctly.

## What This Task Does

1. Confirm (via code inspection + test) that the counts from `_reentry_counts` (open_loops, notable_changes, resurface_candidates, staged, memory_candidates) are not displayed in the `cold_start` render path.
2. Confirm the `full_mist` and `long_mist` re-entry cards (`data-region="reentry-card"`) correctly render the `_reentry_counts` aggregate as counts for the four fixed questions when `entry_resolution.state == "orienting"` and `reentry_shape in ("full_mist", "long_mist")`.
3. Add the `cold_start` suppression assertion to `test_cold_start_omits_relocated_telemetry_regions` and confirm no regression to the `full_mist` and `long_mist` count tests.

## Concretely

```bash
pytest -q \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_renders_four_fixed_questions_with_counts
```

The second test asserts the long-mist card counts directly; the existing full-mist count test must also remain green.

## Why This Matters

`_reentry_counts` is a shared helper. If a future refactor moves its call site, counts could silently re-appear on `cold_start`. The explicit suppression assertion is the enforcement gate. Without it, regression is invisible.

## Acceptance Criteria

- [ ] No count value from `_reentry_counts` (open_loops, notable_changes, resurface_candidates, staged, memory_candidates) appears in the `cold_start` HTML render — not as a grid cell, not as a badge, not as a `+N` overflow.
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions`
- [ ] The `long_mist` re-entry card (`data-region="reentry-card"`) renders `_reentry_counts` counts correctly for the `orienting`/`long_mist` shape.
  - Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_renders_four_fixed_questions_with_counts`
- [ ] The suppression and orientation-card tests pass together without modifying the shipped `_reentry_counts` helper's behavior for `orienting`.
  - Verify: the cold-start suppression test and the long-mist count test named above pass in the same test run.

## How to Verify (Pre-Merge)

```bash
ruff check companion-ui/companion-app tests
pytest -q \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_omits_relocated_telemetry_regions \
  tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_renders_four_fixed_questions_with_counts
```

Both must pass. The existing `test_full_mist_renders_four_fixed_questions_with_counts` must also remain green as adjacent coverage.

## Out of Scope

- Changing the `_reentry_counts` helper (it is used by the `orienting` card correctly; the helper itself is not changed).
- Adding counts to any surface other than the `orienting` card (the only declared destination).
- Changing the four-fixed-questions card structure or content (shipped; not in scope).

## Restart / Durability Posture

`_reentry_counts` is derived from the orientation payload at render time. A process restart produces a fresh payload; the re-entry card reflects whatever the next payload supplies. No state leaks across restarts.

## Related Docs

- `companion-ui/design_handoff/2026-06-19-cold-start-threshold/design-notes.md` § What moves off the door
- `companion-ui/docs/REENTRY_ORIENTATION_TREATMENT.md`
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (`_reentry_counts`, `_render_orientation_index_html`)
- `tests/companion_ui/test_reentry_orientation_treatment.py`

## Related GitHub Issues

Parent: #2174. One implementation issue; can parallelize with GOVERNANCE_RECEIPTS_AND_MAP_NODE. No prerequisites. Should be confirmed before final closure of #2174.
