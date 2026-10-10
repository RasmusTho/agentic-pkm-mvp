"""Source-backed readiness continuity for the ordinary watched-note path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from app.objects import ObjectStore
from app.rebuildability import evaluate_product_store_readiness
from app.services import indexer
from app.workers import outbox_worker
from tests.helpers.pkm_alpha_helper import reset_memory_stores


pytestmark = [pytest.mark.not_pg, pytest.mark.usefixtures("product_model_access_gateway")]


def _write_layout(vault_root: Path) -> None:
    layout = vault_root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir(parents=True, exist_ok=True)
    layout.write_text(
        "---\n"
        "system_folder: ⚙️ System\n"
        "inbox_folder: 📥 Inbox\n"
        "desk_folder: 🛠️ Workbench\n"
        "include_folders:\n"
        "  - Notes\n"
        "---\n\n"
        "Readiness fixture layout.\n",
        encoding="utf-8",
    )


def _configure_deterministic_indexer(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = SimpleNamespace(
        provider="test",
        model="test-embedding",
        dim=4,
        normalize=True,
    )

    class _Client:
        def __init__(self) -> None:
            self.identity = identity

        def embed_text(self, _text: str) -> list[float]:
            return [0.1, 0.2, 0.3, 0.4]

        def close(self) -> None:
            return None

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(indexer, "get_product_embedding_client", lambda: _Client())
    monkeypatch.setattr(
        indexer,
        "llm_embed_text",
        lambda *, text, client: client.embed_text(text),
    )
    monkeypatch.setattr(indexer, "emit_index_object_embedded", lambda **_: None)
    monkeypatch.setattr(indexer, "emit_index_embedding_failed", lambda **_: None)


def _watch_payload(note_path: Path, vault_root: Path) -> dict[str, object]:
    return {
        "vault_path": str(note_path),
        "relative_path": note_path.relative_to(vault_root).as_posix(),
        "hash": "watch-hash",
        "mtime": 1.0,
    }


def _read_projection(note_uuid: str):
    projection = ObjectStore().get_object(note_uuid)
    assert projection is not None
    return projection


def _readiness_row(projection) -> dict[str, object]:
    return {
        "object_id": projection.uuid,
        "kind": projection.kind,
        "source_ref": projection.source_ref,
        "payload": projection.payload,
    }


def _vector_payload(note_uuid: str) -> dict[str, object]:
    rows = indexer.get_vector_index().all_rows()
    for row in rows:
        if str(row.get("object_id")) == note_uuid:
            payload = row.get("payload")
            assert isinstance(payload, dict)
            return payload
    raise AssertionError(f"missing vector projection for {note_uuid}")


def test_watched_note_append_preserves_product_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _configure_deterministic_indexer(monkeypatch)

    vault_root = tmp_path / "vault"
    _write_layout(vault_root)
    note_uuid = "11111111-1111-4111-8111-111111111111"
    note_path = vault_root / "Notes" / "readiness.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\nreview_state: evergreen\n"
        "episode_ref:\n  - ep-source-1\n---\n\n"
        "# Before append\n\nOriginal body.\n",
        encoding="utf-8",
    )
    source_bytes_before = note_path.read_bytes()

    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(note_path, vault_root), vault_root=vault_root
    ).ingested == 1
    initial = _read_projection(note_uuid)
    initial_readiness = evaluate_product_store_readiness(
        vault_root, [_readiness_row(initial)]
    )
    assert initial_readiness.ready is True

    note_path.write_text(
        f"---\nuuid: {note_uuid}\nreview_state: evergreen\n"
        "episode_ref:\n  - ep-source-1\n---\n\n"
        "# After append\n\nOriginal body.\n\nAppended body.\n",
        encoding="utf-8",
    )
    source_bytes_after = note_path.read_bytes()

    for _ in range(2):
        assert outbox_worker.handle_ingest_vault_changed(
            _watch_payload(note_path, vault_root), vault_root=vault_root
        ).ingested == 1

    projection = _read_projection(note_uuid)
    readiness = evaluate_product_store_readiness(
        vault_root, [_readiness_row(projection)]
    )
    assert readiness.ready is True
    assert projection.uuid == note_uuid
    assert projection.source_ref == str(note_path)
    assert projection.payload["title"] == "After append"
    assert projection.payload["review_state"] == "reviewed"
    assert projection.payload["episode_ref"] == ["ep-source-1"]
    assert projection.payload["content"] == "# After append\n\nOriginal body.\n\nAppended body."
    assert projection.payload["replay"]["source_identity"] == "Notes/readiness.md"
    assert projection.payload["replay"]["source_generation"]
    assert _vector_payload(note_uuid)["replay"] == projection.payload["replay"]
    assert _vector_payload(note_uuid)["title"] == "After append"
    assert note_path.read_bytes() == source_bytes_after
    assert source_bytes_before != source_bytes_after


def test_watched_note_uses_canonical_source_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _configure_deterministic_indexer(monkeypatch)

    vault_root = tmp_path / "vault"
    _write_layout(vault_root)
    variants = {
        "frontmatter": (
            "22222222-2222-4222-8222-222222222222",
            "---\nuuid: 22222222-2222-4222-8222-222222222222\n"
            "title: Frontmatter title\nreview_state: unknown\n"
            "episode_ref:\n  - ep-source-2\n---\n\n"
            "Body text.\n%% AI:Start %%\ntransient\n%% AI:End %%\n"
            "> [!info]- AI status\n> generated\n",
            "Frontmatter title",
            "provisional",
            ["ep-source-2"],
            "Body text.",
        ),
        "heading": (
            "33333333-3333-4333-8333-333333333333",
            "---\nuuid: 33333333-3333-4333-8333-333333333333\n"
            "review_state: evergreen\n---\n\n"
            "# Heading fallback\n\nMeaning.\n",
            "Heading fallback",
            "reviewed",
            "unbound",
            "# Heading fallback\n\nMeaning.",
        ),
        "empty": (
            "44444444-4444-4444-8444-444444444444",
            "---\nuuid: 44444444-4444-4444-8444-444444444444\n"
            "title: Empty body\nreview_state: draft\n---\n\n"
            "%% AI:Start %%\ntransient\n%% AI:End %%\n"
            "> [!info]- AI status\n> generated\n",
            "Empty body",
            "draft",
            "unbound",
            "",
        ),
    }

    projections = []
    for name, (note_uuid, raw_text, expected_title, expected_review, expected_episode, expected_text) in variants.items():
        note_path = vault_root / "Notes" / f"{name}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(raw_text, encoding="utf-8")
        assert outbox_worker.handle_ingest_vault_changed(
            _watch_payload(note_path, vault_root), vault_root=vault_root
        ).ingested == 1
        projection = _read_projection(note_uuid)
        assert projection.payload["title"] == expected_title
        assert projection.payload["review_state"] == expected_review
        assert projection.payload["episode_ref"] == expected_episode
        assert projection.payload["content"] == expected_text
        assert projection.payload["replay"]["source_identity"] == f"Notes/{name}.md"
        projections.append(projection)

    readiness = evaluate_product_store_readiness(
        vault_root, [_readiness_row(projection) for projection in projections]
    )
    assert readiness.ready is True
    assert readiness.refused_source_identities == ()
    assert _vector_payload("22222222-2222-4222-8222-222222222222")["content"] == "Body text."
    assert _vector_payload("33333333-3333-4333-8333-333333333333")["content"] == "# Heading fallback\n\nMeaning."
    assert all(
        str(row.get("object_id")) != "44444444-4444-4444-8444-444444444444"
        for row in indexer.get_vector_index().all_rows()
    )


def test_source_replay_update_preserves_ingest_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _configure_deterministic_indexer(monkeypatch)

    vault_root = tmp_path / "vault"
    _write_layout(vault_root)

    raw_uuid = "55555555-5555-4555-8555-555555555555"
    raw_note = vault_root / "Notes" / "raw.md"
    raw_note.parent.mkdir(parents=True, exist_ok=True)
    generic = {
        "uuid": raw_uuid,
        "kind": "note",
        "source_ref": str(raw_note),
        "content": "Raw content",
        "title": "Raw title",
        "review_state": "provisional",
        "payload": {
            "frontmatter": {"title": "Attacker"},
            "raw_text": "Raw content",
            "replay": {
                "source_identity": "Notes/raw.md",
                "source_generation": "attacker",
                "recipe_version": "product-object-replay-v1",
            },
        },
    }
    indexer.handle_ingest_object_created(generic, vault_root=vault_root)
    raw_projection = _read_projection(raw_uuid)
    assert "replay" not in raw_projection.payload

    invalid = vault_root / "Notes" / "invalid.md"
    invalid.write_text(
        "---\ntitle: [unterminated\n---\n\nBad source.\n",
        encoding="utf-8",
    )
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(invalid, vault_root), vault_root=vault_root
    ).ingested == 1
    initial_readiness = evaluate_product_store_readiness(
        vault_root, [_readiness_row(raw_projection)]
    )
    assert initial_readiness.ready is False
    assert "Notes/invalid.md" in initial_readiness.refused_source_identities

    bound_uuid = "66666666-6666-4666-8666-666666666666"
    bound_a = vault_root / "Notes" / "bound-a.md"
    bound_a.write_text(
        f"---\nuuid: {bound_uuid}\ntitle: Bound A\nreview_state: evergreen\n---\n\n"
        "# Bound A\n\nSource A.\n",
        encoding="utf-8",
    )
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(bound_a, vault_root), vault_root=vault_root
    ).ingested == 1

    bound_b = vault_root / "Notes" / "bound-b.md"
    bound_b.write_text(
        f"---\nuuid: {bound_uuid}\ntitle: Bound B\nreview_state: evergreen\n---\n\n"
        "# Bound B\n\nSource B.\n",
        encoding="utf-8",
    )
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(bound_b, vault_root), vault_root=vault_root
    ).ingested == 1
    bound_projection = _read_projection(bound_uuid)
    assert bound_projection.source_ref == str(bound_a)
    assert bound_projection.payload["title"] == "Bound A"
    assert bound_projection.payload["content"] == "# Bound A\n\nSource A."
    assert bound_projection.payload["replay"]["source_identity"] == "Notes/bound-a.md"

    moved_uuid = "77777777-7777-4777-8777-777777777777"
    moved_a = vault_root / "Notes" / "moved-a.md"
    moved_a.write_text(
        f"---\nuuid: {moved_uuid}\ntitle: Moved A\nreview_state: evergreen\n---\n\n"
        "# Moved A\n\nSource A.\n",
        encoding="utf-8",
    )
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(moved_a, vault_root), vault_root=vault_root
    ).ingested == 1
    moved_b = vault_root / "Notes" / "moved-b.md"
    moved_a.rename(moved_b)
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(moved_b, vault_root), vault_root=vault_root
    ).ingested == 1
    moved_projection = _read_projection(moved_uuid)
    assert moved_projection.source_ref == str(moved_a)
    assert moved_projection.payload["title"] == "Moved A"
    assert moved_projection.payload["replay"]["source_identity"] == "Notes/moved-a.md"

    legacy_uuid = "88888888-8888-4888-8888-888888888888"
    legacy_a = vault_root / "Notes" / "legacy-a.md"
    indexer.handle_ingest_object_created(
        {
            "uuid": legacy_uuid,
            "kind": "note",
            "source_ref": str(legacy_a),
            "content": "Legacy content",
            "title": "Legacy title",
            "payload": {"raw_text": "Legacy content"},
        },
        vault_root=vault_root,
    )
    legacy_b = vault_root / "Notes" / "legacy-b.md"
    legacy_b.write_text(
        f"---\nuuid: {legacy_uuid}\ntitle: Legacy B\nreview_state: evergreen\n---\n\n"
        "# Legacy B\n\nSource B.\n",
        encoding="utf-8",
    )
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(legacy_b, vault_root), vault_root=vault_root
    ).ingested == 1
    legacy_projection = _read_projection(legacy_uuid)
    assert legacy_projection.source_ref == str(legacy_a)
    assert "replay" not in legacy_projection.payload

    excluded = vault_root / "⚙️ System" / "companions" / "excluded.meta.md"
    excluded.parent.mkdir(parents=True, exist_ok=True)
    excluded.write_text("companion", encoding="utf-8")
    assert outbox_worker.handle_ingest_vault_changed(
        _watch_payload(excluded, vault_root), vault_root=vault_root
    ).ingested == 0
    assert ObjectStore().get_object("excluded.meta.md") is None
