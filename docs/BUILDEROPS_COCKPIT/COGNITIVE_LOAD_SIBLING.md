---
name: Cognitive Load Sibling
description: The thin Builder-scoped cognitive-load doc — CLPL Decision Test and FA-5 budgets by reference, plus the rebinding table and the button classes
task_id: BOPS-COCKPIT-07
source_anchor: "docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision Test"
parent_capability: BuilderOps Cockpit
github_issue: 4449
prerequisites: []
depends_on: []
can_parallelize_with: [INDUCED_FAILURE_JOURNEYS.md, GITHUB_LIVE_PLANE.md, DOCS_PLANE_CAPABILITY_LANES.md, CHAIN_DERIVED_STATES.md, SURFACE_LENSES.md]
---

# Cognitive Load Sibling

## Purpose

The cockpit needs cognitive-load governance, and the product already has the authority for it:
`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` (CLPL). Extending that Product-owned doc would re-couple
BuilderOps to the product app at the doc level exactly while ADR-0062 is lifting BuilderOps out.
The ruling (three independent reviews, unanimous): write a **thin Builder-scoped sibling** that
imports by reference and adds only what is Builder-specific.

## What This Task Does

Creates `docs/BUILDEROPS_COCKPIT/COGNITIVE_LOAD_REBINDING.md` (docs-only slice) that:

- Imports **by reference, never by restatement**: the CLPL Decision Test
  (`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision Test`), the decision-mode ordering, and the
  FA-5 resurfacing budgets (`:: FA-5 resurfacing budget and why-now contract`). No quoted prose —
  the governance tests are substring-coupled to the product doc, and a re-wrap breaks CI.
- Adds the **rebinding table**: each CLPL term bound to its Builder equivalent (user → owner-as-
  operator; note surface → register card; resurfacing budget → needs-you band admission; why-now
  contract → the gate's own phrasing on the card; decision modes → the tri-state gate banding:
  typed gate status decides *whether* something may demand attention, fail-closed to "needs your
  decision" on ambiguity; TCD orders only *within* the band).
- Adds the **three button classes** as the only genuinely new normative content: `contract`
  (typed call — deterministic, idempotent, receipt of known shape) and `agent` (agent start with a
  prepared prompt — non-deterministic, prose in/out, receipt created by the agent's flow), both
  new, plus `out` (out-link, no mutation — already shipped, restated for the legend contract); the
  class must be visible on the control and legend-explained,
  because determinism changes failure semantics, idempotence, and receipt shape.
- States the friction rule: friction grows with risk level and never shrinks with habituation.
- Registers the new doc in `docs/DOCS_INDEX.md` in the same change.

## Concretely

The doc is ≤ ~120 lines. Every normative sentence is either a reference into CLPL, a rebinding
row, or a button-class/friction statement. If a sentence restates CLPL prose, it is wrong.

## Why This Matters

Without the sibling, the first action-capable cockpit slice would either invent its own attention
rules (drift) or edit the product's CLPL (ownership violation). The button-class contract must
exist *before* any action slice, since it decides what those slices are allowed to render.

## Acceptance Criteria

- [ ] The sibling doc exists, imports Decision Test / decision-mode ordering / FA-5 budgets by
      reference only, and contains no restated CLPL prose
  - Verify: doc writeback at `docs/BUILDEROPS_COCKPIT/COGNITIVE_LOAD_REBINDING.md :: Rebinding table`
- [ ] The rebinding table covers every imported CLPL mechanism with a Builder binding, including
      the tri-state gate banding with fail-closed ambiguity routing
  - Verify: doc writeback at `docs/BUILDEROPS_COCKPIT/COGNITIVE_LOAD_REBINDING.md :: Rebinding table`
- [ ] The three button classes are defined with failure-semantics, idempotence, and receipt-shape
      columns, and the friction rule is stated
  - Verify: doc writeback at `docs/BUILDEROPS_COCKPIT/COGNITIVE_LOAD_REBINDING.md :: Action button classes`
- [ ] `docs/DOCS_INDEX.md` carries the new row in the same PR
  - Verify: doc writeback at `docs/DOCS_INDEX.md` (row for the sibling doc)
- [ ] Existing governance substring tests stay green (no CLPL prose touched)
  - Verify: `tests/governance` suite (the existing CLPL substring tests) green on the PR head SHA

## How to Verify (Pre-Merge)

`pytest tests/governance -m "not pg"`; visual read of the sibling doc against CLPL to confirm
reference-not-restatement.

## Out of Scope

- Any edit to `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` or other Product-owned docs.
- Implementing any `contract`/`agent` button (no action slices exist in v1; EXT-5/EXT-6 decisions).
- Any interruption-cost formula or calibration logging (a future capability if the owner wants it;
  the ergonomics review's suggestion is recorded in the audit trail, not enacted here).

## Related Docs

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` (imported authority)
- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: EXT-5, EXT-6`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

One bounded docs issue. Reference "Implements BUILDEROPS_COCKPIT/COGNITIVE_LOAD_SIBLING".
Unblocked from day one; parallel with everything.
