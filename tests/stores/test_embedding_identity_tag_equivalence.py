from __future__ import annotations

import json

from app.components.embeddings import EmbeddingIdentity
from app.stores import pg


def test_implicit_latest_tag_matches_explicit() -> None:
    bare = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    tagged = EmbeddingIdentity(provider="ollama", model="nomic-embed-text:latest", dim=768)
    assert bare.model == "nomic-embed-text:latest"
    assert bare == tagged


def test_distinct_model_still_mismatches() -> None:
    a = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    b = EmbeddingIdentity(provider="ollama", model="mxbai-embed-large", dim=768)
    assert a != b


def test_non_ollama_provider_tag_untouched() -> None:
    ident = EmbeddingIdentity(provider="openai", model="text-embedding-3-small", dim=1536)
    assert ident.model == "text-embedding-3-small"


class _FakeCursor:
    def __init__(self, stored_json: str | None) -> None:
        self._stored_json = stored_json
        self.executed: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> dict[str, str] | None:
        if self._stored_json is None:
            return None
        return {"identity_json": self._stored_json}


def test_rebuild_then_health_consistent() -> None:
    # Index built with the bare ollama tag; health resolves the explicit `:latest`.
    stored_json = json.dumps(
        {"provider": "ollama", "model": "nomic-embed-text", "dim": 768, "normalize": True}
    )
    cur = _FakeCursor(stored_json)
    requested = EmbeddingIdentity(provider="ollama", model="nomic-embed-text:latest", dim=768)
    resolved = pg._ensure_index_identity(cur, requested, allow_create=False)
    assert resolved.model == "nomic-embed-text:latest"
