---
name: Adopt the Tokens in Bifrost
description: Back the Bifrost YggTheme with a pinned, generated Swift token file instead of iOS system colours.
task_id: YDS-05
source_anchor: "docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Bifrost"
parent_capability: Yggdrasil Design System v2
prerequisites: [YDS-01]
depends_on: [ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md]
can_parallelize_with: [MIGRATE_COMPANION_SURFACES.md, MIGRATE_BUILDER_SURFACES.md]
---

# Adopt the Tokens in Bifrost

## Purpose

Bring the native Bifrost clients into the same design system as the web surfaces.

## What This Task Does

This task is delivered in the constituent repository `RasmusTho/bifrost`, under that repository's
ecosystem authority (ADR-0050). The Issue is filed there after YDS-01 merges. No release or Git tag
is created: the pin is the token `VERSION` plus the exact hub merge-commit SHA that produced the
generated Swift file.

- Vendors `YggdrasilTokens.swift` from a named hub commit, and records the token `VERSION` and that
  commit SHA.
- Backs `YggTheme` colours, spacing, and radius with those tokens. Typography stays on iOS Dynamic
  Type, mapped to Yggdrasil roles.
- Ships Dark with `.preferredColorScheme(.dark)`. Shell waits for the web trial to graduate.
- Adds a Bifrost CI check that the vendored file is byte-identical to
  `design-system/yggdrasil/dist/YggdrasilTokens.swift` at the pinned hub commit.

## Concretely

`YggTheme.Color.accent` resolves to Yggdrasil gold `#d4a843` instead of `Color.accentColor`.

## Why This Matters

Today Bifrost uses stock iOS colours, so the native apps do not look like Yggdrasil.

## Acceptance Criteria

- [ ] The Bifrost Issue and its PR are linked from the parent feature issue, with the pinned token
  `VERSION` and hub commit SHA.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`
- [ ] The spec records S5 as delivered.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`

The behavioral ACs (the Swift tests) live on the Bifrost Issue, in that repository's test suite.

## How to Verify (Pre-Merge)

- In `RasmusTho/bifrost`: that repository's Swift test and CI suite.
- Here: `python3 scripts/docs_guard.py`.

## Out of Scope

- Shell on iOS. Bundling custom fonts into Bifrost.

## Related Docs

- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Bifrost`

## Related GitHub Issues

Parent: #5626. Filed in `RasmusTho/bifrost` after YDS-01 merges. This hub keeps only the link and the receipt.
