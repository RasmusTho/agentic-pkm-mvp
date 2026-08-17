"""Readiness must keep admission claims aligned with their production seam."""

from scripts.validate_issue_readiness import classify_issue_body


def _issue_body(*, scope: str, constraints: str) -> str:
    return f"""\
## Context
Governance contract test.

## Scope
{scope}

## Source Anchors
- `.codex/skills/_shared/ISSUE_CONTRACT.md :: Issue self-sufficiency rule`

## SBS Impact
- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): readiness
- Write class: governance/docs/process
- Persistence impact: none
- Derived/rebuildable impact: none
- New or changed contract: readiness admission claims
- Owner-doc impact: none
- Transition debt impact: reduces
- Boundary risk: no runtime admission changes

## Constraints
{constraints}

## Acceptance Criteria
- [ ] Admission wording is validated.
  - Verify: `tests/governance/test_issue_readiness_admission_contract.py::test_ready_issue_admission_wording_matches_named_production_seam`

## Out of Scope
- Product/runtime changes.

## Suggested Validation
- `python3 -m pytest -q tests/governance/test_issue_readiness_admission_contract.py`

## Source Docs
- `.codex/skills/_shared/ISSUE_CONTRACT.md`
"""


def test_ready_issue_admission_wording_matches_named_production_seam():
    contradictory = _issue_body(
        scope="Require the direct loopback production seam, but forward identity through the proxy.",
        constraints="The production seam has no forwarded identity.",
    )
    report = classify_issue_body(contradictory, labels=("agent:ready",))
    assert report.readiness_classification == "admission_contract_conflict"

    matching = _issue_body(
        scope="Require local admission through the named production seam: direct loopback endpoint.",
        constraints="The direct loopback seam has no forwarded identity.",
    )
    report = classify_issue_body(matching, labels=("agent:ready",))
    assert report.readiness_classification == "ready_candidate"
