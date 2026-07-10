"""ADR-0059 D1 (#3405) — durable index as vector read authority.

Covers step 2 of the ADR-0059 migration: ``rebuild_from_durable_index()`` passes each
durable row's stored ``embedding`` through to the in-process cache, and
``MemoryHybridStore`` never re-embeds a document that already carries a preloaded
vector. Document embedding on the serving path is removed; the lazy-embed path stays
only as an explicit fallback for documents that reach the cache with no stored vector
(test-seeded corpora via ``set_documents()``/``add_document()``, and a fail-safe
per-row fallback for a durable row whose stored vector is unexpectedly empty).

Runs entirely under ``not pg`` via the memory backend (``STORE_BACKEND=memory``),
matching the sibling ``tests/retrieval/test_retrieval_durable_equivalence.py`` and
``tests/retrieval/test_hybrid_generation_identity.py``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.components.retrieval import embed_docs
from app.retrieval import hybrid
from app.stores import get_vector_index, reset_store_backends

_SEED_TEXTS = [
    ("Alpha note", "alpha retrieval content about mountains and glaciers"),
    ("Beta note", "beta retrieval content about oceans and currents"),
    ("Gamma note", "gamma retrieval content about deserts and dunes"),
]


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


def _seed_durable_index_with_real_vectors() -> list[UUID]:
    """Seed the durable index the way ingest does: each row's stored vector is
    computed by the same (deterministic, mock-provider) embedding client the
    serving path would otherwise fall back to lazy-embedding with. Deterministic
    mock embeddings make write-time and read-time embedding of the SAME text
    byte-identical, which is what turns the ranking-parity test below into a
    meaningful golden comparison rather than a tautology.
    """
    texts = [text for _title, text in _SEED_TEXTS]
    vectors, identity = embed_docs(texts)
    idx = get_vector_index()
    ids: list[UUID] = []
    for (title, text), vector in zip(_SEED_TEXTS, vectors):
        oid = uuid4()
        idx.upsert(
            object_id=oid,
            kind="note",
            source_ref=f"unit-test://{title}",
            payload={"title": title, "text": text, "content": text},
            embedding=vector,
            model=identity.model,
            identity=identity,
        )
        ids.append(oid)
    return ids


def test_serving_path_never_embeds_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: after a durable-index rebuild, the cache scores with the stored
    vectors — zero ``embed_docs`` calls occur on the serving path (rebuild +
    query), asserted via a patched embed client that fails the test if called.
    """
    _seed_durable_index_with_real_vectors()

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError(
            "embed_docs must not be called on the serving path when durable "
            "rows already carry stored vectors (ADR-0059 D1)"
        )

    monkeypatch.setattr(hybrid, "embed_docs", _fail_if_called)

    loaded = hybrid.rebuild_from_durable_index()
    assert loaded == len(_SEED_TEXTS)

    hits = hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert hits, "expected at least one hit from the seeded durable index"


def test_ranking_parity_with_ingest_written_vectors() -> None:
    """AC2: ranking parity — for a corpus ingested normally (vectors written at
    write time), result ordering and scores are identical to the lazy-embed
    path over the SAME texts (golden comparison at the ``hybrid_search``
    layer). Deterministic mock embeddings make write-time and read-time
    embedding of identical text byte-identical, so this only passes if the
    stored-vector path is wired correctly end to end.
    """
    _seed_durable_index_with_real_vectors()

    hybrid.rebuild_from_durable_index()
    stored_vector_hits = hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert stored_vector_hits, "expected hits from the stored-vector-backed cache"

    # Baseline: the SAME texts/payloads, reseeded WITHOUT a preloaded vector so
    # the store falls back to its lazy per-document embed path (the shape of
    # every rebuild before ADR-0059 D1). Detach from durable-rebuild state
    # first so the freshness check cannot repopulate the store out from under
    # this manual seed.
    docs_snapshot = [
        {
            "doc_id": doc.doc_id,
            "text": doc.text,
            "language": doc.language,
            "source_ref": doc.source_ref,
            "payload": doc.payload,
        }
        for doc in hybrid.get_store().all()
    ]
    hybrid.reset_durable_rebuild_state()
    hybrid.get_store().set_documents(docs_snapshot)
    lazy_embed_hits = hybrid.hybrid_search("alpha retrieval mountains", k=5)

    assert [h["doc_id"] for h in stored_vector_hits] == [
        h["doc_id"] for h in lazy_embed_hits
    ]
    assert [h["score"] for h in stored_vector_hits] == pytest.approx(
        [h["score"] for h in lazy_embed_hits]
    )


def test_rebuild_works_with_embedder_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: a rebuild succeeds with the embedding backend unavailable (embed
    client raising), proving the read path has no embedding dependency once
    durable rows carry stored vectors.
    """
    _seed_durable_index_with_real_vectors()

    def _embedder_down(*_args, **_kwargs):
        raise RuntimeError("embedding backend unavailable (simulated)")

    monkeypatch.setattr(hybrid, "embed_docs", _embedder_down)

    loaded = hybrid.rebuild_from_durable_index()
    assert loaded == len(_SEED_TEXTS)

    # Scoring against the durable-sourced vectors must also succeed without
    # ever reaching the (down) document-embedding client.
    hits = hybrid.hybrid_search("beta retrieval oceans", k=5)
    assert hits


def test_vectorless_seed_lazy_embed_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: a test-seeded corpus with no stored vectors still works via the
    explicit lazy-embed fallback. Never reachable from
    ``rebuild_from_durable_index()`` (covered by the tests above); reserved
    for ``set_documents()``/``add_document()`` callers that omit ``embedding``.
    """
    real_embed_docs = hybrid.embed_docs
    calls: list[int] = []

    def _counting_embed_docs(texts, **kwargs):
        materialized = list(texts)
        calls.append(len(materialized))
        return real_embed_docs(materialized, **kwargs)

    monkeypatch.setattr(hybrid, "embed_docs", _counting_embed_docs)

    store = hybrid.get_store()
    store.set_documents(
        [
            {"doc_id": "v1", "text": "vectorless alpha retrieval content"},
            {"doc_id": "v2", "text": "vectorless beta retrieval content"},
        ]
    )

    hits = hybrid.hybrid_search("vectorless alpha", k=5)
    assert hits
    assert "v1" in {h["doc_id"] for h in hits}
    assert calls == [2], (
        "expected exactly one lazy-embed batch call covering both "
        "vector-less documents, proving the fallback engaged"
    )


def test_dim_mismatched_preloaded_vector_fails_loud() -> None:
    """Careful-detail guard (ADR-0059 D1): a dim-mismatched preloaded vector
    fails loud with a clear message instead of being silently padded or
    dropped — mirrors the existing ``embedding_scores`` dim-mismatch guard.
    """
    store = hybrid.get_store()
    store.set_documents(
        [
            {"doc_id": "d1", "text": "alpha content", "embedding": [0.1, 0.2, 0.3]},
            {"doc_id": "d2", "text": "beta content", "embedding": [0.1, 0.2]},
        ]
    )
    with pytest.raises(ValueError, match="embedding dim mismatch"):
        store.bm25_scores(["alpha"])
