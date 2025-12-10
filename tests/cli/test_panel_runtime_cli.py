from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from click.testing import CliRunner

from app.cli import cli
from app.store.object_store import DomainObject, ObjectStore


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-runtime-cli")


def test_panel_cli_runs_runtime_by_default(tmp_path: Path, monkeypatch) -> None:
    note_uuid = str(uuid4())
    markdown = """%% AI:Start %%
## AI-instruktion
Promote please.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
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
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run", "--uuid", note_uuid], env=env)

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = {entry.get("event") for entry in lines}
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "promote.intent.created" in events


def test_panel_cli_emit_only_skips_runtime(tmp_path: Path, monkeypatch) -> None:
    note_uuid = str(uuid4())
    markdown = """%% AI:Start %%
## AI-instruktion
Only emit.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run", "--uuid", note_uuid, "--emit-only"], env=env)

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = {entry.get("event") for entry in lines}
    assert events == {"panel.intent.created"}


def test_panel_cli_run_many_happy_path(tmp_path: Path, monkeypatch) -> None:
    note_uuid_a = str(uuid4())
    note_uuid_b = str(uuid4())
    markdown_promote = """%% AI:Start %%
## AI-instruktion
Promote please.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    markdown_log = """%% AI:Start %%
## AI-instruktion
Log only.
## AI-åtgärder
- [x] Do nothing special
%% AI:End %%
"""
    _seed_note(note_uuid_a, markdown_promote)
    _seed_note(note_uuid_b, markdown_log)

    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
  - id: log.only
    label: "Do nothing special"
    intent_type: log
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run-many", note_uuid_a, note_uuid_b], env=env)

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [entry.get("event") for entry in lines]
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "panel.log.created" in events
    assert "promote.intent.created" in events
    assert "panel.action.triggered" in events
    assert "panel.action.logged" in events
    assert "Processed 2 notes; panels_found=2" in result.output
    assert "promotions=1" in result.output
    assert "errors=0" in result.output


def test_panel_cli_run_many_mixed_panels(tmp_path: Path, monkeypatch) -> None:
    note_uuid_a = str(uuid4())
    note_uuid_b = str(uuid4())
    markdown_panel = """%% AI:Start %%
## AI-instruktion
Panel text.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    markdown_plain = "Just a note without panel."
    _seed_note(note_uuid_a, markdown_panel)
    _seed_note(note_uuid_b, markdown_plain)

    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
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
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run-many", note_uuid_a, note_uuid_b], env=env)

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [entry.get("event") for entry in lines]
    assert events.count("panel.intent.created") == 1
    assert "panel.intent.executed" in events
    assert "promote.intent.created" in events
    assert "Processed 2 notes; panels_found=1" in result.output
    assert "promotions=1" in result.output
    assert "errors=0" in result.output


def test_panel_cli_run_many_handles_missing(tmp_path: Path, monkeypatch) -> None:
    note_uuid_a = str(uuid4())
    markdown_panel = """%% AI:Start %%
## AI-instruktion
Panel text.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid_a, markdown_panel)
    missing_uuid = str(uuid4())

    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
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
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run-many", note_uuid_a, missing_uuid], env=env)

    assert result.exit_code == 1
    assert "Note not found in ObjectStore" in result.output
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [entry.get("event") for entry in lines]
    assert "panel.intent.created" in events
    assert "promote.intent.created" in events
    assert "errors=1" in result.output
