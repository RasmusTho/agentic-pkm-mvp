---
name: Surface Lenses
description: The graph lens and one-question-at-a-time lens, many-at-once scaling, and the narrow/200%/print states on the served surface
task_id: BOPS-COCKPIT-06
source_anchor: "docs/BUILDEROPS_COCKPIT/design/2026-07-30-cockpit-exploration/INTAKE.md :: What this directory holds"
parent_capability: BuilderOps Cockpit
github_issue: 4453
prerequisites: [BOPS-COCKPIT-02, BOPS-COCKPIT-04, BOPS-COCKPIT-05]
depends_on: [INDUCED_FAILURE_JOURNEYS.md, CHAIN_DERIVED_STATES.md, DOCS_PLANE_CAPABILITY_LANES.md]
can_parallelize_with: [COGNITIVE_LOAD_SIBLING.md]
---

# Surface Lenses

## Purpose

The accepted design draws three lenses over one dataset: bands (shipped), a graph lens (the eight
rungs fanned out across the delivery-graph levels,
`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: RQ1 — Join keys per level pair`), and
a one-question-at-a-time lens (lowest cognitive load: four
questions, one per screen, a display-serif claim before the list). Plus the scaling behaviors that
keep honesty at volume: many-at-once, narrow+200%, and print.

## What This Task Does

- Adds the lens switcher to `app/web/static/cockpit.html|css|js` following the design's posture:
  the switcher is real radio buttons, CSS-driven state (`:has()`), functional with JavaScript off
  for the drawn states; same data, no extra fetch per lens.
- **Graph lens**: the spine fanned across levels; everything left of `slice` renders dotted/dashed
  per its rung class — the only solid spine is slice → PR → sha → receipt (the machine-keyed
  middle proven in `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: RQ1 — Join keys per
  level pair`).
- **One-question lens**: four questions in fixed order, one per screen, answer as a claim line in
  the display serif followed by at most five rows, then an explicit "and n more in the register"
  link into the bands lens — no silence, just deferral with a count.
- **Many-at-once scaling**: past five cards per lane, cards fall to row form with the same spine —
  the surface gets longer, never denser, and nothing hides (decision Q2).
- **Narrow + 200%**: single column in document order, spine scales with type, no horizontal
  scrolling, no hidden columns.
- **Print**: black-on-white, all details forced open, switcher and action buttons hidden (they are
  not printable claims), spine as solid/hollow nodes; no band, card, or done-band tier split
  across pages.
- Keyboard: cards are `<summary>` elements in natural tab order; the switcher is arrow-navigable
  radios; the token sheet's focus ring, never suppressed.

## Concretely

Load `/cockpit`, switch lenses via keyboard arrows, zoom to 200% at 768px width, and print-preview:
every state shows the same thread identities with the same rung classes.

## Why This Matters

The lenses are the difference between a register the owner can *think with* at 41 threads and a
wall he stops reading — the ergonomics finding. The scaling rules are honesty rules: density caps
and hidden overflow are silences, and every drawn state exists precisely to make silence
impossible.

## Acceptance Criteria

- [ ] Three lenses render from one payload; lens choice changes projection, never data; bands lens
      remains the default
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_lenses_project_same_data`
- [ ] Graph lens draws only the machine-keyed middle solid; weaker rungs dotted per class
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_graph_lens_solid_spine_is_machine_keyed`
- [ ] One-question lens caps at five rows with an explicit counted deferral link, never an uncounted cut
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_one_question_lens_counted_deferral`
- [ ] Overflow falls to row form; no card is hidden at volume
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_many_at_once_no_hiding`
- [ ] Narrow+200% renders one column with no horizontal scroll; print forces all details open and
      hides non-claims
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_narrow_zoom_and_print_states`

## How to Verify (Pre-Merge)

`COMPANION_UI_BROWSER_TESTS=1 pytest tests/companion_ui/test_cockpit_journeys.py` (extends the
BOPS-COCKPIT-02 journey file; post-merge browser lane, not the required PR check). Static-render
assertions that need no browser go in `tests/api/test_cockpit_api.py`.

## Out of Scope

- Any new data source or payload change beyond what BOPS-COCKPIT-04/05 already emit.
- Saved lens preference (persistence is banned in v1 — ADR-0065 posture).
- Session launcher, command palette, search fields (binding out-of-scope list; nothing may require
  typing a path, an id, or a search string).

## Restart / Durability Posture

Lens choice is transient DOM state; a reload returns to the bands lens. Deliberate: no cockpit
state survives a reload, and the reset-to-default is the visible proof of that contract.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/design/2026-07-30-cockpit-exploration/` (drawn states, verbatim)
- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q2, Q4`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md` (graph levels and key classes)

## Related GitHub Issues

One bounded issue. Reference "Implements BUILDEROPS_COCKPIT/SURFACE_LENSES". Blocked until
INDUCED_FAILURE_JOURNEYS, CHAIN_DERIVED_STATES, and DOCS_PLANE_CAPABILITY_LANES merge.
