from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.stores import reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter


def test_ingest_writes_uuid_for_notes_without_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_path = vault_root / "Notes" / "no-uuid.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        """---\ntitle: Missing UUID\n---\nContent without a UUID in frontmatter.\n""",
        encoding="utf-8",
    )

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    reset_store_backends()

    summary = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert summary.ingested == 1

    frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    note_uuid = str(frontmatter.get("uuid") or "").strip()
    assert note_uuid
    uuid.UUID(note_uuid)
