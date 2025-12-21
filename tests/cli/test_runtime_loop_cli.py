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


def test_runtime_loop_defaults_outbox_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Notes/A.md")
    outbox = tmp_path / "fallback-outbox.jsonl"

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

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

    assert result.exit_code == 0, result.output
    payloads = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(rec.get("event") == "watcher.run" for rec in payloads)


def test_runtime_loop_processes_label_style_panel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outbox = tmp_path / "outbox.jsonl"
    snapshot = tmp_path / "snapshot.json"
    actions_path = tmp_path / "panel-actions.yaml"
    actions_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: \"Make this note evergreen\"
    intent_type: promotion
    params:
      maturity: evergreen
""",
        encoding="utf-8",
    )
    note_body = """---
uuid: 12345678-1234-1234-1234-123456789abc
ai_panel_auto_run: watcher
---

%% AI:Start %%
Instruction: promote this
Actions:
- [x] Make this note evergreen
%% AI:End %%
"""
    _write_note(vault, "Notes/A.md", note_body)

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
            "--outbox-path",
            str(outbox),
            "--no-consume-promotions",
        ],
        env={
            "STORE_BACKEND": "memory",
            "PANEL_ACTIONS_PATH": str(actions_path),
            "INDEX_OUTBOX_PATH": str(outbox),
        },
    )

    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = {rec.get("event") for rec in records}
    assert "panel.action.triggered" in events
    assert "promote.intent.created" in events
