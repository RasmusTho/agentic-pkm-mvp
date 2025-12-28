from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.stores import reset_store_backends


def test_vault_alpha_ingest_skips_locked_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")

    reset_store_backends()
    get_store().set_documents([])

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "Good.md").write_text("Good note body", encoding="utf-8")
    (vault_root / "Locked.md").write_text("Locked note body", encoding="utf-8")

    original_read_text = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.name == "Locked.md":
            raise OSError(35, "Resource deadlock avoided")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)

    summary = run_vault_alpha_ingest(vault_root, max_notes=10, force=True)
    output = capsys.readouterr().out

    assert summary.skipped_locked == 1
    assert summary.errors == 0
    assert "Skipped 1 locked files (errno=35)." in output
    assert summary.ingested >= 1
