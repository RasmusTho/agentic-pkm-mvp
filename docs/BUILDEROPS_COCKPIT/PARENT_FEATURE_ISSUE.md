State: Filed. The live parent feature issue is #4447 (open, validation hub); children
#4448-#4453. GitHub is the authoritative backlog/validation surface; this file mirrors it.

# Parent feature issue — BuilderOps Cockpit v1

Title: `feature: BuilderOps cockpit v1 — chain-derived register over live authorities`

## Context

The owner needs one register of everything in motion with coverage control (four questions, five
chain-derived thread states, honest freshness/emptiness). The first increment is delivered
(#4438); this parent tracks the remaining v1 slices specified in `docs/BUILDEROPS_COCKPIT/`
(normalized from the accepted 2026-07-30 design exploration; decisions in `DESIGN_DECISIONS.md`).
Upstream evidence: `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md`. The join contract is
upstream input to #4169's DeliveryRunView — extend/depend, never duplicate.

## Scope

The v1 capability outcome across the remaining slices: browser-level induced-failure journeys;
the live GitHub plane; the docs/capability plane; chain-derived states and flaw predicates;
the three lenses and scale states; the Builder-scoped cognitive-load sibling doc.

## Source Anchors

- `docs/BUILDEROPS_COCKPIT/README.md :: Implementation tasks and execution order`
- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: Invariants`

## SBS Impact

- Primary subsystem: Builder System (BuilderOps cockpit surface)
- Secondary subsystem(s): none (read-only over existing authorities)
- Write class: none (projection)
- Persistence impact: none (nothing survives a reload; ADR-0065 posture)
- Derived/rebuildable impact: all rendered state recomputed per render
- New or changed contract: registry payload extends additively (sources, lanes, flaws)
- Owner-doc impact: will-update-in-PR (README is in the spec directory)
- Transition debt impact: reduces (renders known graph gaps honestly)
- Boundary risk: cockpit must never become a second truth — no attention-state write, no cache
  surviving reload, no CKM-derived selection

## Constraints

- Consume, never implement, the delivery-graph data-edge repairs: #4440 (single-source `task_id`),
  #4441 (sync_state labels/URL), #4442 (epic ledger posting), #4443 (parent-line readiness check),
  #4444 (`github_issue:` backfill) — no cockpit slice edits `app/dispatcher/sync_github.py` or
  `scripts/issue_pickup_claim.sh`
- Required PR check stays `"Unit tests (not pg)"`; journeys stay post-merge
- ADR-0057 A1, ADR-0062, ADR-0065 as bound in the README

## Acceptance Criteria

- [ ] All child slices delivered and green
  - Verify: child issue closures linked below, each with its receipt
- [ ] Induced dead-source journey red-not-calm in the post-merge lane
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_dead_source_renders_refusal_not_calm`
- [ ] Spec directory truthful post-delivery (states, issue links, decisions)
  - Verify: doc writeback at `docs/BUILDEROPS_COCKPIT/README.md :: Implementation tasks and execution order`

## Out of Scope

The binding list in `docs/BUILDEROPS_COCKPIT/README.md :: Out of scope for v1 (binding)`.

## Implementation Tasks

`docs/BUILDEROPS_COCKPIT/` — BOPS-COCKPIT-01 (delivered #4438), 02, 07, 03, 05, 04, 06 in that
order (02/07 parallel; 03/05 parallel; 04 may run parallel with 05 once 03 lands).

## Verification Path

Per-task `Verify:` targets on head SHA + required unit lane; browser journeys post-merge.

## Validation / Acceptance Path

Each child posts a validation receipt comment here before the next child is picked up. Parent
closes when all children are delivered and the rows under
`docs/BUILDEROPS_COCKPIT/README.md :: Capability acceptance criteria` are checked; owner-doc
promotion happens inside the child PRs (the README lives in the spec directory). The top rung —
owner use — is explicitly not automatable and stays visible as the empty tried tier until
INV-DG-7 exists.

## Suggested Validation

- `pytest tests/builderops tests/api/test_cockpit_api.py -m "not pg"`
- `COMPANION_UI_BROWSER_TESTS=1 pytest tests/companion_ui/test_cockpit_journeys.py`

## Source Docs

- `docs/BUILDEROPS_COCKPIT/README.md`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md`

## Applies learning (optional)
