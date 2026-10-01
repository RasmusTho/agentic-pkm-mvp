---
name: Migrate the Companion Surfaces
description: Move every Companion surface onto the generated tokens, fix readable fg-3 uses, and make Shell a per-user trial choice.
task_id: YDS-03
github_issue: 5629
source_anchor: "docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Consumers"
parent_capability: Yggdrasil Design System v2
prerequisites: [YDS-01]
depends_on: [ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md]
can_parallelize_with: [MIGRATE_BUILDER_SURFACES.md]
---

# Migrate the Companion Surfaces

## Purpose

Make the Companion a real consumer of the design system, and give the owner a working Shell to try.

## What This Task Does

- Replaces the inlined token subset and hex literals in `companion_ui/workspace/*` and
  `companion_ui/renderer/*` with tokens from the served binding sheet. Covers
  `serve_dev_page.py`, `settings_drawer.py`, `system_map_overlay.py`, `memory_review_drawer.py`,
  `receipts_history.py`, `vault_settings_panel.py`, `guidance_layer.py`, `overlay_host.py`,
  `capture_modal.py`, `link_preview.py`, and `note_outline.py`.
- Moves readable `var(--fg-3)` uses to `fg-2` in those modules and in `canvas_suggestion_flow.*`,
  `converse_layout.*`, `panel_visual_shell.html`, and `help_guide.html`.
- Opts these surfaces in to the new focus ring and comfortable density.
- Adds a per-user Light (Shell) toggle in Companion settings. The choice is persisted per user.
  Dark stays the default.

## Concretely

Opening the workspace dev page with the toggle on renders porcelain sheets on the city backdrop.
With it off, it renders exactly as Dark.

## Why This Matters

About 260 hex literals in Companion modules bypass the tokens. No theme or density change can reach
those modules until they use tokens.

## Acceptance Criteria

- [ ] Each named Companion module stays within its hex-literal ceiling. The ceiling is zero unless
  the module lists a justified exception.
  - Verify: `tests/companion_ui/test_yggdrasil_token_adoption.py::test_companion_modules_use_tokens_within_hex_ceiling`
- [ ] Every `var(--fg-3)` in a Companion consumer sits on an allowlisted disabled, placeholder, or
  decorative selector.
  - Verify: `tests/companion_ui/test_yggdrasil_token_adoption.py::test_fg3_only_on_allowlisted_selectors`
- [ ] The Light toggle is off by default, persists per user, and sets `data-theme="light"` on the
  served page.
  - Verify: `tests/companion_ui/test_yggdrasil_token_adoption.py::test_light_theme_is_per_user_opt_in`
- [ ] The spec records S3 as delivered.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_yggdrasil_token_adoption.py`
- `pytest -q tests/companion_ui`
- Screenshot the workspace dev page in Dark and in Shell.

## Out of Scope

- Builder surfaces (YDS-04). Making Shell a default. Redesigning components beyond token adoption.

## Related Docs

- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Yggdrasil Light "Shell"`
- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/exploration/2026-09-22-shell-light-theme.html`

## Related GitHub Issues

Filed as #5629 under parent #5626. This task may be split into more than one Issue if `serve_dev_page.py` is too large for one PR. The
trial gate (the owner uses Shell, then decides) is recorded on the parent issue after this lands.
