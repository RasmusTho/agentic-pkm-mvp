"""Retrieval-spine invariants (Track H).

- retrieval_serves_durable_truth_fresh (G1res-1, #2981): after a durable
  upsert/purge commits, retrieval reflects it within the declared freshness
  bound (one generation check, bounded by the >=1s min-check interval)
  without a process restart or explicit force=True rebuild. Extends the
  KERNEL-05 cache-through contract (docs/RUNTIME_CORRECTNESS_KERNEL/
  RETRIEVAL_READS_DURABLE_INDEX.md); changes only WHEN a rebuild happens,
  never what is eligible.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.retrieval import hybrid
from app.stores import get_vector_index, reset_store_backends


@pytest.fixture(autouse=True)
def _isolate_stores(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    yield
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()


def _upsert_doc(oid: UUID, title: str, text: str) -> None:
    identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=8, normalize=False)
    get_vector_index().upsert(
        object_id=oid,
        kind="note",
        source_ref=f"unit-test://{title}",
        payload={"title": title, "text": text, "content": text},
        embedding=[0.1] * 8,
        model=identity.model,
        identity=identity,
    )


def _force_generation_check_due() -> None:
    """Make the next serving-path access due for a generation check without
    weakening the mandatory >=1s production min-check interval."""
    hybrid._LAST_GENERATION_CHECK_MONOTONIC = 0.0


def test_retrieval_serves_durable_truth_fresh() -> None:
    """Invariant: retrieval serves durable truth fresh — an upsert AND a purge
    committed after process warm are both reflected within the freshness
    bound, with no restart and no force=True."""
    kept = uuid4()
    purged = uuid4()
    _upsert_doc(kept, "Kept note", "kept retrieval content about mountains")
    _upsert_doc(purged, "Purged note", "purged retrieval content about oceans")
    hybrid.rebuild_from_durable_index()

    warm_ids = {hit["doc_id"] for hit in hybrid.hybrid_search("retrieval content", k=10)}
    assert {str(kept), str(purged)} <= warm_ids

    # Durable upsert after warm -> visible without restart.
    fresh = uuid4()
    _upsert_doc(fresh, "Fresh note", "fresh retrieval content about glaciers")
    _force_generation_check_due()
    ids = {hit["doc_id"] for hit in hybrid.hybrid_search("fresh retrieval glaciers", k=10)}
    assert str(fresh) in ids, (
        "retrieval_serves_durable_truth_fresh violated: post-warm durable "
        "upsert not visible without restart"
    )

    # Durable purge after warm -> invisible without restart.
    assert get_vector_index().purge_vectors(purged, view="note") == 1
    _force_generation_check_due()
    ids = {hit["doc_id"] for hit in hybrid.hybrid_search("retrieval content", k=10)}
    assert str(purged) not in ids, (
        "retrieval_serves_durable_truth_fresh violated: post-warm durable "
        "purge still served after the freshness bound"
    )
    assert str(kept) in ids
