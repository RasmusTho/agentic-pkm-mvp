## Context
Issue governance maybe needs readiness reporting, but details are TBD.

## Scope
Investigate and update whatever is needed as needed.

## Source Anchors
- `.codex/skills/_shared/ISSUE_CONTRACT.md :: Verify: marker rule`

## SBS Impact
- Primary subsystem: Builder System / CES boundary

## Constraints
- Do not mutate labels or Project status.

## Acceptance Criteria
- [ ] Determine a useful checker shape.
  - Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`

## Out of Scope
- Auto-labeling issues.

## Suggested Validation
- `pytest -q tests/scripts/test_validate_issue_readiness.py`

## Source Docs
- `.codex/skills/_shared/ISSUE_CONTRACT.md`
