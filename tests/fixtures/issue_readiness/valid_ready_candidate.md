## Context
Issue governance needs deterministic observe-only readiness reporting for intake.

## Scope
Add a local checker script, fixture tests, and readiness workflow reporting.

## Source Anchors
- `.codex/skills/_shared/ISSUE_CONTRACT.md :: Verify: marker rule`

## SBS Impact
- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): none
- Write class: governance/docs/process
- Persistence impact: none
- Derived/rebuildable impact: CI artifact only
- New or changed contract: deterministic readiness report
- Owner-doc impact: none
- Transition debt impact: reduces
- Boundary risk: none

## Constraints
- Do not mutate labels or Project status.
- Do not invoke agents.

## Acceptance Criteria
- [ ] The checker reports a ready candidate for canonical issue bodies.
  - Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`
- [ ] The workflow stores a report artifact and fails invalid `agent:ready` issues.
  - Verify: `tests/governance/test_issue_pr_governance.py::test_issue_readiness_workflow_is_strict_for_agent_ready_only`

## Out of Scope
- Auto-labeling issues as agent:ready.

## Suggested Validation
- `pytest -q tests/scripts/test_validate_issue_readiness.py tests/governance/test_issue_pr_governance.py`

## Source Docs
- `.codex/skills/_shared/ISSUE_CONTRACT.md`
- `.github/workflows/issue-pr-governance.yml`
