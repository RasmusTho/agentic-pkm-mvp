"""#5707: the legacy ``app.search`` hybrid exports adapt the canonical retrieval path.

``app.search.hybrid_search`` / ``app.search.search_hybrid`` used to run an independent
full-text-first lookup with a vector fallback. They are now compatibility adapters over
``app.retrieval.hybrid.hybrid_search``: canonical ranking, scope filtering, and durable-cache
freshness, projected onto the legacy ``object_id`` / ``score`` / ``payload`` result shape.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

import app.search as legacy_search
from app.components.embeddings import EmbeddingIdentity
from app.retrieval import hybrid
from app.search import service as legacy_service
from app.stores import get_vector_index, reset_store_backends

_DIM = 8
_LEGACY_ENTRYPOINTS = [
    pytest.param(legacy_search.hybrid_search, id="app.search.hybrid_search"),
    pytest.param(legacy_search.search_hybrid, id="app.search.search_hybrid"),
]


@pytest.fixture(autouse=True)
def _isolate_retrieval(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("EMBED_DIM", str(_DIM))
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)
    reset_store_backends()
    snapshot = list(hybrid.get_store().all())
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    yield
    reset_store_backends()
    hybrid.get_store().set_documents(
        [
            {
                "doc_id": d.doc_id,
                "text": d.text,
                "language": d.language,
                "source_ref": d.source_ref,
                "payload": d.payload,
                "embedding": d.embedding,
            }
            for d in snapshot
        ]
    )
    hybrid.reset_durable_rebuild_state()


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (_DIM - len(head))


def _upsert(oid: UUID, title: str, text: str, embedding: list[float]) -> None:
    identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=_DIM, normalize=False)
    get_vector_index().upsert(
        object_id=oid,
        kind="note",
        source_ref=f"unit-test://{title}",
        payload={"title": title, "text": text, "content": text},
        embedding=embedding,
        model=identity.model,
        identity=identity,
    )


def _shape(results: list) -> list[tuple[str, float, dict]]:
    return [(str(r.object_id), r.score, dict(r.payload)) for r in results]


def _canonical_shape(results: list[dict]) -> list[tuple[str, float, dict]]:
    return [(hit["doc_id"], hit["score"], dict(hit["payload"])) for hit in results]


def test_legacy_exports_delegate_to_canonical_hybrid(monkeypatch: pytest.MonkeyPatch) -> None:
    assert legacy_search.hybrid_search is legacy_service.hybrid_search
    assert legacy_search.search_hybrid is legacy_service.search_hybrid

    def _forbidden(*_a, **_k):
        raise AssertionError("legacy adapter must not use the independent full-text/vector branch")

    monkeypatch.setattr(legacy_service, "search_full_text", _forbidden)
    monkeypatch.setattr(legacy_service, "vector_search", _forbidden)

    calls: list[tuple[str, dict]] = []
    payload = {"title": "Canonical"}

    def _spy(query: str, **kwargs):
        calls.append((query, kwargs))
        return [{"doc_id": "doc-1", "id": "doc-1", "score": 0.75, "payload": payload}]

    monkeypatch.setattr(hybrid, "hybrid_search", _spy)

    qvec = _vec(0.0, 1.0)
    for entrypoint in (legacy_search.hybrid_search, legacy_search.search_hybrid):
        calls.clear()
        results = entrypoint("alpha", qvec, k=3)
        assert calls == [("alpha", {"k": 3, "query_vector": qvec})]
        assert _shape(results) == [("doc-1", 0.75, payload)]


@pytest.mark.parametrize("entrypoint", _LEGACY_ENTRYPOINTS)
def test_legacy_results_preserve_shape_and_canonical_ranking(entrypoint) -> None:
    hybrid.get_store().set_documents(
        [
            {
                "doc_id": "lexical",
                "text": "alpha alpha alpha lexical winner",
                "payload": {"title": "Lexical"},
                "embedding": _vec(1.0, 0.0),
            },
            {
                "doc_id": "semantic",
                "text": "unrelated words about oceans",
                "payload": {"title": "Semantic"},
                "embedding": _vec(0.0, 1.0),
            },
            {
                "doc_id": "mixed",
                "text": "alpha mixed note",
                "payload": {"title": "Mixed"},
                "embedding": _vec(0.5, 0.5),
            },
        ]
    )
    qvec = _vec(0.0, 1.0)

    canonical = hybrid.hybrid_search("alpha", k=3, query_vector=qvec)
    legacy = entrypoint("alpha", qvec, k=3)

    assert len(canonical) == 3
    assert _shape(legacy) == _canonical_shape(canonical)
    for result in legacy:
        assert isinstance(result.score, float)
        assert isinstance(result.payload, dict)

    assert _shape(entrypoint("alpha", qvec, k=1)) == _canonical_shape(canonical[:1])


@pytest.mark.parametrize("entrypoint", _LEGACY_ENTRYPOINTS)
def test_legacy_entrypoint_observes_canonical_cache_refresh(entrypoint) -> None:
    _upsert(uuid4(), "Alpha", "alpha retrieval content about mountains", _vec(1.0, 0.0))
    _upsert(uuid4(), "Beta", "beta retrieval content about oceans", _vec(0.0, 1.0))
    hybrid.rebuild_from_durable_index()

    query, qvec = "gamma retrieval glaciers", _vec(0.0, 0.0, 1.0)
    warm = entrypoint(query, qvec, k=5)
    assert _shape(warm) == _canonical_shape(hybrid.hybrid_search(query, k=5, query_vector=qvec))

    # Durable-index generation change after warm: visible through the legacy adapter
    # via the canonical generation check, without a restart.
    new_id = uuid4()
    _upsert(new_id, "Gamma", "gamma retrieval content about glaciers", _vec(0.0, 0.0, 1.0))
    hybrid._LAST_GENERATION_CHECK_MONOTONIC = 0.0
    refreshed = entrypoint(query, qvec, k=5)
    assert refreshed[0].object_id == str(new_id)
    assert _shape(refreshed) == _canonical_shape(hybrid.hybrid_search(query, k=5, query_vector=qvec))

    # Cold-cache rebuild (process restart): the same visible results through both entrypoints.
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    hybrid.rebuild_from_durable_index()
    cold = entrypoint(query, qvec, k=5)
    assert _shape(cold) == _shape(refreshed)
    assert _shape(cold) == _canonical_shape(hybrid.hybrid_search(query, k=5, query_vector=qvec))
