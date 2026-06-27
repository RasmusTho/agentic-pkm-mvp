"""Eval skeleton: private programming notes do not leak into work results.

Invariant registry: docs/testing/invariant-tests.md :: private_not_in_work_results
Issues: #2550 (registry), #2551 (corpus), #2552 (skeletons).

The runtime skeleton xfails *only* on the missing runtime import (require_future_runtime).
"""

from __future__ import annotations

from tests.evals._helpers import load_group, require_future_runtime


def test_private_fixtures_denied_by_default() -> None:
    # Static precondition (passes today): private fixtures are private-scoped and only background
    # standing — useful enough to tempt leakage, but denied into work by default.
    private = load_group("private_programming")
    assert private, "expected private fixtures"
    for doc in private:
        assert doc.meta["sphere"] == "private"
        assert doc.meta["scope_id"] == "scope:private/programming"
        assert doc.meta["source_role"] == "private_note"
        assert doc.meta["sensitivity"] == "private"
        assert doc.meta["evidence_role"] != "evidence"


def test_private_not_in_work_results() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: private_not_in_work_results
    # Private -> work is denied by default; crossing requires governed promotion/redaction/
    # CrossScopeFlow. Future vertical slice: retrieval prefilter -> GOV cross-scope evaluation.
    rca = require_future_runtime(
        "retrieval",
        "Runtime retrieval/cross-scope enforcement not implemented yet; protects "
        "private_not_in_work_results (#2550) over the corpus (#2551).",
    )
    result = rca.retrieve(query="debugging a stateful system", active_scope_id="scope:work/project-alpha")
    leaked = [c for c in result.candidate_items if c.metadata_bundle.scope_id == "scope:private/programming"]
    assert leaked == [], "private material must not appear in a work result without a governed flow"
