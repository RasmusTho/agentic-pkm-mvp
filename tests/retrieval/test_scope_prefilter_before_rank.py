"""Scope prefilter precedes ranking in the live retrieval entrypoint (KERNEL-10, #2772).

Binds the spec ACs to the production entrypoint ``app.retrieval.hybrid.hybrid_search`` /
``scoped_hybrid_search``:

- ``test_prefilter_precedes_ranking`` — eligibility decides membership BEFORE scoring; ineligible
  material never enters the scored candidate set (AC1).
- ``test_denials_are_content_free`` — excluded-but-relevant material becomes a content-free denial,
  class + reason only, no body/scope/object identity (AC2).
- ``test_in_context_role_clamped`` — ``evidence_role_in_context`` never exceeds the intrinsic role
  (AC3).

Reference implementation for the invariant SHAPE: ``yggdrasil_runtime/retrieval.py`` (consumed, not
imported).
"""

from __future__ import annotations

import pytest

import app.retrieval.hybrid as hybrid
from app.retrieval.hybrid import (
    ScopeDenial,
    get_store,
    hybrid_search,
    scoped_hybrid_search,
)


@pytest.fixture(autouse=True)
def _mock_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield
    get_store().set_documents([])


def _seed_two_scopes() -> None:
    store = get_store()
    store.set_documents([])
    store.add_document(
        doc_id="work-1",
        text="stateful workflow engine event bus reconciliation",
        source_ref="work/arch.md",
        payload={"domain": "work"},
    )
    store.add_document(
        doc_id="rpg-1",
        # Deliberately shares vocabulary with the work doc so similarity alone cannot separate them.
        text="stateful workflow engine event bus reconciliation ritual",
        source_ref="rpg/arch.md",
        payload={"domain": "rpg"},
    )


def test_prefilter_precedes_ranking(monkeypatch) -> None:
    """Eligibility runs BEFORE scoring: ineligible docs never reach the scorer.

    Instrument the eligible-set ranker (``_rank_eligible``) to record exactly which docs it scores.
    Under an active work scope, the RPG doc must never be handed to the scorer — proving the
    prefilter partitions first, rather than scoring everything and masking afterward.
    """
    _seed_two_scopes()
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")

    scored_ids: list[list[str]] = []
    original = hybrid._rank_eligible

    def _spy(query, docs, eligible_idx, **kwargs):
        # Record exactly which docs the scorer was handed (the eligible partition).
        scored_ids.append([docs[i].doc_id for i in eligible_idx])
        return original(query, docs, eligible_idx, **kwargs)

    monkeypatch.setattr(hybrid, "_rank_eligible", _spy)

    results = hybrid_search("stateful workflow engine", k=5)

    # The scorer was invoked over the eligible partition ONLY — the ineligible RPG doc is absent
    # from the scored set (not merely dropped from the sorted output afterwards).
    assert scored_ids, "the eligible-set ranker must have been called"
    for scored in scored_ids:
        assert "rpg-1" not in scored, "ineligible material entered the scored candidate set"
        assert "work-1" in scored
    # And it never surfaces in the results.
    ids = {r["doc_id"] for r in results}
    assert "rpg-1" not in ids
    assert "work-1" in ids


def test_prefilter_does_not_let_ineligible_shift_normalization(monkeypatch) -> None:
    """Scoring/normalization runs over the eligible set only, so ineligible rows cannot shift the
    min/max normalization of eligible rows (the subtle correctness bug the prefilter closes)."""
    _seed_two_scopes()
    # Add a third, very-high-lexical-overlap ineligible doc that WOULD dominate normalization if it
    # entered the scored set.
    get_store().add_document(
        doc_id="rpg-2",
        text="stateful workflow engine event bus reconciliation " * 5,
        source_ref="rpg/big.md",
        payload={"domain": "rpg"},
    )
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    scoped = scoped_hybrid_search("stateful workflow engine", k=5)
    ids = {r["doc_id"] for r in scoped.results}
    assert ids == {"work-1"}, "only the in-scope doc is scored/ranked"


def test_denials_are_content_free(monkeypatch) -> None:
    """Excluded relevant material becomes a content-free denial (class + reason), never a body/id."""
    _seed_two_scopes()
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")

    scoped = scoped_hybrid_search("stateful workflow engine", k=5)

    assert scoped.scope_policy_prefiltered is True
    assert scoped.denials, "relevant out-of-scope material must be recorded as a denial, not dropped"
    for denial in scoped.denials:
        assert isinstance(denial, ScopeDenial)
        assert denial.denial_class == "cross_scope_no_flow"
        assert denial.reason
        payload = denial.to_dict()
        # Content-free: no object/scope identity, no body, no snippet, no per-doc count.
        blob = repr(payload).lower()
        for leaked in ("rpg", "rpg-1", "ritual", "scope:rpg", "work-1", "reconciliation"):
            assert leaked not in blob, f"denial leaked identifying content: {leaked!r}"
        assert set(payload).issubset(
            {"reason", "denial_class", "escalation_recommended", "required_flow_class", "audit_ref"}
        )
        # No count of denied docs anywhere.
        assert "count" not in payload


def test_denials_empty_when_no_relevant_excluded(monkeypatch) -> None:
    """No denial is fabricated when nothing relevant was excluded (query matches only in-scope)."""
    _seed_two_scopes()
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    # A query with a token that appears nowhere in the excluded RPG doc-specific vocabulary but does
    # in the shared vocab would still trip; use a token unique to no doc to get zero relevance.
    scoped = scoped_hybrid_search("zzzznomatchtoken", k=5)
    assert scoped.denials == ()


def test_in_context_role_clamped(monkeypatch) -> None:
    """``evidence_role_in_context`` never exceeds the intrinsic evidence role.

    A doc whose payload carries no evidence_role defaults to intrinsic ``background`` (never
    upgraded to ``evidence``); a doc whose payload explicitly carries ``evidence`` may surface as
    ``evidence``. In-context role is always ordinally <= intrinsic.
    """
    store = get_store()
    store.set_documents([])
    store.add_document(
        doc_id="bg-default",
        text="alpha beta gamma delta",
        payload={"domain": "work"},  # no evidence_role -> intrinsic background
    )
    store.add_document(
        doc_id="explicit-evidence",
        text="alpha beta gamma epsilon",
        payload={"domain": "work", "evidence_role": "evidence"},
    )
    store.add_document(
        doc_id="explicit-inspiration",
        text="alpha beta gamma zeta",
        payload={"domain": "work", "evidence_role": "inspiration"},
    )
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")

    results = {r["doc_id"]: r for r in hybrid_search("alpha beta gamma", k=5)}

    order = ("non_evidence", "inspiration", "analogy", "reference", "background", "evidence")
    intrinsic = {
        "bg-default": "background",
        "explicit-evidence": "evidence",
        "explicit-inspiration": "inspiration",
    }
    for doc_id, expected_intrinsic in intrinsic.items():
        assert doc_id in results
        in_ctx = results[doc_id]["evidence_role_in_context"]
        assert order.index(in_ctx) <= order.index(expected_intrinsic), (
            f"{doc_id}: in-context role {in_ctx!r} exceeds intrinsic {expected_intrinsic!r}"
        )
    # Never invented as evidence: the default-background doc must not surface as evidence.
    assert results["bg-default"]["evidence_role_in_context"] != "evidence"
    # Explicit-evidence may surface as evidence (payload carries intrinsic evidence).
    assert results["explicit-evidence"]["evidence_role_in_context"] == "evidence"


def test_rerank_never_reintroduces_excluded(monkeypatch) -> None:
    """The rerank hook may only reorder/drop within the admitted set — never reintroduce an
    excluded doc (AC1, second clause). A rerank that injects a foreign doc_id fails loud."""
    _seed_two_scopes()
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")

    def _bad_rerank(query, items):
        # Simulate a misbehaving hook that smuggles an out-of-scope doc back in.
        return items + [{"doc_id": "rpg-1", "id": "rpg-1", "text": "x", "score": 1.0}]

    monkeypatch.setattr(hybrid, "maybe_rerank", _bad_rerank)
    with pytest.raises(AssertionError, match="rerank introduced doc_ids"):
        scoped_hybrid_search("stateful workflow engine", k=5)
