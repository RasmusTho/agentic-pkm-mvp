## Context
Cockpit journey coverage needs post-merge browser-lane wiring declared through
non-behavioral concrete-observable targets (#4464 regression shapes from #4448).

## Scope
Wire journey tests into the post-merge browser lane and deselect them from the PR lane.

## Source Anchors
- `.codex/skills/_shared/ISSUE_CONTRACT.md :: Verify: marker rule`

## SBS Impact
- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): none
- Write class: governance/docs/process
- Persistence impact: none
- Derived/rebuildable impact: CI artifact only
- New or changed contract: none
- Owner-doc impact: none
- Transition debt impact: reduces
- Boundary risk: none

## Constraints
- Do not mutate labels or Project status.

## Acceptance Criteria
- [ ] Dead-source journey drives the production route against an unreadable store.
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_dead_source_renders_refusal_not_calm` (enforcement: drives the production `/cockpit` route against an API process whose store path is unreadable)
- [ ] Journey file wired into the post-merge browser lane as its own step.
  - Verify: diff of `.github/workflows/browser-runtime.yml` adding a step running `tests/companion_ui/test_cockpit_journeys.py`
- [ ] Journey module excluded from the required PR lane by the marker mechanism.
  - Verify: `pytestmark = pytest.mark.browser_runtime` present in `tests/companion_ui/test_cockpit_journeys.py`, deselected by the PR marker expression in `scripts/select_pr_tests.py`
- [ ] Delivery wording no longer lists the journey lane as pending.
  - Verify: `docs/development/DEV_WORKFLOW.md :: Acceptance verifiability` removed or rewritten as delivered.

## Out of Scope
- PR-lane semantics changes.

## Suggested Validation
- `pytest -q tests/companion_ui/test_cockpit_journeys.py`

## Source Docs
- `.codex/skills/_shared/ISSUE_CONTRACT.md`
