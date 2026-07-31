---
name: Cognitive Load Rebinding
description: Builder-scoped cognitive-load governance — imports CLPL's Decision Test, decision-mode ordering, and FA-5 resurfacing budgets by reference; adds the rebinding table, action button classes, and the friction rule
task_id: BOPS-COCKPIT-07
source_anchor: "docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision Test"
parent_capability: BuilderOps Cockpit
github_issue: 4449
prerequisites: []
depends_on: []
can_parallelize_with: [INDUCED_FAILURE_JOURNEYS.md, GITHUB_LIVE_PLANE.md, DOCS_PLANE_CAPABILITY_LANES.md, CHAIN_DERIVED_STATES.md, SURFACE_LENSES.md]
---

# Cognitive Load Rebinding

## Purpose

The BuilderOps cockpit needs cognitive-load governance. The authority for it already exists —
`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` (CLPL) — and is Product-owned. Extending CLPL would
re-couple BuilderOps to the product app at the doc level exactly while
`docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md` is lifting BuilderOps out. This is
the thin Builder-scoped sibling: it imports CLPL by reference and adds only what the cockpit's
read-only register needs on top.

## Imported by reference

Nothing below restates CLPL prose. Each line is a pointer; the governing text lives only at the
cited location, and this doc must stay correct if that text is ever reworded.

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision Test` — the table used to classify a
  cognitive-load feature into a projection class and required route before it is built or
  documented.
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: Decision mode` — the fixed field ordering used to
  structure any proposal or choice for human review.
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md :: FA-5 resurfacing budget and why-now contract` — the
  `items_per_orientation_moment`, `foreground_refresh_frequency`, `resurface_salience_threshold`,
  and `why_now` contract fields.

## Rebinding table

CLPL speaks for the product's human-facing surfaces, addressed to many users. The cockpit is a
Builder-facing register read by one owner-as-operator. Each row binds a CLPL term to its Builder
equivalent; the middle column names where the CLPL side is governed, not what it says.

| CLPL term | CLPL reference | Builder binding |
| --- | --- | --- |
| The human / user | Decision Test | Owner-as-operator — the single human reading the register, not an audience of many users. |
| Human-facing view | Projection Stack | Register card — one thread's row in the cockpit registry payload. |
| Resurfacing budget | FA-5 resurfacing budget and why-now contract | Needs-you band admission — the same low-volume, defensible, non-binding admission discipline gates what is promoted into the needs-you band; nothing is added to fill space. |
| `why_now` pointer | FA-5 resurfacing budget and why-now contract | The gate's own phrasing on the card — the register states the typed reason a thread sits in its band (status, staleness, named deficiency), never a generated rationale standing in for `why_now`. |
| Decision modes | Decision mode | Tri-state gate banding: the typed gate status decides *whether* a thread may demand attention at all (working / done / flawed / forgotten / needs-you), fail-closed to the needs-you band whenever that status is ambiguous or unmapped. The risk-meter ordering (`docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: EXT-7`) orders threads only *within* one band and never moves a thread across bands. |

## Action button classes

v1 is entirely read-only, so only `out` renders today
(`docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: EXT-5`). The three-class model is fixed now
because it decides what any future action slice may add; a slice must not invent a fourth class or
blur these columns.

| Class | Meaning | Failure semantics | Idempotence | Receipt shape |
| --- | --- | --- | --- | --- |
| `contract` | Typed call into an existing deterministic endpoint. Not yet built. | A rejected or errored call surfaces a typed failure from the endpoint's own contract — never a silent no-op. | Idempotent: repeating the same call with the same inputs produces the same effect. | new-deterministic-typed-call — a known-shape receipt defined by the endpoint's own contract. |
| `agent` | Agent start with a prepared prompt. Not yet built. | Failure is an agent-run failure (start rejected, run errored), surfaced as run status — never a typed contract error. | Non-deterministic: re-running is a new agent start, not guaranteed to reach the same effect. | new-nondeterministic-prompt-start — the receipt is whatever the agent's own run/session flow produces; the button never claims a stronger receipt than that flow gives it. |
| `out` | Out-link to the owning authority surface (GitHub, dispatcher UI, etc.). Already shipped. | Only a navigation/link failure is possible; there is no mutation to fail. | Trivially idempotent — opening a link never changes state. | already-shipped-no-mutation — no receipt, because nothing was mutated. |

The class must be visible on the control itself and legend-explained, because determinism changes
every column above; a control must not carry `out` semantics while doing `contract` or `agent`
work.

## The friction rule

Friction grows with risk level. It never shrinks with habituation: a control gating a higher-risk
action stays exactly as hard to trigger by accident no matter how many times the same owner has
used it before. Familiarity is not a substitute for the gate.

## Non-goals

- No edit to `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` or any other Product-owned doc.
- No implementation of any `contract` or `agent` button; v1 stays read-only.
- No interruption-cost formula or calibration logging.

## Related docs

- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` (imported authority)
- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: EXT-5, EXT-6`
- `docs/BUILDEROPS_COCKPIT/COGNITIVE_LOAD_SIBLING.md` (task spec this doc fulfills)
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
