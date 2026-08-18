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


def test_forwarded_identity_requires_concrete_production_seam():
    body = _issue_body(
        scope="Require forwarded identity at the production seam.",
        constraints="The forwarded identity is trusted by the admission check.",
    )
    report = classify_issue_body(body, labels=("agent:ready",))
    assert report.readiness_classification == "admission_contract_conflict"


def test_direct_loopback_rejects_forwarded_identity_claim():
    body = _issue_body(
        scope="Require direct loopback endpoint admission with trusted forwarded identity.",
        constraints="The direct loopback endpoint is the production seam.",
    )
    report = classify_issue_body(body, labels=("agent:ready",))
    assert report.readiness_classification == "admission_contract_conflict"


def test_explicit_no_forwarding_conflict_remains_rejected():
    body = _issue_body(
        scope="Require gateway admission to accept forwarded identity.",
        constraints="The gateway has no forwarded identity.",
    )
    report = classify_issue_body(body, labels=("agent:ready",))
    assert report.readiness_classification == "admission_contract_conflict"


def test_negated_or_unrelated_proxy_text_is_not_an_affirmative_admission_claim():
    negative = _issue_body(
        scope="Require direct loopback endpoint admission.",
        constraints="The direct loopback endpoint has no forwarded identity.",
    )
    unrelated = _issue_body(
        scope="Document the reverse proxy used by the deployment.",
        constraints="The readiness claim does not require forwarded identity.",
    )
    assert classify_issue_body(negative, labels=("agent:ready",)).readiness_classification == "ready_candidate"
    assert classify_issue_body(unrelated, labels=("agent:ready",)).readiness_classification == "ready_candidate"
