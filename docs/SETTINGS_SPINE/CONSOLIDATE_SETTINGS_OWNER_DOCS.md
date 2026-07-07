---
name: Consolidate Settings Owner Docs
description: One owner doc for settings; orphaned schema deleted; roadmap items superseded; parent-closure handoff
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
- Deletes `docs/schema/system-settings.schema.json`; `schemas/README.md` and any references point
  only at the wired schema.
- Marks the superseded rows in `docs/implementation/vault-settings-roadmap.md` (external-edits →
  SETTINGS-01, hardcoded extraction → SETTINGS-07, central service → the spine) with delivery
  pointers, resolving its internal delivered-vs-unmet contradiction.
- Updates `docs/DOCS_INDEX.md`: `docs/SETTINGS.md` row becomes the owner row; the spec directory
  and audit rows point at it.
- **Parent-closure handoff:** verifies the capability acceptance checklist in
  `docs/SETTINGS_SPINE/README.md`, posts the final validation receipt on the parent feature issue,
  reconciles `PARENT_FEATURE_ISSUE.md` + `README.md` lifecycle state, and closes the parent.

## Concretely

```
$ grep -rn "docs/schema/system-settings" docs/ app/ schemas/   # no hits
$ head -5 docs/SETTINGS.md    # State: owner doc for the settings spine (two scopes, one spine)
```

## Why This Matters

Doc truth is what the next agent and the next audit read; leaving two half-owners and an orphan
schema regrows F2/F6 within a quarter.

## Acceptance Criteria

- [ ] `docs/SETTINGS.md` is the single owner doc; ENVIRONMENTS/VAULT_AND_SETTINGS_CONTEXT defer
      to it for mechanism and name the same canonical location.
  - Verify: doc writeback at `docs/SETTINGS.md :: Authority` + `docs/DOCS_INDEX.md` owner row
- [ ] `docs/schema/system-settings.schema.json` is deleted with zero remaining references.
  - Verify: `tests/architecture` docs-reference checks green + repo grep in PR evidence
- [ ] Roadmap supersessions are marked with delivery pointers (no silently stale "remaining" rows
      for delivered spine work).
  - Verify: doc writeback at `docs/implementation/vault-settings-roadmap.md :: Migration Notes`
- [ ] Parent feature issue closed with the capability acceptance checklist verified and the final
      receipt posted; local `PARENT_FEATURE_ISSUE.md` and `README.md` reconciled to closed state.
  - Verify: closure receipt on the parent issue + doc writeback at
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

One docs-authoring issue, last in the chain, carries parent closure. TCD hint: sonnet / medium —
docs consolidation with a truth-verification walk; no code risk.
