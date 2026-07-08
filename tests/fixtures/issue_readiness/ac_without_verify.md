## Context
Issue governance needs deterministic observe-only readiness reporting for intake.

## Scope
Add a local checker script and tests.

## Source Anchors
- `.codex/skills/_shared/ISSUE_CONTRACT.md :: Verify: marker rule`

## SBS Impact
- Primary subsystem: Builder System / CES boundary

## Constraints
- Do not mutate labels or Project status.

## Acceptance Criteria
- [ ] The checker identifies acceptance criteria without verify markers.

## Out of Scope
- Auto-labeling issues.

## Suggested Validation
- `pytest -q tests/scripts/test_validate_issue_readiness.py`

## Source Docs
- `.codex/skills/_shared/ISSUE_CONTRACT.md`
