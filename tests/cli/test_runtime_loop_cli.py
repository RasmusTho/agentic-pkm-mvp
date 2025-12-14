from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli

pytestmark = pytest.mark.not_pg


def _write_note(base: Path, rel: str, body: str = "content") -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_runtime_loop_emits_watcher_event_and_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Notes/A.md")
    outbox = tmp_path / "outbox.jsonl"
    snapshot = tmp_path / "snapshot.json"

    monkeypatch.setenv("STORE_BACKEND", "memory")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "runtime-loop",
            "--vault-root",
            str(vault),
            "--snapshot-path",
            str(snapshot),
            "--interval",
            "0",
            "--max-notes",
            "10",
            "--dry-run",
            "--no-run-panels",
            "--no-consume-promotions",
            "--outbox-path",
            str(outbox),
        ],
    )

    assert result.exit_code == 0, result.output
    records = [
        json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    watcher_events = [rec for rec in records if rec.get("event") == "watcher.run"]
    assert watcher_events, "watcher.run event not emitted"
    payload = watcher_events[-1].get("payload", {})
    assert payload.get("vault_root") == str(vault)

    import app.observability.status_service as status_service

    importlib.reload(status_service)
    status_service.INDEX_OUTBOX_PATH = outbox
    status = status_service.get_system_status()
    assert status.events.watcher_runs_total >= 1
    assert status.events.watcher_runs_24h >= 1


def test_runtime_loop_rejects_directory_outbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Notes/A.md")
    outbox_dir = tmp_path / "outbox-dir"
    outbox_dir.mkdir()

    monkeypatch.setenv("STORE_BACKEND", "memory")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "runtime-loop",
            "--vault-root",
            str(vault),
            "--snapshot-path",
            str(tmp_path / "snapshot.json"),
            "--interval",
            "0",
            "--dry-run",
            "--no-run-panels",
            "--no-consume-promotions",
            "--outbox-path",
            str(outbox_dir),
        ],
    )

    assert result.exit_code != 0
    assert "Outbox path points to a directory" in result.output


def test_runtime_loop_requires_outbox_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Notes/A.md")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("INDEX_OUTBOX_PATH", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "runtime-loop",
            "--vault-root",
            str(vault),
            "--snapshot-path",
            str(tmp_path / "snapshot.json"),
            "--interval",
            "0",
            "--dry-run",
            "--no-run-panels",
            "--no-consume-promotions",
        ],
    )

    assert result.exit_code != 0
    assert "Outbox path is required" in result.output
