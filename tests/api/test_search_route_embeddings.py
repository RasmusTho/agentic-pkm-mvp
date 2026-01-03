from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app
from app.components.embeddings import EmbeddingIdentity


class _FakeCursor:
    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def execute(self, *_args, **_kwargs) -> None:  # pragma: no cover - fake cursor
        return None

    def fetchall(self) -> list[tuple[str, str, list[float]]]:
        return [
            ("uuid-1", "Hello", [0.1, 0.2, 0.3]),
        ]


class _FakeConnection:
    def __init__(self) -> None:
        self._cursor = _FakeCursor()

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:  # pragma: no cover - fake connection
        return self._cursor

    def rollback(self) -> None:  # pragma: no cover - fake connection
        return None


def test_search_route_uses_canonical_embedding_entrypoint(monkeypatch) -> None:
    identity = EmbeddingIdentity(provider="mock", model="mock-model", dim=3, normalize=True)
    seen: dict[str, str] = {}

    def fake_embed_query(text: str, profile: str = "default"):
        seen["text"] = text
        seen["profile"] = profile
        return [0.1, 0.2, 0.3], identity

    monkeypatch.setattr("app.api.routes.search.embed_query", fake_embed_query)
    monkeypatch.setattr(
        "app.api.routes.search.psycopg.connect",
        lambda *args, **kwargs: _FakeConnection(),
    )

    client = TestClient(app)
    response = client.get("/search", params={"q": "hello"})

    assert response.status_code == 200
    payload = response.json()
    assert "results" in payload
    assert payload["results"], "Expected at least one result"
    assert payload["results"][0]["uuid"] == "uuid-1"
    assert seen.get("text") == "hello"
