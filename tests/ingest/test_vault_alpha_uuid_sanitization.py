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


def test_invalid_frontmatter_uuid_is_stable_for_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    first_uuid = vault_alpha._ingest_single(
        note_path,
        vault_root=vault_root,
        trace_id="test",
        raw_text=content,
        write_companion_record=False,
    )
    second_uuid = vault_alpha._ingest_single(
        note_path,
        vault_root=vault_root,
        trace_id="test-2",
        raw_text=content,
        write_companion_record=False,
    )

    parsed = uuid.UUID(first_uuid)
    assert parsed.version == 5
    assert first_uuid == second_uuid
    assert dummy_store.put_calls == [uuid.UUID(first_uuid), uuid.UUID(second_uuid)]


@pytest.mark.parametrize("declared", ["{11111111-1111-4111-8111-111111111111}", "11111111-1111-4111-8111-111111111111".upper()])
def test_declared_uuid_identity_is_canonicalized(declared: str, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text(f"---\nuuid: {declared}\n---\nBody\n", encoding="utf-8")

    identity = vault_alpha.resolve_vault_note_identity(
        note, vault_root=tmp_path, frontmatter={"uuid": declared}, body="Body\n"
    )

    assert identity.frontmatter_uuid == "11111111-1111-4111-8111-111111111111"
    assert identity.note_uuid == identity.frontmatter_uuid


def test_alpha_and_product_replay_share_whole_line_frontmatter_boundaries() -> None:
    raw_text = (
        '---\n'
        'title: "Inline --- scalar"\n'
        'uuid: 11111111-1111-4111-8111-111111111111\n'
        '---\n'
        'Body before the rule.\n'
        '---\n'
        'Body after the rule.\n'
    )

    frontmatter, body, malformed = vault_alpha._load_frontmatter_with_reporting(
        raw_text, Path("inline.md")
    )
    from app.rebuildability import parse_markdown_text

    readiness_frontmatter, readiness_body = parse_markdown_text(raw_text)

    assert malformed is False
    assert frontmatter == readiness_frontmatter
    assert body == "Body before the rule.\n---\nBody after the rule.\n"
    assert readiness_body == body.strip()


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
