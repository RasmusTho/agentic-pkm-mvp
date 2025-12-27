from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app


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


def test_search_route_uses_configured_embedding_client(monkeypatch) -> None:
    class _StubClient:
        def embed_text(self, text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    monkeypatch.setattr("app.api.routes.search.get_embedding_client", lambda: _StubClient())
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
