---
name: Project Time-Spend Analysis
description: A rebuildable time-spend projection over screen activity observations — by app / project / scope / day / week — written as a readable markdown projection into the vault, with a named future companion-UI seam; works from observations alone
task_id: SCREEN-05
source_anchor: docs/HEIMDAL_SCREEN_STREAM/README.md :: three downstream tracks (time-spend analysis)
parent_capability: Heimdal Screen Stream
prerequisites: [SCREEN-02]
depends_on: [DERIVE_ACTIVITY_OBSERVATIONS.md]
can_parallelize_with: [BUILD_MACOS_OBSERVER_CLIENT, CONTROL_SURFACE_AND_EXCLUSIONS]
---

# Project Time-Spend Analysis

## Purpose

The third downstream track from the owner's ask: *"analysis of what I spend my time on."* Screen span
observations carry real `observed_at_start`/`observed_at_end` duration, frontmost app, entity mentions,
and a scope tag — everything needed to answer "where did my time go?" This task builds a **rebuildable
projection** that rolls spans up by app / project / scope / day / week and writes a **readable markdown
projection** into the vault. It works **from observations alone** — no episode dependency.

## What This Task Does

1. **Roll up spans.** Aggregate span durations across dimensions: by **app** (frontmost app), by
   **project** (from entity mentions / scope), by **scope** (the span's scope tag), by **day** and
   **week**. Idle/locked gaps are excluded by construction (they were never sampled).
2. **Derived, rebuildable, never authority.** The projection is a **derived representation** (DRI):
   rebuildable deterministically from the observation stream, carries no authority, overwrites no
   human note. Rebuild = re-fold the observations; the projection is disposable. This mirrors the
   machine-mirror/DB-authority contract — the observations are the record, the projection is a lens.
3. **Readable markdown projection into the vault.** Write a human-legible time-spend note (e.g.
   `heimdal/time-spend/YYYY-WW.md`) through the governed write path (WriteGuard, `requires_review` /
   derived class, capture scope). Markdown-first: the note is the surface the owner reads; a companion
   UI is a later lens over the same data (**named future companion-UI seam** — not built here).
4. **Episode-level rollup is a future enrichment, not a dependency.** Once ERE lands (SCREEN-04), a
   richer rollup "by episode" (time-per-meeting/build/trip) becomes possible — **named as a future
   enrichment seam** keyed on `episode_ref`, explicitly **not a dependency**: this task ships fully on
   app/project/scope/day/week from observations, and the episode axis is additive later.

## Concretely

```
$ python -m app.cli heimdal time-spend --week 2026-W28 --json
{"by_app": {"Obsidian": "6h12m", "Safari": "3h48m", "Terminal": "2h30m"},
 "by_scope": {"work": "9h40m", "private": "2h50m"}, "by_project": {"ERE spec": "4h05m"}, "rebuilt_from": 1442}
$ python -m app.cli heimdal time-spend --rebuild --week 2026-W28   # deterministic re-fold from observations
wrote heimdal/time-spend/2026-W28.md  (derived, requires_review, from 1442 observations)
```

## Why This Matters

This is the most legible immediate payoff of the whole capability — the owner sees where their time
goes without any manual tracking. Building it as a rebuildable derived projection (not a persisted
authority) keeps it honest: it never becomes a source of truth that drifts from the observations, and a
bad fold is fixed by a rebuild, not a migration. Keeping it independent of ERE means it ships before the
event motor does.

## Acceptance Criteria

- [ ] AC1: spans roll up by app / project / scope / day / week with correct duration sums (idle gaps
      excluded). Verify: `tests/heimdal/test_time_spend_projection.py::test_rollup_by_all_axes`
- [ ] AC2: the projection rebuilds deterministically from the observation stream — same observations in,
      same rollup out; the projection holds no state the observations do not. Verify: `tests/heimdal/test_time_spend_projection.py::test_time_spend_rebuilds_from_observations`
- [ ] AC3: the markdown projection is written through the governed write path as derived /
      `requires_review` class, never overwriting a human-authored note. Verify: `tests/heimdal/test_time_spend_projection.py::test_projection_written_governed_derived_class`
- [ ] AC4 (non-behavioral): the future companion-UI seam and the future episode-rollup enrichment are
      named as seams, not built, and the task's independence from ERE is stated. Verify: doc writeback at `docs/HEIMDAL_SCREEN_STREAM/PROJECT_TIME_SPEND_ANALYSIS.md :: What This Task Does` (steps 3-4)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/heimdal/test_time_spend_projection.py
pytest -q -m "not pg"
```

## Out of Scope

Capture/derivation (SCREEN-01/02); ERE registration and episode-level rollup (SCREEN-04 + the named
future enrichment); the companion-UI lens (named seam, not built); any authority claim (derived only);
the control surface (SCREEN-06). No cross-machine merge beyond what the observations' machine axis
already carries.

## Restart / Durability Posture

The projection is a derived, rebuildable artifact — a restart or a lost projection note loses nothing:
`--rebuild` re-folds it from the durable observation stream. This is why it must not carry any state
absent from the observations (AC2 enforces it). No in-memory user-facing state to lose.

## Related Docs

- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (derived/rebuildable, never authority)
- `docs/EPISODE_RESOLUTION_ENGINE/README.md` (the future episode axis — enrichment, not dependency)
- `docs/HEIMDAL_SCREEN_STREAM/DERIVE_ACTIVITY_OBSERVATIONS.md` (the span observations this reads)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: three downstream tracks`

## Related GitHub Issues

One issue: `[Heimdal Screen Stream] time-spend-projection: rebuildable markdown rollup by app/project/scope/day/week`. Blocked until SCREEN-02 merges (∥ SCREEN-03, SCREEN-06). **Sonnet-tier** (a rebuildable derived projection over an existing stream — bounded, mirrors existing projection patterns). See scratchpad draft.
