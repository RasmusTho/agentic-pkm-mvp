---
name: Establish the Token Source and Generator
description: One DTCG token source and a deterministic stdlib generator that emits every Yggdrasil token output without changing how existing consumers render.
task_id: YDS-01
github_issue: 5627
source_anchor: "docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: One source, generated outputs"
parent_capability: Yggdrasil Design System v2
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Establish the Token Source and Generator

## Purpose

Replace the hand-copied token sheet with one platform-neutral source and a generator, so every
consumer (web, Builder UIs, Bifrost, and Claude Design) draws from the same versioned values.

## What This Task Does

- Adds `design-system/yggdrasil/` with DTCG JSON for primitives, semantic roles, the Dark and Shell
  themes, per-theme materials, and the comfortable/compact density profiles, plus `VERSION` and a
  stdlib-only `build.py`.
- Generates `companion-ui/companion-app/colors_and_type.css` (the binding path) and
  `app/web/static/colors_and_type.css` from that source, each with a `generated-from` header and
  version. Also generates `design-system/yggdrasil/dist/YggdrasilTokens.swift` and
  `design-system/yggdrasil/dist/tokens.json`.
- Keeps every existing token name and Dark value, the global `:focus-visible` rule, and the
  existing utility classes unchanged. Shell (`[data-theme="light"]`, and `[data-theme="system"]`
  under a light preference), density (`[data-density="compact"]`), the new focus ring, and the
  effects layer are emitted only as opt-in selectors.
- Loads JetBrains Mono from Google Fonts instead of `fonts.bunny.net` and corrects the "DM Sans"
  heading comment.
- Adds CI checks for output freshness and for WCAG AA contrast over the declared role/surface
  pairs in both themes.

## Concretely

```bash
python3 design-system/yggdrasil/build.py            # regenerates every output
python3 design-system/yggdrasil/build.py --check    # exit 1 if any output is stale
pytest -q tests/design_system/test_yggdrasil_tokens.py tests/api/test_cockpit_api.py::test_token_sheet_parity_with_binding_source
```

## Why This Matters

Today the sheet is copied by hand into several places and has already drifted. Without a generator,
a light theme, density, and a Swift export would each add another copy to keep in sync.

## Acceptance Criteria

- [ ] The generated binding sheet keeps every existing token name with its current Dark value.
  - Verify: `tests/design_system/test_yggdrasil_tokens.py::test_generated_binding_sheet_preserves_every_dark_token_value`
- [ ] The global `:focus-visible` rule and existing utility classes are unchanged. New rules are
  only reachable through opt-in selectors.
  - Verify: `tests/design_system/test_yggdrasil_tokens.py::test_new_rules_are_opt_in_and_legacy_rules_unchanged`
- [ ] Every generated output is fresh, and hand edits to an output fail.
  - Verify: `tests/design_system/test_yggdrasil_tokens.py::test_generated_outputs_are_fresh`
- [ ] The Builder copy stays byte-identical to the binding sheet.
  - Verify: `tests/api/test_cockpit_api.py::test_token_sheet_parity_with_binding_source`
- [ ] Every declared text role/surface pair meets WCAG AA (4.5:1) in Dark and Shell. `fg-3` is
  declared decorative-only.
  - Verify: `tests/design_system/test_yggdrasil_tokens.py::test_role_surface_pairs_meet_wcag_aa`
- [ ] The Swift and flattened JSON outputs carry the same values as the token source.
  - Verify: `tests/design_system/test_yggdrasil_tokens.py::test_swift_and_json_outputs_match_token_source`
- [ ] Font imports use only Google Fonts.
  - Verify: `tests/design_system/test_yggdrasil_tokens.py::test_font_imports_use_google_fonts_only`
- [ ] The spec records S1 as delivered.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`

## How to Verify (Pre-Merge)

- `python3 design-system/yggdrasil/build.py --check`
- `pytest -q tests/design_system/test_yggdrasil_tokens.py`
- `pytest -q tests/api/test_cockpit_api.py tests/builderops/test_devui_exact_reuse_candidate_provenance.py`
- `git diff --check`

## Out of Scope

- Migrating any consumer (S3, S4, S5). Reconciling the live Claude Design system (S2).
- Changing any Dark token value or renaming a token.

## Related Docs

- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md`
- `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual Language`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil design-system gate`

## Related GitHub Issues

Filed as #5627 under parent #5626. The binding sheet's bytes change here, so the
live design-system gate fails closed until YDS-02 lands. Merge only when YDS-02 can run right after.
