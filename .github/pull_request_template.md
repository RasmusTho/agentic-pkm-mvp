## Change Lane
- [ ] Implementation lane
- [ ] Docs authoring lane
- [ ] Governance lane

Docs authoring applies only to docs-only changes in approved docs-authoring surfaces. It must not be used for code, runtime behavior, contracts, shipped reality, or implementation writeback.
Governance lane applies to bounded repository-governance changes such as repo-local skills, PR/issue policy, and lightweight enforcement for docs/governance workflows. It may include repo-meta governance scripts and focused tests, but it must not be used for product/runtime implementation.

## Linked Issue
Fixes #

Required for implementation lane. Leave blank for docs authoring lane.
Leave blank for governance lane when the PR stays within approved governance surfaces.

## SBS Impact
- Primary subsystem:
- Secondary subsystem(s):
- Write class:
- Authority impact:
- Persistence impact:
- Derived/rebuildable impact:
- Human knowledge impact:
- Memory impact:
- Retrieval/context impact:
- Sync/deployment impact:
- New or changed contract:
- Boundary risk:

## Summary
-
-

## Implementation Scope Check
- [ ] Change stays within the linked Issue scope.
- [ ] Constraints from the linked Issue were followed.
- [ ] Acceptance Criteria from the linked Issue are satisfied.
- [ ] Docs were updated in the same change when behavior/contracts changed.
- [ ] Owner docs and roadmap/plan wording were updated when this PR turns a tracked backlog item into shipped reality.

## Docs Authoring Check
- [ ] This PR only changes approved docs-authoring surfaces.
- [ ] No code, runtime behavior, contracts, or shipped reality changed.
- [ ] This PR prepares or clarifies authoritative docs/specification and may later feed `docs-to-issue` extraction.

## Governance Lane Check
- [ ] This PR only changes approved governance surfaces.
- [ ] The change is limited to repo governance, agent workflow, or lightweight enforcement.
- [ ] No product/runtime implementation or shipped feature behavior changed.

## Validation
Implementation lane:
- [ ] `ruff check app tests`
- [ ] If files under `app/` or `tests/` changed, lint output from `ruff check app tests` is included below or a tooling limitation is stated.
- [ ] `mypy app`
- [ ] `pytest -q -m "not pg"`
- [ ] Additional targeted checks run as needed

Docs authoring lane:
- [ ] Docs/governance checks run as appropriate for the touched surfaces
- [ ] Any validation gaps or tooling limitations are stated explicitly

Governance lane:
- [ ] Governance checks run as appropriate for the touched surfaces
- [ ] Any validation gaps or tooling limitations are stated explicitly

## BuilderOps Routing
- Records/projections/receipts: <ids or "none">
- Reason: <why no BuilderOps material was created, or what was routed>

## Notes
- State any residual risks, follow-ups, or assumptions.
