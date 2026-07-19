from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import app.ingest.vault_alpha as vault_alpha

pytestmark = pytest.mark.not_pg


class _DummyStore:
    def __init__(self) -> None:
        self.put_calls: list[uuid.UUID] = []
        self.payloads: list[dict] = []

    def put(self, object_uuid: uuid.UUID, **kwargs) -> None:
        self.put_calls.append(object_uuid)
        self.payloads.append(dict(kwargs.get("payload") or {}))


def test_invalid_frontmatter_uuid_generates_uuid4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Explicit memory backend (KERNEL-03, #2765): the DomainObject facade write
    # in _ingest_single fails loud on an unconfigured pg backend; this test
    # exercises uuid sanitization, not the store backend.
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    note_dir = vault_root / "Inbox"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / "bad-uuid.md"
    content = "---\nuuid: alpha-e2e-bad\n---\n# Bad UUID\n"
    note_path.write_text(content, encoding="utf-8")

    dummy_store = _DummyStore()
    monkeypatch.setattr(vault_alpha, "get_object_store", lambda: dummy_store)
    # KERNEL-05 (I-D3): vault_alpha no longer writes the retrieval cache
    # directly (get_store attribute removed); only index_ingest_object feeds
    # the durable index, which the cache rebuilds from.
    monkeypatch.setattr(vault_alpha, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "classify_run", lambda *args, **_kwargs: {})

    note_uuid = vault_alpha._ingest_single(note_path, vault_root=vault_root, trace_id="test", raw_text=content)

    parsed = uuid.UUID(note_uuid)
    assert parsed.version == 4
    assert dummy_store.put_calls
    assert dummy_store.put_calls[0] == uuid.UUID(note_uuid)


def test_vault_alpha_uses_resolved_canonical_id_for_all_durable_producers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    vault_uuid = str(uuid.uuid4())
    canonical_id = str(uuid.uuid4())
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_path = vault_root / "retained.md"
    content = f"---\nuuid: {vault_uuid}\n---\n# Retained\n"
    note_path.write_text(content, encoding="utf-8")

    dummy_store = _DummyStore()
    classified: list[str] = []
    indexed: list[uuid.UUID] = []
    monkeypatch.setattr(vault_alpha, "resolve_canonical_object_id", lambda value: canonical_id)
    monkeypatch.setattr(vault_alpha, "get_object_store", lambda: dummy_store)
    monkeypatch.setattr(
        vault_alpha,
        "index_ingest_object",
        lambda **kwargs: indexed.append(kwargs["object_id"]),
    )
    monkeypatch.setattr(
        vault_alpha,
        "classify_run",
        lambda object_id, **_kwargs: (classified.append(object_id), {})[1],
    )

    result = vault_alpha._ingest_single(
        note_path,
        vault_root=vault_root,
        trace_id="canonical-id",
        raw_text=content,
    )

    assert result == canonical_id
    assert classified == [canonical_id]
    assert dummy_store.put_calls == [uuid.UUID(canonical_id)]
    assert indexed == [uuid.UUID(canonical_id)]
    assert dummy_store.payloads[0]["vault_uuid"] == vault_uuid
