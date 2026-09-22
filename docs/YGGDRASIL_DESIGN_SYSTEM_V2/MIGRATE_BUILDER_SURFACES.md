---
name: Migrate the Builder Surfaces
description: Move every Builder System UI, including the served managed DevUI, onto the generated tokens with compact density.
task_id: YDS-04
github_issue: 5630
source_anchor: "docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Consumers"
parent_capability: Yggdrasil Design System v2
prerequisites: [YDS-01]
depends_on: [ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md]
can_parallelize_with: [MIGRATE_COMPANION_SURFACES.md]
---

# Migrate the Builder Surfaces

## Purpose

Put every Builder System UI on the shared system so the builder tools stop keeping their own
palettes.

## What This Task Does

- Moves `app/web/static/signboard.*`, `app/web/static/index.html`,
  `app/builderops/ckm/overview_html.py`, `companion_ui/workspace/devui_candidate/devui.css`, and
  the served managed stylesheet `app/builderops/devui_managed.css` onto tokens from the served
  binding sheet.
- Gives the served DevUI a token source. Today `overview.html` and `focus.html` load only
  `/devui/assets/devui.css`, and `ROUTES` in `app/builderops/devui_assets.py` exposes no token
  sheet. This task adds a `/devui/assets/colors_and_type.css` route that serves the generated
  sheet, references it from both served HTML pages before `devui.css`, and removes the inline
  `:root` declarations from `devui_managed.css` only after that.
- Updates `ASSET_SHA256` in `app/builderops/devui_assets.py` for every changed asset (the new token
  sheet, `devui.css`, `overview.html`, `focus.html`) and its provenance tests, in the same change.
- Moves readable `var(--fg-3)` uses to `fg-2` (including `cockpit.*`), opts in to the new focus
  ring, and sets compact density on every Builder surface.

## Concretely

The Cockpit, Signboard, legacy dashboard, CKM overview, and DevUI all render from one sheet with
`data-density="compact"`. The DevUI asset inventory hash matches the new stylesheet.

## Why This Matters

The shipped DevUI serves `devui_managed.css`, not the candidate file. Migrating only the candidate
would leave the real DevUI on its old inlined tokens.

## Acceptance Criteria

- [ ] Each named Builder surface stays within its hex-literal ceiling.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_builder_surfaces_use_tokens_within_hex_ceiling`
- [ ] Every `var(--fg-3)` in a Builder consumer sits on an allowlisted disabled, placeholder, or
  decorative selector.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_fg3_only_on_allowlisted_selectors`
- [ ] Every changed DevUI asset (token sheet, stylesheet, both HTML pages) matches its pinned hash.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_managed_devui_asset_hash_matches_migrated_stylesheet`
- [ ] Both served DevUI pages load the token sheet, and every `var(--…)` they use resolves to a
  declared token.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_served_devui_pages_resolve_every_token_variable`
- [ ] The spec records S4 as delivered.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_yggdrasil_token_adoption.py`
- `pytest -q tests/builderops tests/api/test_cockpit_api.py tests/companion_ui/test_cockpit_journeys.py`

## Out of Scope

- Companion surfaces (YDS-03). Shell on Builder surfaces. Changes to Cockpit behavior.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/README.md`
- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Density profiles`

## Related GitHub Issues

Filed as #5630 under parent #5626. This task can run in parallel with YDS-03 because they share no files.
