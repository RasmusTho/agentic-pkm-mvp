---
name: Consolidate Settings Owner Docs
description: One owner doc for settings; orphaned schema deleted; roadmap items superseded; parent acceptance remains with #3156
task_id: SETTINGS-08
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F6, F7
parent_capability: Settings Spine
prerequisites: [SETTINGS-01, SETTINGS-02, SETTINGS-03, SETTINGS-04, SETTINGS-05, SETTINGS-06, SETTINGS-07]
depends_on: [WIRE_SETTINGS_INGESTION.md, SINGLE_DEFAULT_REGISTRY.md, CANONICALIZE_SETTINGS_LOCATION.md, RECEIPT_EVERY_SETTINGS_WRITE.md, REBIND_ON_VAULT_SELECTION.md, PROMPTS_AS_SETTINGS.md, DEHARDCODE_WAVE_ONE.md]
can_parallelize_with: []
---

# Consolidate Settings Owner Docs

## Purpose

Close audit findings F6/F7: two `system-settings.schema.json` files exist (only
`schemas/system-settings.schema.json` is wired; `docs/schema/system-settings.schema.json` is
orphaned with a diverged field name), and no single doc owns settings —
`docs/SETTINGS.md` and `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` own disjoint halves with
contradictions, and `docs/implementation/vault-settings-roadmap.md` records the central service as
simultaneously delivered and unmet.

## What This Task Does

- Rewrites `docs/SETTINGS.md` as the single settings owner doc: the two-scopes/one-spine model,
  canonical location, resolution order, ingestion + degradation semantics, receipt contract,
  tiering — current-state and target-state clearly separated per section.
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` stays the concept contract and defers to
  `docs/SETTINGS.md` for mechanism; the mutual-authority contradiction with `docs/ENVIRONMENTS.md`
  is resolved by explicit pointers.
- Deletes the orphan schema under `docs/schema/`; `schemas/README.md` and operational references
  point only at the wired schema. The audit and this task spec retain the removed path only as
  historical provenance for F6 and are excluded from the operational-reference check.
- Marks the superseded rows in `docs/implementation/vault-settings-roadmap.md` (external-edits →
  SETTINGS-01, hardcoded extraction → SETTINGS-07, central service → the spine) with delivery
  pointers, resolving its internal delivered-vs-unmet contradiction.
- Updates `docs/DOCS_INDEX.md`: `docs/SETTINGS.md` row becomes the owner row; the spec directory
  and audit rows point at it.
- Records the owner-document delivery and the remaining current-versus-target boundary. The
  Settings Spine parent acceptance and closure remain with #3156; this docs-only slice does not
  claim that the parent is closed or that every runtime consumer has converged on one service.

## Concretely

```
$ rg -n "docs/schema/system-settings" docs/ app/ schemas/ \
    -g '!docs/audits/**' -g '!docs/SETTINGS_SPINE/CONSOLIDATE_SETTINGS_OWNER_DOCS.md'  # no hits
$ head -5 docs/SETTINGS.md    # State: owner doc for the delivered SETTINGS-08 docs slice; parent #3156 remains open
```

## Why This Matters

Doc truth is what the next agent and the next audit read; leaving two half-owners and an orphan
schema regrows F2/F6 within a quarter.

## Acceptance Criteria

- [x] `docs/SETTINGS.md` is the single owner doc; ENVIRONMENTS/VAULT_AND_SETTINGS_CONTEXT defer
      to it for mechanism and name the same canonical location.
  - Verify: doc writeback at `docs/SETTINGS.md :: Authority` + `docs/DOCS_INDEX.md` owner row
- [x] The orphan system-settings schema is deleted with zero remaining operational references.
  - Verify: `tests/architecture` docs-reference checks green + repo grep in PR evidence
- [x] Roadmap supersessions are marked with delivery pointers (no silently stale "remaining" rows
      for delivered spine work).
  - Verify: doc writeback at `docs/implementation/vault-settings-roadmap.md :: Migration Notes`
- [x] Parent feature issue remains open with its live capability checklist and closure authority
      preserved; local `PARENT_FEATURE_ISSUE.md` and `README.md` do not claim premature closure.
  - Verify: live parent state at #3156 + doc writeback at
    `docs/SETTINGS_SPINE/PARENT_FEATURE_ISSUE.md :: State`

## How to Verify (Pre-Merge)

- `pytest -q tests/architecture` (docs index + reference coverage checks)
- Manual: capability checklist walk against merged children, linked in the PR.

## Out of Scope

- Any code or runtime behavior change (docs-authoring lane; if a checklist item fails during the
  walk, file the defect — do not patch code from this task).

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F6, F7`
- `docs/DOCS_INDEX.md` (owner-row update target)

## Related GitHub Issues

One docs-authoring issue carries the owner-document slice; parent closure remains governed by #3156.
TCD hint: balanced Codex / medium — docs consolidation with a truth-verification walk; no runtime
implementation is claimed.
