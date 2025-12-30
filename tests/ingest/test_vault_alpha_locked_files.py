from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest, run_vault_alpha_ingest_locked_only
from app.retrieval.hybrid import get_store
from app.stores import reset_store_backends


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        """---\ninclude_folders:\n  - "."\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )


def test_vault_alpha_ingest_skips_locked_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")
    monkeypatch.setenv("LOCKED_FILES_LOG_PATH", str(tmp_path / "locked-files.jsonl"))

    reset_store_backends()
    get_store().set_documents([])

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "Good.md").write_text("Good note body", encoding="utf-8")
    (vault_root / "Locked.md").write_text("Locked note body", encoding="utf-8")

    _write_layout(vault_root)

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


def test_vault_alpha_locked_files_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")
    log_path = tmp_path / "locked-files.jsonl"
    monkeypatch.setenv("LOCKED_FILES_LOG_PATH", str(log_path))

    reset_store_backends()
    get_store().set_documents([])

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "Good.md").write_text("Good note body", encoding="utf-8")
    (vault_root / "Locked.md").write_text("Locked note body", encoding="utf-8")

    _write_layout(vault_root)

    locked = True
    original_read_text = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.name == "Locked.md" and locked:
            raise OSError(35, "Resource deadlock avoided")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)

    summary_first = run_vault_alpha_ingest(vault_root, max_notes=10, force=True)
    assert summary_first.skipped_locked == 1
    assert log_path.exists()
    assert "Locked.md" in log_path.read_text(encoding="utf-8")

    locked = False
    summary_retry = run_vault_alpha_ingest_locked_only(vault_root, force=True)
    assert summary_retry.ingested >= 1
    assert not log_path.exists() or not log_path.read_text(encoding="utf-8").strip()
