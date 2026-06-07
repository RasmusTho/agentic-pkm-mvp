---
name: Surface Scarce Resurfacing Cards
description: Render a scarce, source-linked subset of orientation resurfacing candidates in Companion UI
task_id: CLRA-02
source_anchor: docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Resurfacing mode
parent_capability: cognitive-load-runtime-adoption
prerequisites: []
depends_on: []
can_parallelize_with: [PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md, STAGE_TEXT_CORRECTION_PROPOSALS.md]
---

# Surface Scarce Resurfacing Cards

## Purpose

This task turns the FA-5 resurfacing budget and why-now contract into a visible Companion UI
runtime surface. It uses existing orientation payload fields and keeps resurfacing low-pressure,
source-linked, and read-only.

## What This Task Does

Update the Companion UI orientation/re-entry surface so the displayed resurfacing set is smaller
than the server cap by default, visibly source-linked, and explicit about degraded posture. The
default displayed set is at most 3 cards. Deliberate expansion may reveal additional candidates up
to the server-declared cap, but must not create notification, urgency, or persistence semantics.

## Concretely

When `GET /api/companion/orientation` returns `resurface.candidates`, the UI renders:

- at most 3 cards by default;
- each card's `label`, `why_now`, `source_ref`, `signal_labels`, `authority_role`, and artifact link
  where present;
- a clear degraded state when snapshot freshness or guard posture is partial/degraded;
- an explicit "show more" style expansion only when candidates exceed the default visible budget.

The implementation must not change the orientation endpoint schema or introduce a backend API.

## Why This Matters

Resurfacing can reduce re-entry load only when it stays scarce. A feed-like surface, badge, or hidden
priority ranking would recreate the monitoring burden the feature is meant to remove.

## Acceptance Criteria

- [ ] The orientation surface renders no more than 3 resurfacing cards by default even when the
  server returns up to its `resurface_candidates` cap.
  Verify: `tests/companion_ui/test_reentry_orientation_surface.py::test_resurfacing_cards_are_budgeted_to_three_by_default`
- [ ] Users can deliberately expand additional resurfacing candidates up to the server-declared cap
  without changing the backend payload or endpoint schema.
  Verify: `tests/companion_ui/test_reentry_orientation_surface.py::test_resurfacing_cards_can_expand_to_server_cap`
- [ ] Each rendered card exposes `why_now`, `source_ref`, `signal_labels`, and `authority_role`.
  Verify: `tests/companion_ui/test_reentry_orientation_surface.py::test_resurfacing_cards_show_why_now_source_signals_and_authority`
- [ ] Degraded or partial orientation posture is visible on the resurfacing card set.
  Verify: `tests/companion_ui/test_reentry_orientation_surface.py::test_resurfacing_cards_surface_degraded_posture`
- [ ] The surface has no notification, badge, inbox, urgency, focus-stealing, or persistence-backed
  semantics.
  Verify: `tests/companion_ui/test_reentry_orientation_surface.py::test_resurfacing_cards_do_not_create_notification_semantics`
- [ ] The rendered cards remain read-only and make no mutation calls.
  Verify: `tests/companion_ui/test_reentry_orientation_surface.py::test_no_mutation_calls`

## How to Verify (Pre-Merge)

- `git diff --check`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_reentry_orientation_surface.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_companion_orientation_api.py tests/resurfacing/test_resurfacing_runtime.py`
- `ruff check app tests`

## Out of Scope

- Changing `GET /api/companion/orientation`.
- Implementing notifications, badges, inboxes, ambient push, or polling.
- Persisting dismiss/snooze/pin decisions.
- Implementing learning/spaced-retrieval resurfacing.
- Reclassifying resurfacing as priority, urgency, approval, memory promotion, or write authority.

## Related Docs

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
- `docs/adr/ADR-0011-orientation-push-ambient-resurfacing.md`

## Related GitHub Issues

Execution issue: [#1680](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1680).
Parent validation hub: [#1638](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1638).
