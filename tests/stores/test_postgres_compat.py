"""Compatibility-store guards for the legacy vault-root ingest adapter."""

from __future__ import annotations

from app.stores import postgres


class _CanonicalStore:
    def __init__(self) -> None:
        self.put_calls: list[tuple[object, dict]] = []

    def put(self, object_id, **kwargs) -> None:
        self.put_calls.append((object_id, kwargs))


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.calls.append((query, params))


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_pgobjects_upsert_keeps_only_minimal_legacy_fk_parent(monkeypatch) -> None:
    """The adapter delegates store writes and creates only the FK parent row."""
    canonical_store = _CanonicalStore()
    connection = _Connection()
    monkeypatch.setattr(postgres, "PgObjectStore", lambda: canonical_store)
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _dsn: connection)
    monkeypatch.setattr(postgres, "_dsn", lambda: "postgresql://test")

    result = postgres.PgObjects().upsert(
        id="9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        kind="note",
        payload={"text": "test"},
        source_ref="vault/note.md",
    )

    assert result == {"id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"}
    assert len(canonical_store.put_calls) == 1
    object_id, kwargs = canonical_store.put_calls[0]
    assert str(object_id) == "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
    assert kwargs == {
        "kind": "note",
        "payload": {"text": "test"},
        "source_ref": "vault/note.md",
    }
    assert connection.closed
    assert connection.cursor_instance.calls == [
        (
            "INSERT INTO objects (id, kind, payload) VALUES (%s, %s, '{}'::jsonb) ON CONFLICT (id) DO NOTHING",
            ("9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d", "note"),
        )
    ]
