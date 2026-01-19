from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import app.ingest.vault_alpha as vault_alpha

pytestmark = pytest.mark.not_pg


class _DummyStore:
    def __init__(self) -> None:
        self.put_calls: list[uuid.UUID] = []

    def put(self, object_uuid: uuid.UUID, **_kwargs) -> None:
        self.put_calls.append(object_uuid)


class _DummySearchStore:
    def add_document(self, **_kwargs) -> None:
        return None


def test_invalid_frontmatter_uuid_generates_uuid4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORE_BACKEND", "pg")

    vault_root = tmp_path / "vault"
    note_dir = vault_root / "Inbox"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "bad-uuid.md"
    content = "---\nuuid: alpha-e2e-bad\n---\n# Bad UUID\n"
    note_path.write_text(content, encoding="utf-8")

    dummy_store = _DummyStore()
    monkeypatch.setattr(vault_alpha, "get_object_store", lambda: dummy_store)
    monkeypatch.setattr(vault_alpha, "get_store", lambda: _DummySearchStore())
    monkeypatch.setattr(vault_alpha, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "classify_run", lambda *args, **_kwargs: {})

    note_uuid = vault_alpha._ingest_single(note_path, vault_root=vault_root, trace_id="test", raw_text=content)

    parsed = uuid.UUID(note_uuid)
    assert parsed.version == 4
    assert dummy_store.put_calls
    assert dummy_store.put_calls[0] == uuid.UUID(note_uuid)
