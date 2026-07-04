"""Eval skeleton: general knowledge crosses into work only through an explicit flow.

Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow (general-knowledge case)
Issues: #2550 (registry), #2551 (corpus), #2552 (skeletons). App enforcement: #2772 (KERNEL-10).

Since KERNEL-10 the runtime assertions run un-xfailed against the LIVE app path
(``tests/evals/_app_adapter.py``). The deny-by-default half is enforced by the app scope prefilter
(``retrieve``: cross-scope material is excluded before ranking); the governed-flow decision is
stated explicitly by the adapter's ``evaluate`` (a typed CrossScopeFlow crosses material as the most
conservative role, never over-granting toward ``evidence``).
"""

from __future__ import annotations

from tests.evals import _app_adapter as gov
from tests.evals._helpers import load_group


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


def test_general_knowledge_does_not_auto_cross_into_work() -> None:
    # Deny-by-default, enforced by the LIVE app scope prefilter: a work-scoped query never admits
    # general-scope material without a governed flow (similarity is not permission).
    result = gov.retrieve(query="concurrency patterns state machine", active_scope_id="scope:work/project-alpha")
    assert result.scope_policy_prefiltered is True
    leaked = [
        c for c in result.candidate_items
        if c.metadata_bundle.scope_id == "scope:general/programming"
    ]
    assert leaked == [], "general material must not auto-cross into work without a governed flow"


def test_general_knowledge_crosses_clean() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow
    # General material may cross to work only through an explicit flow, as background/reference, never
    # as real-world evidence and never by a general_knowledge bypass.
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
