---
name: Re-entry Orientation Treatment
description: Latency-ladder re-entry shapes on the orientation surface — four fixed questions, mist variants, delta strip, whisper column, residual ambient layer
task_id: SEP-02
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Resolved Q5
parent_capability: system-entry-point
prerequisites: [SEP-01]
depends_on: [ENTRY_STATE_MACHINE.md]
can_parallelize_with: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md, CAPTURE_TO_VAULT_INBOX.md, MEMORY_REVIEW_DRAWER.md]
---

# Re-entry Orientation Treatment

## Purpose

Turn the shipped orientation page into the spec's latency-ladder re-entry treatment: a calm, peripheral re-entry that answers the four fixed questions without becoming a dashboard or a working-memory burden.

## What This Task Does

Implements the `orienting` treatments per re-entry shape on the existing orientation surface:

- **Four fixed questions card** (`data-region="reentry-card"`) for `full_mist` and `long_mist`: "What was I doing / Where did momentum stop / What remains unresolved / What changed since" — shapes fixed, unresolved shown as **counts with an inspect affordance** (routes to the memory review drawer when SEP-09 lands; until then, to the existing orientation sections), trajectory state pill from server-declared `data-traj-state`.
- **Long mist** adds the **delta strip** (`data-region="delta-strip"`, from `notable_changes`) and the right-margin **whisper column** (suppressed in narrow mode, collapsing into the card).
- **Soft mist** renders **no card**: residual ambient cues only — caret-echo cue at the leave point plus a single peripheral "where you stopped" line, per spec §Resolved Q5.
- **Thread fade (90s–15m)** renders no card and no peripheral line: the conversation/rail pane fades a fraction and the trajectory stays implicit, per the `CONTINUITY_AND_DECAY.md` ladder row normalized in the spec's state-enum table.
- **Cold (>7d)**: no overlay; the existing calm empty/cold copy with Browse-the-vault and System-map affordances. The leave-point cursor TTL is hard-capped at 7d (ADR-0008); re-entry beyond this window is always cold. **Current-state caveat:** the runtime resolver constant `_GAP_COLD_THRESHOLD` in `companion-ui/companion-app/companion_ui/workspace/entry_state.py:75` encodes 14d; the reconciliation to the decided 7d contract (ADR-0008 / #2489) is tracked by #2513.
- **First contact (no vault bound)**: resolves to the `no_vault` entry state and presents the guided vault picker (`SYSTEM_ENTRY_POINT_SPEC.md §First-contact / no-vault-bound picker`). This is a `no_vault` render, not a `cold_start` render.
- **Degraded banner** (amber, names the missing source from `meta.degraded_reasons`); **stale leave point** renders the card with a qualified, guard-held resume affordance per `BLOCKED_AND_STALE_STATE_SPEC.md`.
- **Residual ambient layer** after resume: caret echo at the stop point and marginalia dots persist into `shell_active`; dismissal never erases unresolved tension.
- Display budget: default 3 visible items per collection; counts not enumerations; deliberate expansion never exceeds server caps (8/8/5).

## Concretely

```text
data-entry-state="orienting" data-reentry-shape="full_mist"
  → reentry-card with 4 questions; unresolved = "3 open loops · 1 staged" + inspect
data-reentry-shape="long_mist"
  → card + delta-strip + whisper column; data-traj-state="dormant"
data-reentry-shape="soft_mist"
  → no [data-region="reentry-card"] in DOM; peripheral one-line cue only
entry.resume
  → shell_active; caret echo + marginalia dots present
```

## Why This Matters

Re-entry is the product's core anti-dashboard claim. A re-entry that enumerates, badges, or centers a card on the document converts a continuity prosthesis into an inbox — the named failure mode of `ATTENTION_MODEL.md` and the orientation contract's FA-5 budget.

## Acceptance Criteria

- [ ] `full_mist` renders the four fixed questions with counts-not-enumerations for unresolved items.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_full_mist_renders_four_fixed_questions_with_counts`
- [ ] `long_mist` adds the delta strip and whisper column; the whisper column is suppressed in narrow mode.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_adds_delta_strip_and_whisper_column`
- [ ] `soft_mist` renders no re-entry card — residual ambient cues only.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_soft_mist_renders_no_card`
- [ ] `thread_fade` renders no card and no peripheral line; only the fractional rail fade distinguishes it from the active state.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_thread_fade_renders_no_card_and_no_peripheral_line`
- [ ] Cold start and first contact render no re-entry overlay (asserted at this surface in addition to SEP-01).
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_and_first_contact_render_no_overlay`
- [ ] A degraded snapshot renders the amber banner naming the missing source while the resolved slices still render.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_degraded_banner_names_missing_source`
- [ ] A stale leave point renders the card with a qualified guard-held resume affordance, never a generic error, and never silently resumes into a missing artifact.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_stale_leave_point_renders_qualified_resume`
- [ ] The display budget caps default visible items at 3 per collection and expansion never exceeds server caps.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_display_budget_caps_visible_items`
- [ ] After resume, the residual ambient layer (caret echo, marginalia) is present in `shell_active`.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_residual_ambient_layer_persists_after_resume`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_reentry_orientation_treatment.py`
- `pytest -q tests/companion_ui/test_reentry_orientation_surface.py tests/companion_ui/test_entry_state_machine.py`
- `ruff check app tests`

## Out of Scope

- Changing the orientation endpoint or its caps.
- Notification, badge, urgency, or push semantics of any kind.
- The memory review drawer itself (SEP-09) — only the inspect handoff hint.
- Client-side gap computation: the shape arrives from SEP-01's server resolution.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Resolved Q5, §Resolved Q9
- `companion-ui/docs/CONTINUITY_AND_DECAY.md`
- `companion-ui/docs/ATTENTION_MODEL.md`
- `companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` §Cognitive-Load Display Budget

## Related GitHub Issues

Filed as **#1784** (`[SystemEntryPoint] reentry-orientation-treatment: latency-ladder re-entry shapes`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
