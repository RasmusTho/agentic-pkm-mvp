import os
from pathlib import Path

from app.ingest.vault_root import ingest_vault_root, iter_vault_root_markdown
from app.observability.ingest_meta import reset_ingest_meta
from app.observability.status_service import get_system_status
from app.stores import get_object_store, reset_store_backends


def test_iter_vault_root_filters_and_limits(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("A", encoding="utf-8")
    (tmp_path / "b.md").write_text("B", encoding="utf-8")
    (tmp_path / "note.txt").write_text("C", encoding="utf-8")
    (tmp_path / ".hidden.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "c.md").write_text("Ignored", encoding="utf-8")

    files = list(iter_vault_root_markdown(tmp_path))
    assert [p.name for p in files] == ["a.md", "b.md"]

    limited = list(iter_vault_root_markdown(tmp_path, limit=1))
    assert [p.name for p in limited] == ["a.md"]


def test_ingest_vault_root_updates_status_and_store(tmp_path: Path, monkeypatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "first.md").write_text("# First\nContent", encoding="utf-8")
    (vault_root / "second.md").write_text("# Second\nMore", encoding="utf-8")

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}')
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "ingest_status.json"))

    reset_store_backends()
    reset_ingest_meta()

    ingested = ingest_vault_root(vault_root, limit=2)
    assert ingested == 2

    store = get_object_store()
    assert len(getattr(store, "_objects", {})) >= 2

    status = get_system_status()
    assert status.ingestion.last_run_at is not None
    assert status.ingestion.last_run_ok is True
