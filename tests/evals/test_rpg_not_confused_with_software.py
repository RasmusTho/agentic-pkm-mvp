"""Eval skeleton: RPG/worldbuilding material is not confused with real-world software.

Invariant registry: docs/testing/invariant-tests.md :: rpg_not_confused_with_software
Issues: #2550 (registry), #2551 (corpus), #2552 (skeletons). App enforcement: #2772 (KERNEL-10).

Since KERNEL-10 the runtime assertion runs un-xfailed against the LIVE app retrieval path
(``tests/evals/_app_adapter.py`` -> ``scoped_hybrid_search`` under an active scope), not the
test-only ``mimer_runtime`` reference.
"""

from __future__ import annotations

from tests.evals import _app_adapter as rca
from tests.evals._helpers import load_group


def test_rpg_fixtures_are_distinctly_scoped() -> None:
    # Static precondition (passes today): RPG fixtures are fiction/analogy, not real-world evidence,
    # and live in their own scope — so any later confusion is a runtime failure, not a data artifact.
    rpg = load_group("rpg_worldbuilding")
    assert rpg, "expected RPG fixtures"
    for doc in rpg:
        assert doc.meta["sphere"] == "rpg"
        assert doc.meta["scope_id"] == "scope:rpg/worldbuilding"
        assert doc.meta["source_role"] in {"fictional_simulation", "rpg_rule"}
        # Fiction may be analogy/inspiration only — never real-world evidence.
        assert doc.meta["evidence_role"] in {"analogy", "inspiration"}


def test_rpg_not_confused_with_software() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: rpg_not_confused_with_software
    # A naive embedding search would rank Aethelgard's 'state machine' next to Project Alpha's;
    # correct behavior needs the architecture (scope prefilter before rank), not similarity. Enforced
    # in the live app path: scope/policy eligibility partitions the store before scoring.
    # A software-flavored query in a work scope must not admit RPG fiction as evidence.
    result = rca.retrieve(query="state machine authority rules", active_scope_id="scope:work/project-alpha")
    assert result.scope_policy_prefiltered is True
    for candidate in result.candidate_items:
        assert candidate.metadata_bundle.scope_id != "scope:rpg/worldbuilding" or (
            candidate.evidence_role_in_context in {"analogy", "inspiration"}
        )
