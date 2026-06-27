"""Eval skeleton: general knowledge crosses into work only through an explicit flow.

Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow (general-knowledge case)
Issues: #2550 (registry), #2551 (corpus), #2552 (skeletons).
"""

from __future__ import annotations

import pytest

from tests.evals._helpers import future_runtime, load_group


def test_general_fixtures_marked_eligible() -> None:
    # Static precondition (passes today): general fixtures carry general_knowledge source role and
    # background/reference evidence — eligible to cross, but only as background and only via a flow.
    general = load_group("general_programming")
    assert general, "expected general fixtures"
    for doc in general:
        assert doc.meta["sphere"] == "general"
        assert doc.meta["scope_id"] == "scope:general/programming"
        assert doc.meta["source_role"] == "general_knowledge"
        assert doc.meta["evidence_role"] in {"background", "reference"}
        # Eligibility, not a bypass: there is no general_knowledge boolean flag in the metadata.
        assert "general_knowledge" not in doc.meta


@pytest.mark.xfail(
    reason=(
        "Runtime CrossScopeFlow enforcement not implemented yet; this skeleton protects invariant "
        "cross_scope_only_via_flow (#2550) for general knowledge over the corpus (#2551). General "
        "material may cross to work only through an explicit flow, as background/reference, never as "
        "real-world evidence and never by a general_knowledge bypass. Future vertical slice: GOV "
        "cross-scope evaluation -> ContextEnvelope."
    ),
    strict=True,
)
def test_general_knowledge_crosses_clean() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow
    gov = future_runtime("cross_scope")  # raises until cross-scope runtime exists
    # With an explicit flow that allows cite-as-background, general knowledge may cross — as background.
    decision = gov.evaluate(
        source_scope="scope:general/programming",
        target_scope="scope:work/project-alpha",
        operation="cite",
        flow={"allowed_operations": ["retrieve", "surface", "cite"], "evidence_roles_allowed": ["background"]},
    )
    assert decision.allowed is True
    assert decision.evidence_role_in_target == "background"
    # Without a flow, the same crossing is denied.
    denied = gov.evaluate(
        source_scope="scope:general/programming",
        target_scope="scope:work/project-alpha",
        operation="cite",
        flow=None,
    )
    assert denied.allowed is False
