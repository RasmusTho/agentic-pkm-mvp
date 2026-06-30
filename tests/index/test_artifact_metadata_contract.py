from __future__ import annotations

from pathlib import Path

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.index.ingest_md import parse_markdown
from app.search import service as search_service

pytestmark = pytest.mark.not_pg

REQUIRED_METADATA_FIELDS = {
    "artifact_id",
    "path",
    "source_ref",
    "language",
    "source_role",
    "origin",
    "trust",
    "review_state",
    "embedding_identity",
}
REQUIRED_EMBEDDING_IDENTITY_FIELDS = {"provider", "model", "dim", "normalize"}


class CapturingVectorIndex:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _patch_index(monkeypatch: pytest.MonkeyPatch) -> tuple[CapturingVectorIndex, EmbeddingIdentity]:
    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    index = CapturingVectorIndex()
    monkeypatch.setattr(search_service, "embed_query", lambda text: ([0.1, 0.2, 0.3], identity))
    monkeypatch.setattr(search_service, "get_vector_index", lambda: index)
    return index, identity


def _assert_required_metadata_present(payload: dict) -> None:
    missing = sorted(
        field for field in REQUIRED_METADATA_FIELDS if payload.get(field) in (None, "")
    )
    assert not missing, (
        "indexed unit missing required metadata field(s): " + ", ".join(missing)
    )

    embedding_identity = payload["embedding_identity"]
    missing_identity = sorted(
        field
        for field in REQUIRED_EMBEDDING_IDENTITY_FIELDS
        if embedding_identity.get(field) in (None, "")
    )
    assert not missing_identity, (
        "indexed unit missing embedding_identity field(s): " + ", ".join(missing_identity)
    )


def test_uuidless_note_indexes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index, identity = _patch_index(monkeypatch)
    note_path = tmp_path / "Vault" / "uuidless.md"
    _write(note_path, "# UUID-less note\n\nThis note has no frontmatter uuid.")
    meta, body = parse_markdown(note_path)

    assert "uuid" not in meta
    object_id, dim = search_service.ingest_object(
        kind="note",
        source_ref=str(note_path),
        payload={
            "title": "UUID-less note",
            "origin": "vault",
            "source_role": "vault_note",
        },
        text=body,
    )

    assert dim == identity.dim
    assert index.calls, "uuid-less note should still upsert an indexed unit"
    captured = index.calls[-1]
    assert captured["object_id"] == object_id
    assert captured["payload"]["artifact_id"] == str(object_id)
    assert captured["payload"]["source_ref"] == str(note_path)
    _assert_required_metadata_present(captured["payload"])


def test_required_metadata_present(monkeypatch: pytest.MonkeyPatch) -> None:
    index, identity = _patch_index(monkeypatch)

    object_id, _dim = search_service.ingest_object(
        kind="note",
        source_ref="vault/Notes/retrieved-unit.md",
        payload={
            "artifact_id": "stale-artifact",
            "stable_id": "stale-stable-id",
            "path": "vault/Old/stale.md",
            "source_ref": "vault/Old/stale.md",
            "title": "Retrieved Unit",
            "origin": "vault",
            "language": "en",
            "source_role": "vault_note",
            "trust": "own",
            "review_state": "reviewed",
        },
        text="Retrieved unit contract fixture.",
    )

    captured = index.calls[-1]
    payload = captured["payload"]
    _assert_required_metadata_present(payload)
    assert payload["artifact_id"] == str(object_id)
    assert payload["stable_id"] == str(object_id)
    assert payload["path"] == "vault/Notes/retrieved-unit.md"
    assert payload["source_ref"] == "vault/Notes/retrieved-unit.md"
    assert payload["embedding_identity"] == {
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
    }
    assert captured["identity"] == identity
    assert captured["model"] == identity.model

    with pytest.raises(AssertionError, match="language"):
        _assert_required_metadata_present(
            {
                "artifact_id": str(object_id),
                "path": "vault/Notes/retrieved-unit.md",
                "source_ref": "vault/Notes/retrieved-unit.md",
                "source_role": "vault_note",
                "origin": "vault",
                "trust": "own",
                "review_state": "reviewed",
                "embedding_identity": payload["embedding_identity"],
            }
        )
