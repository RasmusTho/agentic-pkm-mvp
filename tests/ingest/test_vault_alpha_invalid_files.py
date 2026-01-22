from __future__ import annotations

import json
from pathlib import Path

from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.stores import reset_store_backends


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        """---\ninclude_folders:\n  - "."\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )


def test_vault_alpha_ingest_skips_invalid_notes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")

    invalid_report = tmp_path / "ingest-invalid.jsonl"
    monkeypatch.setenv("INGEST_INVALID_REPORT_PATH", str(invalid_report))

    reset_store_backends()
    get_store().set_documents([])

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    (vault_root / "Good.md").write_text("Good note body", encoding="utf-8")
    (vault_root / "Bad.md").write_bytes(b"Bad\x00Note")

    summary = run_vault_alpha_ingest(vault_root, max_notes=10, force=True)

    assert summary.ingested >= 1
    assert summary.skipped_invalid == 1
    assert summary.invalid_report_path == str(invalid_report)
    assert invalid_report.exists()

    lines = invalid_report.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    payload = json.loads(lines[0])
    assert payload.get("path") == "Bad.md"
    assert payload.get("exception_type") == "NullByteError"
