"""#2989: GET /search reads the canonical retrieval substrate.

`/search` previously joined the permanently-empty legacy `objects_embeddings`
table, swallowed every failure via a bare `except Exception`, and silently
fell back to query-independent `_recent_objects()` reads from the legacy
`objects` table. This asserts the route now shares the same durable-index-
backed capability as `/api/ask` (`app.retrieval.capability.retrieve` /
`app.retrieval.hybrid.scoped_hybrid_search`), that results vary with the
query, and that retrieval failure surfaces as an error rather than a filler
response.
"""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.routes.search as search_route
from app.api.app import app
from app.components.retrieval import embed_query
from app.retrieval import hybrid
from app.stores import get_vector_index, reset_store_backends

REPO_ROOT = Path(__file__).resolve().parents[2]
SEARCH_ROUTE_PATH = REPO_ROOT / "app" / "api" / "routes" / "search.py"


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


def _seed_durable_index() -> list[UUID]:
    idx = get_vector_index()
    ids: list[UUID] = []
    seeds = [
        ("Alpha note", "alpha retrieval content about mountains"),
        ("Beta note", "beta retrieval content about oceans"),
    ]
    for title, text in seeds:
        embedding, identity = embed_query(text)
        oid = uuid4()
        idx.upsert(
            object_id=oid,
            kind="note",
            source_ref=f"unit-test://{title}",
            payload={"title": title, "text": text, "content": text},
            embedding=embedding,
            model=identity.model,
            identity=identity,
        )
        ids.append(oid)
    return ids


def test_search_reads_durable_index() -> None:
    """/search results vary with the query and surface freshly indexed notes,
    from the same durable substrate /api/ask retrieval reads."""
    _seed_durable_index()
    hybrid.rebuild_from_durable_index()

    client = TestClient(app)

    alpha_response = client.get("/search", params={"q": "alpha mountains"})
    assert alpha_response.status_code == 200
    alpha_results = alpha_response.json()["results"]
    alpha_titles = [item["title"] for item in alpha_results]
    assert "Alpha note" in alpha_titles

    beta_response = client.get("/search", params={"q": "beta oceans"})
    assert beta_response.status_code == 200
    beta_results = beta_response.json()["results"]
    beta_titles = [item["title"] for item in beta_results]
    assert "Beta note" in beta_titles

    for item in alpha_results:
        assert set(item.keys()) == {"uuid", "title"}

    # Query-dependence: the legacy bug always returned the identical
    # query-independent `_recent_objects()` ordering regardless of `q`.
    # Prove the route forwards `q` straight through to the canonical
    # retrieval capability (rather than ignoring it) by observing that the
    # capability is invoked once per distinct query with that query's own
    # text, and that the resulting payload changes as `request.query` changes.
    from app.retrieval.capability import RetrievalHit, RetrievalResponse

    seen_queries: list[str] = []
    real_retrieve = search_route.retrieve

    def spying_retrieve(request):
        seen_queries.append(request.query)
        hit = RetrievalHit(
            object_id=f"doc-for::{request.query}",
            doc_id=f"doc-for::{request.query}",
            text="irrelevant",
            score=1.0,
            snippet=None,
            source_ref=None,
            payload={"title": f"Title for {request.query}"},
        )
        return RetrievalResponse(query=request.query, hits=[hit])

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(search_route, "retrieve", spying_retrieve)
        first = client.get("/search", params={"q": "alpha mountains"})
        second = client.get("/search", params={"q": "beta oceans"})
    finally:
        monkeypatch.undo()

    assert seen_queries == ["alpha mountains", "beta oceans"]
    assert first.json()["results"] != second.json()["results"]
    assert first.json()["results"][0]["title"] == "Title for alpha mountains"
    assert second.json()["results"][0]["title"] == "Title for beta oceans"
    assert real_retrieve is search_route.retrieve


def test_search_no_legacy_tables_no_silent_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """No code path in app/api/routes/search.py reads objects/objects_embeddings,
    and no bare-except fallback returns query-independent results on failure."""
    source = SEARCH_ROUTE_PATH.read_text(encoding="utf-8")

    assert "objects_embeddings" not in source
    assert "_recent_objects" not in source

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            raise AssertionError(
                "app/api/routes/search.py must not contain a bare `except:` clause"
            )
        if (
            isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "Exception"
        ):
            raise AssertionError(
                "app/api/routes/search.py must not swallow retrieval failures via "
                "`except Exception` — failures must surface as errors"
            )

    # Behavioral: a retrieval failure must surface as an HTTP error, not a
    # filler/fallback payload.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("retrieval backend unavailable")

    monkeypatch.setattr("app.retrieval.capability.scoped_hybrid_search", _boom)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/search", params={"q": "anything"})
    assert response.status_code >= 500
