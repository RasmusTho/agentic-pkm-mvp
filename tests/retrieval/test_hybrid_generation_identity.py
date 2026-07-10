"""ADR-0059 D2 (#3403) — identity-aware generation() invalidates the warm
retrieval cache at the hybrid serving layer.

Covers issue #3403 (first pickup under parent hub #3402): a repin (the
stored embedding identity changes with ZERO durable row rewrite — the same
shape as an ADR-0052 repin) committed after the process warm must still
force a serving-path cache rebuild, because ``VectorIndex.generation()``
tokens now include an identity-hash component (``app/stores/base.py::
identity_generation_component``). ``_revalidate_cache_generation()`` itself
is unchanged and must stay unchanged — it only ever compares the token as an
opaque string; this test proves the token change actually propagates through
it end-to-end. Runs under `not pg` via the memory backend; the sibling
pg-marked test (``tests/stores/test_vector_generation_identity.py``) covers
the same shape against the real ``vector_index_meta`` table.
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


def _seed(identity: EmbeddingIdentity) -> UUID:
    oid = uuid4()
    text = "repin retrieval content about glaciers"
    get_vector_index().upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test://repin",
        payload={"title": "Repin note", "text": text, "content": text},
        embedding=[0.1] * 4,
        model=identity.model,
        identity=identity,
    )
    return oid


def _force_generation_check_due() -> None:
    hybrid._LAST_GENERATION_CHECK_MONOTONIC = 0.0


def test_repin_invalidates_warm_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repin (embedding identity changes, no row rewritten) committed after
    process warm still forces a serving-path cache rebuild — proving the
    identity-aware generation() token, not just row-level upsert/purge,
    drives revalidation (ADR-0059 D2)."""
    primary = EmbeddingIdentity(provider="mock", model="embed-primary", dim=4, normalize=False)
    _seed(primary)

    hybrid.rebuild_from_durable_index()
    generation_before = hybrid._REBUILD_GENERATION
    assert hybrid.hybrid_search("repin retrieval glaciers", k=5), (
        "expected the seeded doc to be retrievable after the initial warm"
    )

    index = get_vector_index()
    # Simulate an ADR-0052-shaped repin directly on the store identity: the
    # identity changes but NO upsert/purge touches any row — the same shape
    # the pg-marked sibling test exercises via a direct UPDATE of
    # vector_index_meta.identity_json.
    repinned = EmbeddingIdentity(provider="mock", model="embed-repinned", dim=4, normalize=False)
    index._identity = repinned  # type: ignore[attr-defined]

    generation_after_repin = index.generation()
    assert generation_after_repin != generation_before, (
        "generation() must change from the identity repin alone, with no row "
        "rewrite (ADR-0059 D2) — this is the precondition the rest of this "
        "test exercises at the hybrid serving layer"
    )

    calls = {"n": 0}
    real_rebuild = hybrid.rebuild_from_durable_index

    def counting_rebuild(*args, **kwargs):
        calls["n"] += 1
        return real_rebuild(*args, **kwargs)

    monkeypatch.setattr(hybrid, "rebuild_from_durable_index", counting_rebuild)

    _force_generation_check_due()
    hits = hybrid.hybrid_search("repin retrieval glaciers", k=5)

    assert calls["n"] == 1, (
        "a generation-token mismatch caused solely by an identity repin must "
        "still force exactly one cache rebuild via _revalidate_cache_generation() "
        "(_revalidate_cache_generation itself stays unchanged; it only compares "
        "the now identity-aware token as an opaque string)"
    )
    assert hits, "the repinned cache must still serve the (re-embedded-identity) document"
    assert hybrid._REBUILD_GENERATION == generation_after_repin, (
        "after the forced rebuild, the cache's captured generation must match "
        "the post-repin durable generation token"
    )
