---
name: Docs Plane and Capability Lanes
description: Join the docs/spec frontmatter plane and capability registry so threads group into capability lanes where an edge exists, freestanding otherwise
task_id: BOPS-COCKPIT-05
source_anchor: "docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: Findings, ranked by blast radius × silence of failure"
parent_capability: BuilderOps Cockpit
github_issue: 4451
prerequisites: [BOPS-COCKPIT-01]
depends_on: [REGISTRY_READ_TIME_JOIN.md]
can_parallelize_with: [GITHUB_LIVE_PLANE.md, CHAIN_DERIVED_STATES.md, INDUCED_FAILURE_JOURNEYS.md, COGNITIVE_LOAD_SIBLING.md]
---

# Docs Plane and Capability Lanes

## Purpose

The shape of the delivery graph lives in the docs plane — 54 specification directories, 410 task
docs with frontmatter (`task_id`, `github_issue`, `depends_on`), the machine-registered capability
seed — while its state lives in GitHub. Joining the two gives the cockpit its capability lanes and
its epic/capability rungs, with every weak edge rendered honestly weak.

## What This Task Does

- Reads at render time, as named sources with their own freshness (file mtimes are the watermark):
  - `app/builderops/ckm/seed/capabilities.yaml` — capability keys, parents, SBS anchors
  - `docs/architecture/traceability-matrix.md` — direct capability→issue edges
  - spec-directory task-doc frontmatter (`docs/*/` matching the parent-feature pattern) —
    `github_issue`, `depends_on`, `task_id`
- Groups threads into capability lanes where a machine edge exists (matrix row, spec-dir
  frontmatter); threads with no fresh capability edge render freestanding in their own lane with an
  amber capability rung — never guessed under a parent (the degraded drawn state in the archived
  design, where two threads unknown to a stale projection render freestanding).
- Upgrades spine rungs where keys exist: `capability` and `epic` rungs move from `absent` to
  `proven` (frontmatter/matrix key) or `derived` (State-line prose), per key class.
- Renders honest partials exactly as the audit names them: an unpopulated `github_issue:` field is
  an `unlinked` rung plus a "no issue link" chip naming the known children; a prose-only parent
  table is a `derived` rung whose card says the child count may be wrong; structurally empty
  labels render as dashed "empty field" chips, never as deliberate content.
- Capability lanes scroll/stack per decision Q4: no cap, single stacked column at narrow widths.
- CKM projection remains a lens only: if the CKM store is present its watermark may annotate "why
  it matters" context, but no lane, band, count, or ordering ever derives from CKM state
  (ADR-0057: projection, never spine).

## Concretely

```
curl -s localhost:18001/api/cockpit/registry | jq '.lanes[] | {capability, threads: (.items|length)}'
```

Expected: lanes for capabilities with machine edges, a freestanding lane for the rest, and sources
listing `docs-frontmatter` with its own watermark.

## Why This Matters

This is the join the audit calls the graph's central weakness — shape and state on different
planes, connected by a mostly-empty field. Rendering that field's emptiness (instead of hiding
threads that lack it) is what makes the register complete: nothing disappears for being badly
linked; it appears with its weakness drawn.

## Acceptance Criteria

- [ ] Threads group into lanes only via machine edges; missing/stale capability edges render
      freestanding with an amber rung, never guessed under a parent
  - Verify: `tests/builderops/test_cockpit_docs_plane.py::test_no_edge_means_freestanding_never_guessed`
    (enforcement AC: production `build_registry` path with a fixture spec-dir lacking edges)
- [ ] Unpopulated `github_issue:` renders the unlinked rung + named-children chip; prose-only
      parent edges render `derived` with the may-be-wrong caveat
  - Verify: `tests/builderops/test_cockpit_docs_plane.py::test_honest_partials_for_weak_edges`
- [ ] The docs plane is a named source with its own watermark; an unreadable docs tree refuses
      lane claims instead of rendering an empty lane set
  - Verify: `tests/builderops/test_cockpit_docs_plane.py::test_docs_source_freshness_and_refusal`
- [ ] No band, count, lane membership, or ordering derives from CKM state
  - Verify: `tests/builderops/test_cockpit_docs_plane.py::test_ckm_is_lens_never_spine`

## How to Verify (Pre-Merge)

`pytest tests/builderops/test_cockpit_docs_plane.py tests/builderops/test_cockpit_registry.py -m "not pg"`
with fixture spec directories under the test tree; no dependency on live repo docs in assertions
beyond schema shape.

## Out of Scope

- Backfilling `github_issue:` fields in existing spec dirs (INV-DG-5 backfill belongs to the
  in-flight delivery-graph data-edge work — this task renders the gap, that work closes it).
- Any CKM store write, any linker run, any maturity number.
- Needs-layer and intention rungs (no keys exist — audit F3; they stay `absent` by design until
  the owner-gated needs-ID and intention-object work exists).

## Restart / Durability Posture

File reads are per-render; nothing persists. A moved or unreadable docs tree degrades to refusal at
the next render — the user sees the source pill go red, not a quietly shrunken register.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q4`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md` (F3, F5, F6, RQ3)
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

One bounded issue. Reference "Implements BUILDEROPS_COCKPIT/DOCS_PLANE_CAPABILITY_LANES".
