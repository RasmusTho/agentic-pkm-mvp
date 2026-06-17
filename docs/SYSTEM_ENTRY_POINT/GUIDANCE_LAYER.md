---
name: Guidance Layer
description: Opt-in data-guidance explanatory callouts across shell and overlays, off by default, integrating with the shipped /help guide
task_id: SEP-06
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Surface composition (NORMATIVE table)
parent_capability: system-entry-point
prerequisites: [SEP-03]
depends_on: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md]
can_parallelize_with: [PANEL_COMMAND_PALETTE.md, SYSTEM_MAP_OVERLAY.md, SETTINGS_DRAWER.md, RECEIPTS_HISTORY_SURFACE.md]
---

# Guidance Layer

## Purpose

Split "help" into its two kinds: evidence (provenance, authority tags, receipts — always present, terse) and explanation (what is this surface, how does re-entry work — opt-in, off by default for the established user). A newcomer turns guidance on and can understand the system from one place; the daily surface stays clean.

## What This Task Does

- Adds `data-guidance="on"` (absent = off) on the shell root, toggled by an `ⓘ` affordance (`guidance.toggle`) in the topbar, in each overlay head, and on the re-entry card.
- When on, reveals explanatory guidance callouts describing each surface and the re-entry model, across the shell and every overlay-host occupant that has shipped.
- The toggle is **UI-local**: persists nothing durable (a session-local value at most), carries no authority, and never changes content semantics — guidance adds explanation, it never restates or re-classifies runtime state.
- Integrates with the shipped `/help` guide (#1755): guidance callouts may deep-link into the help drawer; the help guide remains the long-form document, the guidance layer is the in-place layer.
- Off by default in every state; evidence elements (provenance lines, authority tags, receipt pills, tooltips) are unaffected by the toggle.

## Concretely

```text
default render → no .guidance callouts in DOM (or hidden), data-guidance absent
ⓘ → data-guidance="on" → callouts visible on shell + open overlays
reload → guidance off again (no durable persistence)
```

## Why This Matters

The product is built for one expert who lives here daily; permanent explanatory chrome is attentional debt. But the system must remain learnable — this layer is how both stay true at once.

## Acceptance Criteria

- [ ] Guidance is off by default in every entry state and shows no explanatory callouts.
  Verify: `tests/companion_ui/test_guidance_layer.py::test_guidance_off_by_default`
- [ ] Toggling reveals guidance callouts on the shell and on open overlays; toggling again removes them.
  Verify: `tests/companion_ui/test_guidance_layer.py::test_toggle_reveals_and_hides_callouts`
- [ ] The toggle persists nothing durable and never reaches a save/projection endpoint.
  Verify: `tests/companion_ui/test_guidance_layer.py::test_guidance_toggle_is_ui_local`
- [ ] Evidence elements (provenance, authority tags, receipt pills) render identically with guidance on and off.
  Verify: `tests/companion_ui/test_guidance_layer.py::test_evidence_unaffected_by_guidance`
- [ ] Guidance is reachable from the re-entry card and from each shipped overlay head.
  Verify: `tests/companion_ui/test_guidance_layer.py::test_guidance_affordance_present_on_reentry_and_overlay_heads`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_guidance_layer.py`
- `ruff check app tests`

## Out of Scope

- Rewriting the `/help` guide content.
- Onboarding wizards, tours, or first-run flows.
- A guidance-default setting in the Settings drawer (SEP-07 may add it; this task ships session-local only).

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Data-attribute vocabulary
- `companion-ui/companion-app/companion_ui/workspace/help_guide.html` (shipped help guide, served at `/help`)

## Related GitHub Issues

Filed as **#1788** (`[SystemEntryPoint] guidance-layer: opt-in explanatory callouts`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
