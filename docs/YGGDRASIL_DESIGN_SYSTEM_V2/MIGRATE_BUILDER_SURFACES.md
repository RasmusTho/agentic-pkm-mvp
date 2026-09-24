---
name: Migrate the Builder Surfaces
description: Move the web Builder System UIs onto the generated tokens with compact density; the managed DevUI is split to #5637.
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

- Moves `app/web/static/signboard.*` and `app/web/static/index.html` onto the generated
  tokens-only sheet (`app/web/static/yggdrasil-tokens.css`), replacing their local palettes.
- Moves `app/builderops/ckm/overview_html.py` onto the same tokens. The overview is written as a
  standalone file, so it embeds the generated sheet at render time (without the web-font
  `@import`) instead of linking `/static`.
- Moves readable `var(--fg-3)` uses to `fg-2` in those surfaces and in `cockpit.*`, opts in to the
  v2 focus ring, and sets compact density on every page. Print styles stay a deliberate
  black-on-white exception.
- **Scope correction (2026-09-23):** the managed DevUI (`app/builderops/devui_managed.css`,
  `devui_candidate/*`, `devui_assets.py`) moved to #5637. It already renders Yggdrasil Dark (41 of
  44 inline tokens identical; the three font stacks differ deliberately under its
  `font-src 'none'` CSP), and changing it needs a new `yggdrasil-constrained-reuse.v1` manifest
  revision, browser proof, and VM102 receipts.

## Concretely

Signboard, the legacy dashboard, the Cockpit, and the CKM overview all render from generated
tokens with `data-density="compact"`.

## Why This Matters

Signboard and the legacy dashboard kept their own green and Tailwind-style palettes, so the
Builder tools did not share the system.

## Acceptance Criteria

- [ ] Each named Builder surface stays within its hex-literal ceiling.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_builder_surfaces_use_tokens_within_hex_ceiling`
- [ ] Every `var(--fg-3)` in a Builder consumer sits on an allowlisted disabled, placeholder, or
  decorative selector.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_fg3_only_on_allowlisted_selectors`
- [ ] Every `var(--…)` used by the migrated Builder surfaces resolves to a declared token.
  - Verify: `tests/builderops/test_yggdrasil_token_adoption.py::test_builder_token_references_resolve`
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
