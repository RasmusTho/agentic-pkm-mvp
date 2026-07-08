## Context
Issue governance needs a readiness checker that may change Project status and branch protection.

## Scope
Automatically label issues and enable auto-merge after classification.

## Source Anchors
- `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md :: Matrix`

## SBS Impact
- Primary subsystem: Builder System / CES boundary

## Constraints
- Human must decide whether this authority transfer is acceptable.

## Acceptance Criteria
- [ ] Risky governance mutation is reviewed.
  - Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`

## Out of Scope
- Product runtime changes.

## Suggested Validation
- `pytest -q tests/scripts/test_validate_issue_readiness.py`

## Source Docs
- `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md`
