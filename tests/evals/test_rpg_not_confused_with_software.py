"""Eval skeleton: RPG/worldbuilding material is not confused with real-world software.

Invariant registry: docs/testing/invariant-tests.md :: rpg_not_confused_with_software
Issues: #2550 (registry), #2551 (corpus), #2552 (skeletons).

The runtime skeleton xfails *only* on the missing runtime import (require_future_runtime); the static
precondition passes today.
"""

from __future__ import annotations

from tests.evals._helpers import load_group, require_future_runtime


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
    # correct behavior needs the architecture (scope/source_role/evidence_role/CrossScopeFlow), not
    # similarity. Future vertical slice: retrieval prefilter -> RCA result.
    rca = require_future_runtime(
        "retrieval",
        "Runtime retrieval/scope discrimination not implemented yet; protects "
        "rpg_not_confused_with_software (#2550) over the corpus (#2551).",
    )
    # A software-flavored query in a work scope must not admit RPG fiction as evidence.
    result = rca.retrieve(query="state machine authority rules", active_scope_id="scope:work/project-alpha")
    for candidate in result.candidate_items:
        assert candidate.metadata_bundle.scope_id != "scope:rpg/worldbuilding" or (
            candidate.evidence_role_in_context in {"analogy", "inspiration"}
        )
