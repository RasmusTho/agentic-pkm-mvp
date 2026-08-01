"""Conditional rerank gate (ADR-0059 D3 step 5, #3407): `rerank="conditional"` in
`app/retrieval/hook_adapter.py::maybe_rerank`.

- test_margin_gate_skips_and_invokes: when the top BM25 result dominates by at least
  `rerank_score_margin`, rerank is skipped (items pass through unchanged); when BM25 scores are
  close, rerank is invoked (order changes per the configured provider).
- test_containment_enforced_when_conditional_rerank_runs: end-to-end through
  `scoped_hybrid_search` with `rerank="conditional"` actually invoking the hook (ambiguous BM25),
  `_contain_rerank` still rejects a misbehaving rerank hook — same invariant already covered for
  `"always"` by `test_scope_prefilter_before_rank.py`, exercised here under the new gate.
- test_conditional_stays_dark_by_default: `rerank` stays `"off"` with no override anywhere.
"""

from __future__ import annotations

import pytest

from app.retrieval.hook_adapter import maybe_rerank
from app.retrieval.hybrid import get_store, scoped_hybrid_search
from app.retrieval.tuning import get_retrieval_tuning, reset_retrieval_tuning_cache

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "RETRIEVAL_RERANK",
        "RETRIEVAL_RERANK_SCORE_MARGIN",
        "RERANK_ENABLE",
        "RERANK_PROVIDER",
        "RERANK_TOP_K",
        "ASK_DOMAIN_SCOPE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    reset_retrieval_tuning_cache()
    get_store().set_documents([])
    yield
    get_store().set_documents([])
    reset_retrieval_tuning_cache()


def test_conditional_stays_dark_by_default() -> None:
    assert get_retrieval_tuning().rerank == "off"


def test_margin_gate_skips_and_invokes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_RERANK", "conditional")
    reset_retrieval_tuning_cache()
    assert get_retrieval_tuning().rerank == "conditional"

    calls: list[list[dict]] = []

    def _spy_apply_optional_rerank(query: str, items: list[dict]) -> list[dict]:
        calls.append(list(items))
        return list(reversed(items))

    # Spy on the "actually rerank" step so the assertion is about the gate's own invoke/skip
    # decision, not about a specific rerank provider's scoring quirks.
    monkeypatch.setattr(
        "app.retrieval.hook_adapter.apply_optional_rerank", _spy_apply_optional_rerank
    )

    # Dominant top-1: "dominant" shares every query token repeatedly and uniquely; the others share
    # none. Normalized-BM25 top1-vs-top2 gap is at/near 1.0 -> well over the default 0.2 threshold
    # -> rerank is skipped: the hook is never invoked and items pass through unchanged.
    dominant_items = [
        {"id": "dominant", "text": "unique unique unique unique term", "score": 0.9},
        {"id": "filler-a", "text": "completely unrelated words here", "score": 0.5},
        {"id": "filler-b", "text": "another unrelated passage entirely", "score": 0.4},
    ]
    out = maybe_rerank("unique term", dominant_items)
    assert calls == []
    assert out == dominant_items

    # Ambiguous top-1/top-2: two candidates match the query's terms almost identically (near-tied
    # normalized BM25, margin ~= 0.0), well under the default 0.2 threshold -> the gate invokes the
    # hook (spy called exactly once) and the output reflects the hook's transform.
    ambiguous_items = [
        {"id": "a", "text": "alpha beta gamma filler one text", "score": 0.6},
        {"id": "b", "text": "alpha beta gamma filler two words", "score": 0.5},
        {"id": "c", "text": "totally unrelated content over here", "score": 0.4},
    ]
    out2 = maybe_rerank("alpha beta gamma", ambiguous_items)
    assert len(calls) == 1
    assert calls[0] == ambiguous_items
    assert [o["id"] for o in out2] == ["c", "b", "a"]


def test_containment_enforced_when_conditional_rerank_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_contain_rerank` (app/retrieval/hybrid.py) still rejects a rerank hook that smuggles a doc
    back in when `rerank='conditional'` actually invokes the hook — exercised end-to-end through
    `scoped_hybrid_search` with real gating logic (an ambiguous/near-tied corpus so the margin gate
    does not skip), same invariant `test_scope_prefilter_before_rank.py` covers for `"always"`."""
    get_store().set_documents(
        [
            {"doc_id": "in-scope-a", "text": "alpha beta gamma one", "payload": {}},
            {"doc_id": "in-scope-b", "text": "alpha beta gamma two", "payload": {}},
        ]
    )
    monkeypatch.setenv("RETRIEVAL_RERANK", "conditional")
    reset_retrieval_tuning_cache()

    def _bad_apply_optional_rerank(query, items):
        return items + [{"doc_id": "intruder", "id": "intruder", "text": "x", "score": 1.0}]

    # Patch only the "actually rerank" step; the real conditional gate (hook_adapter.maybe_rerank)
    # still decides whether to call it, proving containment holds along the real gated path.
    monkeypatch.setattr(
        "app.retrieval.hook_adapter.apply_optional_rerank", _bad_apply_optional_rerank
    )
    with pytest.raises(AssertionError, match="rerank introduced doc_ids"):
        scoped_hybrid_search("alpha beta gamma", k=5)


def test_conditional_gate_two_result_unique_match_does_not_collapse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rank-BM25 has a zero-IDF degeneracy on a two-document candidate set;
    the exact lexical result must still be protected from reranking."""
    monkeypatch.setenv("RETRIEVAL_RERANK", "conditional")
    reset_retrieval_tuning_cache()
    calls: list[list[dict]] = []
    monkeypatch.setattr(
        "app.retrieval.hook_adapter.apply_optional_rerank",
        lambda _query, items: calls.append(list(items)) or list(reversed(items)),
    )
    items = [
        {"id": "exact", "text": "alpha beta exact document", "score": 0.9},
        {"id": "other", "text": "unrelated gardening note", "score": 0.5},
    ]

    assert maybe_rerank("alpha beta", items) == items
    assert calls == []


def test_conditional_gate_reranks_when_lower_coverage_item_is_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A coverage fallback only establishes dominance for the ranked top result."""
    monkeypatch.setenv("RETRIEVAL_RERANK", "conditional")
    reset_retrieval_tuning_cache()
    calls: list[list[dict]] = []
    monkeypatch.setattr(
        "app.retrieval.hook_adapter.apply_optional_rerank",
        lambda _query, items: calls.append(list(items)) or list(reversed(items)),
    )
    items = [
        {"id": "weak", "text": "unrelated gardening note", "score": 0.9},
        {"id": "exact", "text": "alpha beta exact document", "score": 0.5},
    ]

    assert [item["id"] for item in maybe_rerank("alpha beta", items)] == ["exact", "weak"]
    assert calls == [items]
