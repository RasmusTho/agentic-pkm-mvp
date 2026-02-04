from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.ingest import vault_alpha as vault_alpha
from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.search import get_vector_index
from app.stores import get_object_store, reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        """---\ninclude_folders:\n  - "."\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )


def _clear_vector_index() -> None:
    vector_index = get_vector_index()
    entries = getattr(vector_index, "_entries", None)
    if isinstance(entries, dict):
        entries.clear()


def test_vault_alpha_title_fallbacks_and_search_titles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")

    reset_store_backends()
    get_store().set_documents([])
    _clear_vector_index()

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    (vault_root / "Heading.md").write_text("# Heading Title\nBody text\n", encoding="utf-8")
    (vault_root / "LineOnly.md").write_text("First line title\nMore\n", encoding="utf-8")
    (vault_root / "NoHeading.md").write_text("\n", encoding="utf-8")

    summary = run_vault_alpha_ingest(vault_root, max_notes=10, force=True)
    assert summary.ingested >= 3

    store = get_object_store()

    heading_fm, _ = load_frontmatter((vault_root / "Heading.md").read_text(encoding="utf-8"))
    line_fm, _ = load_frontmatter((vault_root / "LineOnly.md").read_text(encoding="utf-8"))
    filename_fm, _ = load_frontmatter((vault_root / "NoHeading.md").read_text(encoding="utf-8"))

    heading_uuid = uuid.UUID(str(heading_fm.get("uuid") or ""))
    line_uuid = uuid.UUID(str(line_fm.get("uuid") or ""))
    filename_uuid = uuid.UUID(str(filename_fm.get("uuid") or ""))

    heading_payload = store.get(heading_uuid)
    line_payload = store.get(line_uuid)
    filename_payload = store.get(filename_uuid)

    assert (heading_payload.get("payload") or {}).get("title") == "Heading Title"
    assert (line_payload.get("payload") or {}).get("title") == "First line title"
    assert (filename_payload.get("payload") or {}).get("title") == "NoHeading"

    vector_index = get_vector_index()
    entries = getattr(vector_index, "_entries", {})
    index_titles = [entry.payload.get("title") for entry in entries.values()]
    assert all(title for title in index_titles)
    assert "Heading Title" in index_titles
    assert "First line title" in index_titles
    assert "NoHeading" in index_titles
