from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.stores import reset_store_backends


def _write_note(base: Path, rel: str, body: str) -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _base_env(tmp_path: Path, actions_path: Path, outbox_path: Path) -> dict[str, str]:
    return {
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock response [#1]",
        "PANEL_ACTIONS_PATH": str(actions_path),
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "WATCHER_AUTO_EXEC": "1",
    }


def _panel_note(title: str, auto: str | None = None) -> str:
    auto_line = f"\nai_panel_auto_run: {auto}" if auto else ""
    return f"""---
title: {title}
{auto_line}
---
%% AI:Start %%
## AI-instruktion
Do work
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""


def _read_events(outbox_path: Path) -> list[str]:
    if not outbox_path.exists():
        return []
    return [
        json.loads(line).get("event")
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _set_outbox(monkeypatch, outbox_path: Path) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.agent.INDEX_OUTBOX_PATH",
        outbox_path,
        raising=False,
    )


def test_vault_watcher_cli_no_changes_after_snapshot(tmp_path: Path, monkeypatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    actions_path = tmp_path / "panel-actions.yaml"
    actions_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    _set_outbox(monkeypatch, outbox_path)
    _write_note(vault, "Concepts/A.md", _panel_note("A"))
    snapshot = tmp_path / "state.json"

    runner = CliRunner()
    env = _base_env(tmp_path, actions_path, outbox_path)

    # First run populates snapshot
    first = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot)],
        env=env,
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot)],
        env=env,
    )
    assert second.exit_code == 0, second.output
    assert "Watcher summary:" in second.output
    assert "changed=0" in second.output


def test_vault_watcher_cli_runs_ingest_and_panel_when_allowed(tmp_path: Path, monkeypatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    actions_path = tmp_path / "panel-actions.yaml"
    actions_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    _set_outbox(monkeypatch, outbox_path)
    _write_note(vault, "Concepts/A.md", _panel_note("A", auto="watcher"))
    _write_note(vault, "Concepts/B.md", _panel_note("B", auto="watcher"))
    snapshot = tmp_path / "state.json"

    runner = CliRunner()
    env = _base_env(tmp_path, actions_path, outbox_path)

    result = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot)],
        env=env,
    )

    assert result.exit_code == 0, result.output
    events = [e for e in _read_events(outbox_path) if e]
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "promote.intent.created" in events
    assert "Watcher summary:" in result.output
    assert "panel_runs=2" in result.output


def test_vault_watcher_cli_skips_panel_when_manual(tmp_path: Path, monkeypatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    actions_path = tmp_path / "panel-actions.yaml"
    actions_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    _set_outbox(monkeypatch, outbox_path)
    _write_note(vault, "Concepts/A.md", _panel_note("A"))  # default manual
    snapshot = tmp_path / "state.json"

    runner = CliRunner()
    env = _base_env(tmp_path, actions_path, outbox_path)

    result = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot)],
        env=env,
    )

    assert result.exit_code == 0, result.output
    events = [e for e in _read_events(outbox_path) if e]
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "Watcher summary:" in result.output
    assert "panel_runs=1" in result.output
    assert "skipped_policy=0" in result.output


def test_vault_watcher_cli_bad_root_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["vault-watcher-run", "--vault-root", str(tmp_path / "missing")])
    assert result.exit_code != 0
    assert "Vault root not found" in result.output or "Invalid value" in result.output


def test_vault_watcher_cli_dry_run(tmp_path: Path, monkeypatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    actions_path = tmp_path / "panel-actions.yaml"
    actions_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    _set_outbox(monkeypatch, outbox_path)
    _write_note(vault, "Concepts/A.md", _panel_note("A", auto="watcher"))
    _write_note(vault, "Concepts/B.md", _panel_note("B", auto="watcher"))
    snapshot = tmp_path / "state.json"

    runner = CliRunner()
    env = _base_env(tmp_path, actions_path, outbox_path)

    result = runner.invoke(
        cli,
        [
            "vault-watcher-run",
            "--vault-root",
            str(vault),
            "--snapshot-path",
            str(snapshot),
            "--dry-run",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "dry_run=True" in result.output
    events = [e for e in _read_events(outbox_path) if e]
    assert "watcher.run" in events
    assert set(events) == {"watcher.run"}


def test_vault_watcher_cli_max_notes_blocks_without_force(tmp_path: Path, monkeypatch) -> None:
    reset_store_backends()
    vault = tmp_path / "vault"
    actions_path = tmp_path / "panel-actions.yaml"
    actions_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    _set_outbox(monkeypatch, outbox_path)
    for idx in range(3):
        _write_note(vault, f"Concepts/N{idx}.md", _panel_note(f"N{idx}", auto="watcher"))
    snapshot = tmp_path / "state.json"

    runner = CliRunner()
    env = _base_env(tmp_path, actions_path, outbox_path)

    result = runner.invoke(
        cli,
        [
            "vault-watcher-run",
            "--vault-root",
            str(vault),
            "--snapshot-path",
            str(snapshot),
            "--max-notes",
            "1",
        ],
        env=env,
    )

    assert result.exit_code != 0
    assert "max-notes=1" in result.output
    assert "limit_exceeded=True" in result.output
    events = [e for e in _read_events(outbox_path) if e]
    assert "watcher.run" in events
    assert set(events) == {"watcher.run"}
