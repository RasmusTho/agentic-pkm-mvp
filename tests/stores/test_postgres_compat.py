"""Compatibility-store guards for the legacy vault-root ingest adapter."""

from __future__ import annotations

from app.stores import postgres


class _CanonicalStore:
    def __init__(self) -> None:
        self.put_calls: list[tuple[object, dict]] = []

    def put(self, object_id, **kwargs) -> None:
        self.put_calls.append((object_id, kwargs))


def test_pgobjects_upsert_does_not_write_legacy_objects_table(monkeypatch) -> None:
    """The compatibility adapter delegates durable writes to store_objects only."""
    canonical_store = _CanonicalStore()
    monkeypatch.setattr(postgres, "PgObjectStore", lambda: canonical_store)

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
